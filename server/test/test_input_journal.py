"""Application-order evidence through real production dispatch and finalization."""
import copy
import itertools
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from Tools import journal_replay, run_scenarios
from server import match_server, roster
from server.input_journal import encoded


def initialized_world(directory, sender=lambda op, payload: None):
    owner = object()
    players = roster.default_solo_bots("journal-owner", "journal-test")
    world = match_server.SnapshotStream(owner, players, "journal-test", sender,
                                        log=lambda _: None, journal_directory=directory)
    world._apply_event(1118, struct.pack(">II6x", 265, 0), owner)
    world._apply_event(1123, bytes(6), owner)
    world._apply_event(1119, bytes(6), owner)
    world._finalize()
    world._apply_event(1134, bytes(6), owner)
    world._apply_event(1137, roster.build_hero_ready_ack(1500), owner)
    return world, owner


class TestApplicationJournal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = run_scenarios.resolve_output_dir(None)
        print(f"Journal test evidence: {cls.output}", flush=True)
        cls.environment = patch.dict(os.environ, {name: "" for name in run_scenarios.ISOLATED_ENVIRONMENT})
        cls.environment.start()
        cls.addClassCleanup(cls.environment.stop)
        cls.no_tape = patch.dict(os.environ, {"HALCYON_NO_TAPE": "1", "HALCYON_INPUT_JOURNAL_DIR": ""})
        cls.no_tape.start()
        cls.addClassCleanup(cls.no_tape.stop)
        # Empty numeric switches are invalid; absent is their production default.
        for name in run_scenarios.ISOLATED_ENVIRONMENT:
            os.environ.pop(name, None)
        world, owner = initialized_world(cls.output)
        cls.world = world
        for _ in range(201):
            world.advance_simulation()
        world.submit(1012, struct.pack(">ff6x", 25, 40), owner)
        world._pump(0)
        world.submit(1012, struct.pack(">ff6x", 35, 50), owner)
        world._pump(0)
        world.remove_client(owner)
        reconnected = object()
        world.add_client(reconnected, "journal-owner", lambda op, p: None)
        world._apply_event(1137, roster.build_hero_ready_ack(1500), reconnected)
        # A queued old-generation packet is recorded but cannot regain authority.
        world._apply_event(1012, struct.pack(">ff6x", 50, 60), owner)
        world.advance_simulation()
        world.journal.close()
        cls.path = world.journal.path
        cls.header, cls.records, cls.footer = journal_replay.read_journal(cls.path)

    def test_contents_application_order_and_reconnect_generation(self):
        self.assertEqual([row["seq"] for row in self.records], list(range(1, len(self.records) + 1)))
        self.assertEqual(self.footer["world_starts"], 1)
        moves = [r for r in self.records if r["arguments"].get("opcode") == 1012]
        self.assertEqual([r["sim_tick"] for r in moves], [201, 201, 201])
        for row in moves[:2]:
            args = row["arguments"]
            self.assertEqual((args["uuid"], args["eid"], args["generation"]), ("journal-owner", 1500, 1))
            self.assertLessEqual(args["receive_monotonic_ns"], row["apply_monotonic_ns"])
            self.assertEqual(row["phase"], "world")
        reconnect = next(r for r in self.records if r["method"] == "add_client")
        self.assertEqual(reconnect["arguments"]["generation"], 2)
        self.assertEqual(reconnect["arguments"]["eid"], 1500)
        self.assertEqual(moves[-1]["events"], [])
        self.assertTrue(any(c["label"] == "periodic" and c["tick"] == 200
                            for r in self.records for c in r["checkpoints"]))

    def test_serializer_preserves_connection_keyed_state(self):
        state = self.world.journal.state()
        self.assertIn(b'"connection":["journal-owner",2]', state)
        self.assertIn(b'_resource_catchup', state)
        self.assertIn(b'_completed_bootstrap_conns', state)
        self.assertIn(b'position_burst', state)
        self.assertIn(b'scoreboard', state)
        self.assertNotIn(b'frames_sent', state)

    def test_short_replay_is_exact_in_two_independent_processes(self):
        output = self.output / "two-process"
        code = run_scenarios.main(["--mode", "replay", "--journal", str(self.path), "--output", str(output)])
        summary = json.loads((output / "summary.json").read_text())
        self.assertEqual(code, 0, json.dumps(summary, indent=2))
        self.assertTrue(summary["live_anchors_equal"])
        self.assertTrue(all(summary["byte_identical"].values()))
        self.assertEqual(set(summary["processes"]), {"11", "7919"})
        self.assertNotEqual(summary["processes"]["11"]["process_id"], summary["processes"]["7919"]["process_id"])
        for seed, result in summary["processes"].items():
            self.assertEqual(result["pythonhashseed"], seed)

    def test_actual_world_scheduler_tape_and_periodic_checkpoints_replay(self):
        directory = self.output / "tape-batches"
        directory.mkdir()
        with patch.dict(os.environ, {"HALCYON_NO_TAPE": "", "HALCYON_TRACE_MOVEMENT": "0"}):
            world, _ = initialized_world(directory)
            self.assertTrue(world.tape_frames, "unit qualification requires the owned production tape")
            clock = itertools.count(world.wave_t0, .025)
            # Only OS pacing is virtual in this unit fixture. The actual
            # _run_world loop publishes tape and calls production fixed steps.
            with (patch("server.match_server.time.monotonic", side_effect=lambda: next(clock)),
                  patch.object(match_server.SnapshotStream, "_pump", return_value=None),
                  patch.object(world._stop_event, "is_set", side_effect=lambda: world.sim_tick >= 201)):
                world._run_world()
            world.journal.close()
            out = directory / "replay"
            out.mkdir()
            result = journal_replay.replay(world.journal.path, out)
            self.assertTrue(result["live_anchors_equal"])
            self.assertEqual(result["final_tick"], 201)

    def test_excluded_snapshot_send_error_still_replays_client_removal(self):
        directory = self.output / "snapshot-send-failure"
        directory.mkdir()
        fail = [False]
        def sender(opcode, payload):
            if fail[0] and opcode == 1113:
                raise OSError("injected recipient disconnect")
        world, owner = initialized_world(directory, sender)
        fail[0] = True
        world._broadcast_snapshot((1.0, 7.0))
        self.assertNotIn(owner, world.clients)
        world.journal.close()
        _, records, _ = journal_replay.read_journal(world.journal.path)
        snapshot = next(row for row in records if row["method"] == "_broadcast_snapshot")
        self.assertEqual(snapshot["events"], [])
        self.assertTrue(any(attempt["send_error"] for attempt in snapshot["sends"]))
        out = directory / "replay"
        out.mkdir()
        self.assertTrue(journal_replay.replay(world.journal.path, out)["live_anchors_equal"])

    def tampered(self, name, transform):
        records = copy.deepcopy(self.records)
        transform(records)
        path = self.output / f"{name}.jsonl"
        path.write_bytes(b"\n".join(encoded(row) for row in [self.header, *records, self.footer]) + b"\n")
        output = self.output / name
        output.mkdir()
        return path, output

    def test_altered_payload_reports_first_divergent_tick(self):
        def alter(records):
            move = next(r for r in records if r["arguments"].get("opcode") == 1012)
            move["arguments"]["payload_hex"] = struct.pack(">ff6x", 55, 45).hex()
        path, output = self.tampered("payload-negative", alter)
        with self.assertRaises(journal_replay.ReplayMismatch) as raised:
            journal_replay.replay(path, output)
        self.assertEqual(raised.exception.tick, 201)
        self.assertIn("events", raised.exception.field)

    def test_swapped_order_is_detected_even_with_renumbered_sequence(self):
        def swap(records):
            indexes = [i for i, r in enumerate(records) if r["arguments"].get("opcode") == 1012][:2]
            a, b = indexes
            records[a], records[b] = records[b], records[a]
            records[a]["seq"], records[b]["seq"] = a+1, b+1
        path, output = self.tampered("order-negative", swap)
        with self.assertRaises(journal_replay.ReplayMismatch) as raised:
            journal_replay.replay(path, output)
        self.assertEqual(raised.exception.tick, 201)

    def test_truncated_journal_is_not_accepted(self):
        path = self.output / "truncated.jsonl"
        path.write_bytes(b"\n".join(self.path.read_bytes().splitlines()[:-1]) + b"\n")
        with self.assertRaisesRegex(ValueError, "incomplete journal"):
            journal_replay.read_journal(path)


class TestJournalFailure(unittest.TestCase):
    def test_nonjournal_reconnect_freeze_is_supported_without_inventing_generation(self):
        from server.test.test_reconnect_state import TestReconnectState
        from Tools.verify_sandbox import freeze_state
        fixture = TestReconnectState()
        world = fixture.make_world()
        fixture.join(world)
        frozen = freeze_state(world, SimpleNamespace(state={}), "fixture-mesh")
        self.assertIn(b'"generation":null', frozen)
        self.assertIn(b'"uuid":"reconnect-player"', frozen)

    def test_write_failure_is_loud_and_retained(self):
        from server.input_journal import InputJournal
        journal = object.__new__(InputJournal)
        journal.path, journal.failure = Path("evidence-write-failure"), None
        class BrokenWriter:
            def write(self, data):
                raise OSError("injected disk full")
        journal.output = BrokenWriter()
        with self.assertRaisesRegex(RuntimeError, "input journal write failed"):
            journal.write({"seq": 1})
        self.assertIn("disk full", journal.failure)

    def test_cli_requires_self_host_for_journal(self):
        from Tools import protocol_participants
        with self.assertRaises(SystemExit) as raised:
            protocol_participants.main(["--journal"])
        self.assertEqual(raised.exception.code, 2)
