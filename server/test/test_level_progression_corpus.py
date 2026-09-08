"""Independent native level/XP/ability-point contracts; no production mutation."""
import struct
import unittest

from server import hero_balance, level_wire
from server.test.test_cooldown_wire import CORPUS_ROOT, CORPUS_FILES, recorded_frames
from server.test.test_item_input import CAPTURE, item_capture
from Tools.Teardown.inspect_level_progression import (parse_level_increment,
    parse_xp_requirement, read_hero_progression)


@unittest.skipUnless(all((CORPUS_ROOT / name).is_file() for name in CORPUS_FILES),
                     "external decoded replay caches unavailable")
class TestNativeProgressionSnapshots(unittest.TestCase):
    def test_all_852_hero_levels_match_native_base_stat_growth_and_xp_requirement(self):
        checked = 0
        for name, index, opcode, payload in recorded_frames():
            if opcode != 1011:
                continue
            hero_id = struct.unpack_from(">I", payload)[0]
            stats = hero_balance.STATS.get(hero_balance.HERO_NAMES.get(hero_id))
            if stats is None:
                continue
            progression = read_hero_progression(payload)
            maximum_hp = struct.unpack_from(">f", payload, 46)[0]
            self.assertAlmostEqual(maximum_hp, stats.health_base + stats.health_per_level * (progression.level - 1),
                                   delta=0.25, msg=f"{name}:{index}")
            self.assertEqual(progression.next_level_xp, 68 + 16 * (progression.level - 1))
            self.assertEqual(level_wire.next_level_requirement(progression.level), progression.next_level_xp)
            checked += 1
        self.assertEqual(checked, 852)

    def test_level_increment_grants_point_and_rolls_xp_into_the_next_level(self):
        rows = {index: (opcode, payload) for name, index, opcode, payload in recorded_frames()
                if name == "vgr5frames.pkl"}
        for before_index, after_index, expected_level in ((21137, 22576, 5), (110665, 112171, 3)):
            before = read_hero_progression(rows[before_index][1])
            after = read_hero_progression(rows[after_index][1])
            xp_delta = 0.0
            increments = []
            requirements = []
            for index in range(before_index + 1, after_index):
                opcode, payload = rows[index]
                if len(payload) < 4 or struct.unpack_from(">I", payload)[0] != 1500:
                    continue
                if opcode == 1053 and payload[8] == 8:
                    xp_delta += struct.unpack_from(">f", payload, 4)[0]
                elif opcode == 1076:
                    increments.append(parse_level_increment(payload))
                elif opcode == 1052 and payload[12] == 39:
                    requirements.append(parse_xp_requirement(payload)[1])
                elif opcode == 1082:
                    self.fail("selected level-up window unexpectedly spends an ability point")
            self.assertEqual(increments, [(1500, 1)])
            self.assertEqual((before.level, after.level), (expected_level - 1, expected_level))
            self.assertEqual((before.unspent_points, after.unspent_points), (0, 1))
            self.assertAlmostEqual(after.within_level_xp, before.within_level_xp + xp_delta - before.next_level_xp,
                                   places=4)
            self.assertEqual(requirements, [after.next_level_xp])

    def test_1082_spends_one_ability_point_without_changing_hero_level(self):
        rows = {index: (opcode, payload) for name, index, opcode, payload in recorded_frames()
                if name == "vgr5frames.pkl"}
        before = read_hero_progression(rows[22576][1])
        after = read_hero_progression(rows[24235][1])
        relevant = [(opcode, payload) for index, (opcode, payload) in rows.items()
                    if 22576 < index < 24235 and opcode in (1076, 1082)
                    and struct.unpack_from(">I", payload)[0] == 1500]
        self.assertEqual(len(relevant), 1)
        self.assertEqual(relevant[0][0], 1082)
        self.assertEqual(struct.unpack_from(">II", relevant[0][1]), (1500, 1))
        self.assertEqual(relevant[0][1][8:], bytes(6))
        self.assertEqual((before.level, after.level), (5, 5))
        self.assertEqual((before.unspent_points, after.unspent_points), (1, 0))


@unittest.skipUnless(CAPTURE.is_file(), "external passive progression capture unavailable")
class TestNativeProgressionCapture(unittest.TestCase):
    def test_every_1076_increment_has_the_exact_measured_shape(self):
        rows = [row for row in item_capture()["s2c"] if row.opcode == 1076]
        self.assertEqual(len(rows), 95)
        heroes = 0
        for row in rows:
            eid, delta = parse_level_increment(row.payload)
            self.assertEqual(struct.pack(">II", eid, delta) + bytes(6), row.payload)
            self.assertEqual(level_wire.build_level_increment(eid), row.payload)
            self.assertEqual(level_wire.parse_level_increment(row.payload), (eid, delta))
            heroes += eid in (1500, 1515, 1516, 1517, 1518, 1519)
        self.assertEqual(heroes, 47)

    def test_every_native_xp_requirement_rebuilds_with_production_setter_flags(self):
        rows = [row for row in item_capture()["s2c"] if row.opcode == 1052 and row.payload[12] == 39]
        self.assertEqual(len(rows), 47)
        for row in rows:
            eid, requirement = parse_xp_requirement(row.payload)
            self.assertEqual(level_wire.build_xp_requirement(eid, requirement), row.payload)
            self.assertEqual(level_wire.parse_xp_requirement(row.payload), (eid, requirement))

    def test_all_seven_local_skill_requests_echo_then_ack_the_same_slot(self):
        frames = item_capture()
        requests = [row for row in frames["c2s"] if row.opcode == 1078]
        self.assertEqual(len(requests), 7)
        for request in requests:
            self.assertEqual(len(request.payload), 6)
            slot = request.payload[0]
            self.assertIn(slot, (0, 1, 2))
            self.assertEqual(request.payload[1:], bytes(5))
            echoes = [row for row in frames["s2c"] if request.time <= row.time <= request.time + 1
                      and row.opcode == 1078 and row.payload == request.payload]
            acks = [row for row in frames["s2c"] if request.time <= row.time <= request.time + 1
                    and row.opcode == 1082 and struct.unpack_from(">II", row.payload) == (1500, slot)]
            self.assertEqual(len(echoes), 1)
            self.assertEqual(len(acks), 1)
            self.assertLessEqual(echoes[0].time, acks[0].time)
            self.assertEqual(acks[0].payload[8:], bytes(6))


if __name__ == "__main__":
    unittest.main()
