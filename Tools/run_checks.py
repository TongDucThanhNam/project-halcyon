"""Timed unittest lanes, not a scenario engine or client-acceptance gate.

Default smoke is explicitly a subset. --suite all retains unittest discovery.
Every run preserves full stdout/stderr, failures, skips, per-test events and
source identity outside the checkout. It never starts an emulator itself.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import faulthandler
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from Tools.verification_support import output_directory, runtime_switches

# Explicit regression recipes, not a claim of complete dependency analysis.
LANES = {
    "smoke": ("test_wire", "test_movement_timing", "test_resource_pool_wire",
              "test_multiclient", "test_skye_session", "test_match_end"),
    "movement": ("test_native_steering", "test_hero_movement", "test_locomotion_target",
                 "test_movement_timing", "test_movement_publication", "test_wave_movement_orders"),
    "combat": ("test_status_effects", "test_hero_combat", "test_resource_pool_wire",
               "test_skye_session", "test_celeste_item_session", "test_items_sandbox"),
    "transport": ("test_wire", "test_e2e", "test_multiclient"),
    "client": ("test_nonvisual_movement", "test_nonvisual_abilities", "test_nonvisual_flask",
               "test_nonvisual_recall", "test_nonvisual_shop", "test_nonvisual_classic",
               "test_client_projection", "test_android_input_health", "test_movement_client_report",
               "test_nonvisual_entry"),
    # Kept explicit, not deleted or excluded from --suite all. Its old fixtures
    # need a nonvisual migration; this lane's failures remain release blockers.
    "legacy-client": ("test_scenario_client",),
    "workflow": ("test_setup_local", "test_scenario_runner", "test_verification_support",
                 "test_run_checks", "test_native_health"),
}


def source_manifest():
    suffixes = {".py", ".js", ".cpp", ".h", ".java", ".ps1", ".bat"}
    paths = sorted(path for base in (ROOT / "server", ROOT / "Tools")
                   for path in base.rglob("*") if path.is_file() and path.suffix in suffixes)
    paths += sorted(ROOT.glob("requirements*.txt"))
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, events, issues, **kwargs):
        super().__init__(*args, **kwargs)
        self.events, self.issues = events, issues
        self.started = {}
        self.durations = []

    def event(self, kind, test, **details):
        self.events.write(json.dumps({"event": kind, "test": test.id(), **details},
                                     sort_keys=True, allow_nan=False) + "\n")
        self.events.flush()

    def startTest(self, test):
        super().startTest(test)
        self.started[test.id()] = time.perf_counter()
        self.event("start", test)

    def stopTest(self, test):
        elapsed = time.perf_counter() - self.started.pop(test.id(), time.perf_counter())
        self.durations.append({"test": test.id(), "seconds": elapsed})
        self.event("end", test, seconds=elapsed)
        super().stopTest(test)

    def record_issue(self, kind, test, error):
        self.event(kind, test)
        self.issues.write(f"{kind}: {test.id()}\n{self._exc_info_to_string(error, test)}\n")
        self.issues.flush()

    def addError(self, test, err):
        super().addError(test, err)
        self.record_issue("ERROR", test, err)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record_issue("FAIL", test, err)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.record_issue("SUBTEST_FAIL" if issubclass(err[0], test.failureException)
                              else "SUBTEST_ERROR", subtest, err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.event("SKIP", test, reason=reason)


def execute_suite(suite, output, *, selection, manifest_reader=source_manifest,
                  diagnostic_after=60):
    """Run the unchanged unittest contracts; completed subset != full coverage."""
    output = output_directory(output, prefix="halcyon-checks-")
    before = manifest_reader()
    started = time.perf_counter()
    write_json(output / "run.json", {
        "status": "RUNNING", "selection": selection, "source_manifest": before,
        "python": sys.version, "platform": platform.platform(),
        "runtime_switches": runtime_switches(),
    })
    paths = {name: output / name for name in (
        "unittest.log", "stdout.log", "stderr.log", "events.jsonl", "issues.log", "thread-traces.log")}
    with (paths["unittest.log"].open("x", encoding="utf-8") as log,
          paths["stdout.log"].open("x", encoding="utf-8") as stdout,
          paths["stderr.log"].open("x", encoding="utf-8") as stderr,
          paths["events.jsonl"].open("x", encoding="utf-8") as events,
          paths["issues.log"].open("x", encoding="utf-8") as issues,
          paths["thread-traces.log"].open("x", encoding="utf-8") as traces):
        if diagnostic_after:
            faulthandler.dump_traceback_later(diagnostic_after, repeat=True, file=traces)
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr), warnings.catch_warnings():
                warnings.simplefilter("error", ResourceWarning)
                runner = unittest.TextTestRunner(
                    stream=log, verbosity=2,
                    resultclass=lambda *a, **kw: TimedResult(*a, events=events, issues=issues, **kw))
                result = runner.run(suite)
        finally:
            if diagnostic_after:
                faulthandler.cancel_dump_traceback_later()
    after = manifest_reader()
    stable = before == after
    exercised = result.testsRun - len(result.skipped)
    passed = result.wasSuccessful() and stable and exercised > 0
    report = {
        "status": "PASS" if passed else "FAIL", "complete": True,
        "selection": selection, "tests_run": result.testsRun,
        "failures": [{"test": test.id(), "traceback": tb} for test, tb in result.failures],
        "errors": [{"test": test.id(), "traceback": tb} for test, tb in result.errors],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "expected_failures": [test.id() for test, _ in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "executed_non_skipped": exercised,
        "workspace_matches_start": stable,
        "changed_sources": sorted(name for name in before.keys() | after.keys()
                                  if before.get(name) != after.get(name)),
        "seconds": time.perf_counter() - started,
        "test_durations": sorted(result.durations, key=lambda row: row["seconds"], reverse=True),
        "source_manifest": before, "logs": {name: str(path) for name, path in paths.items()},
        "limits": ["PASS covers only the selected unittest contracts.",
                   "Review every skip; missing owned inputs are not verified.",
                   "No instrumented client acceptance or independent full-game fidelity is established."],
    }
    write_json(output / "result.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--suite", choices=("all", *LANES), default="smoke")
    group.add_argument("--tests", nargs="+", help="explicit unittest module/class/method IDs")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--list", action="store_true", help="show recipes without loading tests")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps({"all": "unittest discover -s server/test -t .", **LANES}, indent=2))
        return 0
    try:
        output = output_directory(args.output, prefix="halcyon-checks-")
        if args.tests:
            names = args.tests
            selection = {"suite": "custom", "coverage": "SUBSET", "tests": names}
        elif args.suite == "all":
            names = None
            selection = {"suite": "all", "coverage": "FULL_UNITTEST_DISCOVERY"}
        else:
            names = ["server.test." + name for name in LANES[args.suite]]
            selection = {"suite": args.suite, "coverage": "SUBSET", "tests": names}
        print(f"Checks: {selection['suite']} ({selection['coverage']}); evidence: {output}", flush=True)
        loader = unittest.TestLoader()
        suite = (loader.loadTestsFromNames(names) if names is not None else
                 loader.discover(str(ROOT / "server/test"), top_level_dir=str(ROOT)))
        report = execute_suite(suite, output, selection=selection)
    except (OSError, ValueError) as exc:
        print(f"CHECK SETUP FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        key: report[key] for key in ("status", "selection", "tests_run", "executed_non_skipped",
                                    "workspace_matches_start", "seconds")
    } | {"failures": len(report["failures"]), "errors": len(report["errors"]),
         "skipped": len(report["skipped"]), "result": str(output / "result.json")}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
