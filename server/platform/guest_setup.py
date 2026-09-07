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
import os
import subprocess
import sys
import time

HOSTS_SRC = "/data/local/tmp/halcyon-hosts-20260905"
CACERTS_SRC = "/data/local/tmp/halcyon-cacerts-20260905"
HOSTS_TARGET = "/system/etc/hosts"
CACERTS_TARGET = "/system/etc/security/cacerts"

DNS_NAMES = [
    "platform.superevil.net",
    "platform.superevilmegacorp.net",
    "rpc.kindred-live.net",
    "preauth.superevil.net",
    "preauth.superevilmegacorp.net",
    "gamefeeds.superevilmegacorp.net",
    "my.superevilmegacorp.net",
]

LOCAL_HOST_COMMENT = "halcyon-target-host"
LOCAL_ONLY_COMMENT = "halcyon-local-only"
LOCAL_ROUTE_COMMENT = "halcyon-local-route"
LOCAL_LAN_ROUTE_COMMENT = "halcyon-lan-route"
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
    for line in reversed(lines):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == target:
            return "ours" if src_hint in parts[0] else "foreign"
    return "missing"


def hosts_content_ok(serial, host="127.0.0.1"):
    res = su(serial, f"grep rpc.kindred-live.net {HOSTS_TARGET}")
    return res.returncode == 0 and host in res.stdout


def cacerts_content_ok(serial):
    res = su(serial, f"ls {CACERTS_TARGET}/41e9eb4e.0")
    return res.returncode == 0 and "41e9eb4e.0" in res.stdout


def ensure_hosts_source(serial, host="127.0.0.1"):
    """Ensure /data/local/tmp/halcyon-hosts-20260905 exists and maps SEMC names to host."""
    check = su(serial, f"cat {HOSTS_SRC} 2>/dev/null")
    if check.returncode == 0 and host in check.stdout:
        return True
    lines = [
        "127.0.0.1 localhost",
        "::1 ip6-localhost",
    ]
    for d in DNS_NAMES:
        lines.append(f"{host} {d}")
    content = "\\n".join(lines) + "\\n"
    res = su(serial, f"printf '{content}' > {HOSTS_SRC} && chmod 0644 {HOSTS_SRC}")
    if res.returncode != 0:
        print(f"[hosts] FAILED to write {HOSTS_SRC}: {res.stderr.strip()}")
        return False
    print(f"[hosts] created overlay source {HOSTS_SRC} -> {host}")
    return True


def ensure_cacerts_source(serial, cert_path=None):
    """Ensure /data/local/tmp/halcyon-cacerts-20260905 contains Halcyon CA cert 41e9eb4e.0."""
    cert_hash = "41e9eb4e.0"
    target_cert = f"{CACERTS_SRC}/{cert_hash}"
    check = su(serial, f"[ -f {target_cert} ] && echo present")
    if "present" in check.stdout:
        return True

    dir_check = su(serial, f"[ -d {CACERTS_SRC} ] && echo present")
    if "present" not in dir_check.stdout:
        print(f"[cacerts] cloning {CACERTS_TARGET} to {CACERTS_SRC}...")
        res = su(serial, f"cp -a {CACERTS_TARGET} {CACERTS_SRC} && chmod 0755 {CACERTS_SRC}")
        if res.returncode != 0:
            print(f"[cacerts] FAILED to clone system cacerts: {res.stderr.strip()}")
            return False

    if not cert_path or not os.path.isfile(cert_path):
        default_cert = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack", "platform_cert.pem")
        if os.path.isfile(default_cert):
            cert_path = default_cert
        else:
            print(f"[cacerts] generating certificate via mkcert...")
            from . import mkcert
            mkcert.main([])
            cert_path = default_cert

    push_res = run(["adb", "-s", serial, "push", cert_path, f"/data/local/tmp/{cert_hash}"])
    if push_res.returncode != 0:
        print(f"[cacerts] FAILED to push cert: {push_res.stderr.strip()}")
        return False
    su(serial, f"cp /data/local/tmp/{cert_hash} {target_cert} && chmod 0644 {target_cert}")
    print(f"[cacerts] installed {cert_hash} into {CACERTS_SRC}")
    return True


def ensure_mount(serial, lines, src, target, effect_ok):
    """Idempotency by effect: 'ours' in /proc/mounts is the clean case, but
    this LDPlayer image mounts /system/etc/hosts and .../cacerts from its
    own block device, and a snapshot can carry the overlay content with the
    bind no longer listed. When the target's content already serves the
    routing (hosts maps the platform names, CA 41e9eb4e.0 present), binding
    again adds nothing — report and skip. Only a target with BOTH the wrong
    mechanism and the wrong content is a hard conflict."""
    state = mount_state(lines, target, src)
    if state == "ours" and effect_ok(serial):
        print(f"[mount] ok (already bound): {src} -> {target}")
        return True
    if effect_ok(serial):
        why = "foreign mount, content verified" if state == "foreign" \
              else "not in /proc/mounts, content verified"
        print(f"[mount] ok ({why}): {target}")
        return True
    if state == "ours":
        # Target was mounted with old content (e.g. host changed); unmount to re-bind
        su(serial, f"umount {target}")
    elif state == "foreign":
        owner = next((l for l in lines if l.split()[1:2] == [target]), "?")
        print(f"[mount] CONFLICT: {target} mounted elsewhere with wrong "
              f"content:\n        {owner}")
        return False
    check = su(serial, f"[ -e {src} ] && echo present")
    if "present" not in check.stdout:
        print(f"[mount] MISSING source {src} — recreate it once per "
              "Docs/Teardown/vainglory-mobile-local-stack.md")
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


def ensure_firewall(serial, uid, http, https, host="127.0.0.1", redirect_lan=False):
    """Firewall policy: local loopback (host=127.0.0.1) rejects non-loopback
    traffic from game uid and redirects 80/443 -> 8080/8443; remote host
    allows traffic to that host while rejecting all other non-loopback traffic,
    preventing any leak to SEMC or the public internet."""
    ok = True
    if host == "127.0.0.1":
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
    else:
        # Remote host on LAN:
        # Rule 1: allow traffic to host
        marker_host = f"{LOCAL_HOST_COMMENT}-{host}"
        ok &= ensure_rule(
            serial, "iptables", [],
            ["-I", "OUTPUT", "1", "-m", "owner", "--uid-owner", str(uid),
             "-d", f"{host}/32", "-m", "comment",
             "--comment", marker_host, "-j", "ACCEPT"],
            [marker_host])
        # Rule 2: reject other non-loopback IPv4 traffic (no internet leak)
        ok &= ensure_rule(
            serial, "iptables", [],
            ["-I", "OUTPUT", "2", "-m", "owner", "--uid-owner", str(uid),
             "!", "-d", "127.0.0.0/8", "-m", "comment",
             "--comment", LOCAL_ONLY_COMMENT, "-j", "REJECT"],
            [LOCAL_ONLY_COMMENT])
        # Rule 3: reject non-loopback IPv6 traffic
        ok &= ensure_rule(
            serial, "ip6tables", [],
            ["-I", "OUTPUT", "1", "-m", "owner", "--uid-owner", str(uid),
             "!", "-d", "::1/128", "-m", "comment",
             "--comment", LOCAL_ONLY_COMMENT, "-j", "REJECT"],
            [LOCAL_ONLY_COMMENT])
        if redirect_lan:
            ok &= ensure_rule(
                serial, "iptables", ["-t", "nat"],
                ["-I", "OUTPUT", "1", "-d", host, "-p", "tcp",
                 "--dport", "80", "-m", "comment",
                 "--comment", LOCAL_LAN_ROUTE_COMMENT, "-j", "DNAT",
                 "--to-destination", f"{host}:{http}"],
                [LOCAL_LAN_ROUTE_COMMENT, f"{host}:{http}"])
            ok &= ensure_rule(
                serial, "iptables", ["-t", "nat"],
                ["-I", "OUTPUT", "1", "-d", host, "-p", "tcp",
                 "--dport", "443", "-m", "comment",
                 "--comment", LOCAL_LAN_ROUTE_COMMENT, "-j", "DNAT",
                 "--to-destination", f"{host}:{https}"],
                [LOCAL_LAN_ROUTE_COMMENT, f"{host}:{https}"])
    return ok


# -- adb reverses ------------------------------------------------------------

def ensure_reverses(serial, ports, host_ports=None):
    """Map guest ports to host ports via adb reverse. host_ports defaults to
    the same port; the drift (guest 8080/8443 → host 9080/9443) routes
    guests to the LIVE stack even when a stale elevated copy holds the
    127.0.0.1-specific binds of the well-known ports (2026-09-07)."""
    host_ports = host_ports or ports
    res = run(["adb", "-s", serial, "reverse", "--list"])
    listed = {part for line in res.stdout.splitlines()
              for part in line.split() if part.startswith("tcp:")}
    ok = True
    for gport, hport in zip(ports, host_ports):
        token = f"tcp:{gport}"
        wanted = f"tcp:{gport} tcp:{hport}"
        if token in listed and wanted in res.stdout:
            print(f"[reverse] ok (already mapped): {wanted}")
            continue
        if token in listed:
            run(["adb", "-s", serial, "reverse", "--remove", token])
        r = run(["adb", "-s", serial, "reverse", token, f"tcp:{hport}"])
        if r.returncode != 0:
            print(f"[reverse] FAILED: {wanted} -> {r.stderr.strip()}")
            ok = False
        else:
            print(f"[reverse] added: {wanted}")
    return ok


# -- verify ------------------------------------------------------------------

def verify_dns(serial, host="127.0.0.1"):
    """The leaf's acceptance: the guest must resolve the platform RPC host
    to the target host IP through the bound hosts file."""
    res = su(serial, f"ping -c 1 -W 2 {VERIFY_HOST}", timeout=15)
    first = res.stdout.splitlines()[0] if res.stdout else ""
    if host in first:
        print(f"[verify] ok: {VERIFY_HOST} -> {host} in guest")
        return True
    print(f"[verify] FAILED: {VERIFY_HOST} did not resolve to {host} "
          f"-> {first or res.stderr.strip() or '(no output)'}")
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Idempotent guest routing re-apply "
                    "(bind mounts + tagged firewall + adb reverses).")
    ap.add_argument("--serial", default="emulator-5554",
                    help="adb device serial (default emulator-5554)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="target platform/match host IP (default 127.0.0.1; set to LAN IP for remote client)")
    ap.add_argument("--cert", default=None,
                    help="path to platform certificate PEM (default: auto-detect/generate)")
    ap.add_argument("--uid", type=int, default=10060,
                    help="game package uid for the local-only REJECT "
                         "(installation-specific, default 10060)")
    ap.add_argument("--http", type=int, default=8080,
                    help="host http port behind the 80 REDIRECT")
    ap.add_argument("--https", type=int, default=8443,
                    help="host https port behind the 443 REDIRECT")
    ap.add_argument("--host-http", type=int, default=None,
                    help="HOST-side port for the guest tcp:HTTP reverse "
                         "(default: same as --http; drift to 9080 when a "
                         "stale elevated stack holds 127.0.0.1:8080)")
    ap.add_argument("--host-https", type=int, default=None,
                    help="HOST-side port for the guest tcp:HTTPS reverse "
                         "(default: same as --https; drift to 9443 when a "
                         "stale elevated stack holds 127.0.0.1:8443)")
    ap.add_argument("--gateway-port", type=int, default=7102,
                    help="current match gateway port (drifts; see leaf)")
    ap.add_argument("--heartbeat-port", type=int, default=2114,
                    help="current heartbeat port (drifts; see leaf)")
    ap.add_argument("--redirect-lan", action="store_true",
                    help="redirect port 80/443 to http/https ports for remote host")
    ap.add_argument("--skip-verify", action="store_true",
                    help="skip the guest DNS ping check")
    args = ap.parse_args(argv)

    if args.host_http is None:
        args.host_http = args.http
    if args.host_https is None:
        args.host_https = args.https

    if not preflight(args.serial):
        print(f"[adb] no shell service on {args.serial} — restart the "
              "emulator or adb (leaf: 'ADB shells timing out')")
        return 2

    ok = True
    ok &= ensure_hosts_source(args.serial, args.host)
    ok &= ensure_cacerts_source(args.serial, args.cert)

    lines = mounts(args.serial)
    ok &= ensure_mount(args.serial, lines, HOSTS_SRC, HOSTS_TARGET,
                       lambda s: hosts_content_ok(s, args.host))
    ok &= ensure_mount(args.serial, lines, CACERTS_SRC, CACERTS_TARGET,
                       cacerts_content_ok)
    ok &= ensure_firewall(args.serial, args.uid, args.http, args.https,
                          host=args.host, redirect_lan=args.redirect_lan)
    if args.host == "127.0.0.1":
        ok &= ensure_reverses(
            args.serial,
            [args.http, args.https, args.gateway_port, args.heartbeat_port],
            [args.host_http, args.host_https, args.gateway_port, args.heartbeat_port])
    ok &= True if args.skip_verify else verify_dns(args.serial, args.host)

    print("[guest] RESULT:", "OK" if ok else "INCOMPLETE — see [..] FAILED/"
          "CONFLICT/MISSING lines above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
