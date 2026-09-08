"""Wave acceptance tests for formation, growth and post-combat pushing."""
import math
import struct
import unittest

from server import jungle, roster, structures, wave
from server.hero_movement import HeroMovement
from server.navigation import DEFAULT_A001_PATH, load_halcyon_navmesh
from server.status_effects import StatusEffect, StatusManager, StatusType


class TestSandboxComposition(unittest.TestCase):
    def test_normal_wave_has_three_melee_and_two_ranged_per_team(self):
        director = wave.Director(0)
        for pair in range(5):
            director._spawn_pair(0, pair)
        for team in (1, 2):
            units = [m for m in director.minions if m.side == team]
            self.assertEqual(sum(m.attack_range == 2 for m in units), 3)
            self.assertEqual(sum(m.minion_class == 'ranged' and m.attack_range == 6.5 for m in units), 2)

    def test_every_third_wave_adds_siege_pair_with_verified_archetype(self):
        director = wave.Director(0, combat=False)
        due = roster.WAVE_FIRST_SPAWN_AT + 2 * roster.WAVE_INTERVAL + director.rules.siege_offset
        frames = director.pump(due)
        siege = [m for m in director.minions if m.minion_class == 'siege']
        self.assertEqual(len(director.minions), 32)
        self.assertEqual(len(siege), 2)
        self.assertEqual({m.spawn_at for m in siege}, {due})
        siege_eids = {m.eid for m in siege}
        payloads = [p for op, p in frames if op == 1010 and struct.unpack_from('>I', p, 8)[0] in siege_eids]
        self.assertEqual(len(payloads), 2)
        self.assertTrue(all(struct.unpack_from('>I', p)[0] == 367 for p in payloads))

    def test_corpus_profile_keeps_original_measured_spawner_sequence(self):
        director = wave.Director(0, corpus_profile=True)
        frames = []
        for pair in range(5):
            frames.extend(director._spawn_pair(0, pair))
        spawners = [struct.unpack_from('>I', body)[0] for op, body in frames if op == 1010]
        self.assertEqual(spawners[::2], [366, 366, 367, 365, 365])
        self.assertEqual(director.minions[4].minion_class, 'captain')

    def test_spawn_strength_grows_per_elapsed_match_minute(self):
        director = wave.Director(1000)
        director._spawn_pair(1000, 0)
        director._spawn_pair(1120, 0)
        first, later = director.minions[0], director.minions[2]
        self.assertEqual(later.max_hp, first.max_hp * 1.2)
        self.assertAlmostEqual(later.attack_damage, first.attack_damage * 1.1)
        self.assertEqual(first.max_hp, 450)

    def test_jungle_eids_do_not_overlap_lane_after_fifteen_minutes(self):
        director = wave.Director(0, combat=False)
        hero = HeroMovement()
        for second in range(0, 1001, 25):
            for minion in director.minions:
                if minion.alive:
                    director.apply_hero_damage_to_minion(minion.eid, minion.hp, hero)
            director.pump(second)
        manager = jungle.JungleManager()
        manager.step(0.05, 1000, {})
        self.assertFalse({m.eid for m in director.minions} & set(manager.monsters))
        self.assertGreater(len(director.minions), 400)


class TestWaveCombatAndPush(unittest.TestCase):
    def test_survivors_close_gap_in_standalone_lane_instead_of_blocking_later_waves(self):
        director = wave.Director(0)
        director._spawn_pair(0, 3)
        right, left = director.minions
        right.x, right.y, left.x, left.y = 6.35, 5.1, -2.48, 5.1
        right.seg, left.seg = len(right.path), len(left.path)
        right.has_engaged = left.has_engaged = True
        distance = director._dist(right, left)
        director.pump(1)
        self.assertLess(director._dist(right, left), distance)
        self.assertEqual(right.hp + left.hp, right.max_hp + left.max_hp)
        director.pump(2.35)
        self.assertLess(right.hp + left.hp, right.max_hp + left.max_hp)

    def pair(self, pair=0):
        director = wave.Director(0)
        director._spawn_pair(0, pair)
        right, left = director.minions
        right.x, right.y, left.x, left.y = 1.5, 5.5, -0.5, 5.5
        return director, right, left

    def test_survivors_push_past_lane_endpoint_and_attack_enemy_turret(self):
        director, right, left = self.pair()
        director.pump(0)
        right.alive = False
        buildings = structures.StructureManager()
        target = buildings.structures[3539]
        for tick in range(1, 180):
            director.pump(tick * 0.05, structures=buildings)
            if target.hp < target.max_hp:
                break
        self.assertGreater(left.x, 10)
        self.assertLess(target.hp, target.max_hp)

    def test_wave_selects_next_vulnerable_structure_after_kill(self):
        director, right, left = self.pair()
        right.alive, left.has_engaged = False, True
        buildings = structures.StructureManager()
        outer, middle = buildings.structures[3539], buildings.structures[3540]
        left.x, left.y = outer.x - 1, outer.y
        outer.hp = 1
        director.pump(0, structures=buildings)
        self.assertTrue(outer.is_alive)
        director.pump(0.5, structures=buildings)
        self.assertFalse(outer.is_alive)
        for tick in range(1, 160):
            director.pump(tick * 0.05, structures=buildings)
            if middle.hp < middle.max_hp:
                break
        self.assertLess(middle.hp, middle.max_hp)

    def test_dead_minion_cannot_counterattack_in_same_tick(self):
        director, right, left = self.pair()
        left.hp = 1
        initial = right.hp
        director.pump(0)
        self.assertTrue(left.alive)
        director.pump(0.5)
        self.assertFalse(left.alive)
        self.assertEqual(right.hp, initial)

    def test_damage_callback_owns_hit_application_once(self):
        director, right, left = self.pair()
        before = right.hp, left.hp
        calls = []
        director.pump(0, damage_callback=lambda a, b, amount, kind, now: calls.append((a.eid, b.eid)) or [])
        self.assertEqual(calls, [])
        director.pump(0.5, damage_callback=lambda a, b, amount, kind, now: calls.append((a.eid, b.eid)) or [])
        self.assertEqual(calls, [(right.eid, left.eid), (left.eid, right.eid)])
        self.assertEqual((right.hp, left.hp), before)

    def test_retaliation_uses_actual_attacking_hero_not_primary_player(self):
        director, right, left = self.pair()
        left.alive = False
        primary = HeroMovement(x=-70, y=1)
        attacker = HeroMovement(eid=1515, team=1, x=right.x, y=right.y)
        director.on_minion_damaged_by_hero(right.eid, attacker)
        primary_hp, attacker_hp = primary.hp, attacker.hp
        director.pump(0, hero=primary)
        self.assertEqual(attacker.hp, attacker_hp)
        director.pump(0.5, hero=primary)
        self.assertEqual(primary.hp, primary_hp)
        self.assertLess(attacker.hp, attacker_hp)

    def test_stopped_combat_time_never_becomes_movement_catchup(self):
        director, right, left = self.pair()
        right.hp = left.hp = 100000
        for tick in range(100):
            director.pump(tick * 0.05)
        right.alive = False
        left.has_engaged = True
        before = left.x, left.y
        director.pump(5, structures=structures.StructureManager())
        self.assertLessEqual(math.dist(before, (left.x, left.y)), roster.MINION_SPEED * 0.05 + 0.00001)

    def test_ranged_units_hold_at_six_point_five_units(self):
        director, right, left = self.pair(3)
        right.x, left.x = 8, 0
        for tick in range(1, 40):
            director.pump(tick * 0.05)
        self.assertAlmostEqual(director._dist(right, left), 6.5, places=4)
        self.assertLess(right.hp, right.max_hp)

    def test_formation_does_not_collapse_same_team_to_one_point(self):
        director = wave.Director(0)
        for tick in range(900):
            director.pump(tick * 0.05)
        alive = [m for m in director.minions if m.alive]
        for team in (1, 2):
            positions = [(m.x, m.y) for m in alive if m.side == team]
            for index, point in enumerate(positions):
                for other in positions[index + 1:]:
                    self.assertGreaterEqual(math.dist(point, other), director.rules.ally_spacing)

    def test_stun_blocks_both_attack_and_movement(self):
        director, right, left = self.pair()
        statuses = StatusManager()
        statuses.apply_effect(StatusEffect('stun', StatusType.STUN, 1500, right.eid, 5, 0, 5))
        initial_hp, initial_pos = left.hp, (right.x, right.y)
        director.pump(0.05, status_manager=statuses)
        self.assertEqual((right.x, right.y), initial_pos)
        self.assertEqual(left.hp, initial_hp)

    def test_fixed_point_minion_positions_are_reproducible(self):
        states = []
        for _ in range(2):
            director = wave.Director(0)
            for tick in range(600):
                director.pump(tick * 0.05)
            states.append([(m.eid, m.position_fixed, m.hp) for m in director.minions])
        self.assertEqual(states[0], states[1])
        self.assertIsInstance(states[0][0][1][0], int)


@unittest.skipUnless(DEFAULT_A001_PATH.is_file(), 'external A001 navmesh unavailable')
class TestWaveActualNavigation(unittest.TestCase):
    def test_lane_wave_and_postfight_push_remain_on_actual_mesh(self):
        mesh = load_halcyon_navmesh()
        director = wave.Director(0, navigation=mesh)
        director._spawn_pair(0, 0)
        right, left = director.minions
        right.alive = False
        buildings = structures.StructureManager()
        target = buildings.structures[3539]
        for tick in range(1, 500):
            director.pump(tick * 0.05, structures=buildings)
            self.assertTrue(mesh.contains((left.x, left.y)))
            if target.hp < target.max_hp:
                break
        self.assertLess(target.hp, target.max_hp)
