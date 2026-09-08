"""Read native/live actor visibility banks and correlate real client targets.

Only reads existing local captures or wire traces; no packets are sent and
no corpus payloads are exported. Four 1067 fields remain raw numeric values.
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

from Tools.Teardown.inspect_item_input import CapturedFrame, read_capture
from server.vision import VisibilityUpdate, parse_visibility


def initial_hero_banks(payload):
    if len(payload) != 750:
        raise ValueError('hero bank observation requires the native 750-byte 1011')
    return {index: (payload[713 + index], payload[721 + index], payload[729 + index])
            for index in range(8)}


def read_wire(path, connection=None):
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    connections = {row['connection'] for row in rows if row['opcode'] == 1001 and row['direction'] == 's2c'}
    if connection is None:
        if len(connections) != 1:
            raise ValueError(f'wire trace has {len(connections)} connections; select --connection explicitly')
        connection = next(iter(connections))
    output = {'c2s': [], 's2c': []}
    for row in rows:
        if row['connection'] == connection and row['direction'] in output:
            output[row['direction']].append(CapturedFrame(row['time'], row['opcode'], bytes.fromhex(row['payload'])))
    return output


def inspect(frames, viewer_index=1, eid=None, limit=12):
    if not 0 <= viewer_index <= 7:
        raise ValueError('viewer index must be 0..7')
    initial, banks, heroes, positions, alive, transitions = {}, {}, {}, {}, {}, []
    fields = Counter()
    entity_counts = Counter()
    for index, row in enumerate(frames['s2c']):
        payload, opcode = row.payload, row.opcode
        if opcode == 1011 and len(payload) == 750:
            actor = int.from_bytes(payload[8:12], 'big')
            heroes[actor] = {'hero_id': int.from_bytes(payload[:4], 'big'), 'team': int.from_bytes(payload[12:16], 'big')}
            actor_banks = initial_hero_banks(payload)
            initial[actor] = actor_banks
            banks.update(((actor, viewer), values) for viewer, values in actor_banks.items())
            alive[actor] = struct.unpack_from('>f', payload, 42)[0] > 0
        elif opcode == 1070 and len(payload) == 14:
            actor = int.from_bytes(payload[:4], 'big')
            positions[actor] = struct.unpack_from('>ff', payload, 4)
        elif opcode in (1072, 1074):
            alive[int.from_bytes(payload[:4], 'big')] = opcode == 1074
        elif opcode == 1067:
            update = parse_visibility(payload)
            old = banks.get((update.eid, update.viewer_index))
            banks[update.eid, update.viewer_index] = update.values
            entity_counts[update.eid] += 1
            if (eid is None or update.eid == eid) and update.viewer_index == viewer_index:
                fields[update.values] += 1
                transitions.append({'frame': index, 'time': row.time, 'eid': update.eid,
                    'before': old, 'after': update.values, 'alive': alive.get(update.eid),
                    'position': positions.get(update.eid)})
    selected = [actor for actor in sorted(heroes) if eid is None or actor == eid]
    clicks = []
    for request in frames['c2s']:
        if request.opcode != 1060 or len(request.payload) != 6:
            continue
        target = int.from_bytes(request.payload[:4], 'big')
        if eid is not None and target != eid:
            continue
        prior = [(index, row) for index, row in enumerate(frames['s2c'])
                 if row.time <= request.time and row.opcode == 1067
                 and int.from_bytes(row.payload[:4], 'big') == target and row.payload[4] == viewer_index]
        if prior:
            index, row = prior[-1]
            update = parse_visibility(row.payload)
            clicks.append({'time': request.time, 'target': target, 'hero': heroes.get(target),
                           'visibility_frame': index, 'visibility_time': row.time, 'values': update.values})
        else:
            clicks.append({'time': request.time, 'target': target, 'hero': heroes.get(target),
                           'visibility_frame': None, 'initial_values': initial.get(target, {}).get(viewer_index)})
    return {'server_frames': len(frames['s2c']), 'viewer_index': viewer_index,
            'heroes': [{**heroes[actor], 'eid': actor, 'initial_values': initial[actor][viewer_index],
                        'last_values': banks.get((actor, viewer_index)), 'position': positions.get(actor),
                        'visibility_events': entity_counts[actor]} for actor in selected],
            'field_counts': [{'values': values, 'count': count} for values, count in sorted(fields.items())],
            'transition_count': len(transitions), 'transitions': transitions[:limit],
            'click_count': len(clicks), 'clicks': clicks[:limit]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--pcap', type=Path)
    source.add_argument('--wire', type=Path)
    parser.add_argument('--match')
    parser.add_argument('--port', type=int, default=7034)
    parser.add_argument('--connection', type=int)
    parser.add_argument('--viewer', type=int, default=1)
    parser.add_argument('--eid', type=int)
    parser.add_argument('--limit', type=int, default=12)
    arguments = parser.parse_args()
    try:
        if arguments.pcap:
            if not arguments.match:
                parser.error('--pcap requires --match')
            frames = read_capture(arguments.pcap, arguments.match, arguments.port)
        else:
            frames = read_wire(arguments.wire, arguments.connection)
        result = inspect(frames, arguments.viewer, arguments.eid, arguments.limit)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
