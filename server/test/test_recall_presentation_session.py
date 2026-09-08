"""Recall presentation follows successful or interrupted session state transitions."""
import struct
import unittest

from server import buff_wire, roster, wire
from server.status_effects import StatusEffect, StatusType
from server.test.test_sandbox_simulation import session, ticks


class RecallPresentationSessionTests(unittest.TestCase):
    def start(self):
        world, frames = session()
        world.enable_bots = False
        world._apply_event(wire.OP.TARGETLESS_CAST, struct.pack(">IBB", 0xffffffff, 4, 0))
        state = world.recall_presentation.active[1500]
        self.assertEqual([op for op, _ in frames][-3:], [1045, 1086, 1086])
        return world, frames, state

    def test_return_trigger_relocation_precede_position_and_resources_once(self):
        world, frames, state = self.start()
        hero = world.hero_sim
        hero.hp, hero.energy = 1, 1
        ticks(world, 79)
        frames.clear()
        ticks(world, 1)
        actions = [(op, p) for op, p in frames if op in (1094, 1049, 1033, 1070)]
        self.assertEqual([op for op, _ in actions][:4], [1094, 1049, 1033, 1070])
        self.assertEqual(struct.unpack_from(">II", actions[0][1]), (1500, state.withdraw_instance))
        self.assertEqual(actions[2][1][16:], bytes(6))
        self.assertFalse(any(op == 1093 for op, _ in frames))
        self.assertNotIn(1500, world.recall_presentation.active)
        ticks(world, 1)
        self.assertEqual(sum(op == 1094 for op, _ in frames), 1)

    def test_movement_and_damage_cancel_both_instances_without_return(self):
        for interruption in ("movement", "damage"):
            with self.subTest(interruption=interruption):
                world, frames, state = self.start()
                ticks(world, 2)
                frames.clear()
                if interruption == "movement":
                    world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-5, 5))
                else:
                    world._emit_frames(world._deal_damage(
                        world.hero_sims[1517], world.hero_sim, 1, "true", world.sim_time))
                    world._drain_effect_frames()
                cancelled = [struct.unpack_from(">II", p) for op, p in frames if op == 1093]
                self.assertEqual(cancelled, [(1500, state.withdraw_instance), (1500, state.ping_instance)])
                ticks(world, 80)
                self.assertFalse(any(op in (1094, 1049, 1033) for op, _ in frames))
                self.assertIsNone(world.hero_sim.last_recall_completed_at)

    def test_hard_control_cancels_before_deadline(self):
        world, frames, state = self.start()
        ticks(world, 20)
        frames.clear()
        world.status_manager.apply_effect(StatusEffect(
            "test-stun", StatusType.STUN, 1517, 1500, 2, world.sim_time, world.sim_time + 2))
        ticks(world, 1)
        self.assertIsNone(world.hero_sim.recall_completes_at)
        self.assertEqual([struct.unpack_from(">II", p) for op, p in frames if op == 1093],
                         [(1500, state.withdraw_instance), (1500, state.ping_instance)])


if __name__ == "__main__":
    unittest.main()
