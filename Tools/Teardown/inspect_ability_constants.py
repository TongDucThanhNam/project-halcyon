"""Read selected numeric INST/PTCH records from an operator-owned CFF file.

Reproduces the mechanics-matrix section 18 name-pointer route. Never extracts
assets or writes decrypted payloads. All output is names, offsets and numbers.
Use named records rather than the older shifted 64-byte-cell TSV labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

MASK = 0xffffffff
GOLDEN = 0x9e3779b9
FIRST_REVISION_ENTRY = 0x9dea872e
LAST_REVISION_ENTRY = 0x56c6c3eb


def derive_key(entry: int, length: int) -> int:
    a, b, c = (GOLDEN + entry) & MASK, GOLDEN, length + 4
    a = ((a - b - c) & MASK) ^ (c >> 13)
    b = ((b - c - a) & MASK) ^ ((a << 8) & MASK)
    c = ((c - a - b) & MASK) ^ (b >> 13)
    a = ((a - b - c) & MASK) ^ (c >> 12)
    b = ((b - c - a) & MASK) ^ ((a << 16) & MASK)
    c = ((c - a - b) & MASK) ^ (b >> 5)
    a = ((a - b - c) & MASK) ^ (c >> 3)
    b = ((b - c - a) & MASK) ^ ((a << 10) & MASK)
    return ((c - a - b) & MASK) ^ (b >> 15)


def decode_inst(ciphertext: bytes, entry: int) -> bytes:
    key = derive_key(entry, len(ciphertext))
    previous = len(ciphertext)
    decoded = bytearray(ciphertext)
    for offset in range(0, len(ciphertext) & ~3, 4):
        word = struct.unpack_from("<I", ciphertext, offset)[0]
        rotated = ((previous << 1) | (previous >> 31)) & MASK
        struct.pack_into("<I", decoded, offset, key ^ rotated ^ word)
        previous = word
    return bytes(decoded)


def read_records(path: Path, fields: set[str], revision: str = "first") -> list[dict]:
    data = path.read_bytes()
    chains, current = [], {}
    offset = 0x40
    while offset + 8 <= len(data):
        tag, size = struct.unpack_from("<4sI", data, offset)
        if size < 8 or offset + size > len(data):
            raise ValueError(f"invalid CFF chunk at {offset:#x}")
        current[tag] = data[offset + 8:offset + size]
        if tag == b"SYMB":
            chains.append(current)
            current = {}
        offset += size
    if current:
        chains.append(current)
    if not chains:
        raise ValueError("CFF contains no revision chains")
    selected = chains[0 if revision == "first" else -1]
    plain = decode_inst(selected[b"INST"], FIRST_REVISION_ENTRY if revision == "first" else LAST_REVISION_ENTRY)
    relocations = selected[b"PTCH"]
    if len(relocations) % 8:
        raise ValueError("PTCH does not contain pairs of u32 words")
    records = []
    for slot, target in struct.iter_unpack("<II", relocations):
        if target == 0 or target >= len(plain) or slot + 28 > len(plain):
            continue
        end = plain.find(b"\0", target)
        if end < 0:
            continue
        try:
            name = plain[target:end].decode("ascii")
        except UnicodeDecodeError:
            continue
        if name.casefold() not in fields:
            continue
        values = struct.unpack_from("<6f", plain, slot + 4)
        records.append({"name": name, "pointer_offset": slot,
                        "coefficients": [round(value, 6) for value in values]})
    return sorted(records, key=lambda record: record["pointer_offset"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="operator-owned hero CFF file outside the repository")
    parser.add_argument("--revision", choices=("first", "last"), default="first")
    parser.add_argument("--field", action="append", help="numeric record label; repeat for more fields")
    args = parser.parse_args()
    fields = {field.casefold() for field in (args.field or ["Cooldown", "Energy Cost", "Range"])}
    print(json.dumps(read_records(args.file, fields, args.revision), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
