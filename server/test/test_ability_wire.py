"""Native action list and packet contracts, including external golden joins."""
import os
from pathlib import Path
import pickle
import struct
import unittest

from server import ability_wire, decode
from server.hero_balance import HERO_NAMES
from Tools.Teardown.inspect_ability_actions import read_actions


class AbilityActionTests(unittest.TestCase):
    def test_ui_slots_do_not_assume_native_ordinals(self):
        self.assertEqual([ability_wire.hero_action_variant(242, slot) for slot in 'ABC'], [1, 2, 3])
        self.assertEqual([ability_wire.hero_action_variant('Gwen', slot) for slot in 'ABC'], [1, 2, 3])
        self.assertEqual(ability_wire.hero_action_variant('Ringo', 'recall'), 4)
        self.assertEqual(ability_wire.hero_action_variant(242, 'recall'), 5)
        self.assertEqual(ability_wire.hero_action_variant(244, 'recall'), 3)
        self.assertIsNone(ability_wire.hero_action_variant(123456, 'recall'))
        self.assertIsNone(ability_wire.hero_action_variant(281, 'A'))

    def test_ground_cast_preserves_float_height_and_rejects_nonfinite(self):
        body = ability_wire.build_ground_cast(1500, 2.5, -3.5, 3, z=0.007)
        self.assertEqual(len(body), 22)
        self.assertEqual(struct.unpack_from('>IfffB', body)[:2], (1500, 2.5))
        self.assertAlmostEqual(struct.unpack_from('>f', body, 8)[0], 0.007)
        self.assertEqual(body[17:], bytes(5))
        with self.assertRaises(ValueError):
            ability_wire.build_ground_cast(1500, float('nan'), 0, 1)

    def test_every_retained_action_ordinal_matches_external_native_vector(self):
        names_path = Path(os.environ.get('TEMP', '')) / 'vg_max/inst_names.tsv'
        base = Path('D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data')
        if not names_path.exists() or not base.exists():
            self.skipTest('operator-owned CFF source is not installed')
        paths = dict(line.split('\t')[:2] for line in names_path.read_text().splitlines())
        for hero_id, retained in ability_wire.HERO_ACTIONS.items():
            with self.subTest(hero_id=hero_id):
                native = read_actions(base / paths[HERO_NAMES[hero_id]])
                actual = [next((row['index'] for row in native if row['name'].endswith('__' + slot)), None)
                          for slot in 'ABC'] + [len(native)]
                self.assertEqual(tuple(actual), retained)

    def test_catherine_target_actions_match_capture_and_named_buff(self):
        base = Path(os.environ.get('TEMP', '')) / 'vg_phaseB/vgr_live'
        prefix = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-1574e27a-e851-492b-8d91-94fc4bd66985'
        for chunk, row, action, kinds in [(4, 506, 'A', (371, 372)),
                                          (13, 1119, 'B', (373,)),
                                          (18, 754, 'recall', (25, 26))]:
            path = base / f'{prefix}.{chunk}.vgr'
            if not path.exists():
                self.skipTest('operator-owned Catherine VGR is not installed')
            frames, stats = decode.walk_vgr(str(path))
            self.assertEqual(stats['failures'], 0)
            _, op, body = frames[row]
            self.assertEqual(op, 1045)
            self.assertEqual(body, ability_wire.build_target_cast(1516, None,
                ability_wire.hero_action_variant(242, action)))
            buffs = {struct.unpack_from('>H', p, 14)[0] for _, opcode, p in frames[row + 1:row + 8]
                     if opcode == 1086 and struct.unpack_from('>II', p) == (1516, 1516)}
            self.assertTrue(set(kinds) <= buffs)

    def test_ground_cast_native_action_is_not_an_impact_kind(self):
        path = Path(os.environ.get('TEMP', '')) / 'vg_max/match6.halcyon_spawn_audit.pkl'
        if not path.exists():
            self.skipTest('operator-owned match6 cache is not installed')
        frames = pickle.loads(path.read_bytes())[0]
        for index, hero_id, action in [(47634, 439, 'C'), (49026, 265, 'C'), (53573, 266, 'C')]:
            op, body = frames[index]
            source, x, z, y = struct.unpack_from('>Ifff', body)
            self.assertEqual(op, 1046)
            self.assertEqual(body, ability_wire.build_ground_cast(source, x, y,
                ability_wire.hero_action_variant(hero_id, action), z=z))


if __name__ == '__main__':
    unittest.main()
