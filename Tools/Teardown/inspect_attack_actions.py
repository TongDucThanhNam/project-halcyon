"""Read named attack groups from the operator-owned 4.13 hero CFF.

Only structural names, offsets and inferred action ordinals are printed.
INST stays in memory. The flattened ordinal rule is corroborated against
independent recorded 1045 attacks; group conditions/selection are not decoded.
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


def read_attack_actions(path: Path) -> list[dict]:
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

    def vector(at):
        for index in range(256):
            target = refs.get(at + index * 4)
            if target is None:
                return
            yield target
        raise ValueError('unterminated pointer vector')

    # The four shared actions follow the kit vector, then each attack group's
    # ordinary entries and critical entries. Corpus tests check this join.
    action = len(list(vector(refs[100]))) + 4
    result = []
    for group_index, group in enumerate(vector(refs[108])):
        for category, field in (('ordinary', 40), ('critical', 44)):
            for entry in vector(refs[group + field]):
                name_at = refs[entry]
                name = plain[name_at:plain.index(b'\0', name_at)].decode('ascii')
                if not name.startswith('Ability__'):
                    raise ValueError('unexpected attack action symbol')
                result.append({'group': group_index, 'category': category,
                               'index': action, 'name': name,
                               'group_offset': group, 'definition_offset': entry})
                action += 1
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    print(json.dumps(read_attack_actions(args.file), indent=2))
