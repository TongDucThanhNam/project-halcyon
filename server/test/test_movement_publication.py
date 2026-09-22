"""Movement orders must agree with production navigation acceptance."""
import struct
import unittest

from server import roster, wire
from server.navigation import NavMesh
from server.test.test_ability_cc_presentation import session


class MovementPublicationTests(unittest.TestCase):
    def setUp(self):
        self.world, self.frames, self.observer_frames, self.owner, _ = session()
        self.hero = self.world.hero_sims[1500]
        # Two disconnected walkable islands; no fallback through the gap.
        self.hero.navigation = NavMesh(
            [(-5, -5), (5, -5), (5, 5), (-5, 5),
             (15, -5), (25, -5), (25, 5), (15, 5)],
            [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)])
        self.hero.teleport(0, 0)

    def move(self, x, y):
        self.frames.clear()
        self.observer_frames.clear()
        self.world._apply_event(wire.OP.MOVE_CAST, struct.pack('>ff6x', x, y), self.owner)

    def test_off_mesh_click_publishes_the_projected_destination_to_both_clients(self):
        self.move(0, 12)
        self.assertEqual(self.hero.move_target, (0, 5))
        expected = roster.build_move_intent(0, 0, 5)
        for frames in (self.frames, self.observer_frames):
            self.assertEqual([p for op, p in frames if op == wire.OP.MOVE_TO], [expected])
        self.assertEqual((self.hero.x, self.hero.y), (0, 0))  # no teleport to endpoint

    def test_1060_accepts_pursuit_without_immediate_1045_attack_start(self):
        self.frames.clear()
        self.world._apply_event(wire.OP.TARGET_ENTITY,struct.pack('>IH',1517,0),self.owner)
        self.assertEqual(self.hero.target_eid,1517)
        self.assertFalse(any(op==wire.OP.TARGET_ACQUIRE for op,_ in self.frames))

    def test_disconnected_click_does_not_start_client_navigation(self):
        self.move(20, 0)
        self.assertFalse(self.hero.is_moving)
        self.assertIsNone(self.hero.move_target)
        self.assertFalse(any(op == wire.OP.MOVE_TO for op, _ in self.frames))
        self.assertTrue(any(op == wire.OP.POSITION for op, _ in self.frames))

    def test_rejected_retarget_preserves_stop_frames_and_valid_click_is_unchanged(self):
        self.move(4, 0)
        self.assertIn((wire.OP.MOVE_TO, roster.build_move_intent(0, 4, 0)), self.frames)
        self.world._step_heroes(.05, .05)
        position = (self.hero.x, self.hero.y)
        self.move(20, 0)
        self.assertFalse(self.hero.is_moving)
        self.assertEqual((self.hero.x, self.hero.y), position)
        self.assertEqual(self.frames, [(wire.OP.POSITION, roster.build_position(1500, *position))] * 2)


class PursuitPublicationTests(unittest.TestCase):
    def test_3d_movement_has_explicit_xyz_and_selection_preservation(self):
        payload=roster.build_move_intent_3d(5,1.25,.75,-3)
        self.assertEqual(len(payload),14)
        self.assertEqual(struct.unpack('>BfffB',payload),(5,1.25,.75,-3.0,1))
        self.assertEqual(roster.build_move_intent_3d(5,1.25,.75,-3,preserve_selection=False)[-1],0)
        with self.assertRaises(ValueError):roster.build_move_intent_3d(0,float('nan'),0,0)

    def setUp(self):
        self.world,self.owner_frames,self.other_frames,self.owner,_=session()
        self.hero=self.world.hero_sims[1500]
        self.hero.teleport(0,0)
        self.world.hero_sims[1517].teleport(60,0)
        self.world.publish_pursuit_intent=True
        self.owner_frames.clear();self.other_frames.clear()

    def targets(self, frames):
        return [p for op,p in frames if op in (wire.OP.MOVE_TO,wire.OP.MOVE_TO_3D) and p[0]==0]

    def test_pursuit_starts_native_route_without_periodic_owner_correction(self):
        self.world._apply_event(wire.OP.TARGET_ENTITY,roster.build_target_entity(1517),self.owner)
        version=self.hero.order_version
        self.world.advance_simulation()
        expected=roster.build_move_intent_3d(0,self.hero.move_target[0],0,self.hero.move_target[1])
        self.assertEqual(self.targets(self.owner_frames),[expected])
        self.assertEqual(self.targets(self.other_frames),[expected])
        self.assertFalse(any(op==wire.OP.MOVE_TO for op,_ in self.owner_frames))
        self.assertEqual(self.hero.target_eid,1517)
        self.assertEqual(self.hero.order_version,version)
        self.assertFalse(any(op==wire.OP.POSITION and p[:4]==(1500).to_bytes(4,'big') for op,p in self.owner_frames))
        self.assertTrue(any(op==wire.OP.POSITION and p[:4]==(1500).to_bytes(4,'big') for op,p in self.other_frames))
        for _ in range(5):self.world.advance_simulation()
        self.assertEqual(self.targets(self.owner_frames),[expected])

    def test_retarget_and_range_stop_are_explicit_but_ground_order_is_not_overwritten(self):
        self.hero.set_target_eid(1517)
        self.world.advance_simulation()
        self.world.hero_sims[1517].teleport(50,0)
        self.world.advance_simulation()
        self.assertEqual(self.targets(self.owner_frames)[-1],roster.build_move_intent_3d(0,50,0,0))
        self.world.hero_sims[1517].teleport(self.hero.x+1,self.hero.y)
        self.world.advance_simulation()
        self.assertFalse(self.hero.is_moving)
        self.assertEqual(self.targets(self.owner_frames)[-1],roster.build_move_intent_3d(0,self.hero.x,0,self.hero.y))
        self.assertNotIn(1500,self.world._last_pursuit_intent)
        self.owner_frames.clear()
        self.world._apply_event(wire.OP.MOVE_CAST,struct.pack('>ff6x',-10,0),self.owner)
        self.world.advance_simulation()
        self.assertEqual(self.targets(self.owner_frames),[roster.build_move_intent(0,-10,0)])

    def test_opt_in_does_not_change_simulation_or_emit_per_tick_duplicate_targets(self):
        def run(enabled):
            world,frames,_,owner,_=session()
            world.publish_pursuit_intent=enabled
            hero=world.hero_sims[1500];hero.teleport(0,0)
            world.hero_sims[1517].teleport(60,0)
            world._apply_event(wire.OP.TARGET_ENTITY,roster.build_target_entity(1517),owner)
            states=[]
            for _ in range(35):
                world.advance_simulation();states.append((hero.position_fixed,hero.target_eid,hero.order_version))
            return states,self.targets(frames)
        enabled,targets=run(True)
        disabled,no_targets=run(False)
        self.assertEqual(enabled,disabled)
        self.assertEqual(len(targets),1)
        self.assertEqual(no_targets,[])

    def test_target_death_stops_the_published_pursuit_route(self):
        self.hero.set_target_eid(1517)
        self.world.advance_simulation()
        before=self.hero.position_fixed
        enemy=self.world.hero_sims[1517]
        enemy.apply_damage(enemy.hp,1500,self.world.sim_time)
        self.assertFalse(enemy.is_alive)
        self.owner_frames.clear()
        self.world.advance_simulation()
        self.assertEqual(self.hero.position_fixed,before)
        self.assertIsNone(self.hero.target_eid)
        self.assertFalse(self.hero.is_moving)
        self.assertEqual(self.targets(self.owner_frames),[roster.build_move_intent_3d(0,self.hero.x,0,self.hero.y)])

    def test_new_ground_order_during_pursuit_is_not_replaced_by_a_stop(self):
        self.hero.set_target_eid(1517)
        self.world.advance_simulation()
        self.assertIn(1500,self.world._last_pursuit_intent)
        self.owner_frames.clear()
        self.world._apply_event(wire.OP.MOVE_CAST,struct.pack('>ff6x',-10,0),self.owner)
        self.world.advance_simulation()
        self.assertEqual(self.targets(self.owner_frames),[roster.build_move_intent(0,-10,0)])
        self.assertTrue(self.hero.is_moving)


if __name__ == '__main__':
    unittest.main()
