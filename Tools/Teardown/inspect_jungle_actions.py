"""Read the direct NPC action vector from an operator-owned first-revision CFF.

Only structural symbols and offsets are returned. NPC PTCH+100 is a direct
action vector, and each action's Ability__ symbol is at entry+4. Heroes use
the separate kit/shared/group flattening in inspect_attack_actions.py.
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


def read_jungle_actions(path: Path) -> list[dict]:
    data = path.read_bytes()
    chunks, offset = {}, 64
    while offset + 8 <= len(data):
        tag, size = struct.unpack_from('<4sI', data, offset)
        if size < 8 or offset + size > len(data):
            raise ValueError('invalid CFF chunk boundary')
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
        name = plain[name_at:plain.index(b'\0', name_at)].decode('ascii')
        if not name.startswith('Ability__'):
            raise ValueError('unexpected NPC action symbol')
        result.append({'index': index, 'name': name, 'definition_offset': entry})
    raise ValueError('unterminated NPC action vector')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    print(json.dumps(read_jungle_actions(args.file), indent=2))
