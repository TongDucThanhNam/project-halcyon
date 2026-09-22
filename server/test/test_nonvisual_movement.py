"""Nonvisual movement evidence must fail closed, without a capture fallback."""
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from Tools import scenario_client as sc
from Tools.Teardown import observe_client_movement as obs


class NonvisualMovementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        setup = bytearray(102)
        struct.pack_into('>I', setup, 0, 1500)
        hero = bytearray(750)
        struct.pack_into('>I', hero, 0, 265)
        struct.pack_into('>I', hero, 8, 1500)
        self.records = [self.record(1001, setup.hex()), self.record(1011, hero.hex()),
                        self.record(1137, '')]
        adb = Mock()
        adb.client_version.return_value = {'version_name': '4.13.4', 'version_code': 147219}
        adb.screencap.side_effect = AssertionError('image invariant')
        tail = Mock(records=self.records, path=Path(self.temp.name) / 'wire.jsonl')
        self.driver = sc.ClientDriver('movement-walk', adb=adb, qa=sc._AbsentQa(), tail=tail,
                                     connection=77, profile={'movement_walk': {
                                         'walks': [{'label': 'probe', 'taps': [[870, 365], [620, 330]]}],
                                         'settle_before_first_walk_s': 0, 'final_wait_s': 0}},
                                     out_dir=Path(self.temp.name), timeout=1)
        self.driver._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
        self.driver.finish = Mock(side_effect=lambda status, **kw: {'status': status, **kw})
        for name in ('_screen_still', '_run_movement_walk_legacy', 'drive_entry', 'start_capture'):
            setattr(self.driver, name, Mock(side_effect=AssertionError('image invariant')))
        self.observer = Mock(errors=[], samples=12, output=Path(self.temp.name) / 'client-movement.jsonl')
        self.observer.start.return_value = {'pid': 42}
        self.observer.stop.return_value = {'samples': 12, 'errors': []}
        self.observer.ui_state.return_value = {'labels': ['Item Shop', 'BUY:', '0:42'], 'nodes': 180}
        self.factory = self.enterContext(patch.object(obs, 'ClientMovementObserver', return_value=self.observer))
        self.enterContext(patch.object(sc, 'verify_resolution'))
        self.enterContext(patch.object(sc.time, 'sleep'))

    @staticmethod
    def record(opcode, payload, **kw):
        return {'connection': 77, 'direction': 's2c', 'opcode': opcode,
                'payload': payload, 'time': time.time(), **kw}

    def rejected(self, stage='SETUP'):
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.driver.run_movement_walk()
        self.assertEqual(caught.exception.stage, stage)

    def test_image_capture_and_legacy_entry_profiles_are_rejected_before_input(self):
        for config in ({'capture_backend': 'host'}, {'drive_entry': True}):
            with self.subTest(config=config):
                self.driver.profile['movement_walk'] = config
                self.rejected()
        self.factory.assert_not_called()
        self.driver.adb.tap.assert_not_called()

    def test_missing_connection_is_not_guessed(self):
        self.driver.connection = None
        self.rejected()
        self.factory.assert_not_called()

    def test_build_back_is_gated_by_native_title_and_verified_once(self):
        self.observer.ui_state.side_effect = [{'labels': ['Choose a Build']}, {'labels': ['BUY:', '0:42']}]
        self.driver._guard_nonvisual_movement_ui(self.observer, dismiss_build=True)
        self.driver.adb.back.assert_called_once_with()
        self.assertEqual(self.driver.observations['native_ui_guards'][0]['after']['labels'], ['BUY:', '0:42'])

    def test_loading_then_build_then_hud_is_observed_before_any_walk(self):
        self.observer.ui_state.side_effect = [
            {'labels': ['Pro Tip: loading']},
            {'labels': ['BUY:', '0:00', 'Prepare For Battle... 10']},
            {'labels': ['Choose a Build']}, {'labels': ['BUY:', '0:12']}]
        self.driver._guard_nonvisual_movement_ui(self.observer, dismiss_build=True)
        self.driver.adb.back.assert_called_once_with()
        self.driver.adb.tap.assert_not_called()
        self.assertEqual(len(self.driver.observations['native_ui_guards'][0]['loading_wait']), 2)

    def test_loading_wait_is_bounded_and_never_taps(self):
        self.observer.ui_state.return_value = {'labels': ['Pro Tip: loading']}
        with patch.object(sc.time, 'monotonic', side_effect=[0, 26]):
            with self.assertRaises(sc.ClientStageFailure):
                self.driver._guard_nonvisual_movement_ui(self.observer, dismiss_build=True)
        self.driver.adb.back.assert_not_called()
        self.driver.adb.tap.assert_not_called()

    def test_missing_hud_is_not_mistaken_for_playable_world(self):
        self.observer.ui_state.return_value = {'labels': ['Guest', 'PLAY']}
        self.rejected()
        self.driver.adb.back.assert_not_called()
        self.driver.adb.tap.assert_not_called()

    def test_persistent_panel_fails_without_repeated_back_or_walk_input(self):
        self.observer.ui_state.return_value = {'labels': ['Choose a Build']}
        self.rejected()
        self.driver.adb.back.assert_called_once_with()
        self.driver.adb.tap.assert_not_called()
        self.observer.stop.assert_called_once_with()

    def test_settings_or_unknown_ui_read_failure_never_sends_back(self):
        self.observer.ui_state.return_value = {'labels': ['Settings']}
        self.rejected()
        self.driver.adb.back.assert_not_called()
        self.observer.ui_state.side_effect = RuntimeError('native UI cycle/node limit')
        self.rejected()
        self.driver.adb.tap.assert_not_called()
        self.driver.adb.back.assert_not_called()

    def test_wrong_hero_is_not_mistaken_for_owner(self):
        self.driver.profile['movement_walk']['hero_id'] = 925
        self.rejected()
        self.factory.assert_not_called()

    def test_ambiguous_owner_is_not_observed(self):
        other = bytearray(102)
        struct.pack_into('>I', other, 0, 1501)
        self.records.append(self.record(1001, other.hex()))
        self.rejected()
        self.factory.assert_not_called()

    def test_stale_world_is_not_driven(self):
        for record in self.records:
            record['time'] -= 60
        self.rejected()
        self.factory.assert_not_called()

    def test_missing_movement_input_stops_after_one_tap_and_releases_observer(self):
        self.driver.tail.wait_for.return_value = None
        self.rejected('CLIENT_INPUT_OBSERVED')
        self.driver.adb.tap.assert_called_once_with(870, 365)
        self.observer.stop.assert_called_once_with()
        self.assertEqual(len(self.driver.artifacts), 2)

    def test_runtime_error_prevents_further_input_and_releases_observer(self):
        self.observer.errors.append('entity lifetime changed')
        self.rejected('TRIAL_CONTINUITY')
        self.driver.adb.tap.assert_not_called()
        self.observer.stop.assert_called_once_with()

    def test_success_is_data_only_and_still_does_not_accept_smoothness(self):
        def receive(predicate, **kw):
            record = self.record(1012, '', direction='c2s')
            self.assertTrue(predicate(record))
            self.assertGreaterEqual(record['time'], kw['min_time'])
            self.records.append(record)
            return record
        self.driver.tail.wait_for.side_effect = receive
        result = self.driver.run_movement_walk()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['expected']['client_smoothness'], 'UNVERIFIED')
        self.assertEqual(self.driver.stages['PRESENTATION']['status'], 'UNVERIFIED')
        self.driver.adb.screencap.assert_not_called()
        self.observer.stop.assert_called_once_with()
        self.assertEqual(self.factory.call_args.args[2], 1500)

    def test_no_samples_cannot_pass_on_wire_inputs_alone(self):
        self.observer.samples = 0
        self.driver.tail.wait_for.return_value = self.record(1012, '', direction='c2s')
        self.rejected('TRIAL_CONTINUITY')

    def world_point(self):
        self.driver.profile['movement_walk']['walks'] = [
            {'label': 'world', 'world_points': [[-71,.00707,12]]}]
        self.observer.camera_control.return_value = {'eid':1500, 'locked':True}
        self.observer.project_position.return_value = {
            'screen_xy':[565.947,226.086], 'camera':{'dimensions':[960,540]}}

    def test_world_point_uses_native_projection_and_retains_it(self):
        self.world_point()
        def receive(predicate, **kw):
            record = self.record(1012, '', direction='c2s')
            self.records.append(record)
            return record
        self.driver.tail.wait_for.side_effect = receive
        result = self.driver.run_movement_walk()
        self.assertEqual(result['status'],'PASS')
        self.driver.adb.tap.assert_called_once_with(566,226)
        self.observer.project_position.assert_called_once_with([-71,.00707,12])
        self.assertIsNotNone(result['observed']['walks'][0]['taps'][0]['projection'])

    def test_camera_failure_or_hud_region_never_sends_world_point_input(self):
        self.world_point()
        self.observer.project_position.side_effect = ValueError('camera changed')
        self.rejected()
        self.driver.adb.tap.assert_not_called()
        self.observer.project_position.side_effect = None
        self.observer.project_position.return_value['screen_xy'] = [900,500]
        self.rejected()
        self.driver.adb.tap.assert_not_called()

    def test_mixed_pixel_and_world_sequence_is_rejected_before_observation(self):
        self.driver.profile['movement_walk']['walks'][0]['world_points'] = [[1,0,1]]
        self.rejected()
        self.factory.assert_not_called()


class ObserverQualificationTests(unittest.TestCase):
    def test_maps_must_identify_one_file_backed_arm64_base(self):
        mapping = '3128000-5000000 r-xp 00000000 08:01 123 /data/app/a/lib/arm64/libGameKindred.so'
        self.assertEqual(obs.mapped_base(mapping), 0x3128000)
        for invalid in ('', mapping.replace('arm64', 'x86'), mapping + '\n' + mapping.replace('3128000-', '6128000-')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                obs.mapped_base(invalid)

    def test_unpinned_library_is_rejected_before_elf_or_memory_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'not-the-owned-library'
            path.write_bytes(b'not a qualified image')
            with self.assertRaisesRegex(ValueError, 'pinned'):
                obs.anchor_config(path)

    def test_stop_preserves_delivery_mismatch_and_detaches_even_if_unload_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = obs.ClientMovementObserver(Mock(), Path(directory) / 'state.jsonl', 1500)
            script, session = Mock(), Mock()
            observer.script, observer.session = script, session
            observer.handle = observer.output.open('x', encoding='utf-8')
            observer._message({'type': 'send', 'payload': {'samples': [{'position_xyz': [1, 0, 2]}]}}, None)
            script.exports_sync.stop.return_value = {'sampled': 0}
            script.unload.side_effect = RuntimeError('unload failed')
            observer.calibrate = Mock()
            report = observer.stop()
            self.assertEqual(report['samples'], 1)
            self.assertTrue(any('count differs' in str(e) for e in report['errors']))
            self.assertTrue(any('unload failed' in str(e) for e in report['errors']))
            session.detach.assert_called_once_with()
            self.assertIsNone(observer.handle)
            self.assertEqual(json.loads(observer.output.read_text())['position_xyz'], [1, 0, 2])
            self.assertEqual(json.loads(observer.output.with_suffix('.metadata.json').read_text())['samples'], 1)
            observer.stop()  # repeated cleanup must not detach twice
            session.detach.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
