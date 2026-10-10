"""Pinned native-leaf execution is optional; its input/refusal contracts are not."""
from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile
import unittest

from Tools.Teardown import verify_native_health as native


class NativeHealthContracts(unittest.TestCase):
    def test_wrong_binary_fingerprint_is_rejected_before_native_execution(self):
        path = Path(tempfile.mkdtemp(prefix='halcyon-native-input-test-')) / 'not-a-library.bin'
        path.write_bytes(b'authored invalid test fixture')
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            native.NativeHealth(path)

    def test_unsupported_numeric_inputs_are_refused_without_rounding(self):
        base = native.BRANCH_CASES[2]
        for field, value in (('delta', float('nan')), ('hp', float('inf')),
                             ('barrier', -1), ('delta', .1), ('hp', True),
                             ('delta', 1e300), ('hp', 10 ** 1000),
                             ('flags', True), ('flags', 1)):
            with self.subTest(field=field, value=str(value)), self.assertRaises(ValueError):
                native.validate_case(replace(base, **{field: value}))
        for case in native.cases(True):
            native.validate_case(case)

    def test_native_only_branches_are_not_misrepresented_as_server_comparisons(self):
        self.assertIsNone(native.production_split(native.BRANCH_CASES[0]))
        self.assertIsNone(native.production_split(native.BRANCH_CASES[-1]))
        for case in native.BRANCH_CASES[1:-1]:
            with self.subTest(case=case.name):
                self.assertEqual(native.production_split(case), case.expected)

    def test_owned_original_leaf_repeats_and_matches_production_branches(self):
        from server import paths
        binary = paths.local_root() / 'vainglory/lib/arm64-v8a/libGameKindred.so'
        if not binary.is_file():
            self.skipTest('owned CE147219 ARM64 library unavailable')
        if importlib.util.find_spec('unicorn') is None:
            self.skipTest('optional requirements-native.txt is not installed')
        result = native.qualify(binary)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual((result['case_count'], result['native_executions'], result['production_comparisons']),
                         (26, 52, 19))
        self.assertEqual(result['isolated_case_count'], 10)
        self.assertEqual(result['sequential_hit_count'], 11)
        self.assertEqual(result['non_dyadic_measurement_count'], 5)
        for sequence in result['sequences']:
            self.assertTrue(all(hit['production_exact_numeric_match'] for hit in sequence['hits']))
            for before, after in zip(sequence['hits'], sequence['hits'][1:]):
                self.assertEqual(before['native_state_after'], tuple(after['input'][k] for k in ('hp', 'barrier', 'fortified')))
        self.assertGreater(result['non_dyadic_max_abs_delta'], 0,
                           'measure actual float32-vs-production differences, never hide them behind a tolerance')
        for measurement in result['non_dyadic_measurements']:
            self.assertEqual(measurement['numeric_parity'], 'MEASURED_ONLY_NOT_QUALIFIED')
        self.assertTrue(result['repeat_byte_exact'])
        self.assertEqual(result['scope'], 'NATIVE_COMPONENT_ONLY')


if __name__ == '__main__':
    unittest.main()
