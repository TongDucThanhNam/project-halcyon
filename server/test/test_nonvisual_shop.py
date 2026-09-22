"""Server purchase success is insufficient without native inventory/stat state."""
import copy
import itertools
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from Tools import scenario_client as sc
from Tools.Teardown import observe_client_movement as obs
from server import roster


class ShopGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.adb = Mock()
        self.adb.screencap.side_effect = AssertionError('no images')
        self.qa = Mock(receipts=[], qa_dir=str(root/'qa'))
        self.initial = {'eid': 1500, 'alive': True, 'target': None,
            'x': roster.HERO_SPAWNS[1500][0], 'y': roster.HERO_SPAWNS[1500][1],
            'inventory': [], 'gold': 1000, 'combat_stats': {'weapon_power': 72},
            'default_items': [{'item': 457, 'instance': 2000}, {'item': 526, 'instance': 2001}]}
        self.final = copy.deepcopy(self.initial)
        self.final.update(inventory=[{'item': 458, 'instance': 2002, 'slot': 0}], gold=706,
                          combat_stats={'weapon_power': 82})
        self.states = [{'heroes': [h], 'phase': 'world', 'match_id': 'same', 'tick': tick}
                       for h, tick in ((self.initial, 100), (self.final, 120))]
        self.qa.snapshot.side_effect = self.states
        self.records = []
        self.tail = Mock(records=self.records)
        self.driver = sc.ClientDriver('shop-purchase', adb=self.adb, qa=self.qa, tail=self.tail,
            connection=7, profile={}, out_dir=root, timeout=2)
        self.driver._qualify_nonvisual_world = Mock(return_value=(1500, 0, 265))
        self.driver._guard_nonvisual_movement_ui = Mock()
        self.driver._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
        self.observer = Mock(errors=[], output=root/'native.jsonl')
        self.observer.start.return_value = {'pid': 42}
        self.observer.stop.return_value = {'errors': []}
        self.observer.snapshot.return_value = {'position_xyz': [self.initial['x'], 1.267, self.initial['y']]}
        for name in ('shop_control', 'shop_item_control', 'shop_buy_control'):
            getattr(self.observer, name).return_value = {'eid': 1500, 'center': [100, 100]}
        self.native = [{'current': {'gold': gold}, 'weapon_power': wp, 'weapon_power_layers': {'bonus': bonus}}
                       for gold, wp, bonus in ((1000, 72, 0), (700, 82, 10), (706, 82, 10))]
        self.inventories = [{'items': [{**i, 'quantity': 1} for i in h['default_items'] + h['inventory']]}
                            for h in (self.initial, self.final, self.final)]
        self.observer.resources.side_effect = self.native
        self.observer.inventory.side_effect = self.inventories
        self.enterContext(patch.object(obs, 'ClientMovementObserver', return_value=self.observer))
        self.enterContext(patch.object(sc.time, 'sleep'))
        self.enterContext(patch.object(sc.time, 'time', side_effect=itertools.count(1000)))
        self.tail.wait_for.side_effect = self.receive

    def receive(self, predicate, timeout, *, min_time):
        item = self.driver.profile.get('shop_purchase', {}).get('item_id', 458)
        row = {'connection': 7, 'direction': 'c2s' if self.tail.wait_for.call_count == 1 else 's2c',
               'opcode': 1081, 'payload': roster.build_shop_buy(1500, item).hex(), 'time': min_time}
        self.assertTrue(predicate(row))
        if row['direction'] == 'c2s':
            frames = [(1053, roster.build_hero_stat(1500, -300 if item == 458 else -850, stat_type=6)),
                      (1085, roster.build_item_inventory(1500, item, self.final['inventory'][0]['instance']))]
            if item == 505:
                frames.append((1099, roster.build_item_remove(1500, 2002)))
            self.records.extend({'connection': 7, 'direction': 's2c', 'opcode': op,
                                 'payload': body.hex(), 'time': min_time + .01} for op, body in frames)
        return row

    def tearDown(self):
        self.adb.screencap.assert_not_called()
        self.qa.submit.assert_not_called()

    def test_ordinary_purchase_requires_native_inventory_and_power(self):
        result = self.driver.run_shop_purchase()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['observed']['cost'], 300)
        self.assertEqual(self.adb.tap.call_count, 3)
        self.adb.back.assert_called_once()

    def test_server_instance_does_not_prove_native_inventory(self):
        self.inventories[-1]['items'][-1]['instance'] = 2999
        with self.assertRaisesRegex(sc.ClientStageFailure, 'native purchased inventory'):
            self.driver.run_shop_purchase()

    def test_native_bonus_must_actually_change(self):
        self.native[-1]['weapon_power_layers']['bonus'] = 0
        with self.assertRaisesRegex(sc.ClientStageFailure, 'native item weapon bonus'):
            self.driver.run_shop_purchase()

    def test_phantom_native_multiplier_blocks_before_any_input(self):
        self.native[0]['weapon_power'] = 79.2
        with self.assertRaisesRegex(sc.ClientStageFailure, 'native initial weapon power'):
            self.driver.run_shop_purchase()
        self.adb.tap.assert_not_called()

    def test_divergent_native_spawn_blocks_before_any_input(self):
        self.observer.snapshot.return_value['position_xyz'][0] += 3
        with self.assertRaisesRegex(sc.ClientStageFailure, 'native shop position'):
            self.driver.run_shop_purchase()
        self.adb.tap.assert_not_called()

    def test_missing_purchase_input_is_not_retried(self):
        self.tail.wait_for.side_effect = None
        self.tail.wait_for.return_value = None
        with self.assertRaisesRegex(sc.ClientStageFailure, 'no fresh matching shop'):
            self.driver.run_shop_purchase()
        self.assertEqual(self.adb.tap.call_count, 3)

    def test_upgrade_consumes_native_component_and_adds_net_power(self):
        self.driver.profile['shop_purchase'] = {'item_id': 505}
        self.initial['inventory'] = [{'item': 458, 'instance': 2002, 'slot': 0}]
        self.initial['combat_stats']['weapon_power'] = 82
        self.final.update(gold=156, inventory=[{'item': 505, 'instance': 2003, 'slot': 0}],
                          combat_stats={'weapon_power': 117})
        for n, gold, wp, bonus in zip(self.native, (1000, 150, 156), (82, 117, 117), (10, 45, 45)):
            n.update(current={'gold': gold}, weapon_power=wp, weapon_power_layers={'bonus': bonus})
        for value, hero in zip(self.inventories, (self.initial, self.final, self.final)):
            value['items'] = [{**i, 'quantity': 1} for i in hero['default_items'] + hero['inventory']]
        result = self.driver.run_shop_purchase()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['observed']['cost'], 850)


if __name__ == '__main__':
    unittest.main()
