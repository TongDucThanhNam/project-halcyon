"""Offline logical/root-model measurements for the existing movement inspector.

No device access, replay execution, expected-value generation or fidelity verdict.
Inputs are the existing scenario's result, observer journal and wire records.
"""
from __future__ import annotations

from bisect import bisect_left
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('nonfinite or nonnumeric client measurement')
    return value


def clock_alignment(batches):
    if len(batches) < 2 or any(not batch for batch in batches):
        raise ValueError('start/end client clock brackets required')
    clocks = []
    for batch in batches:
        candidates = []
        for b in batch:
            width = finite(b['host_monotonic_after_s']) - finite(b['host_monotonic_before_s'])
            if width < 0:
                raise ValueError('reversed client clock bracket')
            offset = finite(b['host_wall_before_s']) + width / 2 - finite(b['client']['guest_monotonic_ms']) / 1000
            candidates.append({'offset_s': offset, 'bracket_s': width})
        clocks.append(min(candidates, key=lambda c: c['bracket_s']))
    offset = statistics.mean(c['offset_s'] for c in clocks)
    # An observed envelope, not a proof against an unobserved mid-run clock jump.
    margin = max(abs(c['offset_s'] - offset) + c['bracket_s'] / 2 for c in clocks)
    return {'offset_s': offset, 'boundary_margin_s': margin, 'brackets': clocks,
            'offset_drift_s': clocks[-1]['offset_s'] - clocks[0]['offset_s']}


def client_report(rows, run_dir, connection, eid, slot, straight_walks=(), *, position_source='logical'):
    from Tools.Teardown.inspect_movement_trace import distribution, timing_report

    run_dir = Path(run_dir)
    results = list(run_dir.glob('client-result-*.json'))
    if len(results) != 1:
        raise ValueError('one unambiguous client result required')
    blobs = {results[0].name: results[0].read_bytes(),
             'client-movement.metadata.json': (run_dir / 'client-movement.metadata.json').read_bytes(),
             'client-movement.jsonl': (run_dir / 'client-movement.jsonl').read_bytes()}
    result = json.loads(blobs[results[0].name])
    metadata = json.loads(blobs['client-movement.metadata.json'])
    if position_source not in ('logical', 'model'):
        raise ValueError('position source must be logical or model')
    if position_source == 'model' and metadata.get('model_transform') is not True:
        raise ValueError('model matrix was not qualified by this observer run')
    if result.get('status') != 'PASS' or result.get('scenario') != 'movement-walk':
        raise ValueError('successful movement-walk data run required; failed setup is not movement evidence')
    if metadata.get('errors') != []:
        raise ValueError('client observer errors are not acceptable measurements')
    identity = result['observations']['wire_identity']
    if (identity['connection'], identity['eid'], identity['slot']) != (connection, eid, slot):
        raise ValueError('selected wire identity differs from client result')
    if metadata['identity']['eid'] != eid:
        raise ValueError('native owner identity mismatch')
    rows = [r for r in rows if r['connection'] == connection]
    owners = {struct.unpack_from('>I', r['decoded'])[0] for r in rows
              if r['direction'] == 's2c' and r['opcode'] == 1001 and len(r['decoded']) == 102}
    heroes = {(struct.unpack_from('>I', r['decoded'])[0], r['decoded'][745]) for r in rows
              if r['direction'] == 's2c' and r['opcode'] == 1011 and len(r['decoded']) == 750
              and struct.unpack_from('>I', r['decoded'], 8)[0] == eid}
    if owners != {eid} or heroes != {(identity['hero_id'], slot)}:
        raise ValueError('native/result identity not corroborated by wire bootstrap')
    alignment = clock_alignment(metadata['clock_brackets'])
    raw = blobs['client-movement.jsonl']
    if raw and not raw.endswith(b'\n'):
        raise ValueError('incomplete native sample journal')
    samples = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not samples or len(samples) != metadata['samples']:
        raise ValueError('native sample delivery/count mismatch')
    times, points = [], []
    for s in samples:
        times.append(finite(s['guest_monotonic_ms']) / 1000 + alignment['offset_s'])
        if len(s['position_xyz']) != 3 or len(s['correction_velocity_xyz']) != 3:
            raise ValueError('client vectors must have three coordinates')
        for value in s['position_xyz'] + s['correction_velocity_xyz']:
            finite(value)
        finite(s['correction_remaining_s'])
        if finite(s['read_ms']) < 0:
            raise ValueError('negative native read duration')
        xyz = s['position_xyz']
        if position_source == 'model':
            model = s.get('model', {})
            matrix = model.get('matrix_column_major', [])
            xyz = model.get('translation_xyz', [])
            if len(matrix) != 16 or len(xyz) != 3 or matrix[12:15] != xyz:
                raise ValueError('model matrix/translation absent or inconsistent')
            for value in matrix:
                finite(value)
            if [matrix[i] for i in (3, 7, 11, 15)] != [0, 0, 0, 1]:
                raise ValueError('model matrix is not affine')
        points.append((xyz[0], xyz[2]))
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError('native sample time regressed')
    window = result['observed']['data_window']
    start, end = finite(window['started_at']), finite(window['ended_at'])
    if end <= start:
        raise ValueError('invalid client data window')
    report = timing_report([r for r in rows if start <= r['time'] <= end], eid, slot)
    gestures = [g for g in result['gestures'] if g.get('kind') == 'walk-tap']
    requests = report['requests']
    if not gestures or len(gestures) != len(requests):
        raise ValueError('gesture/wire input count mismatch')
    declared = set(straight_walks)
    if not declared <= {g['walk'] for g in gestures}:
        raise ValueError('unknown straight-walk label')
    starts = [finite(g['wall_before']) for g in gestures] + [end]
    if starts[0] < start or any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError('invalid scripted-input boundaries')
    measured = []
    for i, (gesture, request) in enumerate(zip(gestures, requests)):
        lo, hi = starts[i:i + 2]
        if not lo <= request['request_time'] < hi:
            raise ValueError('wire request does not match scripted-input window')
        # Local prediction can retarget BEFORE the next server receipt. Use
        # gesture boundaries and trim the measured alignment envelope.
        left = bisect_left(times, lo + alignment['boundary_margin_s'])
        right = bisect_left(times, hi - alignment['boundary_margin_s'])
        # The read is non-atomic; a sample starting before the next gesture
        # may finish after it. Trim crossing reads as well as clock margins.
        while right > left and times[right - 1] + samples[right - 1]['read_ms'] / 1000 >= hi - alignment['boundary_margin_s']:
            right -= 1
        if right - left < 2:
            raise ValueError('insufficient client samples inside input boundaries')
        origin, final = points[left], points[right - 1]
        ack = request['ack']
        target = ack['target'] if ack else None
        row = {'label': gesture['walk'], 'order': gesture['order'],
               'request_line': request['request_line'], 'samples': right - left,
               'origin': origin, 'last_position': final, 'accepted_target': target,
               'ack_delay_s': ack['delay_s'] if ack else None,
               'wire_position_count': request['sample_count'],
               'last_sample_target_distance': math.dist(final, target) if ack else None,
               'correction_active_samples': sum(s['correction_remaining_s'] > 0 for s in samples[left:right]),
               'backward': {'status': 'UNMEASURED', 'reason': 'straight path not declared'},
               'window': {'start': lo, 'end_before_next_gesture': hi}}
        if gesture['walk'] in declared:
            length = math.dist(origin, target) if ack else 0
            if length <= .0001:
                row['backward'] = {'status': 'UNMEASURED', 'reason': 'no accepted nonzero leg'}
            else:
                unit = [(b - a) / length for a, b in zip(origin, target)]
                backwards = []
                for j in range(left + 1, right):
                    distance = sum((a - b) * u for a, b, u in zip(points[j - 1], points[j], unit))
                    if distance > .0001:
                        backwards.append({'after_input_s': times[j] - request['request_time'],
                                          'units': distance,
                                          'correction_remaining_s': samples[j]['correction_remaining_s']})
                row['backward'] = {'status': 'MEASURED', 'count': len(backwards),
                                   'total_units': sum(x['units'] for x in backwards),
                                   'first': backwards[0] if backwards else None}
        measured.append(row)
    evaluated = [r['backward'] for r in measured if r['backward']['status'] == 'MEASURED']
    return {'status': 'MEASURED', 'client_smoothness': 'UNVERIFIED', 'position_source': position_source,
            'cross_run_comparability': 'UNVERIFIED', 'identity': identity,
            'client_version': result['provenance']['client_version'],
            'library_sha256': metadata['library_sha256'],
            'source_sha256': {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()},
            'clock': alignment, 'wire_time_source': report['time_source'],
            'samples': len(samples), 'read_ms': distribution([s['read_ms'] for s in samples]),
            'sample_gap_ms': distribution([(b-a)*1000 for a, b in zip(times, times[1:])]),
            'straight_legs_measured': len(evaluated),
            'straight_legs_with_backward_steps': sum(bool(r['count']) for r in evaluated),
            'requests': measured,
            'limits': [('Logical non-atomic native state, not model/render transform.' if position_source == 'logical'
                        else 'Owner-bound root model world matrix, non-atomic. Not bone pose, camera projection or display-time/frame measurement.'),
                       'Backward projection requires explicitly declared straight legs; never an arbitrary-corner verdict.',
                       '0.0001 units distinguishes backward steps; it is not a smoothness acceptance tolerance.',
                       'Last-sample distance is not proof of arrival for retargeted or unfinished legs.',
                       'Clock margin is from observed brackets, not a bound on every unobserved clock disturbance.',
                       'Latency, buffs, items, ranks and initial state are not proven equal between runs.']}
