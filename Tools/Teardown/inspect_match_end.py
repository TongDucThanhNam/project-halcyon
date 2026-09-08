"""Read an external VGR match and print scalar structure/result evidence.

No captured payload is copied into the repository or included in the report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server.decode import walk_vgr


def inspect(directory: Path, match_id: str, entity_ids: list[int]) -> dict:
    paths = sorted(directory.glob(f"*-{match_id}.*.vgr"),
                   key=lambda path: int(path.name.rsplit(".", 2)[1]))
    if not paths:
        raise ValueError("no VGR chunks matched this directory and match id")
    records = []
    failures = 0
    for path in paths:
        frames, stats = walk_vgr(path)
        failures += stats["failures"] + bool(stats["trailing"])
        for row, (token, opcode, payload) in enumerate(frames):
            seconds = struct.unpack(">f", struct.pack(">I", token))[0]
            records.append((path.name, row, seconds, opcode, payload))

    def location(index: int, record: tuple) -> dict:
        path, row, seconds, _, _ = record
        return {"merged_index": index, "file": path, "row": row, "seconds": seconds}

    endings = []
    entities = {eid: {"entity_id": eid, "snapshot_count": 0, "damage_count": 0,
                      "damage_sum": 0.0, "death_notifications": [],
                      "destroy_or_despawn_count": 0, "substate_count": 0}
                for eid in entity_ids}
    for index, record in enumerate(records):
        _, _, _, op, payload = record
        if op == 1009:
            winner, reason, padding = struct.unpack(">IBB", payload)
            endings.append({**location(index, record), "opcode": op,
                            "winner": winner, "reason": reason, "padding": padding})
        elif op in (1106, 1165):
            endings.append({**location(index, record), "opcode": op,
                            "payload_size": len(payload)})
        if op == 1010 and len(payload) >= 44:
            eid = struct.unpack_from(">I", payload, 8)[0]
            if eid in entities:
                data = entities[eid]
                hp, max_hp = struct.unpack_from(">ff", payload, 36)
                data["snapshot_count"] += 1
                data["last_snapshot"] = {**location(index, record), "hp": hp, "max_hp": max_hp}
                if max_hp > 0 and "initial_state" not in data:
                    data["initial_state"] = {"position": struct.unpack_from(">fff", payload, 12),
                                             "hp": hp, "max_hp": max_hp}
        if len(payload) < 4:
            continue
        victim = struct.unpack_from(">I", payload)[0]
        if victim not in entities:
            continue
        data = entities[victim]
        if op == 1054:
            _, attacker, delta = struct.unpack_from(">IIf", payload)
            data["damage_count"] += 1
            data["damage_sum"] += delta
            data["last_damage"] = {**location(index, record), "attacker": attacker, "delta": delta}
        elif op == 1072:
            data["death_notifications"].append({**location(index, record),
                "killer": struct.unpack_from(">I", payload, 4)[0], "payload_size": len(payload)})
        elif op in (1073, 1035):
            data["destroy_or_despawn_count"] += 1
        elif op == 1068:
            data["substate_count"] += 1
    return {"match_id": match_id, "chunks": len(paths), "frames": len(records),
            "walk_failures": failures, "ending_events": endings,
            "entities": list(entities.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vgr-directory", type=Path, required=True)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--entities", nargs="*", type=int, default=[])
    args = parser.parse_args()
    print(json.dumps(inspect(args.vgr_directory, args.match_id, args.entities), indent=2))


if __name__ == "__main__":
    main()
