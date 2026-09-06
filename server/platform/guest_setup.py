"""Re-apply the LDPlayer guest routing after an emulator reboot — one command.

    python -m server.platform.guest_setup

Host-side only (adb + `adb shell su -c`); re-applies everything the
2026-09-05 roll-forward installed, per
Docs/Teardown/vainglory-mobile-local-stack.md:

  1. bind /data/local/tmp/halcyon-hosts-20260905    -> /system/etc/hosts
  2. bind /data/local/tmp/halcyon-cacerts-20260905  -> /system/etc/security/cacerts
  3. 4 firewall rules (tagged halcyon-*): uid REJECT local-only ×2,
     127.0.0.1:80->8080 and :443->8443 REDIRECT
  4. adb reverse ×4: 8080, 8443 + the current gateway/heartbeat ports

Idempotent: every step checks its current state first — already-applied
items are reported and skipped, never re-inserted. /data/local/tmp survives
reboots, so the overlay files themselves are only expected to exist; when
they don't, the script fails with the recovery pointer instead of inventing
state. The final step verifies from inside the guest that
rpc.kindred-live.net resolves to 127.0.0.1.

A reboot clears the bind mounts; an adb-server restart clears every reverse
mapping; either may happen independently — this script is safe to re-run in
any combination of half-applied state.
"""
import argparse
import subprocess
import sys
import time

HOSTS_SRC = "/data/local/tmp/halcyon-hosts-20260905"
CACERTS_SRC = "/data/local/tmp/halcyon-cacerts-20260905"
HOSTS_TARGET = "/system/etc/hosts"
CACERTS_TARGET = "/system/etc/security/cacerts"

LOCAL_ONLY_COMMENT = "halcyon-local-only"
LOCAL_ROUTE_COMMENT = "halcyon-local-route"
VERIFY_HOST = "rpc.kindred-live.net"
# The documented adb-server wedge: an online transport with a dead shell
# service. One bounded restart attempt before giving up (leaf §"ADB shells
# timing out").
SHELL_RECOVERY = (["adb", "kill-server"], ["adb", "start-server"],
                  ["adb", "connect", "127.0.0.1:5555"])


def run(cmd, timeout=20):
    """Run a host command; returns CompletedProcess (never raises for rc!=0)."""
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, shell=False)


def su(serial, cmd, timeout=20):
    """One guest root command, delivered as ONE quoted string to the guest
    shell — `adb shell "su -c '<cmd>'"`. The leaf's "one correctly quoted
    command string" rule: delivered unquoted, su -c executes only the first
    token and the rest leak as stray argv (cmd must not contain ')."""
    assert "'" not in cmd
    return run(["adb", "-s", serial, "shell", f"su -c '{cmd}'"], timeout)


def preflight(serial):
    """Bounded shell-service check; on timeout, one adb-server restart."""
    probe = run(["adb", "-s", serial, "shell", "echo ok"], timeout=10)
    if probe.returncode == 0 and "ok" in probe.stdout:
        return True
    print("[adb] shell not responding — restarting adb server once")
    for step in SHELL_RECOVERY:
        run(step, timeout=30)
    time.sleep(1.0)
    probe = run(["adb", "-s", serial, "shell", "echo ok"], timeout=10)
    return probe.returncode == 0 and "ok" in probe.stdout


# -- bind mounts -------------------------------------------------------------

def mounts(serial):
    """/proc/mounts lines (via root — the file is world-readable anyway)."""
    res = su(serial, "cat /proc/mounts")
    if res.returncode != 0:
        raise RuntimeError(f"cannot read /proc/mounts: {res.stderr.strip()}")
    return res.stdout.splitlines()


def mount_state(lines, target, src_hint):
    """-> ("ours" | "foreign" | "missing") for one mountpoint."""
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == target:
            return "ours" if src_hint in parts[0] else "foreign"
    return "missing"


def hosts_content_ok(serial):
    res = su(serial, f"grep rpc.kindred-live.net {HOSTS_TARGET}")
    return res.returncode == 0 and "127.0.0.1" in res.stdout


def cacerts_content_ok(serial):
    res = su(serial, f"ls {CACERTS_TARGET}/41e9eb4e.0")
    return res.returncode == 0 and "41e9eb4e.0" in res.stdout


def ensure_mount(serial, lines, src, target, effect_ok):
    """Idempotency by effect: 'ours' in /proc/mounts is the clean case, but
    this LDPlayer image mounts /system/etc/hosts and .../cacerts from its
    own block device, and a snapshot can carry the overlay content with the
    bind no longer listed. When the target's content already serves the
    routing (hosts maps the platform names, CA 41e9eb4e.0 present), binding
    again adds nothing — report and skip. Only a target with BOTH the wrong
    mechanism and the wrong content is a hard conflict."""
    state = mount_state(lines, target, src)
    if state == "ours":
        print(f"[mount] ok (already bound): {src} -> {target}")
        return True
    if effect_ok(serial):
        why = "foreign mount, content verified" if state == "foreign" \
              else "not in /proc/mounts, content verified"
        print(f"[mount] ok ({why}): {target}")
        return True
    if state == "foreign":
        owner = next((l for l in lines if l.split()[1:2] == [target]), "?")
        print(f"[mount] CONFLICT: {target} mounted elsewhere with wrong "
              f"content:\n        {owner}")
        return False
    check = su(serial, f"[ -e {src} ] && echo present")
    if "present" not in check.stdout:
        print(f"[mount] MISSING source {src} — recreate it once per "
              "Docs/Teardown/vainglory-mobile-local-stack.md (the overlay "
              "files survive reboots; this is not expected)")
        return False
    res = su(serial, f"mount --bind {src} {target}")
    if res.returncode != 0:
        print(f"[mount] FAILED: mount --bind {src} {target} "
              f"-> {res.stderr.strip() or res.stdout.strip()}")
        return False
    print(f"[mount] bound: {src} -> {target}")
    return True


# -- firewall ----------------------------------------------------------------

def rule_present(serial, binary, table_args, markers):
    """`-S OUTPUT` is normalized (inserted flags get reordered, defaults
    appear), so presence is judged by marker substrings — the tag comment
    plus whatever makes THIS rule distinct (e.g. --to-ports)."""
    res = su(serial, f"{binary} {' '.join(table_args)} -S OUTPUT".strip())
    return all(m in res.stdout for m in markers)


def ensure_rule(serial, binary, table_args, rule, markers):
    """Insert only when the markers are absent; `-I ... 1` matches the
    measured install (position 1 in its table)."""
    if rule_present(serial, binary, table_args, markers):
        print(f"[fw] ok (already present): {' '.join(markers)} ({binary})")
        return True
    full = [f"{binary}"] + table_args + rule
    res = su(serial, " ".join(full))
    if res.returncode != 0:
        print(f"[fw] FAILED: {' '.join(full)} -> "
              f"{res.stderr.strip() or res.stdout.strip()}")
        return False
    print(f"[fw] inserted: {' '.join(markers)} ({binary})")
    return True


def ensure_firewall(serial, uid, http, https):
    """uid-local-only REJECT (v4+v6) + loopback 80/443 -> http/https
    REDIRECT; exact rule text from the leaf. The two REDIRECTs share the
    same tag comment, so each carries its --to-ports as a presence marker —
    a half-applied nat table must still get its missing half."""
    ok = True
    ok &= ensure_rule(
        serial, "iptables", [],
        ["-I", "OUTPUT", "1", "-m", "owner", "--uid-owner", str(uid),
         "!", "-d", "127.0.0.0/8", "-m", "comment",
         "--comment", LOCAL_ONLY_COMMENT, "-j", "REJECT"],
        [LOCAL_ONLY_COMMENT])
    ok &= ensure_rule(
        serial, "ip6tables", [],
        ["-I", "OUTPUT", "1", "-m", "owner", "--uid-owner", str(uid),
         "!", "-d", "::1/128", "-m", "comment",
         "--comment", LOCAL_ONLY_COMMENT, "-j", "REJECT"],
        [LOCAL_ONLY_COMMENT])
    ok &= ensure_rule(
        serial, "iptables", ["-t", "nat"],
        ["-I", "OUTPUT", "1", "-d", "127.0.0.1", "-p", "tcp",
         "--dport", "80", "-m", "comment",
         "--comment", LOCAL_ROUTE_COMMENT, "-j", "REDIRECT",
         "--to-ports", str(http)],
        [LOCAL_ROUTE_COMMENT, f"--to-ports {http}"])
    ok &= ensure_rule(
        serial, "iptables", ["-t", "nat"],
        ["-I", "OUTPUT", "1", "-d", "127.0.0.1", "-p", "tcp",
         "--dport", "443", "-m", "comment",
         "--comment", LOCAL_ROUTE_COMMENT, "-j", "REDIRECT",
         "--to-ports", str(https)],
        [LOCAL_ROUTE_COMMENT, f"--to-ports {https}"])
    return ok


# -- adb reverses ------------------------------------------------------------

def ensure_reverses(serial, ports):
    res = run(["adb", "-s", serial, "reverse", "--list"])
    listed = {part for line in res.stdout.splitlines()
              for part in line.split() if part.startswith("tcp:")}
    ok = True
    for port in ports:
        token = f"tcp:{port}"
        if token in listed:
            print(f"[reverse] ok (already mapped): {token}")
            continue
        r = run(["adb", "-s", serial, "reverse", token, token])
        if r.returncode != 0:
            print(f"[reverse] FAILED: {token} -> {r.stderr.strip()}")
            ok = False
        else:
            print(f"[reverse] added: {token}")
    return ok


# -- verify ------------------------------------------------------------------

def verify_dns(serial):
    """The leaf's acceptance: the guest must resolve the platform RPC host
    to loopback through the bound hosts file. ping's first line reads
    `PING rpc.kindred-live.net (127.0.0.1) ...`."""
    res = su(serial, f"ping -c 1 -W 2 {VERIFY_HOST}", timeout=15)
    first = res.stdout.splitlines()[0] if res.stdout else ""
    if "127.0.0.1" in first:
        print(f"[verify] ok: {VERIFY_HOST} -> 127.0.0.1 in guest")
        return True
    print(f"[verify] FAILED: {VERIFY_HOST} did not resolve to 127.0.0.1 "
          f"-> {first or res.stderr.strip() or '(no output)'}")
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Idempotent guest routing re-apply "
                    "(bind mounts + tagged firewall + adb reverses).")
    ap.add_argument("--serial", default="emulator-5554",
                    help="adb device serial (default emulator-5554)")
    ap.add_argument("--uid", type=int, default=10060,
                    help="game package uid for the local-only REJECT "
                         "(installation-specific, default 10060)")
    ap.add_argument("--http", type=int, default=8080,
                    help="host http port behind the 80 REDIRECT")
    ap.add_argument("--https", type=int, default=8443,
                    help="host https port behind the 443 REDIRECT")
    ap.add_argument("--gateway-port", type=int, default=7102,
                    help="current match gateway port (drifts; see leaf)")
    ap.add_argument("--heartbeat-port", type=int, default=2114,
                    help="current heartbeat port (drifts; see leaf)")
    ap.add_argument("--skip-verify", action="store_true",
                    help="skip the guest DNS ping check")
    args = ap.parse_args(argv)

    if not preflight(args.serial):
        print(f"[adb] no shell service on {args.serial} — restart the "
              "emulator or adb (leaf: 'ADB shells timing out')")
        return 2

    ok = True
    lines = mounts(args.serial)
    ok &= ensure_mount(args.serial, lines, HOSTS_SRC, HOSTS_TARGET,
                       hosts_content_ok)
    ok &= ensure_mount(args.serial, lines, CACERTS_SRC, CACERTS_TARGET,
                       cacerts_content_ok)
    ok &= ensure_firewall(args.serial, args.uid, args.http, args.https)
    ok &= ensure_reverses(args.serial,
                          [args.http, args.https,
                           args.gateway_port, args.heartbeat_port])
    ok &= True if args.skip_verify else verify_dns(args.serial)

    print("[guest] RESULT:", "OK" if ok else "INCOMPLETE — see [..] FAILED/"
          "CONFLICT/MISSING lines above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
