"""Submit a bounded local fixture request to HALCYON_QA_DIR.

Examples: python Tools/sandbox_qa.py snapshot
          python Tools/sandbox_qa.py teleport --eid 1500 --x -88.5 --y 2
          python Tools/sandbox_qa.py resources --eid 1500 --gold 10000
The server must already run with the same explicit external QA directory.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.sandbox_qa import MAX_REQUEST_BYTES, SandboxQA, atomic_json, validate_command


def submit(command, *, timeout=5.0, request_id=None):
    if not math.isfinite(timeout) or not 0 <= timeout <= 10:
        raise ValueError("timeout must be within 0..10 seconds")
    validate_command(command)
    if len(json.dumps(command, allow_nan=False).encode()) > MAX_REQUEST_BYTES:
        raise ValueError("QA request is too large")
    mailbox = SandboxQA.from_environment()
    if mailbox is None:
        raise ValueError("HALCYON_QA_DIR must name the same external directory used by the server")
    identity = request_id or uuid.uuid4().hex
    if len(identity) > 64 or not identity or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in identity):
        raise ValueError("invalid request identity")
    request = mailbox.directory / f"command-{identity}.json"
    result = mailbox.directory / f"ack-{identity}.json"
    if request.exists() or result.exists() or (mailbox.consumed / request.name).exists():
        raise ValueError("request identity already used")
    atomic_json(request, command)
    deadline = time.monotonic() + timeout
    while True:
        if result.is_file():
            with result.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("QA result exceeds 1 MiB")
            return json.loads(raw)
        if time.monotonic() >= deadline:
            return {"id": identity, "pending": True, "result_path": str(result),
                    "message": "No acknowledgement yet; inspect this result path before submitting another command."}
        time.sleep(min(.05, max(0, deadline - time.monotonic())))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=5, help="wait up to 10 seconds; default 5")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("snapshot")
    teleport = commands.add_parser("teleport")
    teleport.add_argument("--eid", type=int, required=True)
    teleport.add_argument("--x", type=float, required=True)
    teleport.add_argument("--y", type=float, required=True)
    resources = commands.add_parser("resources")
    resources.add_argument("--eid", type=int, required=True)
    for field in ("hp", "energy", "gold"):
        resources.add_argument("--" + field, type=float)
    damage = commands.add_parser("damage")
    damage.add_argument("--source", type=int, required=True)
    damage.add_argument("--target", type=int, required=True)
    damage.add_argument("--amount", type=float, required=True)
    damage.add_argument("--kind", choices=("weapon", "crystal", "true"), required=True)
    status = commands.add_parser("status")
    status.add_argument("--eid", type=int, required=True)
    status.add_argument("--type", choices=("STUN", "SILENCE", "KNOCKBACK", "SLOW"), required=True)
    status.add_argument("--duration", type=float, required=True)
    for field in ("magnitude", "dx", "dy", "speed"):
        status.add_argument("--" + field, type=float)
    learn = commands.add_parser("learn")
    learn.add_argument("--eid", type=int, required=True)
    learn.add_argument("--slot", type=int, choices=(0, 1, 2), required=True)
    arguments = vars(parser.parse_args(argv))
    timeout = arguments.pop("timeout")
    command = {key: value for key, value in arguments.items() if value is not None}
    try:
        result = submit(command, timeout=timeout)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result.get("ok") else 2 if result.get("pending") else 1


if __name__ == "__main__":
    raise SystemExit(main())
