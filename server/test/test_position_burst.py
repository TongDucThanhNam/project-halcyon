"""Owner walking corrections must not weaken authority or other subscribers.

September 22 native data exposes both periodic and start/arrival additive
corrections. Accepted walking now withholds those only from the owner;
explicit stops and attack pursuit retain their existing contract. These
server tests alone do not prove client smoothness.
"""
import struct
import unittest

from server import match_server, roster, wire
from server.test.test_ability_cc_presentation import session

BURST = match_server.LOCAL_POSITION_BURST_SAMPLES


def move_cast(world, conn, x, y):
    world._apply_event(wire.OP.MOVE_CAST, struct.pack('>ff6x', x, y), conn)


def positions(frames):
    return [p for op, p in frames if op == wire.OP.POSITION]


def payload_xy(payload):
    _, x, y = struct.unpack_from('>Iff', payload, 0)
    return x, y


class PositionBurstTests(unittest.TestCase):
    def setUp(self):
        self.world, self.frames, self.observer_frames, self.owner, self.observer = session()
        self.hero = self.world.hero_sims[1500]
        self.hero.teleport(0, 0)

    def test_accepted_walk_withholds_corrections_from_owner_only(self):
        move_cast(self.world, self.owner, 40.0, 0.0)
        self.assertTrue(self.hero.is_moving)
        self.assertEqual(positions(self.frames), [])
        self.assertEqual(positions(self.observer_frames),
                         [roster.build_position(1500, 0, 0)])
        self.frames.clear()
        self.observer_frames.clear()
        for _ in range(220):                              # 40 units at 5/s = 8 s
            if not self.hero.is_moving:
                break
            self.world.advance_simulation()
        owner = positions(self.frames)
        observer = positions(self.observer_frames)
        # Native walking reaches its acknowledged destination without an
        # additive correction that could continue beyond its walking action.
        self.assertEqual(owner, [])
        self.assertEqual(observer[-2:], [roster.build_position(1500, 40, 0)] * 2)
        self.assertEqual((self.hero.x, self.hero.y), (40, 0))
        # Other clients keep the periodic 5 Hz stream through the whole walk.
        self.assertGreater(len(observer), BURST + 12)
        periodic = [payload_xy(p)[0] for p in observer[:-2]]
        self.assertTrue(all(a < b for a, b in zip(periodic, periodic[1:])))

    def test_retarget_keeps_observer_anchors_and_owner_accepted_destination(self):
        move_cast(self.world, self.owner, 40.0, 0.0)
        for _ in range(40):                               # 2 s into the walk
            self.world.advance_simulation()
        self.assertTrue(self.hero.is_moving)
        here = (self.hero.x, self.hero.y)
        self.frames.clear()
        self.observer_frames.clear()
        move_cast(self.world, self.owner, 10.0, 6.0)
        # The retarget correction is order-anchored, never the old start.
        self.assertEqual(positions(self.frames), [])
        self.assertEqual(positions(self.observer_frames),
                         [roster.build_position(1500, *here)])
        self.assertIn((wire.OP.MOVE_TO, roster.build_move_intent(0, 10, 6)),
                      self.frames)
        self.frames.clear()
        self.observer_frames.clear()
        for _ in range(300):
            if not self.hero.is_moving:
                break
            self.world.advance_simulation()
        owner = positions(self.frames)
        self.assertEqual(owner, [])
        self.assertEqual(positions(self.observer_frames)[-2:],
                         [roster.build_position(1500, 10, 6)] * 2)
        self.assertEqual((self.hero.x, self.hero.y), (10, 6))

    def test_diagnostic_baseline_retains_old_anchors_but_same_simulation(self):
        self.world.owner_walk_anchors = True
        move_cast(self.world, self.owner, 4, 0)
        self.assertEqual(positions(self.frames), [roster.build_position(1500, 0, 0)])
        self.frames.clear()
        for _ in range(40):
            self.world.advance_simulation()
            if not self.hero.is_moving:
                break
        self.assertEqual(positions(self.frames), [roster.build_position(1500, 4, 0)] * 2)
        self.assertEqual((self.hero.x, self.hero.y), (4, 0))

    def test_rejected_retarget_still_delivers_stop_double_to_owner(self):
        from server.navigation import NavMesh
        self.hero.navigation = NavMesh(
            [(-5, -5), (5, -5), (5, 5), (-5, 5),
             (15, -5), (25, -5), (25, 5), (15, 5)],
            [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)])
        self.hero.teleport(0, 0)
        move_cast(self.world, self.owner, 5.0, 5.0)   # ~28 ticks of walking
        for _ in range(24):        # 1.2 s: walk still in progress
            self.world.advance_simulation()
        self.assertTrue(self.hero.is_moving)
        here = (self.hero.x, self.hero.y)
        self.frames.clear()
        self.observer_frames.clear()
        move_cast(self.world, self.owner, 20.0, 0.0)      # unreachable island
        self.assertFalse(self.hero.is_moving)
        self.assertEqual(self.frames,
                         [(wire.OP.POSITION, roster.build_position(1500, *here))] * 2)

    def test_attack_order_pursuit_bursts_then_withholds(self):
        self.world.hero_sims[1517].teleport(60.0, 0.0)
        self.world._apply_event(wire.OP.TARGET_ENTITY,
                                roster.build_target_entity(1517), self.owner)
        # The pursuit itself starts inside the first sim step, so tick a
        # fixed window (20 s > the ~12 s approach) instead of gating on
        # is_moving before the first tick. The attack windup emits its own
        # action-anchored position frame at range (build_attack_start_frames
        # via _emit_frames), so the arrival cluster is the burst + windup +
        # stop double; the walk BODY must stay silent for the owner.
        seen: list[tuple[float, bytes]] = []
        previous: list[bytes] = []
        for _ in range(400):
            self.world.advance_simulation()
            current = positions(self.frames)
            for payload in current[len(previous):]:
                seen.append((self.world.sim_time, payload))
            previous = current
            if not self.hero.is_moving and self.world.sim_time > 12:
                break
        self.assertFalse(self.hero.is_moving)         # arrived in range
        end = self.world.sim_time
        self.assertEqual(len([t for t, _ in seen if t < 1.5]), BURST)
        self.assertEqual([t for t, _ in seen if 1.5 < t < end - 0.2], [])
        self.assertEqual(seen[-1][1], seen[-2][1])    # stop double

    def test_owner_presence_cannot_change_the_trajectory(self):
        def trajectory(with_owner):
            world, frames, observer_frames, owner, observer = session()
            hero = world.hero_sims[1500]
            hero.teleport(0, 0)
            move_cast(world, owner, 40.0, 0.0)
            if not with_owner:
                world.clients.pop(owner)
            seq = []
            for _ in range(220):
                if not hero.is_moving:
                    break
                world.advance_simulation()
                seq.append(hero.position_fixed)
            return seq, hero.is_moving

        with_owner, moving_a = trajectory(True)
        without, moving_b = trajectory(False)
        self.assertEqual(with_owner, without)
        self.assertEqual(moving_a, moving_b)
        self.assertFalse(moving_a)

    def test_walk_suppression_never_touches_the_simulation_state(self):
        move_cast(self.world, self.owner, 40.0, 0.0)
        self.assertEqual(self.world.position_burst[1500], 0)
        baseline = self.hero.position_fixed
        seq = []
        for _ in range(20):
            self.world.advance_simulation()
            seq.append(self.hero.position_fixed)
        # The walk continues without owner periodic corrections, and an
        # identical window without any owner is equal on the fixed lattice.
        self.assertEqual(self.world.position_burst[1500], 0)
        self.assertTrue(self.hero.is_moving)
        world2, _frames, _observer_frames, owner2, _observer = session()
        hero2 = world2.hero_sims[1500]
        hero2.teleport(0, 0)
        move_cast(world2, owner2, 40.0, 0.0)
        world2.clients.pop(owner2)
        seq2 = []
        for _ in range(20):
            world2.advance_simulation()
            seq2.append(hero2.position_fixed)
        self.assertEqual(seq, seq2)
        self.assertGreater(seq[-1][0], baseline[0])

    def test_walk_replaces_an_unexhausted_attack_burst(self):
        self.world.hero_sims[1517].teleport(60, 0)
        self.world._apply_event(wire.OP.TARGET_ENTITY,
                               roster.build_target_entity(1517), self.owner)
        self.assertEqual(self.world.position_burst[1500], BURST)
        move_cast(self.world, self.owner, 40, 0)
        self.frames.clear()
        self.observer_frames.clear()
        for _ in range(20):
            self.world.advance_simulation()
        self.assertTrue(self.hero.is_moving)
        self.assertEqual(positions(self.frames), [])
        self.assertGreater(len(positions(self.observer_frames)), 0)


class PositionBurstInterruptionTests(unittest.TestCase):
    setUp = PositionBurstTests.setUp

    def exhausted_walk(self):
        move_cast(self.world, self.owner, 40, 0)
        for _ in range(40):
            self.world.advance_simulation()
        self.assertEqual(self.world.position_burst[1500], 0)
        self.frames.clear()
        self.observer_frames.clear()

    def test_stun_stop_reaches_owner_after_burst_exhaustion(self):
        from server.status_effects import StatusEffect, StatusType
        self.exhausted_walk()
        here = (self.hero.x, self.hero.y)
        now = self.world.sim_time
        self.world.status_manager.apply_effect(StatusEffect(
            'burst-stun', StatusType.STUN, 1517, 1500, 1, now, now + 1))
        self.world.advance_simulation()
        expected = [roster.build_position(1500, *here)] * 2
        self.assertEqual(positions(self.frames), expected)
        self.assertEqual(positions(self.observer_frames), expected)
        self.assertFalse(self.hero.is_moving)

    def test_knockback_is_published_after_owner_burst_is_empty(self):
        from server.status_effects import StatusEffect, StatusType
        self.exhausted_walk()
        old_x = self.hero.x
        now = self.world.sim_time
        self.world.status_manager.apply_effect(StatusEffect(
            'burst-knockback', StatusType.KNOCKBACK, 1517, 1500, .5, now,
            now + .5, direction=(1, 0), speed=6))
        self.world.advance_simulation()
        self.assertGreater(self.hero.x, old_x)
        expected = [roster.build_position(1500, self.hero.x, self.hero.y)]
        self.assertEqual(positions(self.frames), expected)
        self.assertEqual(positions(self.observer_frames), expected)

    def test_reconnect_catchup_includes_current_route_and_position_after_burst(self):
        self.exhausted_walk()
        catchup = []
        self.world._reconnect_hero_state(self.world.players[0],
            lambda op, payload: catchup.append((op, payload)))
        self.assertIn((wire.OP.MOVE_TO, roster.build_move_intent(0, 40, 0)), catchup)
        self.assertIn((wire.OP.POSITION,
                       roster.build_position(1500, self.hero.x, self.hero.y)), catchup)


if __name__ == '__main__':
    unittest.main()
