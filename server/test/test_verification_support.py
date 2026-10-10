"""Evidence boundaries and original-checkout inputs survive source-only pins."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Tools import verification_support as support, verify_sandbox


class EvidenceBoundaries(unittest.TestCase):
    def test_repository_nonempty_and_file_destinations_are_refused_without_overwrite(self):
        with self.assertRaises(support.OutputPathError):
            support.output_directory(support.ROOT / 'audit-output-must-not-exist')
        base = Path(tempfile.mkdtemp(prefix='halcyon-output-test-'))
        retained = base / 'retained.json'
        retained.write_text('original evidence', encoding='utf-8')
        for target in (base, retained):
            with self.subTest(target=target), self.assertRaises(support.OutputPathError):
                support.output_directory(target)
        self.assertEqual(retained.read_text(encoding='utf-8'), 'original evidence')
        child = support.output_directory(base / 'new-run')
        self.assertEqual(child, base / 'new-run')
        with self.assertRaises(support.OutputPathError):
            support.output_directory(child, allow_existing_empty=False)

    def test_junction_attribute_is_refused_before_resolving_destination(self):
        base = Path(tempfile.mkdtemp(prefix='halcyon-reparse-test-'))
        real_lstat = Path.lstat
        def lstat(path):
            if path == base:
                return argparse.Namespace(st_file_attributes=support.REPARSE_ATTRIBUTE)
            return real_lstat(path)
        with patch.object(Path, 'lstat', lstat), patch.object(Path, 'is_symlink', return_value=False):
            with self.assertRaisesRegex(support.OutputPathError, 'symlink or junction'):
                support.reject_link_traversal(base / 'new')

    def test_owned_input_overrides_are_absolute_and_do_not_mutate_process_environment(self):
        overrides = {'HALCYON_LOCAL_ROOT': 'Local',
                     'HALCYON_SKYE_VOLLEY_CORPUS': 'Local/research/runtime-corpus',
                     'HALCYON_NATIVE_STEERING_LIBRARY': 'Local/steering.dll',
                     'UNRELATED_SECRET': 'must-not-be-recorded'}
        with patch.dict(os.environ, overrides):
            before = dict(os.environ)
            inputs = support.owned_input_environment()
            self.assertEqual(dict(os.environ), before)
            self.assertTrue(all(Path(value).is_absolute()
                                for key, value in inputs.items() if key != 'HALCYON_SPAWN_CORPUS'))
            self.assertTrue(all(Path(value).is_absolute()
                                for value in inputs['HALCYON_SPAWN_CORPUS'].split(os.pathsep)))
            self.assertNotIn('UNRELATED_SECRET', inputs)
            self.assertNotIn('UNRELATED_SECRET', support.runtime_switches())

    def test_short_real_pair_uses_original_local_and_never_claims_full_coverage(self):
        from server import navigation, entity_spawn
        if not Path(navigation.DEFAULT_CLASSIC_NAVMESH).is_file():
            self.skipTest('owned native navmesh unavailable')
        if not any(Path(path).is_dir() for path in entity_spawn._source_paths()):
            self.skipTest('owned spawn corpus unavailable')
        output = Path(tempfile.mkdtemp(prefix='halcyon-short-pin-test-')) / 'pair'
        args = argparse.Namespace(output=output, navmesh=None, seconds=.1,
                                  profile_from=None, profile_seconds=10)
        self.assertEqual(verify_sandbox.orchestrate(args), 1)
        result = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(result['identical'], dict.fromkeys(('stream', 'state', 'checkpoints'), True))
        self.assertTrue(result['same_source'])
        self.assertTrue(result['workspace_matches_snapshot'])
        self.assertFalse(result['full_duration_coverage'])
        self.assertEqual(len(result['runs']), 2)
        for run in result['runs']:
            self.assertEqual(run['ticks'], 2)
            self.assertIn('Tools/verification_support.py', run['source_manifest'])
            self.assertEqual(Path(run['navmesh']['path']), Path(navigation.DEFAULT_CLASSIC_NAVMESH).resolve())
            self.assertEqual(run['timing_attribution']['measured_ticks'], 2)
            for tick in run['slowest_ticks']:
                self.assertEqual(set(tick['phases']), {'qa', 'wave', 'bots', 'heroes_effects', 'economy', 'intents'})
                for phase in tick['phases'].values():
                    self.assertGreaterEqual(phase['wall_ms'], 0)
                    self.assertGreaterEqual(phase['thread_cpu_ms'], 0)
                self.assertAlmostEqual(tick['cost_ms'], tick['unattributed_wall_ms'] +
                                       sum(p['wall_ms'] for p in tick['phases'].values()))
        self.assertFalse((Path(result['source_snapshot']) / 'Local').exists())
        for index in (1, 2):
            self.assertEqual((output / f'worker-{index}-stderr.log').read_text(encoding='utf-8'), '')


class TickAttributionTests(unittest.TestCase):
    def test_long_wall_zero_cpu_is_host_or_scheduler_inference_not_cpu_work(self):
        phases = {'wave': {'wall_ms': 250, 'thread_cpu_ms': 0},
                  'heroes_effects': {'wall_ms': 5, 'thread_cpu_ms': 0}}
        row = verify_sandbox.tick_attribution(255, 0, phases)
        self.assertEqual(row['classification'], 'HOST_OR_SCHEDULER_STALL_INFERRED')
        self.assertEqual(row['dominant_wall_phase'], 'wave')
        self.assertIsNone(row['dominant_thread_cpu_phase'])

    def test_cpu_heavy_tick_names_its_measured_phase(self):
        phases = {'wave': {'wall_ms': 40, 'thread_cpu_ms': 39},
                  'heroes_effects': {'wall_ms': 20, 'thread_cpu_ms': 18}}
        row = verify_sandbox.tick_attribution(60, 57, phases)
        self.assertEqual(row['classification'], 'CPU_WORK')
        self.assertEqual(row['dominant_thread_cpu_phase'], 'wave')
        self.assertEqual(row['dominant_wall_phase'], 'wave')

    def test_small_zero_cpu_sample_does_not_prove_a_host_stall(self):
        row = verify_sandbox.tick_attribution(3, 0, {'wave': {'wall_ms': 3, 'thread_cpu_ms': 0}})
        self.assertEqual(row['classification'], 'MIXED_OR_CPU_CLOCK_QUANTIZED')
        self.assertEqual(verify_sandbox.DEADLINE_MS, 50)


if __name__ == '__main__':
    unittest.main()
