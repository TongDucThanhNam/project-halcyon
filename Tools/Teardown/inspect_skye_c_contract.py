"""Audit Skye C from owned definitions, native code and an existing frame cache.

No device/network operations and no payload export. Frame indexes are order,
not time. The cache is the existing (frames, origins) spawn-audit data; only
plain pickle data is accepted. Generated output belongs outside the repository.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import pickle
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.buff_wire import parse_buff_add
from Tools.Teardown.inspect_ability_actions import read_actions
from Tools.Teardown.inspect_ability_constants import read_records

BINARY_SHA256 = 'cd1b8831f82c469274613fc30f1f1f6e78c788102cdad7db5db2c04b96580a47'
VOLLEY_CLASS = 0xF59CDB08


class PlainDataUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise ValueError(f'cache contains executable/global object: {module}.{name}')


def fingerprint(path):
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def audit_frames(frames, origins):
    if len(frames) != len(origins):
        raise ValueError('every frame must retain its source origin')
    actors = []
    current = {}
    hits = []
    damage = []
    casts = {}
    for index, (op, body) in enumerate(frames):
        if not isinstance(op, int) or not isinstance(body, bytes):
            raise ValueError(f'invalid frame at {index}')
        ref = {'frame': index, 'origin': origins[index]}
        if op == 1046 and len(body) >= 17 and body[16] == 4:
            casts[struct.unpack_from('>I', body)[0]] = ref
        if op == 1010 and len(body) == 126:
            archetype, kind, eid = struct.unpack_from('>III', body)
            if kind == VOLLEY_CLASS and archetype in (384, 385):
                if eid in current:
                    raise ValueError(f'volley identity reused before release: {eid}')
                owner = struct.unpack_from('>I', body, 112)[0]
                actor = {'eid': eid, 'owner': owner, 'archetype': archetype,
                         'slot': body[116], 'spawn': ref,
                         'preceding_owner_action4': casts.get(owner),
                         'buffs': [], 'lifecycle': [], 'hit_markers': 0,
                         'actor_attributed_damage': 0}
                actors.append(actor)
                current[eid] = actor
        if op == 1086 and len(body) == 22:
            buff = parse_buff_add(body)
            actor = current.get(buff.target_eid)
            if actor is not None:
                actor['buffs'].append({**ref, 'source': buff.source_eid,
                    'kind': buff.kind, 'duration': buff.duration,
                    'instance': buff.instance_id})
            if buff.kind == 618:
                # Attribute only when one owner field has activated and has
                # not died. This is a structural candidate, not a causal ID.
                candidates = [a for a in current.values() if a['owner'] == buff.source_eid
                    and any(b['kind'] in (613, 615) for b in a['buffs'])
                    and not any(e['opcode'] == 1072 for e in a['lifecycle'])]
                for candidate in candidates:
                    if len(candidates) == 1:
                        candidate['hit_markers'] += 1
                hits.append({**ref, 'target': buff.target_eid,
                    'owner': buff.source_eid, 'duration': buff.duration,
                    'candidate_fields': [a['eid'] for a in candidates]})
        if op == 1054 and len(body) >= 14:
            target, source, delta, tag = struct.unpack_from('>IIfH', body)
            if source in current:
                current[source]['actor_attributed_damage'] += 1
            if tag == 394:
                damage.append({**ref, 'target': target, 'owner': source,
                               'delta': delta, 'tag': tag,
                               'byte14': body[14] if len(body) > 14 else None,
                               'byte15': body[15] if len(body) > 15 else None})
        if op in (1072, 1073, 1035) and len(body) >= 4:
            eid = struct.unpack_from('>I', body)[0]
            if eid in current:
                current[eid]['lifecycle'].append({**ref, 'opcode': op})
                if op == 1035:
                    del current[eid]

    # Consecutive markers for the same owner/victim bracket candidate damage;
    # no arbitrary time/frame-distance tolerance is used.
    by_pair = {}
    for hit in hits:
        by_pair.setdefault((hit['owner'], hit['target']), []).append(hit)
    paired = set()
    for pair, markers in by_pair.items():
        relevant = [d for d in damage if (d['owner'], d['target']) == pair]
        for position, marker in enumerate(markers):
            end = markers[position + 1]['frame'] if position + 1 < len(markers) else len(frames)
            candidates = [a for a in actors if a['eid'] in marker['candidate_fields']
                          and a['spawn']['frame'] <= marker['frame']
                          and (not a['lifecycle'] or marker['frame'] < a['lifecycle'][0]['frame'])]
            deaths = [e['frame'] for a in candidates for e in a['lifecycle'] if e['opcode'] == 1072]
            if deaths:
                end = min(end, min(deaths))
            matches = [d for d in relevant if marker['frame'] < d['frame'] < end]
            marker['candidate_damage_frames'] = [d['frame'] for d in matches]
            if len(matches) == 1 and len(marker['candidate_fields']) == 1:
                paired.add(matches[0]['frame'])
    return {'frames': len(frames), 'volleys': actors,
            'summary': {'volley_count': len(actors),
                'archetypes': dict(Counter(a['archetype'] for a in actors)),
                'complete_lifecycles': sum([e['opcode'] for e in a['lifecycle']] == [1072, 1073, 1035] for a in actors),
                'hit_markers': len(hits), 'tag394_damage': len(damage),
                'uniquely_bracketed_damage': len(paired),
                'actor_attributed_damage': sum(a['actor_attributed_damage'] for a in actors)},
            'hit_marker_associations': hits,
            'tag394_records': damage,
            'limits': ['One recording is not cross-match replication.',
                       'Frame indexes establish order, not elapsed time.',
                       'Unique active-field/owner association is not a wire causal ID.',
                       'S2C records do not establish the full server computation.']}


def inspect_native(path):
    import capstone
    from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_FP
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != BINARY_SHA256:
        raise ValueError('native anchors require the pinned owned ARM64 binary')
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('expected little-endian ELF64')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', data, phoff + i * size) for i in range(count)]

    def file_offset(native, length):
        segment = next(s for s in segments if s[0] == 1 and s[3] <= native and native + length <= s[3] + s[5])
        return segment[2] + native - segment[3]

    cs = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    cs.detail = True
    specs = [(0xE3FDF0, 0x174), (0xE3FF78, 0xBC), (0xE40040, 0x1A4),
             (0xDE3328, 0xC0), (0x92A0BC, 0x74)]
    anchors = []
    instructions = {}
    for ghidra, length in specs:
        native = ghidra - 0x100000
        offset = file_offset(native, length)
        decoded = list(cs.disasm(data[offset:offset + length], native))
        if sum(i.size for i in decoded) != length:
            raise ValueError('native function range does not fully disassemble')
        instructions.update({i.address: i for i in decoded})
        anchors.append({'ghidra': hex(ghidra), 'elf_va': hex(native),
                        'file_offset': offset, 'instructions': len(decoded),
                        'calls': [i.op_str for i in decoded if i.mnemonic == 'bl']})
    radius = instructions[0xD3FE28]
    half = instructions[0xD3FFDC]
    if radius.mnemonic != 'mov' or radius.operands[1].type != ARM64_OP_IMM:
        raise ValueError('cluster scalar anchor changed')
    if half.mnemonic != 'fmov' or half.operands[1].type != ARM64_OP_FP:
        raise ValueError('line endpoint anchor changed')
    selection_ops = [(instructions[a].mnemonic, instructions[a].op_str)
                     for a in (0xCE33BC, 0xCE33C0)]
    if selection_ops != [('fcmp', 's8, s0'), ('cset', 'w0, mi')]:
        raise ValueError('cluster selection comparison anchor changed')
    # Follow the actual cluster object's virtual call, not just the nearby
    # constant. This client accessor returns a subobject without using x1.
    accessor = struct.unpack_from('<Q', data, file_offset(0x26C1130 + 0x30, 8))[0]
    offset = file_offset(accessor, 8)
    accessor_ops = [(i.mnemonic, i.op_str) for i in cs.disasm(data[offset:offset + 8], accessor)]
    if accessor_ops != [('add', 'x0, x0, #0x10'), ('ret', '')]:
        raise ValueError('cluster accessor anchor changed')
    return {'binary': fingerprint(path), 'ghidra_rebase': '0x100000', 'anchors': anchors,
            'cluster_call_argument_scalar': struct.unpack('<f', struct.pack('<I', radius.operands[1].imm))[0],
            'cluster_accessor': {'vtable_elf_va': '0x26c1130', 'slot': '0x30',
                                 'target_elf_va': hex(accessor), 'instructions': accessor_ops,
                                 'uses_scalar_argument': False},
            'cluster_selection': {'elf_va': '0xce33bc', 'instructions': selection_ops,
                                  'condition': 'distance_squared < variable_squared',
                                  'action': 4, 'variable': 2},
            'line_endpoint_half_extent': half.operands[1].fp,
            'limits': ['The cluster constant is passed to an accessor that ignores it in this binary; it does not prove an operational hit radius.',
                       'Native client geometry alone does not establish complete hit filtering or server parity.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frame-cache', type=Path, required=True)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--definition', type=Path, required=True)
    args = parser.parse_args()
    with args.frame_cache.open('rb') as f:
        frames, origins = PlainDataUnpickler(f).load()
    print(json.dumps({'cache': fingerprint(args.frame_cache),
        'definition': {'file': fingerprint(args.definition), 'actions': read_actions(args.definition),
                       'named_records': read_records(args.definition,
                           {'cluster missile range', 'delay', 'duration', 'stun_duration',
                            'slowmagnitude', 'lockonmaxdistancebonus'})},
        'native': inspect_native(args.library), 'recording': audit_frames(frames, origins)}, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
