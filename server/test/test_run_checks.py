"""The fast wrapper must retain failures/skips and refuse false green runs."""
import json
from pathlib import Path
import tempfile
import unittest

from Tools.run_checks import execute_suite
from Tools.verification_support import OutputPathError


class CheckRunnerContracts(unittest.TestCase):
    def run_fixture(self, suite, manifest_reader=lambda: {'fixture.py': 'stable'}):
        output = Path(tempfile.mkdtemp(prefix='halcyon-runner-test-')) / 'evidence'
        report = execute_suite(suite, output, selection={'suite': 'unit-fixture'},
                               manifest_reader=manifest_reader, diagnostic_after=0)
        return output, report

    def test_failures_errors_skips_and_subtests_are_preserved_not_swallowed(self):
        class Fixture(unittest.TestCase):
            def test_fail(self):
                self.fail('deliberate failure marker')
            def test_error(self):
                raise ValueError('deliberate error marker')
            def test_skip(self):
                self.skipTest('unavailable fixture marker')
            def test_subtest(self):
                with self.subTest(case='negative-control'):
                    self.assertEqual(1, 2)
        output, report = self.run_fixture(unittest.defaultTestLoader.loadTestsFromTestCase(Fixture))
        self.assertEqual((report['status'], report['tests_run']), ('FAIL', 4))
        self.assertEqual((len(report['failures']), len(report['errors']), len(report['skipped'])), (2, 1, 1))
        issues = (output / 'issues.log').read_text(encoding='utf-8')
        self.assertIn('deliberate failure marker', issues)
        self.assertIn('deliberate error marker', issues)
        events = [json.loads(line) for line in (output / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue({'FAIL', 'ERROR', 'SUBTEST_FAIL', 'SKIP', 'start', 'end'} <= {row['event'] for row in events})
        self.assertEqual(sum(row['event'] == 'end' for row in events), 4)
        with self.assertRaises(OutputPathError):
            execute_suite(unittest.TestSuite(), output, selection={}, diagnostic_after=0)
        self.assertEqual((output / 'issues.log').read_text(encoding='utf-8'), issues)

    def test_zero_tests_all_skipped_and_source_drift_never_pass(self):
        _, empty = self.run_fixture(unittest.TestSuite())
        self.assertEqual(empty['status'], 'FAIL')
        def skip():
            raise unittest.SkipTest('missing owned data')
        _, skipped = self.run_fixture(unittest.TestSuite([unittest.FunctionTestCase(skip)]))
        self.assertEqual((skipped['status'], skipped['executed_non_skipped']), ('FAIL', 0))
        manifests = iter([{'fixture.py': 'before'}, {'fixture.py': 'after'}])
        _, drift = self.run_fixture(unittest.TestSuite([unittest.FunctionTestCase(lambda: None)]),
                                    manifest_reader=lambda: next(manifests))
        self.assertEqual((drift['status'], drift['workspace_matches_start']), ('FAIL', False))
        self.assertEqual(drift['changed_sources'], ['fixture.py'])

    def test_success_captures_both_output_streams_and_records_subset(self):
        def successful():
            import sys
            print('stdout marker')
            print('stderr marker', file=sys.stderr)
        output, report = self.run_fixture(unittest.TestSuite([unittest.FunctionTestCase(successful)]))
        self.assertEqual((report['status'], report['tests_run']), ('PASS', 1))
        self.assertEqual(report['selection'], {'suite': 'unit-fixture'})
        self.assertEqual((output / 'stdout.log').read_text(encoding='utf-8'), 'stdout marker\n')
        self.assertEqual((output / 'stderr.log').read_text(encoding='utf-8'), 'stderr marker\n')


if __name__ == '__main__':
    unittest.main()
