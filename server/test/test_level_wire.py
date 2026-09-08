"""Native level packet contracts and ordered economy/HUD progression."""
import math
import struct
import unittest

from server import economy, hero_movement, level_wire


class TestLevelWire(unittest.TestCase):
    def test_measured_payload_layouts_and_setter_flags(self):
        increment = level_wire.build_level_increment(1500)
        self.assertEqual(increment, struct.pack(">II", 1500, 1) + bytes(6))
        self.assertEqual(level_wire.parse_level_increment(increment), (1500, 1))
        requirement = level_wire.build_xp_requirement(1500, 84)
        self.assertEqual(requirement, struct.pack(">IIf", 1500, 0xFFFFFFFF, 84) + bytes((39, 0, 1)) + bytes(7))
        self.assertEqual(level_wire.parse_xp_requirement(requirement), (1500, 84))

    def test_malformed_or_unmeasured_packets_are_rejected(self):
        for payload in (bytes(13), struct.pack(">II", 1500, 2) + bytes(6),
                        struct.pack(">II", 1500, 1) + bytes(5) + b"\x01"):
            with self.assertRaises(ValueError):
                level_wire.parse_level_increment(payload)
        for requirement in (0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                level_wire.build_xp_requirement(1500, requirement)
        additive_flags = struct.pack(">IIf", 1500, 0xFFFFFFFF, 84) + bytes((39, 1, 0)) + bytes(7)
        with self.assertRaises(ValueError):
            level_wire.parse_xp_requirement(additive_flags)

    def test_every_native_level_threshold_and_reconnect_xp_conversion(self):
        expected = (0, 68, 152, 252, 368, 500, 648, 812, 992, 1188, 1400, 1628)
        self.assertEqual(economy.XP_LEVEL_THRESHOLDS, expected)
        player = economy.PlayerEconomy(1500)
        for level in range(2, 13):
            threshold = expected[level - 1]
            self.assertEqual(player.add_xp(threshold - player.xp - 0.25), [])
            self.assertEqual(player.level, level - 1)
            self.assertEqual(player.add_xp(0.25), [level])
            self.assertEqual(player.ability_points, level)
            self.assertEqual(level_wire.within_level_xp(player.xp, level), 0)
            self.assertEqual(level_wire.next_level_requirement(level), 68 + 16 * (level - 1))
        self.assertEqual(player.add_xp(10000), [])
        self.assertEqual((player.level, player.ability_points), (12, 12))
        self.assertEqual(level_wire.within_level_xp(504.75, 6), 4.75)
        for level in (0, 13, 1.5, True):
            with self.assertRaises(ValueError):
                level_wire.next_level_requirement(level)


class TestEconomyLevelPresentation(unittest.TestCase):
    def setUp(self):
        self.manager = economy.EconomyManager()
        self.hero = hero_movement.HeroMovement(eid=1500)
        self.heroes = {1500: self.hero}
        self.player = self.manager.get_or_create(1500)

    @staticmethod
    def xp_deltas(frames):
        return [struct.unpack_from(">f", payload, 4)[0] for opcode, payload in frames
                if opcode == 1053 and payload[8] == 8]

    def test_passive_level_flushes_xp_before_coarse_boundary_and_never_twice(self):
        self.player.add_xp(67.25)
        self.manager._pending_xp[1500] = 1.25  # client's last reported XP is 66
        self.manager.last_trickle_at = 10.0
        self.assertEqual(self.manager.step(0.5, 10.5, self.heroes), [])
        old_hp, old_max = self.hero.hp, self.hero.max_hp
        crossing = self.manager.step(0.25, 10.75, self.heroes)
        self.assertEqual([opcode for opcode, _ in crossing], [1053, 1076, 1052])
        self.assertEqual(self.xp_deltas(crossing), [2.0])
        self.assertEqual(level_wire.parse_xp_requirement(crossing[2][1]), (1500, 84))
        self.assertEqual((self.player.level, self.player.ability_points, self.hero.level), (2, 2, 2))
        self.assertAlmostEqual(self.hero.hp - old_hp, self.hero.max_hp - old_max)
        self.assertNotIn(1500, self.manager._pending_xp)
        following = self.manager.step(0.25, 11.0, self.heroes)
        self.assertEqual([opcode for opcode, _ in following], [1053, 1053])
        self.assertEqual(self.xp_deltas(following), [0.25])
        self.assertEqual(struct.unpack_from(">IfB", following[0][1]), (1500, 6.0, 6))

    def test_bounty_level_delivers_pending_and_bounty_xp_before_rollover(self):
        self.player.add_xp(67.5)
        self.manager._pending_xp[1500] = 0.5
        frames = self.manager.reward_minion_bounty(1500, self.heroes)
        self.assertEqual([opcode for opcode, _ in frames], [1053, 1053, 1053, 1076, 1052])
        self.assertEqual(self.xp_deltas(frames), [0.5, 50.0])
        self.assertEqual(level_wire.within_level_xp(self.player.xp, self.player.level), 49.5)
        self.assertEqual(self.manager._pending_xp, {})
        self.assertEqual(self.xp_deltas(self.manager.step(1, 1, self.heroes)), [1.0])

    def test_multi_level_award_emits_each_requirement_and_growth_once(self):
        base_hp = self.hero.max_hp
        self.hero.hp -= 100.0
        frames = self.manager.reward_hero_bounty(1500, 1515, self.heroes, xp=500.0)
        self.assertEqual([opcode for opcode, _ in frames], [1053, 1053] + [1076, 1052] * 5)
        self.assertEqual([level_wire.parse_xp_requirement(payload)[1] for opcode, payload in frames
                          if opcode == 1052], [84, 100, 116, 132, 148])
        self.assertEqual((self.player.level, self.player.ability_points, self.hero.level), (6, 6, 6))
        self.assertEqual(self.xp_deltas(frames), [500])
        self.assertAlmostEqual(self.hero.max_hp - base_hp, 5 * getattr(self.hero, "hp_per_level", economy.HP_PER_LEVEL))
        self.assertAlmostEqual(self.hero.max_hp - self.hero.hp, 100.0)
        before = self.hero.hp
        self.player.apply_to_hero(self.hero)
        self.assertEqual(self.hero.hp, before)
        self.assertFalse(any(opcode == 1053 and payload[8] == 0 for opcode, payload in frames))

    def test_dead_hero_level_changes_stats_without_healing_or_resurrecting(self):
        self.hero.hp = 0.0
        self.hero.is_alive = False
        frames = self.manager.step(68, 68, self.heroes)
        self.assertEqual(self.player.level, 2)
        self.assertEqual(self.hero.hp, 0.0)
        self.assertFalse(self.hero.is_alive)
        self.assertEqual(sum(opcode == 1076 for opcode, _ in frames), 1)
        self.assertFalse(any(opcode == 1053 and payload[8] == 0 for opcode, payload in frames))


if __name__ == "__main__":
    unittest.main()
