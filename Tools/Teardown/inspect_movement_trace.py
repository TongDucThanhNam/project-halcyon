"""Read-only movement geometry checks for an existing local JSONL wire trace.

Loads the operator's external A001 mesh and emits numeric structure only.
The report checks sampled server positions, not rendered client motion or
every fixed tick between samples. No packets, QA requests or files are sent.
"""
from __future__ import annotations

import argparse
import json
import math
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
    trace.add_argument("--seconds", type=float, default=10.0)
    trace.add_argument("--limit", type=int, default=20, help="last N request summaries when no line is selected")
    args = parser.parse_args(argv)
    try:
        if args.mode == "plan":
            report = route_report(load_halcyon_navmesh(args.navmesh), args.start, args.target)
        else:
            if not math.isfinite(args.seconds) or not 0 < args.seconds <= 120 or args.limit < 1:
                raise ValueError("seconds must be within (0,120] and limit positive")
            rows, connection, incomplete = read_rows(args.path, args.connection)
            report = {"connection": connection, "incomplete_trailing_line": incomplete}
            if args.request_line is None:
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
