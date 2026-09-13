"""Join external named attack groups to independently recorded wire ordinals."""
import unittest

from Tools.Teardown.inspect_attack_actions import read_attack_actions
from server.paths import pc_data_dir, research_dir
from server import attack_wire
from server.hero_balance import HERO_NAMES


class TestAttackMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pc_data_dir()
        names = research_dir('vg_max') / 'inst_names.tsv'
        if not cls.root.is_dir() or not names.is_file():
            raise unittest.SkipTest('operator-owned hero store/name index unavailable')
        cls.paths = {row[0]: cls.root / row[1] for line in names.read_text().splitlines()
                     if len(row := line.split('\t')) >= 2}

    def actions(self, eid):
        return read_attack_actions(self.paths[HERO_NAMES[eid]])

    def test_recorded_variants_join_ordinary_groups_including_conditional_group_offsets(self):
        count = 0
        for hero_id, variants in attack_wire.MEASURED_BASIC_VARIANTS.items():
            with self.subTest(hero=HERO_NAMES[hero_id]):
                ordinary = {row['index']: row['name'] for row in self.actions(hero_id)
                            if row['category'] == 'ordinary'}
                for variant in variants:
                    self.assertIn(variant, ordinary)
                count += 1
        self.assertEqual(count, 28)
        baptiste = self.actions(399)
        self.assertEqual([(r['index'], r['group']) for r in baptiste
                          if r['name'].endswith(('__DefaultAttack', '__AltAttack'))], [(10, 1), (11, 1)])

    def test_missing_ranged_kits_use_named_ordinary_actions_and_exclude_critical_entries(self):
        for hero_id, variants in attack_wire.SOURCE_BASIC_VARIANTS.items():
            with self.subTest(hero=HERO_NAMES[hero_id]):
                rows = self.actions(hero_id)
                ordinary = [row for row in rows if row['category'] == 'ordinary']
                self.assertEqual(tuple(row['index'] for row in ordinary), variants)
                self.assertEqual([row['name'].split('__')[-1] for row in ordinary],
                                 ['DefaultAttack', 'AltAttack'])
                self.assertEqual([attack_wire.basic_variant_for(hero_id, i) for i in range(4)],
                                 list(variants) * 2)
                self.assertTrue(set(variants).isdisjoint(row['index'] for row in rows
                                                        if row['category'] == 'critical'))

    def test_magnus_old_7_8_classification_was_perk_and_critical(self):
        rows = {row['index']: row for row in self.actions(418)}
        self.assertTrue(rows[7]['name'].endswith('__PerkProcAttack'))
        self.assertEqual(rows[8]['category'], 'critical')
        self.assertTrue(rows[9]['name'].endswith('__DefaultAttack'))
        self.assertEqual(attack_wire.basic_variant_for(418), 9)


if __name__ == '__main__':
    unittest.main()
