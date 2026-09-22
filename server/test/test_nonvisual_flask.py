"""Ordinary-item client gate cannot pass on server effects alone."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from Tools import scenario_client as sc
from Tools.Teardown import observe_client_movement as obs
from server import buff_wire, cooldown_wire, roster


class NonvisualFlaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.records = []
        self.adb = Mock()
        self.adb.screencap.side_effect = AssertionError('no images')
        self.qa = Mock(receipts=[])
        self.qa.submit.return_value = {'ok': True}
        hero = {'eid': 1500, 'hero_id': 265, 'alive': True, 'team': 1,
                'hp': 500, 'max_hp': 1214.2, 'energy': 100, 'max_energy': 508,
                'level': 5, 'statuses': [], 'default_items': [
                    {'instance': 2000, 'item': 457, 'remaining': 0}]}
        self.initial = {'phase': 'world', 'match_finished': False, 'heroes': [hero]}
        final = copy.deepcopy(self.initial)
        final['heroes'][0].update(hp=806, energy=255.448)
        self.qa.snapshot.side_effect = [self.initial, self.initial, final]
        tail = Mock(records=self.records, path=self.output / 'wire.jsonl')
        self.driver = sc.ClientDriver('healing-flask', adb=self.adb, qa=self.qa, tail=tail,
                                     connection=77, profile={}, out_dir=self.output, timeout=2)
        self.driver._qualify_nonvisual_world = Mock(return_value=(1500, 0, 265))
        self.driver._guard_nonvisual_movement_ui = Mock()
        self.driver._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
        self.driver.finish = Mock(side_effect=lambda status, **kw: {'status': status, **kw})
        self.observer = Mock(errors=[], samples=12, output=self.output / 'client-movement.jsonl')
        self.observer.start.return_value = {'pid': 42}
        self.observer.stop.return_value = {'errors': []}
        self.observer.default_item_control.return_value = {'eid': 1500, 'instance': 2000, 'center': [324, 497]}
        self.resources = [self.resource(500, 100, 0), self.resource(518, 110, 255),
                          self.resource(806, 255.448, 0), self.resource(806, 255.448, 0)]
        self.observer.resources.side_effect = self.resources
        self.enterContext(patch.object(obs, 'ClientMovementObserver', return_value=self.observer))
        self.enterContext(patch.object(sc.time, 'sleep'))
        self.enterContext(patch.object(sc.time, 'monotonic', side_effect=[0, 0, 7]))
        tail.wait_for.side_effect = self.receive

    @staticmethod
    def resource(hp, energy, barrier):
        return {'eid': 1500, 'current': {'hp': hp, 'energy': energy, 'barrier': barrier, 'fortified': 0}}

    def receive(self, predicate, **kwargs):
        request = {'connection': 77, 'direction': 'c2s', 'opcode': 1096,
                   'payload': struct.pack('>IH', 2000, 0).hex(), 'time': time.time()}
        self.assertTrue(predicate(request))
        self.assertGreaterEqual(request['time'], kwargs['min_time'])
        frames = [(1096, bytes.fromhex(request['payload'])),
                  (1086, buff_wire.build_buff_add(1500, 1500, 5, 1234, 259)),
                  (1162, cooldown_wire.build_item_timer(1500, cooldown_wire.ITEM_TAGS['healing_flask'], 120, 120))]
        frames += [(1054, struct.pack('>IIf', 1500, 1500, 18) + bytes(6))] * 17
        frames += [(1053, roster.build_hero_stat(1500, 508 * .3 * .3 / 5, 2))] * 17
        self.records.extend({'connection': 77, 'direction': 's2c', 'opcode': op,
                             'payload': payload.hex(), 'time': time.time()} for op, payload in frames)
        return request

    def reject(self, expected_stage):
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.driver.run_healing_flask()
        self.assertEqual(caught.exception.stage, expected_stage)
        self.observer.stop.assert_called_once()
        self.adb.screencap.assert_not_called()

    def test_success_needs_native_pool_lifetime_and_final_resource_agreement(self):
        result = self.driver.run_healing_flask()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['observed']['model_effects'], 'UNVERIFIED')
        self.assertEqual(result['expected']['official_timing_parity'], 'UNVERIFIED')
        self.adb.tap.assert_called_once_with(324, 497)
        self.adb.screencap.assert_not_called()
        self.assertEqual(len((self.output / 'client-resources.jsonl').read_text().splitlines()), 4)

    def test_existing_resource_drift_fails_setup_before_item_input(self):
        self.resources[0]['current']['hp'] = 457.455322
        self.reject('SETUP')
        self.adb.tap.assert_not_called()
        self.assertEqual(len((self.output / 'client-resources.jsonl').read_text().splitlines()), 1)

    def test_fresh_level_one_reserves_actual_pulses_not_fixed_350_hp(self):
        self.initial['heroes'][0].update(level=1, max_hp=672.7, hp=438.7)
        self.resources[0]['current']['hp'] = 438.7
        self.driver.tail.wait_for.side_effect = None
        self.driver.tail.wait_for.return_value = None
        # Reaching this stage proves setup accepted the uncapped level-one
        # fixture, while still refusing to claim that an input was observed.
        self.reject('CLIENT_INPUT_OBSERVED')
        command = self.qa.submit.call_args_list[1].args[0]
        self.assertAlmostEqual(command['hp'], 438.7)

    def test_high_level_fixed_margin_cannot_allow_healing_cap(self):
        self.initial['heroes'][0].update(level=12, max_hp=900, hp=500)
        self.driver.profile['healing_flask'] = {'hp': 500}
        self.reject('SETUP')
        self.adb.tap.assert_not_called()

    def test_server_success_cannot_hide_missing_native_barrier(self):
        self.resources[1]['current']['barrier'] = 0
        self.reject('PRESENTATION')
        self.assertEqual(self.driver.stages['AUTHORITATIVE_EFFECT']['status'], 'PASS')

    def test_native_hp_disagreement_fails_even_with_complete_wire_contract(self):
        for value in self.resources[2:]:
            value['current']['hp'] = 778.955322
        self.reject('PRESENTATION')

    def test_missing_input_stops_after_one_tap_and_keeps_resources(self):
        self.driver.tail.wait_for.side_effect = None
        self.driver.tail.wait_for.return_value = None
        self.reject('CLIENT_INPUT_OBSERVED')
        self.adb.tap.assert_called_once()

    def test_not_ready_item_is_not_forced_or_tapped(self):
        self.initial['heroes'][0]['default_items'][0]['remaining'] = 1
        self.reject('SETUP')
        self.qa.submit.assert_not_called()
        self.adb.tap.assert_not_called()


if __name__ == '__main__':
    unittest.main()
