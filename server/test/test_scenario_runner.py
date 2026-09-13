"""Scenario pilot tests: deterministic repeatability, evidence integrity, refusal paths.

These tests exercise Tools/run_scenarios.py the way the pilot runs it:
independent worker processes with different PYTHONHASHSEED values compared by
exact event/state bytes, tampered evidence detected despite PASS labels,
external reference fixtures validated, and invalid output/navmesh setups
refused before any simulation. They do not mirror result labels.
"""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import argparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.navigation import DEFAULT_A001_PATH
from Tools.run_scenarios import (
    COMPARED_ARTIFACTS,
    OutputPathError,
    ReferenceFixtureError,
    SCENARIO_TABLE,
    STAGES,
    StageFailure,
    check_reference_compatibility,
    compare_reference,
    identical_files,
    load_reference,
    manifest_digest,
    pin_sources,
    resolve_output_dir,
    run_headless,
    run_worker,
    scenario_skye_a,
    source_manifest,
)

NAV = str(DEFAULT_A001_PATH)
HAVE_NAV = DEFAULT_A001_PATH.is_file()


def _isolated_env(seed: int) -> dict:
    env = dict(os.environ)
    for name in ("HALCYON_QA_DIR", "HALCYON_NO_WAVE", "HALCYON_BOTS", "HALCYON_NO_TAPE"):
        env.pop(name, None)
    env["HALCYON_NO_TAPE"] = "1"
    env["PYTHONHASHSEED"] = str(seed)
    return env


def _worker_args(**overrides) -> argparse.Namespace:
    defaults = dict(seed=11, scenario="skye-a", output=None, navmesh=NAV,
                    expect_manifest=None)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@unittest.skipUnless(HAVE_NAV, "external A001 navmesh unavailable")
class TestTwoProcessRepeatability(unittest.TestCase):
    """The contract: two independent Python processes, different hash seeds,
    identical deterministic artifacts."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-test-repeat-"))
        cls.results = {}
        cls.dirs = {}
        for seed in (11, 7919):
            run_dir = cls.base / f"run-seed{seed}"
            run_dir.mkdir()
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
                 "--worker", "--seed", str(seed), "--scenario", "skye-a",
                 "--output", str(run_dir), "--navmesh", NAV],
                env=_isolated_env(seed), cwd=ROOT, capture_output=True, text=True)
            cls.results[seed] = (completed, run_dir)

    def test_both_workers_exit_zero_with_pass(self):
        for seed, (completed, run_dir) in self.results.items():
            self.assertEqual(completed.returncode, 0,
                             f"seed {seed} worker failed: {completed.stderr[-2000:]}")
            result = json.loads((run_dir / "skye-a" / "result.json").read_text())
            self.assertEqual(result["status"], "PASS", result.get("failure_detail"))

    def test_deterministic_artifacts_are_byte_identical_across_seeds(self):
        first = self.base / "run-seed11" / "skye-a"
        second = self.base / "run-seed7919" / "skye-a"
        for artifact in COMPARED_ARTIFACTS:
            self.assertTrue(identical_files(first / artifact, second / artifact),
                            f"{artifact} differs between PYTHONHASHSEED runs")

    def test_events_contain_tick_indexed_authored_intents(self):
        result = json.loads(
            (self.base / "run-seed11" / "skye-a" / "result.json").read_text())
        # Authored intents live in the result record, tick-indexed...
        learn = [row for row in result["intents"] if row["opcode"] == 1078]
        self.assertTrue(learn, "no 1078 learn intent recorded")
        self.assertEqual(learn[0]["tick"], 2)
        self.assertEqual(learn[0]["payload"], "00" + "00" * 5)
        casts = [row for row in result["intents"] if row["opcode"] == 1042]
        self.assertTrue(casts, "no 1042 ground cast recorded")
        self.assertEqual(casts[0]["payload"][24:], "0000",
                         "the cast payload must carry native Skye action 0 "
                         "and flag 0 at offsets 12/13")
        # ...while the event log carries the world's attributed responses.
        events = (self.base / "run-seed11" / "skye-a" / "events.jsonl").read_text(
            encoding="ascii").splitlines()
        records = [json.loads(line) for line in events]
        self.assertEqual(records[0]["phase"], 0, "bootstrap frames come first")
        learn_echo = [r for r in records if r["opcode"] == 1078]
        self.assertTrue(learn_echo, "no 1078 learn echo recorded")
        self.assertEqual(learn_echo[0]["tick"], 2)
        self.assertEqual(learn_echo[0]["phase"], 1, "learn must be attributed to the intent phase")
        acks = [r for r in records if r["opcode"] == 1046]
        self.assertTrue(acks, "no authoritative 1046 cast acknowledgment recorded")
        self.assertEqual(bytes.fromhex(acks[0]["payload"])[16], 0,
                         "the 1046 acknowledgment must carry native action 0")
        damage = [r for r in records if r["opcode"] == 1054]
        self.assertTrue(damage, "no authoritative 1054 damage recorded")
        victim, attacker = struct.unpack_from(">II", bytes.fromhex(damage[0]["payload"]), 0)
        self.assertEqual(attacker, 1500, "damage must be attributed to the Skye hero eid")

    def test_seed_label_differs_while_artifacts_do_not(self):
        left = json.loads((self.base / "run-seed11" / "skye-a" / "result.json").read_text())
        right = json.loads((self.base / "run-seed7919" / "skye-a" / "result.json").read_text())
        self.assertNotEqual(left["seed"], right["seed"])
        self.assertNotEqual(left["wall_elapsed_s"], 0.0)
        # The compared artifacts must not embed the seed or wall time.
        for artifact in COMPARED_ARTIFACTS:
            self.assertTrue(identical_files(
                self.base / "run-seed11" / "skye-a" / artifact,
                self.base / "run-seed7919" / "skye-a" / artifact))

    def test_tampered_event_byte_is_detected_despite_pass_labels(self):
        tampered = self.base / "tampered"
        shutil.copytree(self.base / "run-seed7919" / "skye-a", tampered)
        events = tampered / "events.bin"
        raw = bytearray(events.read_bytes())
        self.assertGreater(len(raw), 64)
        # Flip one payload byte deep inside the stream.
        raw[-32] ^= 0x01
        events.write_bytes(bytes(raw))
        result_json = json.loads((tampered / "result.json").read_text())
        self.assertEqual(result_json["status"], "PASS",
                         "precondition: the tampered run itself passed its assertions")
        self.assertFalse(identical_files(tampered / "events.bin",
                                         self.base / "run-seed11" / "skye-a" / "events.bin"),
                         "a changed effect/event must fail the byte comparison")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)


@unittest.skipUnless(HAVE_NAV, "external A001 navmesh unavailable")
class TestOrchestratorEndToEnd(unittest.TestCase):
    """run_headless: pinning, two seeded subprocesses, summary and refusal. """

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="halcyon-test-orchestrate-"))

    def test_full_orchestration_passes_and_pins_source(self):
        summary = run_headless(["skye-lock-neg"], self.out / "pilot", Path(NAV), None)
        self.assertEqual(summary["overall"], "PASS",
                         json.dumps(summary["scenarios"], default=str)[:2000])
        self.assertTrue(summary["workspace_matches_snapshot"])
        self.assertTrue(all(summary["scenarios"]["skye-lock-neg"]["byte_identical"].values()))
        snapshot = Path(summary["source_snapshot"])
        self.assertTrue((snapshot / "Tools" / "run_scenarios.py").is_file())
        self.assertTrue((snapshot / "server" / "match_server.py").is_file())
        self.assertTrue((snapshot / "Tools" / "verify_sandbox.py").is_file(),
                        "the imported verifier must be part of the pin")
        for seed in (11, 7919):
            log = self.out / "pilot" / f"run-seed{seed}" / "process-stdout.log"
            self.assertTrue(log.is_file(), "worker stdout must be preserved externally")
        summary_disk = json.loads((self.out / "pilot" / "summary.json").read_text())
        self.assertEqual(summary_disk["overall"], "PASS")

    def test_reference_fixture_verifies_against_observed_metrics(self):
        result = json.loads(
            (self.out / "pilot" / "run-seed11" / "skye-lock-neg" / "result.json").read_text())
        metrics = result["observed_metrics"]
        fixture = {
            "schema_version": 1,
            "provenance": {"source": "test-synthetic fixture from a prior verified run",
                           "captured_at": "2026-09-09T00:00:00Z",
                           "connection": "test"},
            "compatibility": {"scenario": "skye-lock-neg", "hero_id": 265,
                              "enemy_hero_id": 243},
            "metrics": [{"name": "nolock_b_acks", "expected": metrics["nolock_b_acks"],
                         "tolerance": 0.0},
                        {"name": "stalelock_b_acks", "expected": 0, "tolerance": 0.0}],
        }
        path = self.out / "fixture.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        loaded = load_reference(path)
        check_reference_compatibility(loaded, result["configuration"]
                                      | {"scenario_id": "skye-lock-neg"})
        evaluation = compare_reference(loaded, metrics)
        self.assertEqual(evaluation["status"], "VERIFIED")

    def test_wrong_expected_value_fails_reference(self):
        fixture = {"schema_version": 1,
                   "provenance": {"source": "test", "captured_at": "now"},
                   "compatibility": {"scenario": "skye-lock-neg"},
                   "metrics": [{"name": "nolock_b_acks", "expected": 3, "tolerance": 0.0}]}
        evaluation = compare_reference(fixture, {"nolock_b_acks": 0})
        self.assertEqual(evaluation["status"], "FAILED")

    def test_missing_metric_and_malformed_and_incompatible(self):
        evaluation = compare_reference(
            {"schema_version": 1, "provenance": {"source": "t", "captured_at": "n"},
             "compatibility": {"scenario": "x"}, "metrics": [{"name": "nope", "expected": 1}]},
            {"other": 1})
        self.assertEqual(evaluation["status"], "FAILED")
        with self.assertRaises(ReferenceFixtureError) as ctx:
            load_reference(self.out / "does-not-exist.json")
        self.assertEqual(ctx.exception.kind, "MALFORMED")
        bad = self.out / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ReferenceFixtureError) as ctx:
            load_reference(bad)
        self.assertEqual(ctx.exception.kind, "MALFORMED")
        no_provenance = self.out / "noprov.json"
        no_provenance.write_text(json.dumps({"schema_version": 1,
                                             "compatibility": {}, "metrics": []}),
                                 encoding="utf-8")
        with self.assertRaises(ReferenceFixtureError) as ctx:
            load_reference(no_provenance)
        self.assertEqual(ctx.exception.kind, "MALFORMED")
        fixture = {"schema_version": 1,
                   "provenance": {"source": "t", "captured_at": "n"},
                   "compatibility": {"scenario": "skye-a", "hero_id": 999},
                   "metrics": [{"name": "energy_spent", "expected": 40, "tolerance": 1}]}
        with self.assertRaises(ReferenceFixtureError) as ctx:
            check_reference_compatibility(fixture, {"scenario_id": "skye-a",
                                                    "hero_id": 265, "enemy_hero_id": 243,
                                                    "navmesh": {"sha256": "x"}})
        self.assertEqual(ctx.exception.kind, "INCOMPATIBLE")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)


class TestOutputPathAndWorkerRefusals(unittest.TestCase):
    def test_output_inside_repository_is_refused(self):
        with self.assertRaises(OutputPathError):
            resolve_output_dir(str(ROOT / "Docs" / "scenario-out"))

    def test_non_existing_directory_is_created_outside_repo(self):
        target = Path(tempfile.gettempdir()) / "halcyon-test-outdir" / "fresh"
        if target.exists():
            shutil.rmtree(target)
        resolved = resolve_output_dir(str(target))
        self.assertTrue(resolved.is_dir())
        shutil.rmtree(resolved, ignore_errors=True)
        shutil.rmtree(target.parent, ignore_errors=True)

    def test_non_empty_existing_directory_is_refused(self):
        target = Path(tempfile.mkdtemp(prefix="halcyon-test-nonempty-"))
        (target / "prior-evidence.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(OutputPathError):
            resolve_output_dir(str(target))
        self.assertTrue((target / "prior-evidence.txt").is_file(),
                        "existing evidence must be preserved")
        shutil.rmtree(target, ignore_errors=True)

    def test_worker_refuses_unknown_scenario(self):
        self.assertEqual(run_worker(_worker_args(scenario="made-up",
                                                 output=tempfile.mkdtemp())), 2)

    @unittest.skipUnless(HAVE_NAV, "external A001 navmesh unavailable")
    def test_worker_refuses_missing_navmesh(self):
        self.assertEqual(run_worker(_worker_args(navmesh="Z:/definitely-missing-nav",
                                                 output=tempfile.mkdtemp())), 2)

    @unittest.skipUnless(HAVE_NAV, "external A001 navmesh unavailable")
    def test_worker_refuses_wrong_pinned_manifest(self):
        """A worker bound to one snapshot must refuse to simulate when its
        imported source does not match the expected manifest digest."""
        self.assertEqual(run_worker(_worker_args(expect_manifest="0" * 64,
                                                 output=tempfile.mkdtemp())), 3)


class TestSourcePinning(unittest.TestCase):
    def test_manifest_covers_server_and_pinned_tools(self):
        manifest = source_manifest()
        self.assertIn("Tools/run_scenarios.py", manifest)
        self.assertIn("Tools/scenario_client.py", manifest)
        self.assertIn("Tools/verify_sandbox.py", manifest)
        self.assertIn("server/match_server.py", manifest)

    def test_pin_snapshot_is_complete_and_stable(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-test-pin-"))
        try:
            snapshot, pinned = pin_sources(base)
            self.assertEqual(source_manifest(), pinned)
            for name, digest in pinned.items():
                import hashlib
                self.assertEqual(
                    hashlib.sha256((snapshot / name).read_bytes()).hexdigest(), digest)
            self.assertNotEqual(manifest_digest(pinned),
                                manifest_digest({**pinned, "server/match_server.py": "0"}))
        finally:
            shutil.rmtree(base, ignore_errors=True)


class TestRegistryBasics(unittest.TestCase):
    def test_all_scenarios_registered(self):
        self.assertEqual(set(SCENARIO_TABLE),
                         {"skye-a", "skye-b", "skye-c", "skye-lock-neg",
                          "minion-push", "minion-wave-regression"})

    def test_worker_flag_dispatches_to_worker_not_orchestration(self):
        """Regression: --worker must reach run_worker; the draft re-entered
        run_headless, recursively spawning orchestrations forever."""
        from Tools import run_scenarios
        sentinels = {"worker_calls": 0, "orchestrations": 0}
        original_worker = run_scenarios.run_worker
        original_headless = run_scenarios.run_headless

        def fake_worker(args):
            sentinels["worker_calls"] += 1
            return 7

        def fake_headless(*_args, **_kwargs):
            sentinels["orchestrations"] += 1
            return {"overall": "PASS"}

        run_scenarios.run_worker = fake_worker
        run_scenarios.run_headless = fake_headless
        try:
            code = run_scenarios.main(["--worker", "--seed", "11",
                                       "--scenario", "skye-a",
                                       "--output", str(Path(tempfile.mkdtemp()))])
        finally:
            run_scenarios.run_worker = original_worker
            run_scenarios.run_headless = original_headless
        self.assertEqual(code, 7)
        self.assertEqual(sentinels["worker_calls"], 1)
        self.assertEqual(sentinels["orchestrations"], 0)

    def test_client_cli_maps_failure_to_nonzero_exit(self):
        from Tools import run_scenarios
        # No adb serial supplied: run_client must fail at SETUP and the CLI
        # must translate that into a nonzero exit with a retained result file.
        code = run_scenarios.main(["--mode", "client", "--scenario", "skye-a"])
        self.assertEqual(code, 1)

    def test_client_cli_reference_problem_fails_the_run(self):
        from Tools import run_scenarios
        import unittest.mock as mock
        fixture = {"schema_version": 1,
                   "provenance": {"source": "test", "captured_at": "now"},
                   "compatibility": {"scenario": "skye-a", "mode": "client"},
                   "metrics": [{"name": "attributed_damage_events",
                                "expected": 9, "tolerance": 0}]}
        base = Path(tempfile.mkdtemp(prefix="halcyon-client-ref-test-"))
        path = base / "fixture.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        passing = {"scenario": "skye-a", "mode": "client", "status": "PASS",
                   "observed": {"attributed_damage_events": 2}, "expected": {},
                   "artifact_paths": []}
        try:
            with mock.patch("Tools.run_scenarios.load_reference",
                            return_value=fixture), \
                 mock.patch("Tools.scenario_client.run_client",
                            return_value=passing):
                code = run_scenarios.main(["--mode", "client", "--scenario",
                                           "skye-a", "--reference", str(path)])
            self.assertEqual(code, 1,
                             "a reference mismatch must fail the client run "
                             "even when the driver itself reported PASS")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_stage_failure_rejects_unknown_stage(self):
        with self.assertRaises(ValueError):
            StageFailure("MADE_UP_STAGE", "detail")

    def test_stages_order(self):
        self.assertEqual(STAGES, ("SETUP", "INPUT_NOT_OBSERVED", "INPUT_UNACKNOWLEDGED",
                                  "ACCEPTED", "AUTHORITATIVE_EFFECT", "PRESENTATION"))


@unittest.skipUnless(HAVE_NAV, "external A001 navmesh unavailable")
class TestScenarioResultShape(unittest.TestCase):
    """One in-process scenario verifies the evidence contract end to end."""

    def test_skye_a_evidence_contract(self):
        out = Path(tempfile.mkdtemp(prefix="halcyon-test-shape-")) / "skye-a"
        result = scenario_skye_a(11, out, DEFAULT_A001_PATH)
        try:
            self.assertEqual(result["status"], "PASS", result.get("failure_detail"))
            for key in ("scenario_id", "mode", "seed", "configuration", "intents",
                        "fixture_operations", "stages", "status", "first_failed_stage",
                        "observed", "expected", "observed_metrics", "events",
                        "initial_state", "final_state", "checkpoints", "artifact_paths"):
                self.assertIn(key, result)
            self.assertNotEqual(result["fixture_operations"], [],
                                "fixture placement must be recorded explicitly")
            self.assertNotEqual(result["intents"], [],
                                "authored production intents must be recorded")
            self.assertEqual(result["stages"]["PRESENTATION"]["status"], "UNVERIFIED",
                             "wire evidence must never be presented as visual evidence")
            for artifact in COMPARED_ARTIFACTS:
                self.assertTrue((out / artifact).is_file(), f"{artifact} missing")
            self.assertTrue((out / "evidence.json").is_file())
        finally:
            shutil.rmtree(out.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
