"""Read static item attributes and selected named values from native CFF metadata.

Uses the already recovered INST cipher and the final 64-bit PTCH pointer graph.
No executable analysis, network activity, or payload extraction. Output contains
only record names, offsets, attribute IDs and numeric constants.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct

try:
    from .inspect_ability_constants import decode_inst, LAST_REVISION_ENTRY
except ImportError:
    from inspect_ability_constants import decode_inst, LAST_REVISION_ENTRY


def read_last_instance(path: Path) -> tuple[bytes, dict[int, int]]:
    data = path.read_bytes()
    if data[:4] == b"RSC0":
        data = data[32:]
    if data[:4] != b"CFF0":
        raise ValueError("expected an original CFF0 metadata container")
    offset = struct.unpack_from("<I", data, 20)[0]
    instances, patches = [], []
    while offset + 8 <= len(data):
        tag, size = struct.unpack_from("<4sI", data, offset)
        if size < 8 or offset + size > len(data):
            raise ValueError("invalid CFF chunk boundary")
        body = data[offset + 8:offset + size]
        if tag == b"INST":
            instances.append(body)
        if tag == b"PTCH":
            patches.append(body)
        offset += size
    if not instances or len(instances) != len(patches):
        raise ValueError("each INST requires its PTCH group")
    instance = decode_inst(instances[-1], LAST_REVISION_ENTRY)
    patch = patches[-1]
    count = struct.unpack_from("<I", patch)[0]
    end = 8 + count * 8
    if not end <= len(patch) <= end + 15 or any(patch[end:]):
        raise ValueError("unexpected PTCH relocation shape")
    refs = dict(struct.unpack_from("<II", patch, 8 + i * 8) for i in range(count))
    if any(slot % 8 or slot + 8 > len(instance) or target >= len(instance)
           for slot, target in refs.items()):
        raise ValueError("expected the final 64-bit pointer revision")
    return instance, refs


def _string(instance: bytes, target: int) -> str:
    end = instance.find(b"\0", target)
    if end < 0:
        raise ValueError("unterminated metadata name")
    return instance[target:end].decode("ascii")


def read_item_stats(path: Path) -> list[dict]:
    """Root +72 -> pointer array -> {u32 attr, f32 value, u32 zero, u32 mode}."""
    instance, refs = read_last_instance(path)
    pointer = refs.get(72)
    if pointer is None:
        raise ValueError("item has no static attribute-array pointer")
    records = []
    while pointer in refs:
        record = refs[pointer]
        if record + 16 > len(instance):
            raise ValueError("item attribute record exceeds the instance")
        attribute, value, reserved, mode = struct.unpack_from("<IfII", instance, record)
        if reserved != 0 or mode not in (1, 2, 3) or not math.isfinite(value):
            raise ValueError("unexpected item attribute record")
        records.append({"attribute": attribute, "value": value,
                        "metadata_mode": mode, "record_offset": record})
        pointer += 8
    if pointer + 8 > len(instance) or any(instance[pointer:pointer + 8]):
        raise ValueError("expected the item attribute array's null terminator")
    return records


def read_named_constants(path: Path, fields: set[str]) -> list[dict]:
    """Resolve selected variable-name pointers; the f32 base follows the u64 pointer."""
    instance, refs = read_last_instance(path)
    records = []
    for slot, target in refs.items():
        try:
            name = _string(instance, target)
        except (ValueError, UnicodeDecodeError):
            continue
        if name.casefold() not in fields:
            continue
        if slot + 24 > len(instance):
            raise ValueError("named numeric record exceeds the instance")
        coefficients = struct.unpack_from("<4f", instance, slot + 8)
        if not all(math.isfinite(value) for value in coefficients):
            raise ValueError("nonfinite named numeric coefficient")
        records.append({"name": name, "coefficients": coefficients,
                        "record_offset": slot})
    return sorted(records, key=lambda row: row["record_offset"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="operator-owned item or ability CFF outside the repository")
    parser.add_argument("--field", action="append", help="selected named numeric variable; repeat as needed")
    parser.add_argument("--ability-only", action="store_true", help="skip item static-array inspection")
    args = parser.parse_args()
    result = {}
    if not args.ability_only:
        result["stats"] = read_item_stats(args.file)
    result["variables"] = read_named_constants(args.file, {name.casefold() for name in (args.field or ["Cooldown", "MOVE"])})
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
