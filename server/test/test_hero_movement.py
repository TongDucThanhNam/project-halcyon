"""Unit tests for HeroMovement (T3 Slice 4)."""
import math
import struct
import unittest

from server import roster, wire
from server.hero_movement import HeroMovement


class TestHeroMovement(unittest.TestCase):
    def test_walk_single_target_arrives_and_stops(self):
        hero = HeroMovement(eid=1500, team=1)
        self.assertEqual((hero.x, hero.y), (roster.SPAWN_X, roster.SPAWN_Y))
        self.assertFalse(hero.is_moving)

        target = (roster.SPAWN_X + 2.0, roster.SPAWN_Y)
        start_frames = hero.set_target(*target)

        # Spatial anchor only; the session owns compact-id ActionMoveTo.
        self.assertEqual(len(start_frames), 1)
        op_pos, payload_pos = start_frames[0]
        self.assertEqual(op_pos, wire.OP.POSITION)
        eid, px, py, pad = struct.unpack(">IffH", payload_pos)
        self.assertEqual((eid, px, py, pad), (1500, roster.SPAWN_X, roster.SPAWN_Y, 0))

        self.assertTrue(hero.is_moving)

        # Step at MOVE_TICK = 0.2s; speed = 5.0 u/s -> 1.0 unit per step
        # Step 1: moves from 0 to 1.0 (midway)
        step1 = hero.step(roster.MOVE_TICK)
        self.assertEqual(len(step1), 1)
        self.assertEqual(step1[0][0], wire.OP.POSITION)
        eid, px, py, pad = struct.unpack(">IffH", step1[0][1])
        self.assertEqual(eid, 1500)
        self.assertAlmostEqual(px, roster.SPAWN_X + 1.0, places=4)
        self.assertTrue(hero.is_moving)

        # Step 2: moves remaining 1.0 unit -> reaches target (roster.SPAWN_X + 2.0)
        step2 = hero.step(roster.MOVE_TICK)
        # Arrival must not change visibility (1067 was misidentified as idle).
        self.assertEqual(len(step2), 2)
        self.assertEqual(step2[0][0], wire.OP.POSITION)
        self.assertEqual(step2[1][0], wire.OP.POSITION)
        for _, body in step2:
            self.assertEqual(struct.unpack(">IffH", body)[0], 1500)
            self.assertAlmostEqual(struct.unpack(">IffH", body)[1], target[0], places=4)
            self.assertAlmostEqual(struct.unpack(">IffH", body)[2], target[1], places=4)
        self.assertFalse(hero.is_moving)

        # Subsequent steps while stationary: silence (zero frames)
        idle_frames = hero.step(roster.MOVE_TICK)
        self.assertEqual(idle_frames, [])

    def test_walk_multi_waypoint_path(self):
        hero = HeroMovement(eid=1500, team=1, x=0.0, y=0.0)
        waypoints = [(0.0, 3.0), (4.0, 3.0)]  # Total path: 3 units North, 4 units East = 7 units
        start_frames = hero.set_path(waypoints)
        self.assertEqual(len(start_frames), 1)

        # Step 1: 0.5s * 5.0 = 2.5 units along first segment (0, 0) -> (0, 3)
        hero.step(0.5)
        self.assertAlmostEqual(hero.x, 0.0, places=4)
        self.assertAlmostEqual(hero.y, 2.5, places=4)
        self.assertTrue(hero.is_moving)

        # Step 2: 0.5s * 5.0 = 2.5 units (reaches (0, 3), then 2.0 units towards (4, 3))
        hero.step(0.5)
        self.assertAlmostEqual(hero.x, 2.0, places=4)
        self.assertAlmostEqual(hero.y, 3.0, places=4)
        self.assertTrue(hero.is_moving)

        # Step 3: 0.5s * 5.0 = 2.5 units (only 2.0 units left to (4, 3) -> arrives!)
        arrival_frames = hero.step(0.5)
        self.assertEqual(len(arrival_frames), 2)
        self.assertAlmostEqual(hero.x, 4.0, places=4)
        self.assertAlmostEqual(hero.y, 3.0, places=4)
        self.assertFalse(hero.is_moving)

    def test_hero_eid_and_team_spawns(self):
        # Team 1: left side (negative X)
        for eid in (1500, 1515, 1516):
            hero = HeroMovement(eid=eid, team=1)
            self.assertEqual(hero.team, 1)
            self.assertEqual(hero.eid, eid)
            self.assertLess(hero.x, 0.0, f"Team 1 hero {eid} must have negative X spawn")
            # Step and check 1070 eid
            frames = hero.set_target(hero.x + 1.0, hero.y)
            eid_out = struct.unpack_from(">I", frames[0][1], 0)[0]
            self.assertEqual(eid_out, eid)

        # Team 2: right side (positive X)
        for eid in (1517, 1518, 1519):
            hero = HeroMovement(eid=eid, team=2)
            self.assertEqual(hero.team, 2)
            self.assertEqual(hero.eid, eid)
            self.assertGreater(hero.x, 0.0, f"Team 2 hero {eid} must have positive X spawn")
            frames = hero.set_target(hero.x - 1.0, hero.y)
            eid_out = struct.unpack_from(">I", frames[0][1], 0)[0]
            self.assertEqual(eid_out, eid)

    def test_anti_rubberband_retarget_while_moving(self):
        hero = HeroMovement(eid=1500, team=1, x=0.0, y=0.0)
        hero.set_target(10.0, 0.0)

        # Move 1 second (5 units) towards (10, 0)
        hero.step(1.0)
        self.assertAlmostEqual(hero.x, 5.0, places=4)
        self.assertAlmostEqual(hero.y, 0.0, places=4)

        # Player taps new target (5.0, 5.0) while already in motion
        new_frames = hero.set_target(5.0, 5.0)
        # Must NOT emit an old start anchor (empty list returned)
        self.assertEqual(new_frames, [])
        # Position must NOT snap back
        self.assertAlmostEqual(hero.x, 5.0, places=4)
        self.assertAlmostEqual(hero.y, 0.0, places=4)

        # Facing updates towards new target (0, 1)
        self.assertAlmostEqual(hero.facing[0], 0.0, places=4)
        self.assertAlmostEqual(hero.facing[1], 1.0, places=4)

        # Step 1 second (5 units) towards (5, 5) -> arrives!
        arrival = hero.step(1.0)
        self.assertEqual(len(arrival), 2)
        self.assertAlmostEqual(hero.x, 5.0, places=4)
        self.assertAlmostEqual(hero.y, 5.0, places=4)
        self.assertFalse(hero.is_moving)

    def test_simulation_never_changes_visibility_for_locomotion(self):
        hero = HeroMovement(eid=1500, team=1)
        frames = hero.set_target(hero.x + 5.0, hero.y)
        for _ in range(10):
            frames.extend(hero.step(roster.MOVE_TICK))

        opcodes = [op for op, _ in frames]
        self.assertNotIn(wire.OP.ENTITY_VISIBILITY, opcodes)
        self.assertTrue(all(op == wire.OP.POSITION for op in opcodes))

    def test_stop_and_teleport_do_not_hide_hero(self):
        hero = HeroMovement(eid=1500)
        hero.set_target(hero.x + 20, hero.y)
        frames = hero.stop() + hero.teleport(hero.spawn_x, hero.spawn_y)
        self.assertTrue(all(op == wire.OP.POSITION for op, _ in frames))


if __name__ == "__main__":
    unittest.main()
