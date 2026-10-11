"""Ordinary gateway socket acceptance; no privileged gameplay preparation."""
import json
import threading
import time
import unittest
from unittest.mock import patch

from Tools import protocol_participants as pp
from server import gateway, match_server, paths


class TestBoundaries(unittest.TestCase):
    def test_public_and_non_rfc1918_hosts_refused(self):
        for host in ("8.8.8.8", "1.1.1.1", "169.254.1.1", "100.64.1.1", "0.0.0.0"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                pp.private_host(host)
        for host in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.2"):
            self.assertEqual(pp.private_host(host), host)

    def test_existing_output_refused_including_empty(self):
        output = pp.new_output()
        with self.assertRaises(ValueError):
            pp.new_output(output)
        (output / "retained.txt").write_text("must survive", encoding="utf-8")
        with self.assertRaises(ValueError):
            pp.new_output(output)
        self.assertEqual((output / "retained.txt").read_text(), "must survive")
        with self.assertRaises(ValueError):
            pp.new_output(pp.ROOT / "server/unsafe-evidence")
        with self.assertRaises(ValueError):
            pp.new_output(pp.ROOT.parent / "unsafe-protocol-evidence")

    def test_missing_owned_tape_is_setup_not_gameplay(self):
        parent = pp.new_output()
        output = parent / "missing-input"
        with patch.object(paths, "stack_dir", return_value=parent / "absent-stack"):
            self.assertEqual(pp.main(["--self-host", "--output", str(output)]), 2)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "SETUP")
        self.assertEqual(summary["gameplay_failures"], [])
        self.assertIn(f"missing: {parent / 'absent-stack/world_tape.bin'}", summary["setup_failures"])


class TestParticipants(unittest.TestCase):
    def setUp(self):
        self.output = pp.new_output()
        self.log_lock = threading.Lock()
        print(f"Participant evidence: {self.output}", flush=True)
        # TEST FIXTURE ONLY: shorten the lock countdown and omit corpus tape.
        # Production navmesh, wall-paced simulation and all gameplay stay intact.
        for name, value in (("LOCK_COUNTDOWN", 0.3),
                            ("WORLD_TAPE_PATH", str(self.output / "no-tape.bin"))):
            override = patch.object(match_server, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.gateway = gateway.Gateway("127.0.0.1", 0, pp.MATCH_ID,
                                       heartbeat_port=0, log=self.log)
        self.gateway.start()
        self.addCleanup(self.gateway.stop)

    def log(self, line):
        with self.log_lock, (self.output / "server.log").open("a", encoding="utf-8") as log:
            log.write(f"{time.time():.6f} {line}\n")

    def test_six_participants_all_actions_and_reconnect(self):
        summary = pp.run("127.0.0.1", self.gateway.port, self.output,
                         heartbeat_port=self.gateway.relay.port, mode="unit-test-no-tape")
        self.assertEqual(summary["status"], "PASS", json.dumps(summary, indent=2))
        self.assertEqual(len({p["identity"] for p in summary["participants"]}), 6)
        for i, participant in enumerate(summary["participants"]):
            self.assertEqual((participant["eid"], participant["slot"], participant["team"]),
                             (pp.EIDS[i], pp.SLOTS[i], 1 if i % 2 == 0 else 2))
            for stage in pp.STAGES[:-1]:
                with self.subTest(hero=participant["hero"], stage=stage):
                    record = participant["stages"][stage]
                    self.assertEqual(record["classification"], pp.OBSERVED)
                    self.assertTrue(record["proving_opcodes"])
            with open(participant["wire_log"], encoding="utf-8") as log:
                rows = [json.loads(line) for line in log]
            self.assertTrue(any(r["lane"] == "heartbeat" and r["direction"] == "c2s" for r in rows))
            self.assertTrue(any(r["opcode"] == 0 and r["direction"] == "c2s" for r in rows))
            self.assertIsNone(participant["receive_error"])
        self.assertEqual(summary["participants"][0]["stages"]["reconnect"]["classification"], pp.OBSERVED)

    def test_cast_before_learning_is_not_accepted(self):
        players = [pp.Participant("127.0.0.1", self.gateway.port, pp.MATCH_ID, hero, self.output,
                                  heartbeat_port=self.gateway.relay.port) for hero in pp.HEROES]
        try:
            pp.enter_world(players)
            p = players[0]
            mark = p.begin("cast")
            op, payload, response = pp.native_cast(p)
            p.input("cast", op, payload)
            with self.assertRaises(pp.StageFailure):
                p.wait(lambda received, body: received == response and pp.u32(body) == p.eid,
                       after=mark, timeout=1.5)
            self.assertIsNone(p.error, "transport failure is not an illegal-action negative control")
            self.assertEqual(p.stages["cast"]["classification"], "unacknowledged (reason unknown)")
            self.assertEqual(p.stages["cast"]["proving_opcodes"], [])
            self.assertFalse(any(op == 1053 and pp.u32(body) == p.eid and body[8] == 2
                                 and pp.struct.unpack_from(">f", body, 4)[0] < 0
                                 for op, body, row in p.messages if row['stream_index'] > mark))
        finally:
            for p in players:
                p.close()
            (self.output / "summary.json").write_text(json.dumps(
                {"mode": "negative-control", "source": pp.source_identity(),
                 "participants": [p.report() for p in players]}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
