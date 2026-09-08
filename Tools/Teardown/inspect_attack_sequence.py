"""Audit attack/wave ordering in your own external pcap or VGR corpus.

Examples (no capture payload is written into the repository):
  python Tools/Teardown/inspect_attack_sequence.py --pcap <capture.pcap> \
      --match <match-uuid> --source-eid 1516
  python Tools/Teardown/inspect_attack_sequence.py --vgr <chunk-directory> \
      --source-eid 1516 --limit 8

1045 variant meaning and native projectile rendering require client evidence.
Following damage records are sequence observations, not proof of causality.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import decode, roster, vgdecode
from server.actor_slots import ActorSlots


def pcap_frame_times(path, selected_flow, start, frame_count):
    """Frame completion times from first captured TCP bytes, not sim ticks."""
    data = path.read_bytes()
    formats = {b'\xd4\xc3\xb2\xa1': ('<', 1_000_000), b'\xa1\xb2\xc3\xd4': ('>', 1_000_000),
               b'\x4d\x3c\xb2\xa1': ('<', 1_000_000_000), b'\xa1\xb2\x3c\x4d': ('>', 1_000_000_000)}
    if len(data) < 24 or data[:4] not in formats:
        raise ValueError('unsupported or truncated pcap header')
    endian, divisor = formats[data[:4]]
    linktype = struct.unpack_from(endian + 'I', data, 20)[0] & 255
    offset, segments = 24, []
    while offset < len(data):
        if offset + 16 > len(data):
            raise ValueError('truncated pcap record')
        seconds, fraction, size, _ = struct.unpack_from(endian + '4I', data, offset)
        offset += 16
        if offset + size > len(data):
            raise ValueError('truncated pcap packet')
        packet = vgdecode.l3(data[offset:offset + size], linktype)
        offset += size
        if packet is not None and packet[-1] and str(packet[:4]) == selected_flow:
            segments.append((packet[4], packet[5], seconds + fraction / divisor))
    if not segments:
        raise ValueError('decoded TCP flow has no timestamped packets')
    base = min(sequence for sequence, _, _ in segments)
    stream, received = {}, {}
    for sequence, payload, seconds in segments:
        for index, value in enumerate(payload, sequence - base):
            if index in stream and stream[index] != value:
                raise ValueError('conflicting TCP retransmission bytes')
            stream.setdefault(index, value)
            received.setdefault(index, seconds)
    raw = bytes(stream[index] for index in range(max(stream) + 1))
    offset, times = start, []
    for _ in range(frame_count):
        size = struct.unpack_from('>H', raw, offset)[0] + 2
        times.append(max(received[index] for index in range(offset, offset + size)))
        offset += size
    if offset != len(raw):
        raise ValueError('frame timestamps do not account for the complete stream')
    return [time - times[0] for time in times]


def inspect_variants(frames, times):
    """Join hero identity to action and subsequent matching class-5 damage.

    This proves observed associations only. Special/empowered/critical actions
    can also produce class-5 damage and require separate interpretation.
    """
    heroes, pending, results = {}, {}, {}
    for index, (opcode, payload) in enumerate(frames):
        if opcode == 1006 and len(payload) >= 168:
            eid, hero_id = struct.unpack_from('>II', payload, 160)
            heroes[eid] = hero_id
        if opcode == 1045 and len(payload) >= 9:
            source, target = struct.unpack_from('>II', payload)
            if source in heroes and target != source and target != 0xffffffff:
                hero_id = heroes[source]
                result = results.setdefault(hero_id, {'observed_variants': Counter(),
                            'damage_joined_variants': Counter(), 'examples': {}})
                result['observed_variants'][payload[8]] += 1
                pending[source] = (index, target, payload[8], hero_id)
        if opcode == 1054 and len(payload) >= 15 and payload[13] == 5:
            victim, source, delta = struct.unpack_from('>IIf', payload)
            action = pending.get(source)
            if action is not None and delta < 0 and victim == action[1] and 0 <= times[index] - times[action[0]] <= 3:
                begin, _, variant, hero_id = action
                result = results[hero_id]
                result['damage_joined_variants'][variant] += 1
                result['examples'].setdefault(variant, {'action_frame': begin, 'impact_frame': index,
                    'source': source, 'target': victim, 'delta': delta, 'damage_type': payload[14],
                    'seconds_after_action': times[index] - times[begin]})
                del pending[source]
    return results


def inspect(frames, source_eid, limit=8, times=None):
    attacks, current, variants = [], None, Counter()
    wave_count, wave_exact, wave_slots, wave_field_differences = 0, 0, 0, Counter()
    slots, slot_conflicts = ActorSlots(), []
    for index, (opcode, payload) in enumerate(frames):
        try:
            slots.observe(opcode, payload)
        except ValueError as exc:
            slot_conflicts.append({'frame': index, 'error': str(exc)})
        if opcode == 1045 and len(payload) == 14:
            source, target = struct.unpack_from('>II', payload)
            if source == source_eid and source != target and target != 0xffffffff:
                variants[payload[8]] += 1
                following = frames[index + 1] if index + 1 < len(frames) else (None, b'')
                current = {'frame': index, 'source': source, 'target': target,
                           'variant': payload[8],
                           'immediate_source_position': following[0] == 1070 and following[1][:4] == payload[:4],
                           'following_damage': []}
                if times is not None:
                    current['received_seconds'] = times[index]
                    if attacks and attacks[-1]['target'] == target:
                        current['same_target_start_gap'] = times[index] - times[attacks[-1]['frame']]
                attacks.append(current)
        elif opcode == 1054 and current is not None and len(payload) >= 12:
            victim, source, delta = struct.unpack_from('>IIf', payload)
            if source == source_eid and victim == current['target']:
                damage = {'frame': index, 'delta': delta, 'damage_fields': list(payload[12:15])}
                if times is not None:
                    damage['seconds_after_action'] = times[index] - times[current['frame']]
                current['following_damage'].append(damage)
        if opcode == 1010 and len(payload) == 126:
            archetype, _, eid = struct.unpack_from('>III', payload)
            if archetype not in (365, 366, 367, 368):
                continue
            wave_count += 1
            x, y = struct.unpack_from('>f', payload, 12)[0], struct.unpack_from('>f', payload, 20)[0]
            rebuilt = roster.build_minion_spawn_1010(archetype, eid, x, y, payload[116], payload[121])
            wave_exact += rebuilt == payload
            wave_field_differences.update(i for i, (a, b) in enumerate(zip(rebuilt, payload)) if a != b)
            # Enhanced captain spawns insert an attribute record before move.
            following = frames[index + 1:index + 4]
            movement = next((body for op, body in following if op == 1016), None)
            wave_slots += movement is not None and movement[0] == payload[116]
    timers = [{'frame': i, 'duration': struct.unpack_from('>f', p, 12)[0]}
              for i, (op, p) in enumerate(frames) if op == 1162 and len(p) >= 16
              and struct.unpack_from('>I', p)[0] == source_eid and p[4:8] == bytes.fromhex('d60c580b')]
    return {'frames': len(frames), 'source_eid': source_eid, 'default_attack_timers': timers,
            'attack_count': len(attacks), 'variants': dict(variants),
            'attacks_with_immediate_source_position': sum(row['immediate_source_position'] for row in attacks),
            'examples': attacks[:limit], 'wave_spawns': wave_count,
            'wave_spawns_matching_initial_template': wave_exact,
            'wave_spawn_field_differences': dict(wave_field_differences),
            'wave_move_uses_assigned_actor_slot': wave_slots,
            'actor_slot_conflicts': slot_conflicts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--pcap', type=Path)
    source.add_argument('--vgr', type=Path)
    parser.add_argument('--match')
    parser.add_argument('--source-eid', type=int)
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--variant-census', action='store_true', help='join every recorded hero to attack/damage variants')
    args = parser.parse_args()
    if args.source_eid is None and not args.variant_census:
        parser.error('--source-eid is required unless --variant-census is selected')
    if args.pcap:
        if not args.match:
            parser.error('--pcap requires --match')
        frames, stats = decode.decode_pcap(str(args.pcap), args.match)
        if frames is None or stats['missed']:
            parser.error(f'capture did not decode completely: {stats}')
        times = pcap_frame_times(args.pcap, stats['flow'], stats['start'], len(frames))
    else:
        pattern = f'*-{args.match}.*.vgr' if args.match else '*.vgr'
        paths = [args.vgr] if args.vgr.is_file() else sorted(args.vgr.glob(pattern),
                key=lambda p: ('.'.join(p.name.split('.')[:-2]), int(p.name.split('.')[-2])))
        if not paths:
            parser.error('no external VGR chunks found')
        matches = {'.'.join(path.name.split('.')[:-2]) for path in paths}
        if len(matches) > 1:
            parser.error('VGR directory contains multiple matches; use --match to select one')
        frames, times = [], []
        for path in paths:
            chunk, stats = decode.walk_vgr(str(path))
            if stats['failures']:
                parser.error(f'VGR did not decode completely: {path}')
            frames.extend((opcode, payload) for _, opcode, payload in chunk)
            times.extend(struct.unpack('>f', struct.pack('>I', token))[0] for token, _, _ in chunk)
    result = inspect_variants(frames, times) if args.variant_census else inspect(frames, args.source_eid, args.limit, times)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
