"""Synthetic evidence: offline metrics must retain attribution and unknowns."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from Tools.Teardown.movement_client_report import client_report


class ClientReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.rows = []
        setup, hero = bytearray(102), bytearray(750)
        struct.pack_into('>I', setup, 0, 1500)
        struct.pack_into('>I', hero, 0, 925)
        struct.pack_into('>I', hero, 8, 1500)
        self.row(0, 's2c', 1001, setup)
        self.row(.1, 's2c', 1011, hero)
        self.row(1.2, 'c2s', 1012, struct.pack('>ff6x', 2, 0))
        self.row(1.3, 's2c', 1016, struct.pack('>Bff5x', 0, 2, 0))
        self.row(1.9, 's2c', 1070, struct.pack('>Iff2x', 1500, 2, 0))
        self.row(2.4, 'c2s', 1012, struct.pack('>ff6x', 0, 0))
        self.row(2.5, 's2c', 1016, struct.pack('>Bff5x', 0, 0, 0))
        self.row(2.9, 's2c', 1070, struct.pack('>Iff2x', 1500, 0, 0))
        self.result = {'status': 'PASS', 'scenario': 'movement-walk',
                       'observations': {'wire_identity': {'connection': 77, 'eid': 1500, 'slot': 0, 'hero_id': 925}},
                       'observed': {'data_window': {'started_at': .9, 'ended_at': 3}},
                       'gestures': [{'kind': 'walk-tap', 'walk': name, 'order': 0, 'wall_before': t}
                                    for name, t in [('forward', 1), ('retarget', 2)]],
                       'provenance': {'client_version': {'version_code': 147219, 'version_name': '4.13.4'}}}
        self.samples = [{'guest_monotonic_ms': t * 1000, 'position_xyz': [x, 0, 0],
                         'correction_velocity_xyz': [-.2, 0, 0], 'correction_remaining_s': .3, 'read_ms': .1}
                        for t, x in [(.99, 0), (1.01, 0), (1.4, 1), (1.5, .9), (1.95, 2), (2.1, 1.5), (2.8, 0)]]
        self.meta = {'identity': {'eid': 1500}, 'errors': [], 'samples': len(self.samples),
                     'library_sha256': 'synthetic', 'clock_brackets': [self.clock(0), self.clock(3)]}

    @staticmethod
    def clock(t):
        return [{'host_monotonic_before_s': t, 'host_monotonic_after_s': t,
                 'host_wall_before_s': t, 'client': {'guest_monotonic_ms': t * 1000}}]

    def row(self, t, direction, opcode, payload):
        self.rows.append({'time': t, 'direction': direction, 'opcode': opcode,
                          'decoded': bytes(payload), 'connection': 77, 'line': len(self.rows) + 1})

    def write(self):
        (self.path / 'client-result-1.json').write_text(json.dumps(self.result))
        (self.path / 'client-movement.metadata.json').write_text(json.dumps(self.meta))
        (self.path / 'client-movement.jsonl').write_text(''.join(json.dumps(s) + '\n' for s in self.samples))

    def analyze(self, labels=('forward',)):
        self.write()
        return client_report(self.rows, self.path, 77, 1500, 0, labels)

    def test_real_reversal_is_counted_but_predicted_retarget_is_excluded(self):
        report = self.analyze()
        first, second = report['requests']
        self.assertAlmostEqual(first['backward']['total_units'], .1)
        self.assertEqual(first['backward']['count'], 1)
        self.assertEqual(first['last_sample_target_distance'], 0)
        self.assertEqual(second['backward']['status'], 'UNMEASURED')
        self.assertEqual(report['straight_legs_with_backward_steps'], 1)
        self.assertEqual(report['client_smoothness'], 'UNVERIFIED')
        self.assertEqual(report['cross_run_comparability'], 'UNVERIFIED')

    def test_corner_paths_and_missing_acks_never_get_reversal_verdict(self):
        self.assertEqual(self.analyze(())['straight_legs_measured'], 0)
        self.rows = [r for r in self.rows if r['opcode'] != 1016]
        report = self.analyze()
        self.assertEqual(report['straight_legs_measured'], 0)
        self.assertIsNone(report['requests'][0]['last_sample_target_distance'])

    def test_read_spanning_the_next_gesture_cannot_create_a_reversal(self):
        sample = dict(self.samples[4], guest_monotonic_ms=1999,
                      position_xyz=[1.4, 0, 0], read_ms=5)
        self.samples.insert(5, sample)
        self.meta['samples'] += 1
        report = self.analyze()
        self.assertEqual(report['requests'][0]['last_position'], (2, 0))
        self.assertEqual(report['requests'][0]['backward']['count'], 1)

    def test_clock_uncertainty_trims_boundary_samples(self):
        # Each RPC midpoint is still zero offset, but has a +/-20 ms bracket.
        for batch in self.meta['clock_brackets']:
            b = batch[0]
            b['host_wall_before_s'] -= .02
            b['host_monotonic_after_s'] += .04
        report = self.analyze()
        self.assertAlmostEqual(report['clock']['boundary_margin_s'], .02)
        self.assertEqual(report['requests'][0]['origin'], (1, 0))

    def test_wrong_actor_and_wrong_bootstrap_are_rejected(self):
        self.result['observations']['wire_identity']['slot'] = 1
        with self.assertRaisesRegex(ValueError, 'wire identity'):
            self.analyze()
        self.result['observations']['wire_identity']['slot'] = 0
        self.result['observations']['wire_identity']['hero_id'] = 265
        with self.assertRaisesRegex(ValueError, 'bootstrap'):
            self.analyze()

    def test_setup_failure_and_observer_error_are_not_gameplay_measurements(self):
        self.result['status'] = 'ERROR'
        with self.assertRaisesRegex(ValueError, 'failed setup'):
            self.analyze()
        self.result['status'] = 'PASS'
        self.meta['errors'] = ['entity lifetime changed']
        with self.assertRaisesRegex(ValueError, 'observer errors'):
            self.analyze()

    def test_partial_and_missing_samples_fail_closed(self):
        self.meta['samples'] += 1
        with self.assertRaisesRegex(ValueError, 'count mismatch'):
            self.analyze()
        self.meta['samples'] -= 1
        self.write()
        path = self.path / 'client-movement.jsonl'
        path.write_bytes(path.read_bytes().rstrip(b'\n'))
        with self.assertRaisesRegex(ValueError, 'incomplete native'):
            client_report(self.rows, self.path, 77, 1500, 0)

    def test_clock_regression_and_missing_end_brackets_are_rejected(self):
        self.samples[2]['guest_monotonic_ms'] = 0
        with self.assertRaisesRegex(ValueError, 'time regressed'):
            self.analyze()
        self.samples[2]['guest_monotonic_ms'] = 1400
        self.meta['clock_brackets'].pop()
        with self.assertRaisesRegex(ValueError, 'start/end'):
            self.analyze()

    def test_wrong_input_attribution_cannot_silently_compare(self):
        self.rows[2]['time'] = .95
        with self.assertRaisesRegex(ValueError, 'scripted-input window'):
            self.analyze()

    def test_unknown_label_is_not_silently_skipped(self):
        with self.assertRaisesRegex(ValueError, 'unknown straight'):
            self.analyze(('typo',))

    def add_models(self):
        self.meta['model_transform'] = True
        for sample in self.samples:
            xyz = list(sample['position_xyz'])
            sample['model'] = {'translation_xyz': xyz,
                'matrix_column_major': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] + xyz + [1]}

    def test_model_metrics_do_not_silently_reuse_logical_positions(self):
        self.add_models()
        self.samples[3]['model']['translation_xyz'][0] = 1.1
        self.samples[3]['model']['matrix_column_major'][12] = 1.1
        self.assertEqual(self.analyze()['straight_legs_with_backward_steps'], 1)
        report = client_report(self.rows, self.path, 77, 1500, 0, ('forward',), position_source='model')
        self.assertEqual(report['straight_legs_with_backward_steps'], 0)
        self.assertEqual(report['position_source'], 'model')
        self.assertEqual(report['client_smoothness'], 'UNVERIFIED')

    def test_unqualified_model_run_is_refused(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'not qualified'):
            client_report(self.rows, self.path, 77, 1500, 0, position_source='model')

    def test_missing_or_inconsistent_model_sample_is_not_filled_from_entity(self):
        self.add_models()
        self.samples[2]['model']['translation_xyz'][0] = 99
        self.write()
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            client_report(self.rows, self.path, 77, 1500, 0, position_source='model')
        del self.samples[2]['model']
        self.write()
        with self.assertRaisesRegex(ValueError, 'absent'):
            client_report(self.rows, self.path, 77, 1500, 0, position_source='model')


if __name__ == '__main__':
    unittest.main()
