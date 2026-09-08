"""Read native hero action ordinals from an operator-owned first-revision CFF.

Only names, offsets and numeric indices are returned. The decoded INST stays
in memory. Hero header PTCH[100] points to a null-terminated pointer vector;
each entry's PTCH[entry+4] names the native action. This is an action vector,
not the three UI slots: empowered attacks and alternate casts also occupy it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

try:
    from .inspect_ability_constants import decode_inst, FIRST_REVISION_ENTRY
except ImportError:
    from inspect_ability_constants import decode_inst, FIRST_REVISION_ENTRY


def read_actions(path: Path) -> list[dict]:
    data = path.read_bytes()
    offset, chunks = 64, {}
    while offset + 8 <= len(data):
        tag, size = struct.unpack_from('<4sI', data, offset)
        if size < 8 or offset + size > len(data):
            raise ValueError(f'invalid CFF chunk at {offset:#x}')
        chunks[tag] = data[offset + 8:offset + size]
        offset += size
        if tag == b'SYMB':
            break
    plain = decode_inst(chunks[b'INST'], FIRST_REVISION_ENTRY)
    refs = dict(struct.iter_unpack('<II', chunks[b'PTCH']))
    vector = refs[100]
    result = []
    for index in range(256):
        entry = refs.get(vector + index * 4)
        if entry is None:
            return result
        name_at = refs[entry + 4]
        end = plain.index(b'\0', name_at)
        name = plain[name_at:end].decode('ascii')
        if not name.startswith('Ability__'):
            raise ValueError(f'action {index} has an unexpected symbol: {name!r}')
        result.append({'index': index, 'pointer_offset': vector + index * 4,
                       'definition_offset': entry, 'name': name})
    raise ValueError('action list did not terminate within a u8 index')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    print(json.dumps(read_actions(args.file), indent=2))


if __name__ == '__main__':
    main()
