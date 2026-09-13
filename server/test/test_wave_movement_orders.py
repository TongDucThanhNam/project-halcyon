"""Native lane order evidence and continuous stop/turn/resume presentation."""
import struct
import unittest

from server.paths import research_dir
from server import decode, roster, wave
from server.hero_movement import HeroMovement
from server.status_effects import StatusEffect, StatusManager, StatusType


def goals(frames, slot):
    return [struct.unpack_from('>ff', body, 1) for opcode, body in frames
            if opcode == 1016 and body[0] == slot]


class TestNativeLaneMovementOrders(unittest.TestCase):
    def test_native_first_wave_receives_lane_turns_and_combat_destination_changes(self):
        root = research_dir('vg_max') / 'vgr2'
        prefix = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-591146df-33f2-4f12-9a04-8d800d239821'
        paths = {chunk: root / f'{prefix}.{chunk}.vgr' for chunk in (1, 2, 3)}
        if not all(path.is_file() for path in paths.values()):
            self.skipTest('operator-owned lane movement corpus unavailable')
        frames = {}
        for chunk, path in paths.items():
            frames[chunk], stats = decode.walk_vgr(path)
            self.assertEqual(stats['failures'], 0)
        _, opcode, spawn = frames[1][638]
        self.assertEqual(opcode, 1010)
        source = struct.unpack_from('>I', spawn, 8)[0]
        self.assertEqual(source, 4443)
        slot = spawn[116]
        destinations = []
        for chunk, row in ((1, 639), (1, 683), (2, 210), (2, 262), (3, 315)):
            _, opcode, body = frames[chunk][row]
            self.assertEqual(opcode, 1016)
            destination = struct.unpack_from('>ff', body, 1)
            self.assertEqual(body, roster.build_move_intent(slot, *destination))
            destinations.append(destination)
        self.assertEqual(len(set(destinations)), 5)
        self.assertTrue(all(a[0] > b[0] for a, b in zip(destinations, destinations[1:])))
        self.assertEqual(frames[3][326][1], 1045)
        self.assertEqual(struct.unpack_from('>I', frames[3][326][2])[0], source)


class TestWaveMovementOrders(unittest.TestCase):
    def actor(self, *, combat=False, spacing=0, pair=0):
        director = wave.Director(0, combat=combat, rules=wave.WaveRules(ally_spacing=spacing))
        minion = wave.Minion(4610, 1, 0, pair)
        minion.x, minion.y = 0, 0
        minion.path = [(1, 0), (1, 2), (4, 2)]
        director.minions = [minion]
        slot = director.actor_slots.register(minion.eid, 203)
        director._publish_move_intent(minion, minion.path[0])
        return director, minion, slot

    def test_lane_turn_replaces_first_spawn_goal_without_repeating_unchanged_orders(self):
        director, minion, slot = self.actor()
        first_turn = director.pump(0.25)
        self.assertEqual(goals(first_turn, slot), [(1, 2)])
        self.assertEqual((minion.x, minion.y), (1, 0.125))
        self.assertEqual(goals(director.pump(0.30), slot), [])
        second_turn = director.pump(0.75)
        self.assertEqual(goals(second_turn, slot), [(4, 2)])
        self.assertEqual((minion.x, minion.y), (1.375, 2))
        director.pump(2)
        self.assertTrue(minion.arrived)
        self.assertEqual(goals(director.pump(2.05), slot), [])

    def test_ally_obstruction_stops_once_and_death_releases_following_actor(self):
        director, minion, slot = self.actor(spacing=0.75)
        minion.path = [(4, 0)]
        director._publish_move_intent(minion, minion.path[0])
        ally = wave.Minion(4611, 1, 0)
        ally.x, ally.y, ally.path = 1, 0, []
        director.minions.append(ally)
        stopped = director.pump(0.1)
        self.assertEqual((minion.x, minion.y), (0, 0))
        self.assertEqual(goals(stopped, slot), [(0, 0)])
        self.assertTrue(any(op == 1070 and struct.unpack_from('>I', body)[0] == minion.eid
                            for op, body in stopped))
        self.assertEqual(goals(director.pump(0.2), slot), [])
        director.on_minion_death(ally, 1500, 0.2)
        resumed = director.pump(0.3)
        self.assertEqual(goals(resumed, slot), [(4, 0)])
        self.assertEqual((minion.x, minion.y), (0.45, 0))

    def test_stun_stops_current_goal_and_expiry_resumes_without_banking_travel(self):
        director, minion, slot = self.actor()
        minion.path = [(10, 0)]
        director._publish_move_intent(minion, minion.path[0])
        director.pump(0.2)
        status = StatusManager()
        status.apply_effect(StatusEffect('lane-stun', StatusType.STUN, 1500, minion.eid,
                                         0.3, 0.2, 0.5))
        stopped = director.pump(0.25, status_manager=status)
        self.assertEqual(goals(stopped, slot), [(struct.unpack('>f', struct.pack('>f', 0.9))[0], 0)])
        self.assertEqual(goals(director.pump(0.45, status_manager=status), slot), [])
        resumed = director.pump(0.5, status_manager=status)
        self.assertEqual(goals(resumed, slot), [(10, 0)])
        self.assertEqual(minion.x, 1.125)

    def test_attack_range_stops_before_action_then_pursuit_resumes_and_retargets(self):
        director, minion, slot = self.actor(combat=True)
        target = HeroMovement(eid=1517, team=2, x=5, y=0)
        minion.target_hero = target
        self.assertEqual(goals(director.pump(0.1), slot), [(5, 0)])
        arrived = director.pump(0.7)
        self.assertEqual((minion.x, minion.y), (3, 0))
        self.assertEqual(goals(arrived, slot), [(3, 0)])
        self.assertLess(next(i for i, (op, _) in enumerate(arrived) if op == 1016),
                        next(i for i, (op, _) in enumerate(arrived) if op == 1045))
        self.assertEqual(goals(director.pump(0.7), slot), [])
        target.teleport(7, 0)
        self.assertEqual(goals(director.pump(0.75), slot), [(7, 0)])
        target.teleport(8, 0)
        self.assertEqual(goals(director.pump(0.8), slot), [(8, 0)])

    def test_reconnect_replays_actual_blocked_goal_and_does_not_resume_dead_actor(self):
        director, minion, slot = self.actor(spacing=0.75)
        minion.path = [(4, 0)]
        director._publish_move_intent(minion, minion.path[0])
        ally = wave.Minion(4611, 1, 0)
        ally.x, ally.y, ally.path = 1, 0, []
        director.minions.append(ally)
        director.pump(0.1)
        self.assertEqual(goals(director.get_spawn_frames(0.1), slot), [(0, 0)])
        director.on_minion_death(minion, 1500, 0.1)
        self.assertEqual(goals(director.get_spawn_frames(0.15), slot), [])
        self.assertEqual(goals(director.pump(0.2), slot), [])

    def test_stationary_attack_release_and_contact_do_not_repeat_stop_intent(self):
        director, minion, slot = self.actor(combat=True, pair=3)
        target = HeroMovement(eid=1517, team=2, x=3, y=0)
        minion.target_hero = target
        release = lambda *args: [(1037, b'projectile')]
        first = director.pump(0.05, on_projectile_release=release)
        self.assertEqual(goals(first, slot), [(0, 0)])
        self.assertEqual([op for op, _ in first], [1016, 1070, 1045])
        later = []
        for tick in range(2, 32):
            frames = director.pump(tick / 20, on_projectile_release=release)
            self.assertEqual(goals(frames, slot), [])
            later.extend(frames)
        self.assertEqual(sum(op == 1037 for op, _ in later), 2)
        self.assertTrue(any(op == 1054 for op, _ in later))


if __name__ == '__main__':
    unittest.main()
