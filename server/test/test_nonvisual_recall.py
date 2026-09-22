"""Recall acceptance cannot substitute wire arrival for native client state."""
import copy
import itertools
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from Tools import scenario_client as sc
from Tools.Teardown import observe_client_movement as obs
from server import ability_wire, buff_wire, recall_wire, roster


class RecallGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.adb = Mock()
        self.adb.screencap.side_effect = AssertionError('no images')
        self.qa = Mock(receipts=[], qa_dir=str(root / 'qa'))
        self.qa.submit.return_value = {'ok': True}
        hero = {'eid': 1500, 'alive': True, 'statuses': [], 'recall_completes_at': None,
                'hp': 400, 'energy': 125, 'max_hp': 1000, 'max_energy': 500, 'x': -65, 'y': 0}
        state = {'heroes': [hero], 'phase': 'world', 'match_finished': False, 'match_id': 'same', 'tick': 100}
        channel = copy.deepcopy(state)
        channel['heroes'][0]['recall_completes_at'] = 104
        final = copy.deepcopy(state)
        final['tick'] = 210
        final['heroes'][0].update(hp=900, energy=400, x=roster.HERO_SPAWNS[1500][0], y=roster.HERO_SPAWNS[1500][1])
        self.qa.snapshot.side_effect = [state, state, channel, final]
        self.records = []
        self.tail = Mock(records=self.records)
        self.driver = sc.ClientDriver('recall-return', adb=self.adb, qa=self.qa, tail=self.tail,
            connection=7, profile={}, out_dir=root, timeout=2)
        d = self.driver
        d._qualify_nonvisual_world = Mock(return_value=(1500, 0, 265))
        d._guard_nonvisual_movement_ui = Mock()
        d._lock_nonvisual_camera = Mock()
        d._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
        self.observer = Mock(errors=[], output=root / 'positions.jsonl')
        self.observer.start.return_value = {'pid': 42}
        self.observer.stop.return_value = {'errors': []}
        self.observer.recall_control.return_value = {'eid': 1500, 'center': [715, 506]}
        self.resources = [self.resource(400, 125)] + [self.resource(900, 400) for _ in range(3)]
        self.observer.resources.side_effect = self.resources
        sx, sy = roster.HERO_SPAWNS[1500]
        self.positions = [{'position_xyz': [-65, 0, 0]}] + [{'position_xyz': [sx, 1.3, sy]} for _ in range(3)]
        self.observer.snapshot.side_effect = self.positions
        self.enterContext(patch.object(obs, 'ClientMovementObserver', return_value=self.observer))
        self.enterContext(patch.object(sc.time, 'sleep'))
        self.enterContext(patch.object(sc.time, 'monotonic', side_effect=[0, 0, 6]))
        self.enterContext(patch.object(sc.time, 'time', side_effect=itertools.count(1000)))
        self.tail.wait_for.side_effect = self.receive

    @staticmethod
    def resource(hp, energy):
        return {'current': {'hp': hp, 'energy': energy}, 'max_hp': 1000, 'max_energy': 500}

    def receive(self, predicate, timeout, *, min_time):
        if self.tail.wait_for.call_count == 1:
            request = {'connection': 7, 'direction': 'c2s', 'opcode': 1041,
                       'payload': 'ffffffff0500', 'time': min_time}
            self.assertTrue(predicate(request))
            sx, sy = roster.HERO_SPAWNS[1500]
            frames = [(1086, buff_wire.build_buff_add(1500, 1500, 4, 100, 25)),
                      (1086, buff_wire.build_buff_add(1500, 1500, 4, 101, 26)),
                      (1094, recall_wire.build_recall_trigger(1500, 100)),
                      (1033, recall_wire.build_return_relocation(1500, sx, sy, 1.3))]
            self.records.extend({'connection': 7, 'direction': 's2c', 'opcode': op,
                                 'payload': payload.hex(), 'time': min_time + (4 if op in (1033, 1094) else .01)}
                                for op, payload in frames)
            return request
        ack = {'connection': 7, 'direction': 's2c', 'opcode': 1045,
               'payload': ability_wire.build_target_cast(1500, None, 5).hex(), 'time': min_time}
        self.assertTrue(predicate(ack))
        return ack

    def tearDown(self):
        self.adb.screencap.assert_not_called()

    def test_success_requires_native_return_and_resource_restoration(self):
        result = self.driver.run_recall_return()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['observed']['model_effect'], 'UNVERIFIED')
        self.adb.tap.assert_called_once_with(715, 506)

    def test_wire_return_does_not_prove_native_relocation(self):
        self.positions[-1]['position_xyz'] = [-65, 0, 0]
        with self.assertRaisesRegex(sc.ClientStageFailure, 'native client did not reach'):
            self.driver.run_recall_return()

    def test_server_refill_does_not_prove_native_healing(self):
        for value in self.resources[1:]:
            value['current']['hp'] = 400
        with self.assertRaisesRegex(sc.ClientStageFailure, 'native Recall healing'):
            self.driver.run_recall_return()

    def test_missing_input_stops_after_one_tap(self):
        self.tail.wait_for.side_effect = None
        self.tail.wait_for.return_value = None
        with self.assertRaisesRegex(sc.ClientStageFailure, 'no fresh native Recall'):
            self.driver.run_recall_return()
        self.adb.tap.assert_called_once()
        self.observer.stop.assert_called_once()

    def test_native_fixture_position_mismatch_prevents_input(self):
        self.positions[0]['position_xyz'] = [-50, 0, 0]
        with self.assertRaisesRegex(sc.ClientStageFailure, 'fixture position/resources disagree'):
            self.driver.run_recall_return()
        self.adb.tap.assert_not_called()


if __name__ == '__main__':
    unittest.main()
