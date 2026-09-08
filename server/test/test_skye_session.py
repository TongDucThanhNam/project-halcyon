"""Skye native upgrade/cast input through the actual 50 ms match session."""
import struct
import unittest

from server import abilities, buff_wire, jungle, match_server, roster
from server.navigation import NavMesh
from server.status_effects import StatusType


class TestSkyeSession(unittest.TestCase):
    def setUp(self):
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        players = roster.default_solo_bots('skye-test', 'skye-test')
        players = [players[0], players[3]]
        players[0].hero_id, players[1].hero_id = 265, 243
        for player in players:
            player.is_bot = False
        self.frames = []
        self.owner = object()
        self.world = match_server.SnapshotStream(self.owner, players, 'skye-test',
            lambda op, payload: self.frames.append((op, payload)), log=lambda _: None,
            navigation_mesh=mesh)
        self.world._finalize()
        self.hero, self.enemy = self.world.hero_sims.values()
        self.hero.teleport(0, 35)
        self.enemy.teleport(4, 35)
        self.hero.energy = self.hero.max_energy = 1000
        self.enemy.hp = self.enemy.max_hp = 10000
        self.world.jungle = jungle.JungleManager(open_time=1000000)
        for structure in self.world.structures.structures.values():
            structure.is_alive = False
        self.world.phase = self.world.WORLD
        self.kit = self.world.hero_kits[1500]
        self.frames.clear()

    def ticks(self, count):
        for _ in range(count):
            self.world.advance_simulation()

    def learn(self, slot):
        self.world._apply_event(1078, bytes((slot,)) + bytes(5), self.owner)

    def cast(self, native_action, point=(10, 35)):
        self.world._apply_event(1042, struct.pack('>fffBB', point[0], 0, point[1], native_action, 0))

    def establish_lock(self):
        self.world._apply_event(1060, roster.build_target_entity(1517))
        for _ in range(20):
            self.ticks(1)
            if self.kit.locked_target is self.enemy:
                break
        self.assertIs(self.kit.locked_target, self.enemy)
        self.world._apply_event(1012, roster.build_move(0, 35))
        self.hero.stop()
        self.frames.clear()

    def test_ui_upgrade_zero_one_two_echoes_and_native_rank_ack_zero_two_four(self):
        progression = self.world.economy.get_or_create(1500)
        progression.add_xp(500)
        progression.apply_to_hero(self.hero)
        for slot in (0, 1, 2):
            self.learn(slot)
        self.assertIsInstance(self.kit, abilities.SkyeKit)
        self.assertEqual(self.kit.ranks, {0: 1, 1: 1, 2: 1})
        self.assertEqual([p for op, p in self.frames if op == 1078],
                         [bytes((slot,)) + bytes(5) for slot in (0, 1, 2)])
        self.assertEqual([struct.unpack_from('>II', p) for op, p in self.frames if op == 1082],
                         [(1500, 0), (1500, 2), (1500, 4)])
        self.assertEqual(progression.ability_points, 3)

    def test_real_basic_projectile_impact_creates_lock_after_hit_and_not_at_windup(self):
        self.world._apply_event(1060, roster.build_target_entity(1517))
        self.ticks(1)
        self.assertIsNone(self.kit.locked_target)
        self.assertTrue(any(op == 1045 for op, _ in self.frames))
        self.assertFalse(any(op == 1086 and buff_wire.parse_buff_add(p).kind == 602
                             for op, p in self.frames))
        for _ in range(20):
            self.ticks(1)
            if self.kit.locked_target is self.enemy:
                break
        self.assertIs(self.kit.locked_target, self.enemy)
        hit = next(i for i, (op, p) in enumerate(self.frames) if op == 1054)
        lock = next(i for i, (op, p) in enumerate(self.frames)
                    if op == 1086 and buff_wire.parse_buff_add(p).kind == 602)
        self.assertLess(hit, lock)
        self.assertEqual(self.hero.revealed_targets[1517], self.world.sim_time + 3)

    def test_native_a_moves_without_basic_attacks_and_action_one_cancels_for_free(self):
        self.learn(0)
        self.cast(0)
        cost_energy, cooldown = self.hero.energy, self.kit.cooldowns[0]
        self.world._apply_event(1012, roster.build_move(0, 38))
        self.ticks(4)
        self.assertGreater(self.hero.y, 35)
        self.assertTrue(self.hero.basic_attack_disabled)
        self.assertEqual(self.hero.facing, (1, 0))
        self.assertFalse(any(op == 1037 for op, _ in self.frames))
        before = self.hero.energy
        self.world._apply_event(1041, struct.pack('>IBB', 0xffffffff, 1, 0))
        self.assertEqual(self.hero.energy, before)
        self.assertEqual(self.kit.cooldowns[0], cooldown)
        self.assertFalse(self.hero.basic_attack_disabled)
        self.assertEqual([p[8] for op, p in self.frames if op == 1045], [1])
        self.assertAlmostEqual(cost_energy, 960)

    def test_b_native_action_two_requires_lock_then_dash_and_missiles_resolve(self):
        self.learn(1)
        self.cast(2, (4, 35))
        self.assertFalse(any(op == 1046 for op, _ in self.frames))
        self.establish_lock()
        before = self.enemy.hp
        self.cast(2, (4, 35))
        self.assertTrue(self.hero.basic_attack_disabled)
        self.assertEqual([p[16] for op, p in self.frames if op == 1046], [2])
        self.ticks(4)
        self.assertAlmostEqual(self.hero.x, 3.6)
        self.assertEqual(self.enemy.hp, before)
        self.ticks(16)
        self.assertAlmostEqual(self.hero.x, 4)
        self.assertFalse(self.hero.basic_attack_disabled)
        self.assertLess(self.enemy.hp, before)
        self.assertEqual(sum(op == 1054 for op, _ in self.frames), 4)

    def test_c_native_action_four_pays_energy_and_waits_for_delayed_damage(self):
        progression = self.world.economy.get_or_create(1500)
        progression.add_xp(500)
        progression.apply_to_hero(self.hero)
        self.learn(2)
        self.establish_lock()
        before, energy = self.enemy.hp, self.hero.energy
        self.cast(4, (4, 35))
        self.assertEqual(energy - self.hero.energy, 70)
        self.assertEqual([p[16] for op, p in self.frames if op == 1046], [4])
        self.ticks(25)
        self.assertEqual(self.enemy.hp, before)
        self.ticks(1)
        self.assertLess(self.enemy.hp, before)
        self.assertTrue(self.world.status_manager.has_effect(1517, StatusType.STUN, self.world.sim_time))

    def test_live_target_provider_routes_barrage_through_structure_damage_rules(self):
        turret = next(s for s in self.world.structures.structures.values() if s.team == 2 and not s.is_crystal)
        turret.is_alive = True
        turret.x, turret.y = 3, 35
        turret.hp = 10000
        turret.armor = turret.shield = 0
        self.learn(0)
        self.cast(0)
        self.ticks(2)
        raw = (140 + 1.8 * self.hero.crystal_power + 1.2 * self.hero.attack_damage) * .1
        self.assertAlmostEqual(turret.hp, 10000 - raw * .5 * .25)
        self.assertEqual(self.enemy.hp, 10000)
        hits = [struct.unpack_from('>II', p) for op, p in self.frames if op == 1054]
        self.assertEqual(hits, [(turret.eid, 1500)])


if __name__ == '__main__':
    unittest.main()
