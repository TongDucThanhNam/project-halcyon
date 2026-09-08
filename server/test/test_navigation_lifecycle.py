"""Synthetic geometry invariants plus optional external A001 integration.

The synthetic grid is original test geometry, not a copied Vainglory mesh.
"""
import math
from pathlib import Path
import struct
import tempfile
import unittest

from server import roster, wire
from server.hero_movement import HeroMovement
from server.navigation import DEFAULT_A001_PATH, NavMesh, SCALE, fixed, load_halcyon_navmesh
from server.status_effects import StatusEffect, StatusManager, StatusType


def ring_mesh():
    axis = (0, 4, 6, 10)
    vertices = [(x, y) for y in axis for x in axis]
    triangles = []
    for y in range(3):
        for x in range(3):
            if x == y == 1:
                continue
            a = y * 4 + x
            triangles.extend(((a, a + 1, a + 5), (a, a + 5, a + 4)))
    return NavMesh(vertices, triangles)


def effect(kind, *, speed=0, direction=(0, 0), magnitude=1):
    return StatusEffect('test', kind, 99, 1500, 5, 0, 5, magnitude, direction, speed)


class TestNavigation(unittest.TestCase):
    def setUp(self):
        self.mesh = ring_mesh()

    def test_hole_is_not_walkable(self):
        self.assertTrue(self.mesh.contains((1, 5)))
        self.assertFalse(self.mesh.contains((5, 5)))
        self.assertFalse(self.mesh.contains((-1, 5)))

    def test_collision_query_detects_crossing_even_with_walkable_endpoints(self):
        self.assertFalse(self.mesh.segment_walkable((1, 5), (9, 5)))
        self.assertTrue(self.mesh.segment_walkable((1, 1), (9, 1)))

    def test_astar_routes_around_hole_with_all_segments_walkable(self):
        start = (1, 5)
        route = self.mesh.find_path(start, (9, 5))
        self.assertGreater(len(route), 1)
        self.assertEqual(route[-1], (9, 5))
        for a, b in zip([start] + route, route):
            self.assertTrue(self.mesh.segment_walkable(a, b), (a, b))
        self.assertGreater(sum(math.dist(a, b) for a, b in zip([start] + route, route)), 8)

    def test_astar_ties_are_repeatable(self):
        expected = self.mesh.find_path((1, 5), (9, 5))
        for _ in range(10):
            self.assertEqual(self.mesh.find_path((1, 5), (9, 5)), expected)

    def test_caller_cannot_mutate_cached_route_for_later_actors(self):
        expected = self.mesh._find_path((1, 5), (9, 5))
        result = self.mesh.find_path([1, 5], [9, 5])
        result[:] = [(999, 999)]
        self.assertEqual(self.mesh.find_path((1, 5), (9, 5)), expected)

    def test_wall_click_projects_to_walkable_boundary(self):
        route = self.mesh.find_path((1, 5), (5, 5))
        self.assertTrue(route)
        self.assertTrue(self.mesh.contains(route[-1]))
        self.assertEqual(math.dist(route[-1], (5, 5)), 1)

    def test_disconnected_components_cannot_be_crossed(self):
        mesh = NavMesh([(0, 0), (1, 0), (0, 1), (4, 0), (5, 0), (4, 1)], [(0, 1, 2), (3, 4, 5)])
        self.assertEqual(mesh.find_path((0.1, 0.1), (4.1, 0.1)), [])

    def test_invalid_start_does_not_jump_out_of_rock(self):
        self.assertEqual(self.mesh.find_path((5, 5), (9, 5)), [])

    def test_knockback_stops_at_first_wall(self):
        endpoint = self.mesh.clamp_segment((1, 5), (9, 5))
        self.assertLessEqual(endpoint[0], 4)
        self.assertGreater(endpoint[0], 3.99)
        self.assertTrue(self.mesh.segment_walkable((1, 5), endpoint))

    def test_dash_short_of_midpoint_stops_at_near_wall(self):
        endpoint = self.mesh.dash_endpoint((1, 5), (4.9, 5))
        self.assertLessEqual(endpoint[0], 4)

    def test_dash_exact_midpoint_does_not_cross(self):
        self.assertLessEqual(self.mesh.dash_endpoint((1, 5), (5, 5))[0], 4)

    def test_dash_past_midpoint_exits_thin_wall(self):
        endpoint = self.mesh.dash_endpoint((1, 5), (5.1, 5))
        self.assertGreaterEqual(endpoint[0], 6)
        self.assertLess(endpoint[0], 6.01)
        self.assertTrue(self.mesh.contains(endpoint))

    def test_dash_beyond_thin_wall_reaches_endpoint(self):
        self.assertEqual(self.mesh.dash_endpoint((1, 5), (8, 5)), (8, 5))

    def test_dash_cannot_escape_outer_boundary(self):
        endpoint = self.mesh.dash_endpoint((1, 1), (-100, 1))
        self.assertTrue(self.mesh.contains(endpoint))
        self.assertGreaterEqual(endpoint[0], 0)

    def test_loader_validates_full_byte_accounting(self):
        header = bytearray(134)
        struct.pack_into('<3I', header, 0, 1, 0, 3)
        struct.pack_into('<I', header, 103, 3)
        struct.pack_into('<2I', header, 109, 72, 24)
        payload = bytes(header) + b''.join(struct.pack('<6f', x, 0, y, 0, 1, 0) for x, y in ((0, 0), (1, 0), (0, 1))) + bytes((0, 1, 2))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'original-test-mesh.bin'
            path.write_bytes(payload)
            self.assertTrue(NavMesh.from_file(path).contains((0.1, 0.1)))
            path.write_bytes(payload[:-1])
            with self.assertRaisesRegex(ValueError, 'byte accounting'):
                NavMesh.from_file(path)

    def test_missing_geometry_fails_explicitly(self):
        with self.assertRaises(FileNotFoundError):
            load_halcyon_navmesh('nonexistent-external-navmesh')

    def test_nonfinite_coordinate_is_rejected(self):
        with self.assertRaises(ValueError):
            self.mesh.find_path((1, 1), (float('nan'), 0))


class TestHeroNavigation(unittest.TestCase):
    def test_hero_routes_ground_click_and_stays_walkable(self):
        mesh = ring_mesh()
        hero = HeroMovement(x=1, y=5, navigation=mesh)
        hero.set_target(9, 5)
        for tick in range(100):
            hero.step(0.05, tick * 0.05)
            self.assertTrue(mesh.contains((hero.x, hero.y)))
        self.assertEqual((hero.x, hero.y), (9, 5))

    def test_client_waypoints_do_not_bypass_collision(self):
        mesh = ring_mesh()
        hero = HeroMovement(x=1, y=5, navigation=mesh)
        hero.set_path([(9, 5), (9, 9)])
        for a, b in zip([(1, 5)] + hero.waypoints, hero.waypoints):
            self.assertTrue(mesh.segment_walkable(a, b))

    def test_knockback_clamps_to_wall_and_clears_path(self):
        hero = HeroMovement(x=1, y=5, navigation=ring_mesh())
        hero.set_target(9, 5)
        statuses = StatusManager()
        statuses.apply_effect(effect(StatusType.KNOCKBACK, speed=10, direction=(1, 0)))
        hero.step(1, 1, status_manager=statuses)
        self.assertLessEqual(hero.x, 4)
        self.assertFalse(hero.is_moving)
        self.assertEqual(hero.waypoints, [])

    def test_stun_stops_movement_at_current_position(self):
        hero = HeroMovement(x=1, y=1, navigation=ring_mesh())
        hero.set_target(9, 1)
        statuses = StatusManager()
        statuses.apply_effect(effect(StatusType.STUN))
        hero.step(0.2, 1, status_manager=statuses)
        self.assertEqual((hero.x, hero.y), (1, 1))
        self.assertFalse(hero.is_moving)

    def test_fixed_point_integration_is_repeatable(self):
        heroes = [HeroMovement(x=0, y=0, speed=4.873) for _ in range(2)]
        for hero in heroes:
            hero.set_target(50, 37)
            for _ in range(91):
                hero.step(0.05)
        self.assertEqual(heroes[0].position_fixed, heroes[1].position_fixed)
        self.assertIsInstance(heroes[0].position_fixed[0], int)

    def test_move_speed_formula_applies_flat_boots_after_base_multiplier(self):
        hero = HeroMovement(speed=5)
        hero.attr_0x284, hero.attr_0x68, hero.attr_0x1D0 = 0.4, 2, -0.3
        self.assertAlmostEqual(hero.effective_speed(), 6.3)

    def test_speed_modifier_expires_without_reverting_equipment(self):
        hero = HeroMovement(speed=5)
        hero.add_speed_modifier('sprint', bonus=2, expires_at=3)
        self.assertEqual(hero.effective_speed(now=2.999), 7)
        hero.item_move_speed = 1
        self.assertEqual(hero.effective_speed(now=3), 6)

    def test_move_then_attack_changes_order_stamp_before_tick(self):
        hero = HeroMovement(x=0, y=0)
        hero.set_target_eid(10)
        previous = hero.order_version
        hero.set_target(1, 0)
        hero.set_target_eid(10)
        self.assertGreater(hero.order_version, previous)
        previous = hero.order_version
        hero.step(0.05, 1, target_pos=(1, 0))
        self.assertEqual(hero.order_version, previous)

    def test_movement_never_emits_hitscan_attack(self):
        hero = HeroMovement(x=0, y=0)
        hero.set_target_eid(10)
        self.assertNotIn(wire.OP.COMBAT_DELTA, [op for op, _ in hero.step(0.2, 1, target_pos=(1, 0))])


class TestLifecycle(unittest.TestCase):
    def test_recall_completes_exactly_after_four_seconds(self):
        hero = HeroMovement()
        hero.teleport(0, 10)
        hero.start_recall(10)
        hero.tick_lifecycle(0, 13.999)
        self.assertEqual((hero.x, hero.y), (0, 10))
        frames = hero.tick_lifecycle(0, 14)
        self.assertEqual(hero.position_fixed, (fixed(hero.spawn_x), fixed(hero.spawn_y)))
        self.assertIn(wire.OP.POSITION, [op for op, _ in frames])
        self.assertIsNone(hero.recall_completes_at)

    def test_move_cancels_recall_immediately(self):
        hero = HeroMovement(x=0, y=10)
        hero.start_recall(1)
        hero.set_target(5, 10)
        self.assertIsNone(hero.recall_completes_at)

    def test_damage_cancels_recall_immediately(self):
        hero = HeroMovement(x=0, y=10)
        hero.start_recall(1)
        hero.apply_damage(1, 99, 2)
        self.assertIsNone(hero.recall_completes_at)

    def test_stun_cancels_recall(self):
        hero, statuses = HeroMovement(x=0, y=10), StatusManager()
        hero.start_recall(0)
        statuses.apply_effect(effect(StatusType.STUN))
        hero.tick_lifecycle(0.05, 1, status_manager=statuses)
        self.assertIsNone(hero.recall_completes_at)

    def test_base_restores_fifteen_percent_plus_natural_energy_regen(self):
        hero = HeroMovement(hp=100, max_hp=1000, energy=0, max_energy=200, energy_regen=2)
        frames = hero.tick_lifecycle(1, 1)
        self.assertEqual(hero.hp, 250)
        self.assertEqual(hero.energy, 32)
        hp_update = next(body for op, body in frames if op == wire.OP.ENTITY_STAT)
        self.assertEqual(struct.unpack_from('>IfB', hp_update), (1500, 150, 0))
        self.assertEqual(hp_update[9:], bytes.fromhex('0001000000'))

    def test_natural_regen_away_from_base_does_not_heal_hp(self):
        hero = HeroMovement(x=0, y=10, hp=100, max_hp=1000, energy=0, energy_regen=2)
        hero.tick_lifecycle(1, 1)
        self.assertEqual(hero.hp, 100)
        self.assertEqual(hero.energy, 2)

    def test_fountain_cannot_overheal(self):
        hero = HeroMovement(hp=999, max_hp=1000, energy=299)
        hero.tick_lifecycle(1, 1)
        self.assertEqual((hero.hp, hero.energy), (1000, 300))

    def test_opposing_fountain_deals_true_damage_and_respects_hit_cadence(self):
        hero = HeroMovement(hp=2500, max_hp=2500)
        hero.teleport(*roster.HERO_SPAWNS[1517])
        hero.armor = 10000
        hero.tick_lifecycle(0.05, 1)
        self.assertEqual(hero.hp, 1500)
        hero.tick_lifecycle(0.05, 1.05)
        self.assertEqual(hero.hp, 1500)
        hero.tick_lifecycle(0.05, 2)
        self.assertEqual(hero.hp, 500)

    def test_dynamic_respawn_scales_level_and_elapsed_match_minutes(self):
        hero = HeroMovement()
        self.assertEqual(hero.respawn_seconds(0), 8.5)
        hero.level = 12
        self.assertEqual(hero.respawn_seconds(900), 51)

    def test_death_countdown_matches_dynamic_respawn_and_resources_restore(self):
        hero = HeroMovement(energy=0)
        hero.level, hero.match_elapsed = 4, 300
        frames = hero.apply_damage(hero.hp, 99, 100)
        timer = next(body for op, body in frames if op == 1075)
        self.assertEqual(struct.unpack_from('>If', timer)[1], 21)
        self.assertNotIn(1162, [op for op, _ in frames])
        self.assertEqual([op for op, _ in hero.check_respawn(101.8)], [1073])
        self.assertFalse(hero.is_alive)
        self.assertEqual([op for op, _ in hero.check_respawn(120.7)], [1033, 1070])
        self.assertFalse(hero.is_alive)
        self.assertEqual(hero.hp, 0)
        self.assertEqual(hero.check_respawn(120.99), [])
        self.assertEqual([op for op, _ in hero.check_respawn(121)], [1074])
        self.assertEqual((hero.hp, hero.energy), (hero.max_hp, hero.max_energy))
        self.assertTrue(hero.is_alive)

    def test_energy_cost_rejects_insufficient_and_negative_amounts(self):
        hero = HeroMovement(energy=10)
        for amount in (11, -1, float('nan')):
            with self.assertRaises(ValueError):
                hero.spend_energy(amount)
        self.assertEqual(hero.energy, 10)
        frames = hero.spend_energy(10)
        self.assertEqual(struct.unpack_from('>IfB', frames[0][1]), (1500, -10, 2))
        self.assertEqual(frames[0][1][9:], bytes.fromhex('0001000000'))
        self.assertEqual(hero.energy, 0)

    def test_disabled_energy_mapping_is_never_sent(self):
        hero = HeroMovement(energy=0, energy_stat_type=None)
        frames = hero.tick_lifecycle(1, 1)
        self.assertFalse(any(op == wire.OP.ENTITY_STAT for op, _ in frames))

    def test_configured_energy_mapping_encodes_resource_delta(self):
        hero = HeroMovement(energy=100, energy_stat_type=99)
        frames = hero.spend_energy(20)
        self.assertEqual(struct.unpack_from('>IfB', frames[0][1]), (1500, -20, 99))


@unittest.skipUnless(DEFAULT_A001_PATH.is_file(), 'external A001 store unavailable')
class TestExternalA001(unittest.TestCase):
    def test_real_mesh_routes_around_halcyon_jungle_walls(self):
        mesh = load_halcyon_navmesh(DEFAULT_A001_PATH)
        self.assertEqual((len(mesh.vertices), len(mesh.triangles)), (793, 832))
        start, destination = (-78.18, 0.88), (40, 30)
        self.assertFalse(mesh.segment_walkable(start, destination))
        route = mesh.find_path(start, destination)
        self.assertGreater(len(route), 1)
        self.assertEqual(route[-1], destination)
        for a, b in zip([start] + route, route):
            self.assertTrue(mesh.segment_walkable(a, b))

    def test_real_mesh_hero_traversal_reaches_destination_without_entering_rock(self):
        mesh = load_halcyon_navmesh(DEFAULT_A001_PATH)
        hero = HeroMovement(navigation=mesh)
        hero.set_target(40, 30)
        for tick in range(1000):
            hero.step(0.05, tick * 0.05)
            self.assertTrue(mesh.contains((hero.x, hero.y)))
            if not hero.is_moving:
                break
        self.assertFalse(hero.is_moving)
        self.assertEqual((hero.x, hero.y), (40, 30))
