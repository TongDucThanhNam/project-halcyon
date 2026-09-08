"""Check actor creation/removal ordering in our local match-server JSONL trace.

Read-only: prints structural diagnostics, never packet bodies or credentials.
This detects specific protocol inconsistencies; a clean report is not proof
that a native client will accept the complete stream.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct


def inspect(path: Path):
    clients = {}
    problems = []
    for line_number, line in enumerate(path.open(encoding="utf-8"), 1):
        row = json.loads(line)
        if row["direction"] != "s2c":
            continue
        connection = row["connection"]
        state = clients.setdefault(connection, {
            "actors": {}, "slots": {}, "deaths": {}, "destroys": {}, "counts": Counter(),
            "death_to_removal_ms": [], "destroy_to_removal_ms": [],
        })
        opcode, payload = row["opcode"], bytes.fromhex(row["payload"])
        state["counts"][opcode] += 1

        def problem(kind, **fields):
            problems.append(dict(line=line_number, time=row["time"],
                                 connection=connection, kind=kind, **fields))

        if ((opcode == 1011 and len(payload) == 750)
                or (opcode == 1010 and len(payload) in (122, 126))):
            eid = struct.unpack_from(">I", payload, 8)[0]
            slot = payload[745 if opcode == 1011 else 116]
            old_owner = state["slots"].get(slot)
            old_slot = state["actors"].get(eid)
            if old_owner is not None and old_owner != eid:
                problem("occupied_slot", slot=slot, previous=old_owner, new=eid)
            if old_slot is not None and old_slot != slot:
                problem("actor_changed_slot", eid=eid, previous=old_slot, new=slot)
            state["slots"][slot] = eid
            state["actors"][eid] = slot
        elif opcode == 1054 and len(payload) >= 12:
            victim, attacker = struct.unpack_from(">II", payload)
            for role, eid in (("victim", victim), ("attacker", attacker)):
                if eid not in (0, 0xFFFFFFFF) and eid not in state["actors"]:
                    problem("combat_before_creation", role=role, eid=eid)
        elif opcode == 1070 and len(payload) >= 4:
            eid = struct.unpack_from(">I", payload)[0]
            if eid not in state["actors"]:
                problem("position_before_creation", eid=eid)
        elif opcode == 1072 and len(payload) >= 4:
            state["deaths"][struct.unpack_from(">I", payload)[0]] = row["time"]
        elif opcode == 1073 and len(payload) >= 4:
            state["destroys"][struct.unpack_from(">I", payload)[0]] = row["time"]
        elif opcode == 1035 and len(payload) >= 4:
            eid = struct.unpack_from(">I", payload)[0]
            slot = state["actors"].pop(eid, None)
            if slot is not None and state["slots"].get(slot) == eid:
                del state["slots"][slot]
            died = state["deaths"].pop(eid, None)
            if died is not None:
                state["death_to_removal_ms"].append((row["time"] - died) * 1000)
            destroyed = state["destroys"].pop(eid, None)
            if destroyed is not None:
                state["destroy_to_removal_ms"].append((row["time"] - destroyed) * 1000)
    summaries = {}
    for connection, state in clients.items():
        summaries[connection] = {
            "message_counts": dict(sorted(state["counts"].items())),
            "remaining_actors": len(state["actors"]),
            **{kind: {"count": len(state[kind]),
                      "min": min(state[kind], default=None),
                      "max": max(state[kind], default=None)}
               for kind in ("death_to_removal_ms", "destroy_to_removal_ms")},
        }
    return {"connections": summaries, "problems": problems}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    report = inspect(args.trace)
    print(json.dumps(report, indent=2))
    return int(bool(report["problems"]))


if __name__ == "__main__":
    raise SystemExit(main())
