"""Project Halcyon — preauth response-shape probe (T1).

The client GETs ``/kindred/live/<REV>-status-redirect`` on
``preauth.superevil.net`` exactly twice at boot, then gives up. The response
format is unknown, so this driver tries candidate shapes against the live
client: for each candidate it (re)writes answers.json, restarts the client,
waits, and reports which requests followed. Success = anything beyond the
status-redirect itself (ideally a POST /JSONRpc/<service>).

Usage:  python -m server.platform.preauth_probe
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

STACK_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack")
ANSWERS_PATH = os.path.join(STACK_DIR, "answers.json")
HTTP_LOG = os.path.join(STACK_DIR, "http_log.txt")
CLIENT_DIR = r"D:\Downloads\vg\pc\Vainglory 4.13\Vainglory"
CLIENT_EXE = os.path.join(CLIENT_DIR, "Vainglory.exe")
WAIT_S = 40

CANDIDATES = [
    ("E1: 200 body = http url text",
     {"mode": "body", "body": "http://platform.superevil.net"}),
    ("E2: 200 body = json platformUrl",
     {"mode": "body", "body": {"platformUrl": "http://platform.superevil.net"}}),
    ("E3: 302 -> http://rpc.kindred-live.net/",
     {"mode": "302", "location": "http://rpc.kindred-live.net/"}),
    ("E4: 200 body = bare host",
     {"mode": "body", "body": "platform.superevil.net"}),
]


def kill_client() -> None:
    subprocess.run(["taskkill", "/f", "/im", "Vainglory.exe"],
                   capture_output=True)
    time.sleep(2)


def set_status_redirect(cfg: dict) -> None:
    with open(ANSWERS_PATH, encoding="utf-8") as fh:
        answers = json.load(fh)
    answers["status_redirect"] = cfg
    with open(ANSWERS_PATH, "w", encoding="utf-8") as fh:
        json.dump(answers, fh, indent=1)


def log_size() -> int:
    try:
        return os.path.getsize(HTTP_LOG)
    except OSError:
        return 0


def run_candidate(label: str, cfg: dict) -> str:
    kill_client()
    set_status_redirect(cfg)
    before = log_size()
    proc = subprocess.Popen([CLIENT_EXE], cwd=CLIENT_DIR)
    time.sleep(WAIT_S)
    with open(HTTP_LOG, "rb") as fh:
        fh.seek(before)
        delta = fh.read().decode("utf-8", "replace").strip()
    lines = [ln for ln in delta.splitlines() if ln]
    interesting = [ln for ln in lines if "status-redirect" not in ln]
    verdict = "NO FOLLOW-UP" if not interesting else f"FOLLOW-UP x{len(interesting)}"
    print(f"--- {label}: {verdict}")
    for ln in lines[:8]:
        print(f"    {ln[:160]}")
    return verdict


def main() -> None:
    if not os.path.isfile(CLIENT_EXE):
        raise SystemExit(f"client not found: {CLIENT_EXE}")
    for label, cfg in CANDIDATES:
        run_candidate(label, cfg)
    kill_client()
    print("done — stack left running; answers.json holds the last candidate")


if __name__ == "__main__":
    main()
