"""Production Recall refills use actual deltas and a successful-return marker."""
import struct
import unittest

from server.paths import research_dir
from server import decode, recall_wire, wire
from server.hero_movement import HeroMovement
from server.status_effects import StatusEffect, StatusManager, StatusType
from server.test.test_sandbox_simulation import session


def hero():
    result = HeroMovement(hp=100, max_hp=1000, energy=10, max_energy=200, energy_regen=0)
    result.teleport(0, 10)
    return result


class RecallRefillTests(unittest.TestCase):
    def test_production_four_second_return_restores_once_then_adds_normal_regen(self):
        world, frames = session()
        world.enable_bots = False
        player = world.hero_sim
        player.hp, player.max_hp = 100, 1000
        player.energy, player.max_energy, player.energy_regen = 10, 200, 0
        world._apply_event(wire.OP.TARGETLESS_CAST, struct.pack('>IBB', 0xffffffff, 4, 0))
        for _ in range(79):
            world.advance_simulation()
        self.assertIsNone(player.last_recall_completed_at)
        self.assertEqual((player.hp, player.energy), (100, 10))
        frames.clear()
        world.advance_simulation()
        self.assertEqual(player.last_recall_completed_at, 4)
        self.assertAlmostEqual(player.hp, 357.5)
        self.assertAlmostEqual(player.energy, 61.5)
        heals = [p for op, p in frames if op == 1054 and struct.unpack_from('>II', p) == (player.eid, player.eid)]
        self.assertEqual(len(heals), 1)
        self.assertEqual(struct.unpack_from('>f', heals[0], 8)[0], 250)
        hp_stats = [struct.unpack_from('>f', p, 4)[0] for op, p in frames
                    if op == 1053 and struct.unpack_from('>I', p)[0] == player.eid and p[8] == 0]
        self.assertEqual(hp_stats, [7.5])  # Only ordinary fountain regeneration.
        energy_stats = [struct.unpack_from('>f', p, 4)[0] for op, p in frames
                        if op == 1053 and struct.unpack_from('>I', p)[0] == player.eid and p[8] == 2]
        self.assertEqual(energy_stats, [50, 1.5])
        self.assertIn(1070, [op for op, _ in frames])
        frames.clear()
        world.advance_simulation()
        self.assertFalse(any(op == 1054 and struct.unpack_from('>II', p) == (player.eid, player.eid)
                             for op, p in frames))
        self.assertEqual(player.last_recall_completed_at, 4)

    def test_resource_caps_emit_only_missing_amounts_and_zero_when_full(self):
        player = hero()
        player.hp, player.energy = 990, 195
        player.start_recall(10)
        frames = player.tick_lifecycle(0, 14)
        self.assertEqual((player.hp, player.energy), (1000, 200))
        heal = next(p for op, p in frames if op == 1054)
        self.assertEqual(struct.unpack_from('>IIf', heal), (1500, 1500, 10))
        energy = next(p for op, p in frames if op == 1053)
        self.assertEqual(struct.unpack_from('>IfB', energy), (1500, 5, 2))
        player.start_recall(15)
        frames = player.tick_lifecycle(0, 19)
        self.assertEqual(player.last_recall_completed_at, 19)
        self.assertFalse(any(op in (1053, 1054) for op, _ in frames))

    def test_wound_applies_once_to_immediate_and_ordinary_healing(self):
        player, statuses = hero(), StatusManager()
        statuses.apply_effect(StatusEffect('wound', StatusType.WOUND, 1517, 1500, 20, 0, 20, magnitude=0.33))
        player.start_recall(10)
        frames = player.tick_lifecycle(0.05, 14, status_manager=statuses)
        self.assertAlmostEqual(player.hp, 100 + 250 * 0.67 + 7.5 * 0.67)
        heal = next(p for op, p in frames if op == 1054)
        self.assertAlmostEqual(struct.unpack_from('>f', heal, 8)[0], 167.5)
        self.assertAlmostEqual(player.energy, 61.5)  # Wound does not reduce energy.

    def test_move_damage_and_control_cancellations_never_mark_completion(self):
        for cause in ('move', 'damage', 'stun', 'death'):
            with self.subTest(cause=cause):
                player, statuses = hero(), StatusManager()
                player.start_recall(10)
                if cause == 'move':
                    player.set_target(5, 10)
                elif cause == 'damage':
                    player.apply_damage(1, 1517, 11, damage_type='true')
                elif cause == 'death':
                    player.apply_damage(player.hp, 1517, 11, damage_type='true')
                else:
                    statuses.apply_effect(StatusEffect('stun', StatusType.STUN, 1517, 1500, 5, 11, 16))
                before = player.hp, player.energy
                frames = player.tick_lifecycle(0, 14, status_manager=statuses)
                self.assertIsNone(player.last_recall_completed_at)
                self.assertIsNone(player.recall_completes_at)
                self.assertEqual((player.hp, player.energy), before)
                self.assertNotIn(1054, [op for op, _ in frames])

    def test_measured_return_heights_rebuild_right_and_stable_left_slots(self):
        cases = [(research_dir('vg_phaseB') / 'vgr_live', '*-0e7de8af-96d9-4e3a-b3c2-609ed5e71120.17.vgr', 1026, 2, 1517),
                 (research_dir('vg_phaseB') / 'vgr_live', '*-5ac8f358-2683-4205-9b7b-969ea31b3c72.19.vgr', 297, 2, 1518),
                 (research_dir('vg_max') / 'vgr5b', '*-045f86d4-7ef2-4125-a835-e70a96288c88.26.vgr', 1088, 2, 1519),
                 (research_dir('vg_phaseB') / 'vgr_live', '*-1574e27a-e851-492b-8d91-94fc4bd66985.18.vgr', 1287, 1, 1515),
                 (research_dir('vg_max') / 'vgr5b', '*-045f86d4-7ef2-4125-a835-e70a96288c88.47.vgr', 619, 1, 1500)]
        self.assertNotIn(1, recall_wire.RETURN_HEIGHTS)
        self.assertNotIn(1516, recall_wire.RETURN_HEIGHTS_BY_EID)
        for base, pattern, row, team, eid in cases:
            files = list(base.glob(pattern))
            if not files:
                self.skipTest('operator-owned return-height VGR is not installed')
            frames, stats = decode.walk_vgr(str(files[0]))
            self.assertEqual(stats['failures'], 0)
            heights = recall_wire.RETURN_HEIGHTS_BY_EID.get(eid, recall_wire.RETURN_HEIGHTS.get(team))
            effect, relocation = frames[row][2], frames[row + 1][2]
            x, y = struct.unpack_from('>f', effect, 8)[0], struct.unpack_from('>f', effect, 16)[0]
            self.assertEqual(effect, recall_wire.build_return_effect(eid, x, y, heights[0]))
            self.assertEqual(relocation, recall_wire.build_return_relocation(eid, x, y, heights[1]))


if __name__ == '__main__':
    unittest.main()
