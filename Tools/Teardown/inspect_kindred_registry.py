"""Resolve requested registry names to numeric wire IDs from recovered metadata.

Reads a CFF0 manifest's first PTCH group and its already-decrypted 32-bit INST
outside the repository. No binary analysis, payload export, or network activity.

Example:
  python Tools/Teardown/inspect_kindred_registry.py --manifest <store-file> \
      --inst <KindredManifest.inst.bin> --name Item_SprintBoots --name Ringo
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct


def registry_entries(manifest: bytes, instance: bytes) -> dict[str, int | None]:
    """Resolve ID -> record -> symbol using the manifest's pointer relocations."""
    if manifest[:4] == b"RSC0":
        manifest = manifest[32:]
    if manifest[:4] != b"CFF0":
        raise ValueError("manifest must be a CFF0 container")
    offset = struct.unpack_from("<I", manifest, 20)[0]
    expected_size = None
    refs = None
    while offset + 8 <= len(manifest):
        tag = manifest[offset:offset + 4]
        size = struct.unpack_from("<I", manifest, offset + 4)[0]
        if size < 8 or offset + size > len(manifest):
            raise ValueError("invalid manifest chunk boundary")
        body = manifest[offset + 8:offset + size]
        if tag == b"INST" and expected_size is None:
            expected_size = len(body)
        if tag == b"PTCH" and expected_size is not None:
            count = struct.unpack_from("<I", body)[0]
            end = 8 + count * 8
            if not end <= len(body) <= end + 15 or any(body[end:]):
                raise ValueError("unexpected PTCH relocation shape")
            refs = dict(struct.unpack_from("<II", body, 8 + index * 8) for index in range(count))
            break
        offset += size
    if refs is None or expected_size != len(instance):
        raise ValueError("decrypted INST must match the first manifest revision")
    array_start = refs.get(0)
    if array_start != 4:
        raise ValueError("expected the recovered 32-bit registry array at offset 4")
    first_record = refs.get(array_start)
    if first_record is None or first_record <= array_start:
        raise ValueError("missing registry root record")
    result = {}
    for slot in range(array_start, first_record, 4):
        record = refs.get(slot)
        name_pointer = refs.get(record) if record is not None else None
        if name_pointer is None:
            continue  # alignment padding or a null registry entry
        if not 0 <= name_pointer < len(instance):
            raise ValueError("registry symbol pointer is outside the instance")
        end = instance.find(b"\0", name_pointer)
        if end < 0:
            raise ValueError("unterminated registry symbol")
        name = instance[name_pointer:end].decode("ascii").strip("*")
        # Several game-mode aliases occur twice. Never pick an arbitrary ID
        # for an ambiguous symbol; requested item/hero names are unique.
        result[name] = None if name in result else (slot - array_start) // 4
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inst", type=Path, required=True)
    parser.add_argument("--name", action="append", required=True,
                        help="exact registry symbol to resolve; repeat for several names")
    args = parser.parse_args()
    entries = registry_entries(args.manifest.read_bytes(), args.inst.read_bytes())
    missing = [name for name in args.name if name not in entries]
    if missing:
        parser.error("symbols absent: " + ", ".join(missing))
    ambiguous = [name for name in args.name if entries[name] is None]
    if ambiguous:
        parser.error("symbols have multiple registry entries: " + ", ".join(ambiguous))
    print(json.dumps({name: entries[name] for name in args.name}, indent=2))


if __name__ == "__main__":
    main()
