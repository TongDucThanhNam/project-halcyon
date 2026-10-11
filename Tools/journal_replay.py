"""Recorded scheduling + production dispatch, used only by run_scenarios replay.

No gameplay state is restored from checkpoints. They are read-only expectations;
the initial roster goes through ordinary finalization/dump/entry, and every input
uses its registered connection, including disconnected older generations.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import struct
import sys
import traceback

from server.input_journal import (InputJournal, STATE_EXCLUSIONS, EVENT_EXCLUSIONS, FIELD_EXCLUSIONS,
                                  CanonicalState, encoded, file_digest, validate_dependencies)

ARTIFACTS = ("events.bin", "recipients.jsonl", "initial-state.json", "final-state.json",
             "state-checkpoints.jsonl", "send-outcomes.jsonl")


class ReplayMismatch(AssertionError):
    def __init__(self, tick, field, expected, observed):
        self.tick, self.field = tick, field
        self.expected, self.observed = expected, observed
        super().__init__(f"first divergence tick {tick}, {field}: expected {expected!r}, observed {observed!r}")


def difference(expected, observed, path="state"):
    """Name a semantic field inside the canonical graph rather than a byte offset."""
    if type(expected) is not type(observed):
        return path, expected, observed
    if isinstance(expected, dict):
        if expected.keys() != observed.keys():
            return path + ".keys", sorted(expected), sorted(observed)
        if set(expected) == {"map"}:
            if len(expected["map"]) != len(observed["map"]):
                return path + ".length", len(expected["map"]), len(observed["map"])
            for (key, value), (other, actual) in zip(expected["map"], observed["map"]):
                found = difference(key, other, path + ".key") or difference(value, actual, f"{path}[{key!r}]")
                if found:
                    return found
            return None
        for key in sorted(expected):
            found = difference(expected[key], observed[key], f"{path}.{key}")
            if found:
                return found
    elif isinstance(expected, list):
        for index, (left, right) in enumerate(zip(expected, observed)):
            found = difference(left, right, f"{path}[{index}]")
            if found:
                return found
        if len(expected) != len(observed):
            return path + ".length", len(expected), len(observed)
    elif expected != observed:
        return path, expected, observed
    return None


class _JournalRecords:
    """Reiterable disk-backed operations; long replay needs only one at a time."""

    def __init__(self, path, header, footer):
        self.path, self.header, self.footer = Path(path), header, footer

    def __len__(self):
        return self.footer["records"]

    def __iter__(self):
        with self.path.open(encoding="utf-8") as source:
            if json.loads(next(source)) != self.header:
                raise ValueError("journal header changed after validation")
            for sequence in range(1, len(self) + 1):
                row = json.loads(next(source))
                _validate_operation(row, sequence)
                yield row
            if json.loads(next(source)) != self.footer or next(source, None) is not None:
                raise ValueError("journal footer changed after validation")


def _validate_operation(record, sequence):
    if type(record.get("seq")) is not int or record["seq"] != sequence:
        raise ReplayMismatch(record.get("sim_tick", 0), "sequence", sequence, record.get("seq"))
    if record.get("kind") != "operation":
        raise ValueError(f"unexpected record kind at sequence {sequence}")


def read_journal(path, *, streaming=False):
    operations = [] if not streaming else None
    header = footer = last = None
    count = 0
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if header is None:
                header = row
                continue
            if footer is not None:
                raise ValueError("data after journal footer")
            if row.get("kind") == "footer":
                footer = row
                continue
            count += 1
            _validate_operation(row, count)
            last = row
            if operations is not None:
                operations.append(row)
    if header is None or header.get("kind") != "header" or footer is None or count == 0:
        raise ValueError("incomplete journal: header and successful close footer required")
    if header.get("version") != 1 or footer["records"] != count:
        raise ValueError("journal version/record count mismatch")
    if last["method"] != "close" or footer["world_starts"] < 1:
        raise ValueError("journal has no completed WORLD interval")
    return header, _JournalRecords(path, header, footer) if streaming else operations, footer


def validate_inputs(header):
    validate_dependencies(header)


def replay_batch(world, record):
    """Reproduce _run_world's recorded scheduling decisions, not its wall clock.

    All publication builders and state stepping remain production calls. The
    cursor/tick targets are scheduling inputs, never copied authoritative state.
    """
    from server import roster, wire
    target = record["schedule"]
    with world._state_lock, world.journal.operation("world_batch"):
        world._load_tape()
        if not world.tape_frames:
            world.tape_done = True
        if not world.tape_done:
            if not world.tape_i <= target["tape_i"] <= len(world.tape_frames):
                raise ValueError("invalid tape scheduling cursor")
            while world.tape_i < target["tape_i"]:
                _, body = world.tape_frames[world.tape_i]
                opcode = struct.unpack_from(">H", body)[0]
                world._broadcast(opcode, body[2:], bootstrap=True)
                world.tape_i += 1
            if world.tape_i >= len(world.tape_frames):
                world.tape_done = True
        elif world.emit_hero_1010 and target["world_tick"] == world.world_tick + 1:
            world.world_tick += 1
            for player in world.players:
                if player.is_bot:
                    continue
                sim = world.hero_sims.get(player.eid)
                if sim is None:
                    continue
                world.seq_1010 = world.actor_slots.allocate(player.eid)
                world._broadcast(wire.OP.ENTITY_FULL_UPDATE, roster.build_entity_full_update(
                    player.eid, world.world_tick, sim.x, sim.y, world.seq_1010, sim.facing))
        if target["wall_ping"]:
            world.journal.active["wall_ping"] = True
            world._broadcast(wire.OP.SLOT_FLAGS_PING, roster.build_slot_flags(world.players))
        if not 0 <= record["end_tick"] - world.sim_tick <= 4:
            raise ValueError("invalid production catch-up batch tick count")
        while world.sim_tick < record["end_tick"]:
            if not world.tape_done or (world.clients and not world.ready_clients):
                raise ValueError("record requests a tick before the production readiness barrier")
            if not world._jungle_published:
                sequence = [world.seq_1010]
                world._emit_frames(world.jungle.get_spawn_frames(seq_1010=sequence,
                                                                actor_slots=world.actor_slots))
                world.seq_1010 = sequence[0]
                world._jungle_published = True
            world.advance_simulation()


def compare_record(expected, actual):
    tick = expected["sim_tick"]
    for field in ("method", "arguments", "sim_tick", "phase", "end_tick", "end_phase", "schedule", "transitions"):
        found = difference(expected[field], actual[field], field)
        if found:
            raise ReplayMismatch(tick, *found)
    for field in ("events", "sends"):
        for index, (left, right) in enumerate(zip(expected[field], actual[field])):
            found = difference(left, right, f"{field}[{index}]")
            if found:
                raise ReplayMismatch(min(left["tick"], right["tick"]), *found)
        if len(expected[field]) != len(actual[field]):
            index = min(len(expected[field]), len(actual[field]))
            extra = expected[field] if len(expected[field]) > index else actual[field]
            raise ReplayMismatch(extra[index]["tick"], f"{field}.length", len(expected[field]), len(actual[field]))
    for index, (left, right) in enumerate(zip(expected["checkpoints"], actual["checkpoints"])):
        # Compare state before digest to retain the first useful field name.
        for field in ("tick", "label", "state", "sha256"):
            observed = json.loads(right[field]) if isinstance(right[field], CanonicalState) else right[field]
            found = difference(left[field], observed, f"checkpoints[{index}].{field}")
            if found:
                raise ReplayMismatch(left["tick"], *found)
    if len(expected["checkpoints"]) != len(actual["checkpoints"]):
        raise ReplayMismatch(tick, "checkpoints.length", len(expected["checkpoints"]), len(actual["checkpoints"]))


def replay(path, output):
    from Tools import run_scenarios as runner
    from server import match_server, navigation, roster
    header, records, footer = read_journal(path, streaming=True)
    validate_inputs(header)
    if header["source_sha256"] != runner.manifest_digest(runner.source_manifest()):
        raise ValueError("live journal source does not match replay source pin")
    players = []
    for row in header["players"]:
        player = roster.Player(**{key: value for key, value in row.items() if key not in ("slot", "pick_flags")})
        player.slot, player.pick_flags = row["slot"], row["pick_flags"]
        players.append(player)
    connections = {}
    owner = object() if header["initial_connection"] else None
    if owner is not None:
        connections[players[0].uuid, 1] = owner
    mesh = navigation.load_halcyon_navmesh(Path(header["input_environment"]["HALCYON_NAVMESH"]))
    world = match_server.SnapshotStream(owner, players, header["match_id"],
                                       lambda op, payload: None, log=lambda _: None, navigation_mesh=mesh)
    journal = InputJournal(world, header=header)
    events = runner.EventLog(output / "events.bin")
    initial = False
    try:
        with ((output / "recipients.jsonl").open("wb") as recipients,
              (output / "state-checkpoints.jsonl").open("wb") as checkpoints,
              (output / "send-outcomes.jsonl").open("wb") as sends):
            for record in records:
                tick, method, args = record["sim_tick"], record["method"], record["arguments"]
                if world.sim_tick != tick or world.phase != record["phase"]:
                    raise ReplayMismatch(tick, "application-boundary", [tick, record["phase"]], [world.sim_tick, world.phase])
                journal.expected = record
                key = (args.get("uuid"), args.get("generation"))
                conn = connections.get(key)
                if method == "add_client":
                    if key in connections:
                        raise ReplayMismatch(tick, "connection-generation", "new generation", key)
                    conn = connections[key] = object()
                    world.add_client(conn, args["session_uuid"], lambda op, payload: None)
                elif method == "_apply_event":
                    if args["bot_eid"] is not None:
                        raise ValueError("recorded participant input cannot use bot_eid authority")
                    if args["uuid"] is not None and conn is None:
                        raise ReplayMismatch(tick, "connection-authority", key, None)
                    world._apply_event(args["opcode"], bytes.fromhex(args["payload_hex"]), conn,
                                       received_monotonic_ns=args["receive_monotonic_ns"])
                elif method == "remove_client":
                    world.remove_client(conn)
                elif method == "_begin_lock":
                    world._begin_lock(send_commit_ack=args["send_commit_ack"])
                elif method == "_broadcast_snapshot":
                    world._broadcast_snapshot(tuple(args["countdown"]))
                elif method == "_dump_world_to":
                    world._dump_world_to(conn)
                elif method == "world_batch":
                    replay_batch(world, record)
                elif method == "close":
                    journal.close()
                elif method in ("_finalize", "_dump_world", "_enter_world", "advance_simulation"):
                    getattr(world, method)()
                else:
                    raise ValueError(f"unhandled journal operation: {method}")
                actual = journal.last
                compare_record(record, actual)
                for attempt in actual["sends"]:
                    sends.write(encoded(attempt) + b"\n")
                phase = runner.PHASE_SIM if method in ("world_batch", "advance_simulation") else runner.PHASE_INTENT
                for event in actual["events"]:
                    events.extend(event["tick"], phase, [(event["opcode"], bytes.fromhex(event["payload_hex"]))])
                    recipients.write(encoded(event) + b"\n")
                for checkpoint in actual["checkpoints"]:
                    checkpoints.write(encoded(checkpoint) + b"\n")
                    if checkpoint["label"] == "world-start" and not initial:
                        (output / "initial-state.json").write_bytes(encoded(checkpoint["state"]))
                        initial = True
        (output / "final-state.json").write_bytes(journal.state())
        if (not initial or journal.checkpoint_count != footer["checkpoints"]
                or journal.world_start_count != footer["world_starts"]):
            raise ValueError("WORLD/checkpoint completeness mismatch")
        validate_inputs(header)
        return {"status": "PASS", "records": len(records), "checkpoints": journal.checkpoint_count,
                "events": events.frames, "final_tick": world.sim_tick, "live_anchors_equal": True}
    finally:
        events.close()


def worker(args):
    from Tools import run_scenarios as runner
    output = runner.resolve_output_dir(args.output)
    result = {"status": "FAIL", "live_anchors_equal": False, "process_id": os.getpid(),
              "pythonhashseed": os.environ.get("PYTHONHASHSEED")}
    try:
        if args.expect_manifest != runner.manifest_digest(runner.source_manifest()):
            raise ValueError("pinned replay manifest mismatch")
        result["runtime_modules"] = runner._assert_pinned_runtime(runner.ROOT)
        import server.input_journal as journal_module
        for name, module in (("server.input_journal", journal_module),
                             ("Tools.journal_replay", sys.modules[__name__])):
            location = Path(module.__file__).resolve()
            if not location.is_relative_to(runner.ROOT.resolve()):
                raise AssertionError(f"pinned replay module violation: {name}: {location}")
            result["runtime_modules"][name] = str(location)
        result.update(replay(Path(args.journal), output))
    except Exception as exc:
        result["error"] = str(exc)
        if isinstance(exc, ReplayMismatch):
            result.update(first_divergent_tick=exc.tick, first_divergent_field=exc.field)
        (output / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
    (output / "result.json").write_bytes(encoded(result))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


def orchestrate(args):
    from Tools import run_scenarios as runner
    output = runner.resolve_output_dir(args.output)
    path = Path(args.journal).resolve()
    try:
        header, records, _ = read_journal(path, streaming=True)
        validate_inputs(header)
        snapshot, manifest = runner.pin_sources(output)
        digest = runner.manifest_digest(manifest)
        if digest != header["source_sha256"]:
            raise ValueError("live journal source differs from current source; replay requires the recorded source")
        copied = output / "journal.jsonl"
        shutil.copyfile(path, copied)
    except Exception as exc:
        summary = {"mode": "replay", "overall": "FAIL", "journal": str(path),
                   "live_anchors_equal": False, "error": str(exc),
                   "state_exclusions": STATE_EXCLUSIONS, "event_exclusions": EVENT_EXCLUSIONS,
                   "field_exclusions": FIELD_EXCLUSIONS}
        if isinstance(exc, ReplayMismatch):
            summary.update(first_divergent_tick=exc.tick, first_divergent_field=exc.field)
        (output / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        (output / "summary.json").write_bytes(encoded(summary))
        print(f"FAIL: {exc}; {output / 'summary.json'}", flush=True)
        return 1
    summary = {"mode": "replay", "overall": "FAIL", "journal": str(path),
               "journal_sha256": file_digest(copied), "source_snapshot": str(snapshot),
               "source_pin_sha256": digest, "record_count": len(records),
               "state_exclusions": STATE_EXCLUSIONS, "event_exclusions": EVENT_EXCLUSIONS,
               "field_exclusions": FIELD_EXCLUSIONS,
               "processes": {}, "live_anchors_equal": False}
    env = dict(os.environ)
    env.pop("HALCYON_INPUT_JOURNAL_DIR", None)
    for name, value in header["environment"].items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    env.update(header["input_environment"])
    arguments = ["--mode", "replay", "--journal", str(copied)]
    for seed, directory, process in runner.seeded_workers(snapshot, output, digest, env, arguments):
        result_path = directory / "result.json"
        result = json.loads(result_path.read_text()) if result_path.is_file() else {"status": "ERROR", "error": "worker produced no result"}
        summary["processes"][str(seed)] = {**process, **result}
    left, right = (output / f"run-seed{seed}" for seed in runner.SEEDS)
    summary["byte_identical"] = {name: (left / name).is_file() and (right / name).is_file()
                                 and runner.identical_files(left / name, right / name) for name in ARTIFACTS}
    summary["workspace_matches_snapshot"] = runner.source_manifest() == manifest
    summary["live_anchors_equal"] = all(row.get("live_anchors_equal") for row in summary["processes"].values())
    if (all(row["returncode"] == 0 and row["status"] == "PASS" for row in summary["processes"].values())
            and all(summary["byte_identical"].values()) and summary["workspace_matches_snapshot"]
            and summary["live_anchors_equal"]):
        summary["overall"] = "PASS"
    latencies = [(row["apply_monotonic_ns"] - row["arguments"]["receive_monotonic_ns"]) / 1e6
                 for row in records if row["arguments"].get("receive_monotonic_ns") is not None]
    if latencies:
        ordered = sorted(latencies)
        summary["receive_to_apply_ms"] = {"count": len(ordered), "min": ordered[0],
            "median": ordered[len(ordered)//2], "p95": ordered[round((len(ordered)-1)*.95)], "max": ordered[-1]}
    (output / "summary.json").write_bytes(encoded(summary))
    print(f"{summary['overall']}: {output / 'summary.json'}", flush=True)
    return 0 if summary["overall"] == "PASS" else 1
