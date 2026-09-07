"""Unit tests for hero combat, HP, death and respawn (T3 Slice 5).

Verifies:
- Hero basic attack on enemy entity (c2s 1060 -> pursuit -> s2c 1054 at 0.8s cadence).
- Hero HP management and s2c 1053 type-6 emission.
- Hero death chain (1073 DESTROY + 1067 dead state + 1162 respawn timer).
- Hero respawn (resurrection at spawn base + 1070 teleport + HP restoration).
- Minion retaliatory aggro against hero (aggro phan don).
- Manual move tap cancels entity target (orb-walking / animation canceling).
"""
import struct
import unittest

from server import hero_movement, roster, wave, wire


class TestHeroCombat(unittest.TestCase):

    def setUp(self):
        self.hero = hero_movement.HeroMovement(
            eid=1500,
            team=1,
            x=0.0,
            y=0.0,
            speed=5.0,
            hp=740.0,
            max_hp=740.0,
            attack_damage=70.0,
            attack_range=2.5,
            attack_cooldown=0.8,
            respawn_duration=6.0,
        )

    def test_hero_targeting_and_pursuit(self):
        self.hero.set_target_eid(4610)
        self.assertEqual(self.hero.target_eid, 4610)

        frames = self.hero.step(dt=1.0, now=1.0, target_pos=(10.0, 0.0))
        self.assertTrue(any(op == wire.OP.POSITION for op, _ in frames))
        self.assertAlmostEqual(self.hero.x, 5.0, places=2)
        self.assertAlmostEqual(self.hero.y, 0.0, places=2)

    def test_hero_basic_attack_cadence(self):
        self.hero.x = 8.0
        self.hero.y = 0.0
        self.hero.set_target_eid(4610)

        frames = self.hero.step(dt=0.1, now=1.0, target_pos=(10.0, 0.0))
        atk_frames = [f for f in frames if f[0] == wire.OP.COMBAT_DELTA]
        self.assertEqual(len(atk_frames), 1)

        src, tgt, delta = struct.unpack_from(">IIf", atk_frames[0][1], 0)
        tail = atk_frames[0][1][12:]
        self.assertEqual(src, 1500)
        self.assertEqual(tgt, 4610)
        self.assertAlmostEqual(delta, -70.0, places=2)
        self.assertEqual(tail, roster.COMBAT_DELTA_HERO_TAIL)

        frames2 = self.hero.step(dt=0.1, now=1.2, target_pos=(10.0, 0.0))
        atk_frames2 = [f for f in frames2 if f[0] == wire.OP.COMBAT_DELTA]
        self.assertEqual(len(atk_frames2), 0)

        frames3 = self.hero.step(dt=0.1, now=1.85, target_pos=(10.0, 0.0))
        atk_frames3 = [f for f in frames3 if f[0] == wire.OP.COMBAT_DELTA]
        self.assertEqual(len(atk_frames3), 1)

    def test_orb_walk_cancels_target(self):
        self.hero.set_target_eid(4610)
        self.assertEqual(self.hero.target_eid, 4610)

        self.hero.set_target(-10.0, 5.0)
        self.assertIsNone(self.hero.target_eid)
        self.assertEqual(self.hero.move_target, (-10.0, 5.0))

    def test_hero_damage_and_hp_stat(self):
        frames = self.hero.apply_damage(100.0, attacker_eid=4610, now=5.0)
        self.assertAlmostEqual(self.hero.hp, 640.0)

        stat_frames = [f for f in frames if f[0] == wire.OP.ENTITY_STAT]
        self.assertEqual(len(stat_frames), 1)
        eid, val, typ = struct.unpack_from(">IfB", stat_frames[0][1], 0)
        self.assertEqual(eid, 1500)
        self.assertAlmostEqual(val, -100.0, places=2)
        self.assertEqual(typ, 6)

    def test_hero_death_and_respawn_cycle(self):
        frames = self.hero.apply_damage(740.0, attacker_eid=4610, now=10.0)
        self.assertFalse(self.hero.is_alive)
        self.assertAlmostEqual(self.hero.hp, 0.0)

        opcodes = [f[0] for f in frames]
        self.assertNotIn(wire.OP.DESTROY, opcodes)
        self.assertIn(wire.OP.ENTITY_STATE, opcodes)
        self.assertIn(wire.OP.TIMER_TICK, opcodes)

        tframe = next(f[1] for f in frames if f[0] == wire.OP.TIMER_TICK)
        eid, inst, unk, timer = struct.unpack_from(">IIHf", tframe, 0)
        self.assertEqual(eid, 1500)
        self.assertEqual(inst, 0xb855d752)
        self.assertAlmostEqual(timer, 6.0, places=2)

        self.assertEqual(self.hero.set_target(10.0, 10.0), [])
        self.assertEqual(self.hero.step(dt=1.0, now=12.0), [])

        respawn_frames = self.hero.step(dt=0.1, now=16.1)
        self.assertTrue(self.hero.is_alive)
        self.assertAlmostEqual(self.hero.hp, 740.0)
        self.assertAlmostEqual(self.hero.x, self.hero.spawn_x, places=2)
        self.assertAlmostEqual(self.hero.y, self.hero.spawn_y, places=2)

        r_ops = [f[0] for f in respawn_frames]
        self.assertIn(wire.OP.POSITION, r_ops)
        self.assertIn(wire.OP.ENTITY_STAT, r_ops)


class TestMinionRetaliation(unittest.TestCase):

    def test_minion_retaliates_when_hit_by_hero(self):
        d = wave.Director(t0=0.0, combat=True)
        d._spawn_pair(0.0, 0)
        m_right = d.minions[0]

        hero = hero_movement.HeroMovement(eid=1500, team=1, x=m_right.x, y=m_right.y)
        initial_hero_hp = hero.hp

        d.apply_hero_damage_to_minion(m_right.eid, 70.0, hero)
        self.assertAlmostEqual(m_right.hp, roster.MINION_HP - 70.0)
        self.assertEqual(m_right.target_hero, hero)

        frames = d.pump(now=1.0, hero=hero)
        c_frames = [f for f in frames if f[0] == wire.OP.COMBAT_DELTA]
        self.assertTrue(any(
            struct.unpack_from(">II", f[1], 0) == (m_right.eid, hero.eid)
            for f in c_frames
        ))
        self.assertAlmostEqual(hero.hp, initial_hero_hp - roster.MINION_ATTACK_DAMAGE)


if __name__ == '__main__':
    unittest.main()
