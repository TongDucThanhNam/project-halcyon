"""Unit tests for hero combat, HP, death and respawn (T3 Slice 5).

Verifies:
- Hero basic attack on enemy entity (c2s 1060 -> pursuit -> s2c 1054 at 0.8s cadence).
- Hero HP management and s2c 1053 type-0 emission.
- Hero death/countdown, delayed 1073 corpse hiding, then 1033 resurrection.
- Hero respawn (resurrection at spawn base + 1070 teleport + HP restoration).
- Minion retaliatory aggro against hero (aggro phan don).
- Manual move tap cancels entity target (orb-walking / animation canceling).
"""
import struct
import unittest

from server import hero_movement, roster, wave, wire, combat
from types import SimpleNamespace


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
        self.hero.set_target_eid(4610)
        engine = combat.BasicAttackEngine()
        target = SimpleNamespace(eid=4610, team=2, x=10.0, y=0.0, is_alive=True)
        # Movement owns pursuit; only the combat FSM may commit a hit.
        frames = self.hero.step(.1, now=1.0, target_pos=(10.0, 0.0))
        self.assertFalse(any(op == wire.OP.COMBAT_DELTA for op, _ in frames))
        self.assertEqual(engine.step_attacker(self.hero, target, 1.0), [])
        self.assertEqual(engine.step_attacker(self.hero, target, 1.2), [])
        first = engine.step_attacker(self.hero, target, 1.24)
        self.assertEqual(len(first), 1)
        self.assertEqual((first[0].source_eid, first[0].target_eid, first[0].damage), (1500, 4610, 70.0))
        self.assertEqual(engine.step_attacker(self.hero, target, 1.79), [])
        self.assertEqual(engine.step_attacker(self.hero, target, 1.8), [])
        self.assertEqual(len(engine.step_attacker(self.hero, target, 2.04)), 1)

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
        self.assertEqual(typ, roster.STAT_HEALTH)

    def test_hero_death_and_respawn_cycle(self):
        frames = self.hero.apply_damage(740.0, attacker_eid=4610, now=10.0)
        self.assertFalse(self.hero.is_alive)
        self.assertAlmostEqual(self.hero.hp, 0.0)

        opcodes = [f[0] for f in frames]
        self.assertNotIn(wire.OP.DESTROY, opcodes)
        self.assertIn(wire.OP.ENTITY_DEATH, opcodes)
        self.assertIn(wire.OP.RESPAWN_TIMER, opcodes)

        tframe = next(f[1] for f in frames if f[0] == wire.OP.RESPAWN_TIMER)
        eid, timer = struct.unpack_from(">If", tframe, 0)
        self.assertEqual(eid, 1500)
        self.assertAlmostEqual(timer, 6.0, places=2)

        self.assertEqual(self.hero.set_target(10.0, 10.0), [])
        corpse_frames = self.hero.step(dt=1.0, now=12.0)
        self.assertEqual(corpse_frames, [(1073, roster.build_destroy(self.hero.eid))])
        self.assertFalse(self.hero.is_alive)
        self.assertEqual(self.hero.step(dt=.1, now=12.1), [])

        respawn_frames = self.hero.step(dt=0.1, now=16.1)
        self.assertTrue(self.hero.is_alive)
        self.assertAlmostEqual(self.hero.hp, 740.0)
        self.assertAlmostEqual(self.hero.x, self.hero.spawn_x, places=2)
        self.assertAlmostEqual(self.hero.y, self.hero.spawn_y, places=2)

        r_ops = [f[0] for f in respawn_frames]
        self.assertIn(wire.OP.POSITION, r_ops)
        self.assertIn(wire.OP.ENTITY_RESPAWN, r_ops)
        self.assertNotIn(wire.OP.ENTITY_STAT, r_ops)


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
        self.assertIn((1045, struct.pack('>IIB', m_right.eid, hero.eid, 0) + bytes(5)), frames)
        self.assertFalse(any(op == wire.OP.COMBAT_DELTA for op, _ in frames))
        self.assertEqual(hero.hp, initial_hero_hp)
        before_contact = d.pump(now=1.499999, hero=hero)
        self.assertFalse(any(op == wire.OP.COMBAT_DELTA for op, _ in before_contact))
        self.assertEqual(hero.hp, initial_hero_hp)
        frames = d.pump(now=1.5, hero=hero)
        c_frames = [f for f in frames if f[0] == wire.OP.COMBAT_DELTA]
        self.assertTrue(any(
            struct.unpack_from(">II", f[1], 0) == (hero.eid, m_right.eid)
            for f in c_frames
        ))
        self.assertAlmostEqual(hero.hp, initial_hero_hp - roster.MINION_ATTACK_DAMAGE)


if __name__ == '__main__':
    unittest.main()
