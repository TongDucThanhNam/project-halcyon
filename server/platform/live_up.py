"""One command for the whole host side of a live run:

    python -m server.platform.live_up

1. stop any previous instance of this stack (processes whose command line
   contains `server.platform.local_stack`; a stale NON-stack holder of
   :80/:443 is left alone — the stack tolerates it by design);
2. start a fresh `python -m server.platform.local_stack` detached, output
   to the private runtime directory's live-stdout.txt;
3. wait until the gateway/heartbeat ports listen (from answers.json
   `_gw_port`/`_hb_port`);
4. re-apply the guest routing via server.platform.guest_setup (idempotent).

After this: force-stop + relaunch the game on the emulator and drive the
taps; the platform FSM is automatic (boot=menus, joinLobby->playing).
"""
import os
import subprocess
import sys
import time

from . import guest_setup, local_stack

KILL_PS = ("Get-CimInstance Win32_Process "
           "-Filter \"Name like 'python%'\" "
           "| Where-Object {$_.CommandLine -match 'local_stack'} "
           "| Select-Object -ExpandProperty ProcessId")


def _running_pids() -> list[int]:
    res = subprocess.run(["powershell", "-NoProfile", "-c", KILL_PS],
                         capture_output=True, text=True, timeout=30)
    return [int(line) for line in res.stdout.split()
            if line.strip().isdigit()]


def _ports_listening(ports: list[int]) -> bool:
    res = subprocess.run(["netstat", "-ano"], capture_output=True,
                         text=True, timeout=30)
    listening = set()
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "TCP" and parts[3] == "LISTENING":
            try:
                listening.add(int(parts[1].rsplit(":", 1)[1]))
            except ValueError:
                pass
    return all(p in listening for p in ports)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="One command for the host side of a live run")
    ap.add_argument("--bind-host", default=None,
                    help="IP to bind stack listeners to (default 0.0.0.0)")
    ap.add_argument("--match-host", default=None,
                    help="Host IP returned in playing state (default 127.0.0.1 or LAN IP)")
    ap.add_argument("--serial", default="emulator-5554",
                    help="ADB serial of the local emulator to configure (default emulator-5554)")
    ap.add_argument("--device-serial", default=None,
                    help="second local emulator; its guest 8443 reverse maps to "
                         "--device-host-https where the stack keys a per-device "
                         "identity (cloned images share hwid + token)")
    ap.add_argument("--device-host-https", type=int, default=9444,
                    help="host TLS port of the per-device listener (default 9444)")
    ap.add_argument("--skip-guest", action="store_true",
                    help="Skip running guest_setup after stack startup")
    args = ap.parse_args(argv)

    pids = _running_pids()
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=30)
        print(f"[live] stopped previous stack pid {pid}")
    if not pids:
        print("[live] no previous stack process found")

    answers = local_stack._answers()
    ports = [int(answers.get("_gw_port", 7100)),
             int(answers.get("_hb_port", 2112)),
             8080, 8443]
    if args.device_serial:
        ports.append(args.device_host_https)
    log_path = os.path.join(local_stack.STACK_DIR, "live-stdout.txt")
    os.makedirs(local_stack.STACK_DIR, exist_ok=True)

    cmd = [sys.executable, "-B", "-u", "-m", "server.platform.local_stack"]
    if args.bind_host:
        cmd += ["--bind-host", args.bind_host]
    if args.match_host:
        cmd += ["--match-host", args.match_host]

    env = dict(os.environ)
    if args.device_serial:
        # Tag = device serial → identity survives port drift across restarts.
        env["HALCYON_DEVICE_PORTS"] = f"{args.device_host_https}={args.device_serial}"
        print(f"[live] device listener: {args.device_serial} -> TLS :{args.device_host_https}")

    with open(log_path, "ab") as log_fh:
        proc = subprocess.Popen(
            cmd, env=env,
            stdout=log_fh, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP |
            subprocess.DETACHED_PROCESS)
    print(f"[live] stack starting detached (pid {proc.pid}, log {log_path})")

    deadline = time.time() + 30
    while time.time() < deadline:
        if _ports_listening(ports):
            print(f"[live] stack ports up: {ports}")
            break
        time.sleep(0.5)
    else:
        print(f"[live] FAILED: ports {ports} not listening within 30 s — "
              f"see {log_path}")
        return 2

    if args.skip_guest:
        print("[live] guest setup skipped as requested")
        return 0

    guest_argv = ["--serial", args.serial,
                  "--gateway-port", str(ports[0]),
                  "--heartbeat-port", str(ports[1]),
                  "--host-http", "9080", "--host-https", "9443"]
    if args.match_host and args.match_host != "127.0.0.1":
        guest_argv += ["--host", args.match_host]
    rc = guest_setup.main(guest_argv)
    if args.device_serial:
        device_argv = ["--serial", args.device_serial,
                       "--gateway-port", str(ports[0]),
                       "--heartbeat-port", str(ports[1]),
                       "--host-http", "9080",
                       "--host-https", str(args.device_host_https)]
        if args.match_host and args.match_host != "127.0.0.1":
            device_argv += ["--host", args.match_host]
        rc = guest_setup.main(device_argv) and rc
    print("[live] host side ready — relaunch the game and drive the taps")
    return rc


if __name__ == "__main__":
    sys.exit(main())
