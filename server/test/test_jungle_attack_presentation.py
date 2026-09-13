"""Native NPC ordinals and one presentation action per actual jungle attack."""
import struct
import unittest

from Tools.Teardown.inspect_jungle_actions import read_jungle_actions
from server.paths import pc_data_dir, research_dir
from server import decode, jungle, jungle_attack_wire, structures
from server.hero_movement import HeroMovement
from server.navigation import within_distance


STORE_PATHS = {
    357: '49/49C06DCA45B7A62D1658D7060775CDF9',
    358: '1D/1D445E1A9C41B6C0219159F85DD681CE',
    359: '1B/1B0FA18811EC4D6F6027BF06081F9A5F',
    360: '9A/9A66B107F6CF9BAB912D7DAD1436CBCF',
    361: '5E/5EC683C4C7E2442DC2884382FB31F70A',
    362: '6F/6F2963E4A635C92A389523AA51F30969',
    363: 'F3/F30335D5EF888FC30E4944D370B9EC51',
    364: '95/95C3C182530326BD98A1D38E4289E28C',
}


class TestJungleActionEvidence(unittest.TestCase):
    def test_external_direct_vectors_identify_ordinary_and_exclude_special_actions(self):
        root = pc_data_dir()
        if not all((root / path).is_file() for path in STORE_PATHS.values()):
            self.skipTest('operator-owned jungle CFFs unavailable')
        for archetype, path in STORE_PATHS.items():
            with self.subTest(archetype=archetype):
                rows = read_jungle_actions(root / path)
                self.assertTrue(all('Default' in row['name'] or 'Alt' in row['name']
                                    for row in rows[:2]))
                self.assertEqual([jungle_attack_wire.basic_variant_for(archetype, i)
                                  for i in range(4)], [0, 1, 0, 1])
                if archetype in (363, 364):
                    suffixes = [row['name'].split('__')[-1] for row in rows]
                    self.assertEqual(suffixes[:4], ['DefaultAttack', 'AltAttack', 'CritAttack', 'Spawn'])
                    if archetype == 364:
                        self.assertEqual(suffixes[4], 'Victory')
        self.assertIsNone(jungle_attack_wire.basic_variant_for(999))
        with self.assertRaises(ValueError):
            jungle_attack_wire.build_basic_attack(100000, 1500, 999)

    def test_eight_complete_native_actions_and_independent_damage_pairs(self):
        session = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-'
        match = '591146df-33f2-4f12-9a04-8d800d239821'
        elder = '045f86d4-7ef2-4125-a835-e70a96288c88'
        samples = [
            (research_dir('vg_max') / 'vgr2', match, 5, 1254, 1295, 357),
            (research_dir('vg_max') / 'vgr2', match, 5, 1041, 1094, 357),
            (research_dir('vg_max') / 'vgr2', match, 4, 1026, 1103, 359),
            (research_dir('vg_max') / 'vgr2', match, 4, 1132, 1169, 359),
            (research_dir('vg_max') / 'vgr2', match, 4, 333, 373, 360),
            (research_dir('vg_max') / 'vgr2', match, 3, 960, 1048, 360),
            (research_dir('vg_max') / 'vgr5b', elder, 8, 330, 352, 358),
            (research_dir('vg_max') / 'vgr5b', elder, 8, 822, 881, 358),
        ]
        paths = [folder / f'{session}{match_id}.{chunk}.vgr'
                 for folder, match_id, chunk, *_ in samples]
        if not all(path.is_file() for path in paths):
            self.skipTest('operator-owned jungle attack corpus unavailable')
        seen = set()
        for path, (_, _, _, start, impact, archetype) in zip(paths, samples):
            frames, stats = decode.walk_vgr(path)
            self.assertEqual(stats['failures'], 0)
            _, opcode, payload = frames[start]
            self.assertEqual(opcode, 1045)
            source, target = struct.unpack_from('>II', payload)
            self.assertEqual(jungle_attack_wire.build_basic_attack(source, target, archetype, payload[8]),
                             (opcode, payload))
            # NPCs do not have the heroes' immediate current-position pair.
            self.assertEqual(frames[start + 1][1], 1086)
            _, opcode, damage = frames[impact]
            self.assertEqual(opcode, 1054)
            self.assertEqual(struct.unpack_from('>II', damage), (target, source))
            self.assertLess(struct.unpack_from('>f', damage, 8)[0], 0)
            self.assertEqual(damage[13], 5)
            seen.add((archetype, payload[8]))
        self.assertEqual(seen, {(a, v) for a in (357, 358, 359, 360) for v in (0, 1)})


class TestJungleAttackCadence(unittest.TestCase):
    def test_live_treant_oblique_boundary_closes_then_attacks_without_early_damage(self):
        # Celeste2's server coordinates stopped 1.12 microunits outside 2.0.
        # The previous float residual repeatedly emitted 1070 without moving.
        monster = jungle.Monster(100000, 'left_a', jungle.CONFIGS[jungle.MonsterType.TREANT],
                                 -45.3795, 17.534555)
        hero = HeroMovement(eid=1500, x=-46.120217, y=19.392334)
        monster.target_eid = hero.eid
        before = monster.x, monster.y
        self.assertFalse(within_distance(before, (hero.x, hero.y), monster.config.attack_range))
        hp = hero.hp
        approach = monster.step(0.05, 0, {hero.eid: hero})
        self.assertNotIn(1045, [op for op, _ in approach])
        self.assertNotIn(1054, [op for op, _ in approach])
        self.assertEqual(hero.hp, hp)
        self.assertNotEqual((monster.x, monster.y), before)
        self.assertTrue(within_distance((monster.x, monster.y), (hero.x, hero.y), monster.config.attack_range))
        frames = monster.step(0.05, 0.05, {hero.eid: hero})
        self.assertEqual([op for op, _ in frames if op in (1045, 1054)], [1045, 1054])
        self.assertEqual(struct.unpack_from('>II', frames[0][1]), (monster.eid, hero.eid))
        self.assertEqual(struct.unpack_from('>II', frames[1][1]), (hero.eid, monster.eid))
        self.assertLess(hero.hp, hp)
        self.assertEqual(monster.step(0.05, 0.1, {hero.eid: hero}), [])

    def test_each_neutral_kind_presents_once_before_unchanged_damage_cadence(self):
        for kind in jungle.CONFIGS:
            with self.subTest(kind=kind):
                monster = jungle.Monster(100000, 'test', jungle.CONFIGS[kind], 0, 0)
                hero = HeroMovement(eid=1500, x=1, y=0)
                monster.target_eid = hero.eid
                hits = []
                def hit(a, b, amount, damage_type, now):
                    hits.append((amount, damage_type, now))
                    return [(1054, b'contact')]
                first = monster.step(0.05, 2, {hero.eid: hero}, hit)
                self.assertEqual([op for op, _ in first], [1045, 1054])
                self.assertEqual(struct.unpack_from('>II', first[0][1]), (monster.eid, hero.eid))
                self.assertEqual(first[0][1][8], 0)
                self.assertEqual(monster.step(0.05, 2.05, {hero.eid: hero}, hit), [])
                next_at = 2 + monster.config.attack_cooldown
                second = monster.step(0.05, next_at, {hero.eid: hero}, hit)
                self.assertEqual([op for op, _ in second], [1045, 1054])
                self.assertEqual(second[0][1][8], 1)
                self.assertEqual(hits, [(monster.config.attack_damage, 'weapon', 2),
                                        (monster.config.attack_damage, 'weapon', next_at)])

    def test_pursuit_leashing_dead_and_friendly_targets_emit_no_attack(self):
        for state in ('pursuit', 'leashing', 'dead', 'friendly'):
            with self.subTest(state=state):
                monster = jungle.Monster(100000, 'test', jungle.CONFIGS[jungle.MonsterType.TREANT], 0, 0)
                hero = HeroMovement(eid=1500, x=1, y=0)
                monster.target_eid = hero.eid
                if state == 'pursuit':
                    hero.teleport(7, 0)
                elif state == 'leashing':
                    monster.leashing = True
                elif state == 'dead':
                    monster.is_alive = False
                else:
                    monster.team = hero.team
                frames = monster.step(0.05, 2, {hero.eid: hero})
                self.assertNotIn(1045, [op for op, _ in frames])
                self.assertEqual(monster.attack_ordinal, 0)

    def test_captured_kraken_has_one_action_for_two_damage_components(self):
        manager = jungle.JungleManager()
        hero = HeroMovement()
        manager.step(0.05, 900, {})
        kraken = manager.active_kraken
        kraken.attack_ordinal = 7
        manager.apply_damage_to_monster(kraken.eid, kraken.hp, hero, 901)
        self.assertEqual(kraken.attack_ordinal, 0)
        buildings = structures.StructureManager()
        outer = buildings.structures[3539]
        kraken.siege_stage, kraken.x, kraken.y = 'siege', outer.x - 2, outer.y
        hits = []
        def hit(a, b, amount, kind, now):
            hits.append((b.eid, amount, kind, now))
            return [(1054, kind.encode())]
        frames = manager.step(0.05, 903, {}, structures=buildings, damage_callback=hit)
        self.assertEqual([op for op, _ in frames], [1045, 1054, 1054])
        self.assertEqual(struct.unpack_from('>II', frames[0][1]), (kraken.eid, outer.eid))
        self.assertEqual(frames[0][1][8], 0)
        self.assertEqual(hits, [(outer.eid, 271, 'weapon', 903), (outer.eid, 70, 'true', 903)])
        self.assertEqual(manager.step(0.05, 903.05, {}, structures=buildings, damage_callback=hit), [])
        frames = manager.step(0.05, kraken.next_attack_at, {}, structures=buildings, damage_callback=hit)
        self.assertEqual([op for op, _ in frames], [1045, 1054, 1054])
        self.assertEqual(frames[0][1][8], 1)


if __name__ == '__main__':
    unittest.main()
