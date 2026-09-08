"""Read authored launch-socket names and hashes from an owned hero/minion CFF.

1037's launch hash matches FNV-1a of names in the selected skin's socket vector.
This inspector prints only names, hashes and offsets. It does not infer the
separate projectile-kind ID, launch-argument semantics or projectile speed.
The decrypted INST remains in memory; no payload or asset is written.
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


def socket_hash(name: str) -> int:
    value = 2166136261
    for octet in name.encode('ascii'):
        value = ((value ^ octet) * 16777619) & 0xffffffff
    return value


def read_projectile_sockets(path: Path, skin: str | None = None) -> dict:
    """Resolve root+356 -> skin vector -> skin+32 -> named socket records."""
    data = path.read_bytes()
    if data[:4] == b'RSC0':
        data = data[32:]
    if data[:4] != b'CFF0' or len(data) < 24:
        raise ValueError('expected an owned CFF0 hero/minion definition')
    chunks = {}
    at = struct.unpack_from('<I', data, 20)[0]
    while at + 8 <= len(data):
        tag, size = struct.unpack_from('<4sI', data, at)
        if size < 8 or at + size > len(data):
            raise ValueError('invalid CFF chunk boundary')
        chunks[tag] = data[at + 8:at + size]
        at += size
        if tag == b'SYMB':
            break
    if b'INST' not in chunks or b'PTCH' not in chunks:
        raise ValueError('first CFF revision lacks INST/PTCH metadata')
    plain = decode_inst(chunks[b'INST'], FIRST_REVISION_ENTRY)
    patch = chunks[b'PTCH']
    if len(patch) < 8:
        raise ValueError('truncated PTCH header')
    count = struct.unpack_from('<I', patch)[0]
    end = 8 + count * 8
    if not end <= len(patch) <= end + 15 or any(patch[end:]):
        raise ValueError('unexpected first-revision PTCH shape')
    refs = dict(struct.unpack_from('<II', patch, 8 + index * 8) for index in range(count))

    def string(offset):
        if not 0 <= offset < len(plain):
            raise ValueError('name pointer outside INST')
        end = plain.find(b'\0', offset)
        if end < offset:
            raise ValueError('unterminated metadata name')
        name = plain[offset:end].decode('ascii')
        if not name or any(not 32 <= ord(char) < 127 for char in name):
            raise ValueError('invalid metadata name')
        return name

    def vector(offset):
        for index in range(4096):
            target = refs.get(offset + 4 * index)
            if target is None:
                return
            if not 0 <= target < len(plain):
                raise ValueError('vector pointer outside INST')
            yield target
        raise ValueError('unterminated metadata pointer vector')

    if 356 not in refs:
        raise ValueError('definition has no recovered skin vector')
    selected = None
    for record in vector(refs[356]):
        name = string(refs[record])
        if skin is None or name == skin:
            selected = (record, name)
            break
    if selected is None:
        raise ValueError('requested skin is absent from the owned definition')
    record, name = selected
    if record + 32 not in refs:
        raise ValueError('skin has no recovered socket vector')
    sockets = []
    for index, socket in enumerate(vector(refs[record + 32])):
        name_offset = refs[socket]
        key = string(name_offset)
        sockets.append({'index': index, 'name': key, 'hash': f'{socket_hash(key):08x}',
                        'record_offset': socket, 'name_offset': name_offset})
    return {'skin': name, 'skin_offset': record, 'sockets': sockets}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path, help='operator-owned hero/minion CFF outside the repository')
    parser.add_argument('--skin', help='exact authored skin name; defaults to the first/native default skin')
    args = parser.parse_args()
    print(json.dumps(read_projectile_sockets(args.file, args.skin), indent=2))
