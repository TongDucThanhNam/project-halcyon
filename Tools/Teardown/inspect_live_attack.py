"""Audit attack/move/damage sequences in an existing local JSONL wire trace.

Read-only: prints numeric observations, never sends packets or QA commands.
Example:
  python Tools/Teardown/inspect_live_attack.py <wire.jsonl> --source-eid 1500 \
      --hero-id 395 --limit 12

Logged wall times and sampled positions do not expose projectile release,
rendered animation frames, or the full deterministic simulation state.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.attack_wire import MEASURED_BASIC_VARIANTS, SOURCE_BASIC_VARIANTS


INTENTS = frozenset((1012, 1041, 1042, 1060, 1096, 1098, 1102))


def read_rows(path, connection=None):
    rows, incomplete_tail = [], False
    for line_number, line in enumerate(path.read_bytes().splitlines(keepends=True), 1):
        if not line.strip():
            continue
        if not line.endswith(b'\n'):
            incomplete_tail = True
            continue
        try:
            row = json.loads(line)
            if not math.isfinite(row['time']) or row['direction'] not in ('c2s', 's2c'):
                raise ValueError('invalid time or direction')
            row['decoded'] = bytes.fromhex(row['payload'])
            row['line'] = line_number
            rows.append(row)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f'invalid trace line {line_number}: {error}') from error
    connections = sorted({row['connection'] for row in rows
                          if row['direction'] == 'c2s' and row['opcode'] == 1060})
    if connection is None:
        if len(connections) != 1:
            raise ValueError(f'target-intent connections are {connections}; select --connection')
        connection = connections[0]
    if connection not in {row['connection'] for row in rows}:
        raise ValueError(f'connection {connection} is absent')
    return [row for row in rows if row['connection'] == connection], connection, incomplete_tail


def reference(row):
    return {'line': row['line'], 'time': row['time'],
            'utc': datetime.fromtimestamp(row['time'], timezone.utc).isoformat(timespec='microseconds'),
            'opcode': row['opcode']}


def events_from_rows(rows, source_eid, hero_id=None):
    positions, events, active_target = {}, [], None
    last_action, backwards = None, []
    for index, row in enumerate(rows):
        if index and row['time'] < rows[index - 1]['time']:
            backwards.append(row['line'])
        payload, opcode, direction = row['decoded'], row['opcode'], row['direction']
        if direction == 's2c' and opcode == 1006 and len(payload) >= 168:
            eid, observed = struct.unpack_from('>II', payload, 160)
            if eid == source_eid:
                if hero_id is not None and hero_id != observed:
                    raise ValueError(f'hero identity disagrees at line {row["line"]}: {hero_id} != {observed}')
                hero_id = observed
        if direction == 's2c' and opcode == 1070:
            if len(payload) != 14 or payload[12:] != bytes(2):
                raise ValueError(f'invalid 1070 at line {row["line"]}')
            eid, x, y = struct.unpack_from('>Iff', payload)
            if not all(math.isfinite(value) for value in (x, y)):
                raise ValueError(f'nonfinite position at line {row["line"]}')
            observed_position = {**reference(row), 'xy': [x, y]}
            positions[eid] = observed_position
            if eid == source_eid and last_action is not None and last_action[0] == index - 1:
                last_action[1]['immediate_source_position_echo'] = observed_position
            continue
        event = None
        basic_actions = MEASURED_BASIC_VARIANTS.get(hero_id, SOURCE_BASIC_VARIANTS.get(hero_id, ()))
        if direction == 'c2s' and opcode in INTENTS:
            event = {**reference(row), 'kind': 'intent', 'hero_id': hero_id}
            if opcode == 1060:
                if len(payload) != 6 or payload[4:] != bytes(2):
                    raise ValueError(f'invalid target1060 at line {row["line"]}')
                active_target = struct.unpack_from('>I', payload)[0]
                event['known_basic_actions'] = list(basic_actions)
            elif opcode == 1012:
                if len(payload) != 14 or payload[8:] != bytes(6):
                    raise ValueError(f'invalid move1012 at line {row["line"]}')
                point = struct.unpack_from('>ff', payload)
                if not all(math.isfinite(value) for value in point):
                    raise ValueError(f'nonfinite move at line {row["line"]}')
                event['requested_xy'] = list(point)
            event['target_eid'] = active_target
        elif direction == 's2c' and opcode == 1045:
            if len(payload) != 14:
                raise ValueError(f'invalid action1045 at line {row["line"]}')
            source, target, action = struct.unpack_from('>IIB', payload)
            if source == source_eid and target not in (source_eid, 0xffffffff):
                event = {**reference(row), 'kind': 'action', 'source_eid': source,
                         'target_eid': target, 'hero_id': hero_id, 'action_id': action,
                         'known_ordinary_action': action in basic_actions if basic_actions else None}
                active_target = target
                last_action = index, event
        elif direction == 's2c' and opcode == 1054:
            if len(payload) < 15:
                raise ValueError(f'invalid damage1054 at line {row["line"]}')
            victim, source, delta = struct.unpack_from('>IIf', payload)
            if not math.isfinite(delta):
                raise ValueError(f'nonfinite damage at line {row["line"]}')
            if source == source_eid and delta < 0:
                event = {**reference(row), 'kind': 'damage', 'source_eid': source,
                         'target_eid': victim, 'delta': delta,
                         'damage_fields': list(payload[12:15]), 'damage_class': payload[13],
                         'damage_type': payload[14],
                         'ordinary_damage_candidate': payload[13] == 5 and payload[14] == 0}
        if event is not None:
            for label, eid in (('source_position', source_eid), ('target_position', event['target_eid'])):
                seen = positions.get(eid)
                event[label] = None if seen is None else {**seen, 'age_seconds': row['time'] - seen['time']}
            events.append(event)
    return events, backwards


def window(events, start_index, seconds, trace_end):
    """First movement is retained; any subsequent intent bounds its evidence."""
    start = events[start_index]
    move, hits = None, []
    bound = {'reason': 'trace_end', **reference(trace_end)}
    for event in events[start_index + 1:]:
        if event['time'] - start['time'] > seconds:
            bound = {'reason': 'time_limit', 'time': start['time'] + seconds,
                     'first_event_after_limit': reference(event)}
            break
        if event['kind'] == 'action':
            bound = {'reason': 'next_source_action', **reference(event)}
            break
        if event['kind'] == 'intent':
            if event['opcode'] == 1012 and move is None:
                move = event
                continue
            bound = {'reason': 'next_player_intent', **reference(event)}
            break
        if event['kind'] == 'damage' and event['target_eid'] == start['target_eid']:
            hits.append({**event, 'seconds_after_start': event['time'] - start['time']})
    if bound['reason'] == 'trace_end' and trace_end['time'] > start['time'] + seconds:
        bound = {'reason': 'time_limit', 'time': start['time'] + seconds}
    return move, hits, bound


def inspect(rows, source_eid, *, hero_id=None, seconds=3.0, from_line=1, to_line=None, limit=12):
    if not rows:
        raise ValueError('selected connection has no complete trace rows')
    if not math.isfinite(seconds) or seconds <= 0 or limit < 0:
        raise ValueError('seconds must be positive and finite; limit must be nonnegative')
    events, backwards = events_from_rows(rows, source_eid, hero_id)
    selected = lambda event: event['line'] >= from_line and (to_line is None or event['line'] <= to_line)
    examples, early_moves, last_intent = [], [], None
    for index, event in enumerate(events):
        if event['kind'] == 'intent':
            last_intent = event
            if event['opcode'] == 1060 and selected(event):
                move, hits, bound = window(events, index, seconds, rows[-1])
                if move is not None:
                    ordinary = [hit for hit in hits if hit['ordinary_damage_candidate']]
                    early_moves.append({'target_intent': event, 'move': move,
                        'following_damage': hits, 'observation_end': bound,
                        'candidate_cancel_before_attack_start': bool(event['known_basic_actions']) and not ordinary and bound['time'] > move['time'],
                        'seconds_observed_after_move': max(0, bound['time'] - move['time'])})
            continue
        if event['kind'] != 'action' or not selected(event):
            continue
        move, hits, bound = window(events, index, seconds, rows[-1])
        intent = last_intent if last_intent is not None and last_intent['opcode'] == 1060 and last_intent['target_eid'] == event['target_eid'] else None
        following = [hit for hit in hits if move is not None and hit['line'] > move['line']]
        ordinary_after_move = [hit for hit in following if hit['ordinary_damage_candidate']]
        ordinary = [hit for hit in hits if hit['ordinary_damage_candidate']]
        # A movement after an already observed ordinary hit is recovery only;
        # it cannot serve as a movement-before-first-hit observation.
        before_first_hit = move is not None and (not ordinary or move['line'] < ordinary[0]['line'])
        examples.append({'attack_start': event, 'target_intent': intent, 'move': move,
            'following_damage': hits, 'observation_end': bound,
            'candidate_move_before_hit': event['known_ordinary_action'] is True and before_first_hit and bool(ordinary_after_move),
            'candidate_windup_cancel': event['known_ordinary_action'] is True and before_first_hit and not ordinary and bound['time'] > move['time'],
            'seconds_observed_after_move': None if move is None else max(0, bound['time'] - move['time'])})
    candidates = [example for example in examples if example['candidate_move_before_hit'] or example['candidate_windup_cancel']]
    return {'source_eid': source_eid, 'complete_rows': len(rows), 'last_complete_row': reference(rows[-1]),
            'selected_start_lines': [from_line, to_line], 'per_attempt_seconds_limit': seconds,
            'action_ids': dict(Counter(example['attack_start']['action_id'] for example in examples)),
            'counts': {'target_intents': sum(event['kind'] == 'intent' and event['opcode'] == 1060 and selected(event) for event in events),
                       'targeted_actions': len(examples), 'ordinary_actions': sum(example['attack_start']['known_ordinary_action'] is True for example in examples),
                       'move_before_hit_candidates': sum(example['candidate_move_before_hit'] for example in examples),
                       'windup_cancel_candidates': sum(example['candidate_windup_cancel'] for example in examples),
                       'moves_before_attack_start': len(early_moves)},
            'candidates': candidates[:limit], 'moves_before_attack_start': early_moves[:limit],
            'action_examples': examples[:limit], 'wall_time_backwards_at_lines': backwards,
            'limits': ['Associations use log order; wall times include input queues, logging and delivery delays.',
                       'Known ordinary action IDs come from measured/native-metadata tables, including Gwen 8/9.',
                       'Class5/type0 negative damage is an ordinary-damage candidate; type4 may be a proc or spell. Causality is not proven.',
                       'Positions are last observed 1070 samples; age is explicit and motion between samples is unknown.',
                       'No release frame, projectile commitment, rendered stutter step, or deterministic state is inferred.',
                       'A no-hit window ends at the next intent, next source action, time limit or complete trace end; it does not prove cancellation.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--source-eid', type=int, required=True)
    parser.add_argument('--hero-id', type=int, help='optional identity when the connection lacks 1006')
    parser.add_argument('--connection', type=int)
    parser.add_argument('--seconds', type=float, default=3.0)
    parser.add_argument('--from-line', type=int, default=1)
    parser.add_argument('--to-line', type=int)
    parser.add_argument('--limit', type=int, default=12)
    args = parser.parse_args()
    try:
        rows, connection, incomplete_tail = read_rows(args.trace, args.connection)
        result = inspect(rows, args.source_eid, hero_id=args.hero_id, seconds=args.seconds,
                         from_line=args.from_line, to_line=args.to_line, limit=args.limit)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    result.update(trace=str(args.trace.resolve()), connection=connection, incomplete_final_line=incomplete_tail)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
