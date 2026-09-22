"""Read-only movement checks for existing wire and optional native client data.

Loads the operator's external A001 mesh and emits numeric structure only.
Wire positions are not client positions or every fixed tick between samples.
--client-run joins logical native state, never a model/render transform.
No packets, QA requests or files are sent.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import json
import math
import statistics
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.navigation import load_halcyon_navmesh


def movement(payload):
    if len(payload) != 14 or payload[8:] != bytes(6):
        raise ValueError("1012 must contain two floats and six zero bytes")
    point = struct.unpack_from(">ff", payload)
    if not all(math.isfinite(value) for value in point):
        raise ValueError("nonfinite movement target")
    return point


def position(payload):
    if len(payload) != 14 or payload[12:] != bytes(2):
        raise ValueError("1070 must contain EID, two floats and two zero bytes")
    eid, x, y = struct.unpack_from(">Iff", payload)
    if not all(math.isfinite(value) for value in (x, y)):
        raise ValueError("nonfinite position")
    return eid, (x, y)


def read_rows(path, connection=None):
    rows, incomplete_tail = [], False
    # Take one finite snapshot; an unfinished final JSON line is reported.
    for index, line in enumerate(path.read_bytes().splitlines(keepends=True), 1):
        if not line.strip():
            continue
        if not line.endswith(b"\n"):
            incomplete_tail = True
            continue
        try:
            row = json.loads(line)
            row["line"] = index
            row["decoded"] = bytes.fromhex(row["payload"])
            if not math.isfinite(row["time"]):
                raise ValueError("nonfinite timestamp")
            rows.append(row)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"invalid trace line {index}: {error}") from error
    connections = sorted({row["connection"] for row in rows
                          if row["direction"] == "c2s" and row["opcode"] == 1012})
    if connection is None:
        if len(connections) != 1:
            raise ValueError(f"movement connections are {connections}; select --connection")
        connection = connections[0]
    if connection not in connections:
        raise ValueError(f"no c2s1012 on connection {connection}; available {connections}")
    return [row for row in rows if row["connection"] == connection], connection, incomplete_tail


def route_report(mesh, start, target):
    route = [tuple(start)] + mesh.find_path(start, target)
    lengths = [math.dist(a, b) for a, b in zip(route, route[1:])]
    return {"start": start, "requested_target": target,
            "start_walkable": mesh.contains(start), "target_walkable": mesh.contains(target),
            "projected_target": mesh.nearest_point(target),
            "direct_walkable": mesh.segment_walkable(start, target),
            "direct_distance": math.dist(start, target), "route": route,
            "route_distance": sum(lengths),
            "route_segments_walkable": [mesh.segment_walkable(a, b)
                                         for a, b in zip(route, route[1:])],
            "vertex_count": len(mesh.vertices), "triangle_count": len(mesh.triangles)}


def project_to_route(point, route):
    """Euclidean distance and distance along the closest route segment."""
    choices, walked = [], 0.0
    for a, b in zip(route, route[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        squared = dx * dx + dy * dy
        ratio = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / squared)) if squared else 0.0
        projected = a[0] + ratio * dx, a[1] + ratio * dy
        length = math.sqrt(squared)
        choices.append((math.dist(point, projected), walked + ratio * length))
        walked += length
    return min(choices) if choices else (math.dist(point, route[0]), 0.0)


def list_requests(rows, eid):
    last = None
    requests = []
    for row in rows:
        if row["direction"] == "s2c" and row["opcode"] == 1070:
            actor, point = position(row["decoded"])
            if actor == eid:
                last = {"line": row["line"], "time": row["time"], "position": point}
        elif row["direction"] == "c2s" and row["opcode"] == 1012:
            requests.append({"line": row["line"], "time": row["time"],
                             "target": movement(row["decoded"]), "last_hero_position": last})
    return requests


def inspect(rows, mesh, eid, request_line, seconds=10.0):
    requests = {row["line"]: row for row in list_requests(rows, eid)}
    if request_line not in requests:
        raise ValueError("--request-line must identify a c2s1012 on the selected connection")
    request = requests[request_line]
    if request["last_hero_position"] is None:
        raise ValueError("no preceding hero1070; record a known stationary starting position first")
    start = request["last_hero_position"]["position"]
    plan = route_report(mesh, start, request["target"])
    if len(plan["route"]) < 2 or not all(plan["route_segments_walkable"]):
        raise ValueError("selected starting point and target have no complete walkable route")
    samples, interruptions = [], []
    previous, previous_progress = start, 0.0
    end_reason = "trace_end"
    target = plan["projected_target"]
    for row in rows:
        if row["line"] <= request_line:
            continue
        if row["time"] > request["time"] + seconds:
            end_reason = "time_window"
            break
        opcode, payload = row["opcode"], row["decoded"]
        if row["direction"] == "c2s" and opcode in (1012, 1041, 1042, 1060, 1096, 1098, 1102):
            end_reason = "next_client_intent"
            interruptions.append({"line": row["line"], "opcode": opcode})
            break
        if row["direction"] != "s2c":
            continue
        if opcode in (1033, 1072) and len(payload) >= 4 and int.from_bytes(payload[:4], "big") == eid:
            end_reason = "hero_lifecycle"
            interruptions.append({"line": row["line"], "opcode": opcode})
            break
        if opcode != 1070:
            continue
        actor, point = position(payload)
        if actor != eid:
            continue
        route_distance, progress = project_to_route(point, plan["route"])
        on_mesh = mesh.contains(point)
        mesh_distance = 0.0 if on_mesh else math.dist(point, mesh.nearest_point(point))
        samples.append({"line": row["line"], "time_since_request": row["time"] - request["time"],
                        "position": point, "on_mesh_exact": on_mesh,
                        "distance_from_mesh": mesh_distance, "distance_from_route": route_distance,
                        "route_progress": progress, "progress_change": progress - previous_progress,
                        "sample_chord_walkable": mesh.segment_walkable(previous, point)})
        previous, previous_progress = point, progress
        if math.dist(point, target) <= 0.1:
            end_reason = "target_sampled"
            break
    return {"eid": eid, "request": request, "plan": plan, "end_reason": end_reason,
            "interruptions": interruptions, "samples": samples,
            "sample_count": len(samples),
            "max_distance_from_mesh": max((row["distance_from_mesh"] for row in samples), default=None),
            "max_distance_from_route": max((row["distance_from_route"] for row in samples), default=None),
            "backward_samples_over_0_02": sum(row["progress_change"] < -0.02 for row in samples),
            "blocked_sample_chords": sum(not row["sample_chord_walkable"] for row in samples),
            "final_target_distance": math.dist(previous, target),
            "limits": ["Only sampled server1070 positions are measured; rendered motion requires live observation.",
                       "A blocked chord can skip a valid route corner between samples; it is not by itself wall crossing.",
                       "No speed conclusion: wire timestamps are wall time and contain scheduling/network delay.",
                       "Verify connection ownership and absence of QA teleports/forced movement during this interval.",
                       "A stale pre-request position makes the calculated route diagnostic rather than exact."]}


def timing_report(rows, eid, slot, seconds=10.0):
    """Keep capture-side provenance; never infer client consumption or ticks."""
    sources = {r.get('time_source', 'server_trace') for r in rows}
    if len(sources) > 1:
        raise ValueError('mixed wire timestamp sources')
    source = next(iter(sources), 'server_trace')
    timing_limits = {
        'server_trace': 'Wire timestamps measure server observations, not network RTT, simulation ticks, or client positions.',
        'client-interface capture + measured host offset':
            'Wire timestamps measure client-interface request/response observations, not server receipt, pure network RTT, or client consumption.',
    }
    if source not in timing_limits:
        raise ValueError('unknown wire timestamp source')
    results = []
    interruptions = {1012, 1041, 1042, 1060, 1096, 1098, 1102}
    for index, request in enumerate(rows):
        if request['direction'] != 'c2s' or request['opcode'] != 1012:
            continue
        requested = movement(request['decoded'])
        ack, samples, end = None, [], 'trace_end'
        end_time = min(request['time'] + seconds, rows[-1]['time'])
        for row in rows[index + 1:]:
            elapsed = row['time'] - request['time']
            if elapsed > seconds:
                end = 'time_window'
                break
            if row['direction'] == 'c2s' and row['opcode'] in interruptions:
                end = 'next_client_intent'
                end_time = row['time']
                break
            if row['direction'] != 's2c':
                continue
            payload = row['decoded']
            if row['opcode'] == 1016 and len(payload) == 14 and payload[0] == slot:
                target = struct.unpack_from('>ff', payload, 1)
                if not all(math.isfinite(x) for x in target):
                    raise ValueError('nonfinite accepted destination')
                if ack is None:
                    ack = {'delay_s': elapsed, 'target': target, 'line': row['line']}
            elif row['opcode'] == 1070:
                actor, point = position(payload)
                if actor == eid:
                    samples.append({'elapsed_s': elapsed, 'position': point,
                                    'time': row['time'], 'line': row['line']})
        gaps = [b['elapsed_s'] - a['elapsed_s'] for a, b in zip(samples, samples[1:])]
        arrival = next((s['elapsed_s'] for s in samples
                        if ack and s['elapsed_s'] >= ack['delay_s']
                        and math.dist(s['position'], ack['target']) <= 0.0001), None)
        results.append({'request_line': request['line'], 'request_time': request['time'],
                        'end_time': end_time, 'requested_target': requested,
                        'ack': ack, 'sample_count': len(samples),
                        'position_gaps_s': gaps, 'arrival_after_input_s': arrival,
                        'requested_to_accepted_distance': math.dist(requested, ack['target']) if ack else None,
                        'end_reason': end, 'samples': samples})
    return {'eid': eid, 'slot': slot, 'requests': results, 'time_source': source,
            'limits': ['Slot/EID identity is supplied by the caller, not inferred.',
                       timing_limits[source],
                       'Sparse corrections and duplicate stop samples are intentional; gaps alone do not establish stalls.',
                       'No acknowledgement means unobserved, not proven rejection.']}


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return {'count': len(values), 'min': values[0], 'median': statistics.median(values),
            'p95': values[math.ceil(.95 * len(values)) - 1], 'max': values[-1]}


def correlate_ticks(report, path, match_id=None):
    """Join server publication to adjacent authoritative samples, never client state.

    Tick wall_time is sampled AFTER advance_simulation, whereas wire positions
    are traced before sendall DURING the tick or an input handler. Thus either
    adjacent state can legitimately match a position; no interpolation is used.
    """
    if report.get('time_source', 'server_trace') != 'server_trace':
        raise ValueError('server tick correlation requires server-side wire observations')
    requests = report['requests']
    if not requests:
        raise ValueError('no movement requests to correlate')
    start, end = requests[0]['request_time'], requests[-1]['end_time']
    ticks, incomplete = [], False
    # Windows launchers may emit locale-encoded prose around the ASCII JSON
    # telemetry. Decode only the selected record; never replace bad JSON bytes.
    marker = b'[movement-tick] '
    with path.open('rb') as source:
        for number, line in enumerate(source, 1):
            if marker not in line:
                continue
            if not line.endswith(b'\n'):
                incomplete = True
                continue
            try:
                tick = json.loads(line.split(marker, 1)[1])
                if not math.isfinite(tick['wall_time']):
                    raise ValueError('nonfinite tick timestamp')
                if start - 1 <= tick['wall_time'] <= end + 1:
                    if match_id is None or tick['match_id'] == match_id:
                        ticks.append(tick)
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f'invalid movement tick at log line {number}: {error}') from error
    matches = {t['match_id'] for t in ticks}
    if len(matches) != 1:
        raise ValueError(f'expected one match in wire time window, found {sorted(matches)}; select --match-id')
    # Do not silently combine restarts with a reused match UUID or sort away
    # a wall-clock discontinuity. Either would make temporal joins unreliable.
    for a, b in zip(ticks, ticks[1:]):
        if (b['tick'] <= a['tick'] or b['wall_time'] <= a['wall_time']
                or b['started_monotonic'] <= a['started_monotonic']):
            raise ValueError('tick reset/overlap or clock reversal in selected window; use a single session log')
    states = []
    for tick in ticks:
        heroes = [h for h in tick['heroes'] if h['eid'] == report['eid']]
        if len(heroes) != 1:
            raise ValueError(f"tick {tick['tick']} does not uniquely identify EID {report['eid']}")
        states.append(heroes[0])
    times = [t['wall_time'] for t in ticks]
    publication_matches, publication_unmatched, publication_unbracketed = [], [], []
    for request in requests:
        for sample in request['samples']:
            after = bisect_left(times, sample['time'])
            if after == 0 or after == len(ticks):
                publication_unbracketed.append(sample['line'])
                continue
            if ticks[after]['tick'] != ticks[after - 1]['tick'] + 1:
                publication_unbracketed.append(sample['line'])
                continue
            encoded = struct.pack('>ff', *sample['position'])
            matching = [ticks[i]['tick'] for i in (after - 1, after)
                        if struct.pack('>ff', *(v / 1_000_000 for v in states[i]['position_fixed'])) == encoded]
            if matching:
                publication_matches.append({'line': sample['line'], 'ticks': matching})
            else:
                publication_unmatched.append(sample['line'])
    windows = []
    for request in requests:
        begin = request['request_time'] + (request['ack']['delay_s'] if request['ack'] else 0)
        indices = [i for i, t in enumerate(ticks) if begin <= t['wall_time'] < request['end_time']]
        pairs = [(a, b) for a, b in zip(indices, indices[1:])
                 if ticks[b]['tick'] == ticks[a]['tick'] + 1]
        moving_pairs = [(a, b) for a, b in pairs if states[a]['moving']
                        and states[a]['order_version'] == states[b]['order_version']]
        steps = [math.dist(states[a]['position_fixed'], states[b]['position_fixed']) / 1_000_000
                 for a, b in moving_pairs]
        windows.append({
            'request_line': request['request_line'], 'tick_count': len(indices),
            'late_ms': distribution(ticks[i]['late_ms'] for i in indices),
            'work_ms': distribution(ticks[i]['work_ms'] for i in indices),
            'tick_start_gap_ms': distribution((ticks[b]['started_monotonic'] - ticks[a]['started_monotonic']) * 1000
                                               for a, b in pairs),
            'moving_step_units': distribution(steps),
            'zero_steps_while_moving': sum(step == 0 for step in steps),
            'order_versions': sorted({states[i]['order_version'] for i in indices}),
        })
    offsets = [t['wall_time'] - t['work_ms'] / 1000 - t['started_monotonic'] for t in ticks]
    return {'match_id': next(iter(matches)), 'incomplete_trailing_tick': incomplete,
            'missing_tick_count': sum(b['tick'] - a['tick'] - 1 for a, b in zip(ticks, ticks[1:])),
            'clock_offset_spread_ms': (max(offsets) - min(offsets)) * 1000,
            'requests': windows,
            'publication': {'matched': publication_matches, 'unmatched_lines': publication_unmatched,
                            'unbracketed_lines': publication_unbracketed},
            'limits': ['Tick wall_time is post-work; work_ms excludes telemetry serialization/log I/O.',
                       'Lateness and start gaps include earlier logging/OS costs; probes are not free.',
                       'Exact float32 matches relate two SERVER observations, not client receipt/consumption or position.',
                       'Unmatched positions require investigation; other within-tick effects can change state.',
                       'No interpolation across missing ticks, retargets, resets, or clock reversals.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--navmesh", type=Path)
    commands = parser.add_subparsers(dest="mode", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--start", type=float, nargs=2, required=True)
    plan.add_argument("--target", type=float, nargs=2, required=True)
    trace = commands.add_parser("trace")
    trace.add_argument("path", type=Path)
    trace.add_argument("--connection", type=int)
    trace.add_argument("--eid", type=int, default=1500)
    trace.add_argument("--request-line", type=int)
    trace.add_argument("--timing", action="store_true", help="data-only ack/position timing; no mesh required")
    trace.add_argument('--client-run', type=Path, help='join an existing successful nonvisual movement run (offline)')
    trace.add_argument('--client-position', choices=('logical', 'model'), default='logical',
                       help='select qualified logical entity or root model matrix translation')
    trace.add_argument('--straight-walk', action='append', default=[], help='explicit straight-leg label for backward-motion measurement; repeatable')
    trace.add_argument("--tick-log", type=Path, help="correlate --timing with movement-tick server log")
    trace.add_argument("--match-id", help="match identity in --tick-log (required if ambiguous)")
    trace.add_argument("--slot", type=int, default=0, help="verified owner movement slot for timing")
    trace.add_argument("--seconds", type=float, default=10.0)
    trace.add_argument("--limit", type=int, default=20, help="last N request summaries when no line is selected")
    args = parser.parse_args(argv)
    try:
        if args.mode == "plan":
            report = route_report(load_halcyon_navmesh(args.navmesh), args.start, args.target)
        else:
            if not math.isfinite(args.seconds) or not 0 < args.seconds <= 120 or args.limit < 1:
                raise ValueError("seconds must be within (0,120] and limit positive")
            if (args.tick_log and not args.timing) or (args.match_id and not args.tick_log):
                raise ValueError('--tick-log requires --timing; --match-id requires --tick-log')
            if (args.client_run and not args.timing) or (args.straight_walk and not args.client_run):
                raise ValueError('--client-run requires --timing; --straight-walk requires --client-run')
            if args.client_position != 'logical' and not args.client_run:
                raise ValueError('--client-position model requires --client-run')
            rows, connection, incomplete = read_rows(args.path, args.connection)
            report = {"connection": connection, "incomplete_trailing_line": incomplete}
            if args.timing:
                if not 0 <= args.slot <= 255:
                    raise ValueError('slot must fit one byte')
                report.update(timing_report(rows, args.eid, args.slot, args.seconds))
                if args.client_run:
                    from Tools.Teardown.movement_client_report import client_report
                    report['client'] = client_report(rows, args.client_run, connection, args.eid, args.slot,
                                                    args.straight_walk, position_source=args.client_position)
                if args.tick_log:
                    report['ticks'] = correlate_ticks(report, args.tick_log, args.match_id)
            elif args.request_line is None:
                report["requests"] = list_requests(rows, args.eid)[-args.limit:]
            else:
                report.update(inspect(rows, load_halcyon_navmesh(args.navmesh), args.eid,
                                      args.request_line, args.seconds))
        print(json.dumps(report, indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
