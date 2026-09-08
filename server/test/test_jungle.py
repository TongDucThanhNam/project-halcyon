"""Unit tests for Project Halcyon jungle camps, monsters, objectives, leashing, and brush."""
import struct
import unittest

from server import economy, hero_movement, jungle, level_wire, roster, wire


class TestJungleCampsInitialization(unittest.TestCase):
    def setUp(self):
        self.jm = jungle.JungleManager(open_time=0.0)

    def test_all_8_camps_exist(self):
        camp_ids = {m.camp_id for m in self.jm.monsters.values()}
        expected_camps = {
            "LCampA", "LCampB", "LCampC", "LCampD",
            "RCampA", "RCampB", "RCampC", "RCampD",
        }
        self.assertEqual(camp_ids, expected_camps)

    def test_monster_compositions(self):
        # Camp A (Treant) has 1 monster
        l_camp_a = [m for m in self.jm.monsters.values() if m.camp_id == "LCampA"]
        self.assertEqual(len(l_camp_a), 1)
        self.assertEqual(l_camp_a[0].config.monster_type, jungle.MonsterType.TREANT)
        self.assertEqual(l_camp_a[0].hp, 750.0)

        # Camp B (Big Bear + Small Bear) has 2 monsters
        l_camp_b = [m for m in self.jm.monsters.values() if m.camp_id == "LCampB"]
        self.assertEqual(len(l_camp_b), 2)
        types_b = {m.config.monster_type for m in l_camp_b}
        self.assertEqual(types_b, {jungle.MonsterType.BIG_BEAR, jungle.MonsterType.SMALL_BEAR})

        # Camp D (Two Small Bears) has 2 monsters
        l_camp_d = [m for m in self.jm.monsters.values() if m.camp_id == "LCampD"]
        self.assertEqual(len(l_camp_d), 2)
        for m in l_camp_d:
            self.assertEqual(m.config.monster_type, jungle.MonsterType.SMALL_BEAR)
            self.assertEqual(m.hp, 480.0)


class TestMonsterCombatAndBounty(unittest.TestCase):
    def setUp(self):
        self.jm = jungle.JungleManager(open_time=0.0)
        self.hero = hero_movement.HeroMovement(eid=1500, hp=500.0, max_hp=800.0)
        self.heroes = {1500: self.hero}
        self.econ = economy.EconomyManager()

    def test_monster_takes_damage_and_aggros(self):
        treant = next(m for m in self.jm.monsters.values() if m.camp_id == "LCampA")
        self.assertIsNone(treant.target_eid)

        # Attack treant for 100 dmg
        frames = self.jm.apply_damage_to_monster(
            monster_eid=treant.eid,
            damage=100.0,
            attacker_hero=self.hero,
            now=1.0,
        )
        self.assertEqual(treant.hp, 650.0)
        self.assertEqual(treant.target_eid, 1500)
        self.assertTrue(treant.is_alive)
        self.assertEqual(len(frames), 0)  # no death frames yet

    def test_monster_kill_rewards_bounty_and_heal(self):
        treant = next(m for m in self.jm.monsters.values() if m.camp_id == "LCampA")
        init_gold = self.econ.get_or_create(1500).gold

        # Lethal hit to Treant (750 HP)
        frames = self.jm.apply_damage_to_monster(
            monster_eid=treant.eid,
            damage=800.0,
            attacker_hero=self.hero,
            now=10.0,
            economy_mgr=self.econ,
            all_heroes=self.heroes,
        )
        self.assertFalse(treant.is_alive)

        # Native1072 death retains the Treant corpse until its4-second removal.
        opcodes = [op for op, _ in frames]
        self.assertIn(wire.OP.ENTITY_DEATH, opcodes)
        self.assertNotIn(wire.OP.DESTROY, opcodes)
        self.assertNotIn(wire.OP.DESPAWN, opcodes)
        # The 70 XP bounty crosses the native first requirement of 68. The
        # fixture gains one 70-HP level increase as well as one Treant heal.
        player_econ = self.econ.get_or_create(1500)
        self.assertEqual(economy.XP_LEVEL_THRESHOLDS[1], 68.0)
        self.assertEqual((player_econ.level, self.hero.level), (2, 2))
        self.assertEqual(player_econ.ability_points, 2)
        self.assertEqual(self.hero.max_hp, 800.0 + 70.0)
        self.assertEqual(self.hero.hp, 500.0 + 220.0 + 70.0)

        # Native1076 already grows client HP. Only the +220 heal belongs in
        # additive1053 HP traffic; publishing +70 again would double growth.
        hp_frames = [(op, p) for op, p in frames
                     if op == wire.OP.ENTITY_STAT and p[8] == roster.STAT_HEALTH]
        self.assertEqual(hp_frames, [(wire.OP.ENTITY_STAT,
                                     roster.build_hero_stat(1500, 220.0, roster.STAT_HEALTH))])
        levels = [p for op, p in frames if op == level_wire.OP_LEVEL_INCREMENT]
        self.assertEqual(levels, [level_wire.build_level_increment(1500)])
        xp_index = next(i for i, (op, p) in enumerate(frames)
                        if op == wire.OP.ENTITY_STAT and p[8] == roster.STAT_EXPERIENCE)
        self.assertEqual(struct.unpack_from(">f", frames[xp_index][1], 4)[0], 70.0)
        self.assertLess(xp_index, opcodes.index(level_wire.OP_LEVEL_INCREMENT))

        # Killer receives the bounty once, including after another corpse hit.
        self.assertEqual(player_econ.gold, init_gold + 65.0)
        self.assertEqual(player_econ.xp, 70.0)
        repeated = self.jm.apply_damage_to_monster(
            treant.eid, 800.0, self.hero, now=10.1,
            economy_mgr=self.econ, all_heroes=self.heroes)
        self.assertEqual(repeated, [])
        self.assertEqual((self.hero.hp, self.hero.max_hp, self.hero.level), (790.0, 870.0, 2))
        self.assertEqual((player_econ.gold, player_econ.xp), (init_gold + 65.0, 70.0))
        removal = self.jm.step(0.05, 14.0, {})
        self.assertEqual([op for op, _ in removal], [wire.OP.DESTROY, wire.OP.DESPAWN])


class TestCampRespawn(unittest.TestCase):
    def test_camp_respawn_timing(self):
        jm = jungle.JungleManager(open_time=0.0)
        hero = hero_movement.HeroMovement(eid=1500)
        heroes = {1500: hero}

        # Clear Camp A (Treant) at now=10.0s
        treant = next(m for m in jm.monsters.values() if m.camp_id == "LCampA")
        jm.apply_damage_to_monster(treant.eid, 1000.0, hero, now=10.0)

        # Native Camp A respawn duration is 60s -> respawns at 70.0s.
        self.assertIn("LCampA", jm.camp_respawns)
        self.assertEqual(jm.camp_respawns["LCampA"], 70.0)

        # A tick immediately before the deadline must not respawn the camp.
        jm.step(dt=0.05, now=69.95, all_heroes=heroes)
        self.assertFalse(any(m.camp_id == "LCampA" and m.is_alive for m in jm.monsters.values()))

        # The first tick at the deadline respawns with a fresh EID.
        spawn_frames = jm.step(dt=0.05, now=70.0, all_heroes=heroes)
        self.assertNotIn("LCampA", jm.camp_respawns)
        new_treant = next(m for m in jm.monsters.values() if m.camp_id == "LCampA" and m.is_alive)
        self.assertIsNotNone(new_treant)
        self.assertNotEqual(new_treant.eid, treant.eid)
        self.assertTrue(len(spawn_frames) > 0)


class TestLeashMechanics(unittest.TestCase):
    def test_leash_and_hp_reset(self):
        jm = jungle.JungleManager(open_time=0.0)
        treant = next(m for m in jm.monsters.values() if m.camp_id == "LCampA")
        hero = hero_movement.HeroMovement(eid=1500, x=treant.anchor_x, y=treant.anchor_y)
        heroes = {1500: hero}

        # Attack Treant and damage to 300 HP
        treant.take_damage(450.0, attacker_eid=1500)
        self.assertEqual(treant.hp, 300.0)
        self.assertEqual(treant.target_eid, 1500)

        # Pull Treant 12.0u away from camp anchor (> 8.5u leash radius)
        treant.x = treant.anchor_x + 12.0
        treant.y = treant.anchor_y

        # Step -> triggers leash
        jm.step(dt=0.5, now=1.0, all_heroes=heroes)
        self.assertTrue(treant.leashing)
        self.assertIsNone(treant.target_eid)

        # Run leashing return steps until back at anchor
        for step_idx in range(40):
            jm.step(dt=0.5, now=1.0 + step_idx * 0.5, all_heroes=heroes)
            if not treant.leashing:
                break

        self.assertFalse(treant.leashing)
        self.assertAlmostEqual(treant.x, treant.anchor_x, places=1)
        self.assertAlmostEqual(treant.y, treant.anchor_y, places=1)
        self.assertEqual(treant.hp, treant.max_hp)  # fully regenerated


class TestBrushZones(unittest.TestCase):
    def test_brush_detection(self):
        # Point inside pit river brush (-4..4, 13..17)
        self.assertTrue(jungle.JungleManager.is_in_brush(0.0, 15.0))
        self.assertTrue(jungle.JungleManager.is_in_brush(-2.0, 14.5))

        # Point inside left jungle brush (-30..-25, 21..25)
        self.assertTrue(jungle.JungleManager.is_in_brush(-28.0, 22.0))

        # Point in open lane (0.0, 0.0)
        self.assertFalse(jungle.JungleManager.is_in_brush(0.0, 0.0))
        self.assertFalse(jungle.JungleManager.is_in_brush(-76.0, 0.0))


if __name__ == "__main__":
    unittest.main()
