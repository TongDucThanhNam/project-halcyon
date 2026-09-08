"""Audit native level increments, XP requirements and hero snapshot fields.

Reads operator-owned capture/trace bytes only. Output is numeric structure and
event timing; no payload is exported and no network traffic is sent.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Tools.Teardown.inspect_item_input import CapturedFrame, read_capture


@dataclass(frozen=True)
class HeroProgression:
    hero_id: int
    eid: int
    level: int
    unspent_points: int
    within_level_xp: float
    next_level_xp: float


def read_hero_progression(payload: bytes) -> HeroProgression:
    """1011: level@294, points@314, within-level XP@318, requirement@322."""
    if len(payload) not in (746, 750):
        raise ValueError("expected the measured hero snapshot shape")
    hero_id, eid = struct.unpack_from(">I", payload)[0], struct.unpack_from(">I", payload, 8)[0]
    level, points, xp, requirement = [struct.unpack_from(">f", payload, offset)[0]
                                     for offset in (294, 314, 318, 322)]
    if level not in range(1, 13) or points not in range(13):
        raise ValueError("unexpected native level or unspent-point value")
    if not all(math.isfinite(value) and value >= 0 for value in (xp, requirement)):
        raise ValueError("invalid native XP state")
    return HeroProgression(hero_id, eid, int(level), int(points), xp, requirement)


def parse_level_increment(payload: bytes) -> tuple[int, int]:
    """1076 is an entity-level increment, not the 1078 ability-slot request."""
    if len(payload) != 14 or payload[8:] != bytes(6):
        raise ValueError("1076 requires two u32 values and six zero bytes")
    eid, increment = struct.unpack_from(">II", payload)
    if increment != 1:
        raise ValueError("only the native single-level increment is measured")
    return eid, increment


def parse_xp_requirement(payload: bytes) -> tuple[int, float]:
    """1052 attribute39 has its measured set-style suffix, not item-add flags."""
    if (len(payload) != 22 or payload[4:8] != bytes.fromhex("ffffffff")
            or payload[12:] != bytes((39, 0, 1)) + bytes(7)):
        raise ValueError("unexpected native next-level XP attribute update")
    eid, requirement = struct.unpack_from(">I", payload)[0], struct.unpack_from(">f", payload, 8)[0]
    if not math.isfinite(requirement) or requirement <= 0:
        raise ValueError("invalid next-level XP requirement")
    return eid, requirement


def inspect_levels(frames: dict[str, list[CapturedFrame]], eid: int) -> dict:
    initial = [read_hero_progression(row.payload) for row in frames["s2c"]
               if row.opcode == 1011 and struct.unpack_from(">I", row.payload, 8)[0] == eid]
    events = []
    xp_total = 0.0
    for index, row in enumerate(frames["s2c"]):
        payload = row.payload
        if row.opcode == 1053 and payload[8] == 8 and struct.unpack_from(">I", payload)[0] == eid:
            xp_total += struct.unpack_from(">f", payload, 4)[0]
        if row.opcode != 1076 or parse_level_increment(payload)[0] != eid:
            continue
        requirements = []
        for following in frames["s2c"][index + 1:index + 16]:
            body = following.payload
            if following.time > row.time + 0.01:
                break
            if following.opcode == 1052 and struct.unpack_from(">I", body)[0] == eid and body[12] == 39:
                requirements.append(parse_xp_requirement(body)[1])
        events.append({"frame": index, "time": round(row.time, 6), "increment": 1,
                       "observed_xp_sum": round(xp_total, 6), "following_requirements": requirements})
    return {"eid": eid, "initial": [asdict(value) for value in initial],
            "level_events": events, "observed_xp_sum": round(xp_total, 6)}


def inspect_local_trace(path: Path, eid: int) -> dict:
    counts = Counter()
    xp = 0.0
    health = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["direction"] != "s2c":
            continue
        payload = bytes.fromhex(row["payload"])
        if len(payload) < 4 or struct.unpack_from(">I", payload)[0] != eid:
            continue
        opcode = row["opcode"]
        if opcode in (1076, 1082):
            counts[opcode] += 1
        if opcode == 1053 and payload[8] == 8:
            xp += struct.unpack_from(">f", payload, 4)[0]
        if opcode == 1053 and payload[8] == 0:
            health.append({"time": row["time"], "amount": struct.unpack_from(">f", payload, 4)[0]})
    return {"eid": eid, "level_increment_frames": counts[1076], "ability_rank_frames": counts[1082],
            "xp_sent": xp, "health_deltas": health}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--match", help="captured match UUID for a PCAP")
    parser.add_argument("--port", type=int, help="captured match TCP port")
    parser.add_argument("--eid", type=int, default=1500)
    parser.add_argument("--local-trace", action="store_true", help="read a local wire JSONL trace")
    args = parser.parse_args()
    if args.local_trace:
        result = inspect_local_trace(args.file, args.eid)
    else:
        if args.match is None or args.port is None:
            parser.error("PCAP inspection requires --match and --port")
        result = inspect_levels(read_capture(args.file, args.match, args.port), args.eid)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
