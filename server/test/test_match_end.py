"""Structure-death/result builders checked against the external natural ending."""
import pickle
import struct
import unittest

from server.paths import research_dir
from server import match_end


CORPUS_ROOT = research_dir('vg_max')
NATURAL_CACHE = CORPUS_ROOT / "match6.halcyon_spawn_audit.pkl"
SURRENDER_CACHE = CORPUS_ROOT / "vgfull.pcap.halcyon_spawn_audit.pkl"
NATURAL_FINAL_CHUNK = research_dir('vg_phaseB') / "vgr_live" / (
    "ea4c7fda-4b61-481d-abb7-1c757d24ae58-a683aa80-9811-47c3-bb64-0731a802e889.74.vgr")


class TestMatchEndBuilders(unittest.TestCase):
    def test_team_and_reason_are_separate_fields(self):
        self.assertEqual(struct.unpack(">IBB", match_end.build_match_result(1)), (1, 0, 0))
        self.assertEqual(struct.unpack(">IBB", match_end.build_match_result(
            2, match_end.MatchEndReason.SURRENDER)), (2, 2, 0))

    def test_reject_invalid_winner_and_unknown_reason(self):
        for team in (0, 3, -1, True, 1.0, "1"):
            with self.subTest(team=team), self.assertRaises(ValueError):
                match_end.build_match_result(team)
        for reason in (1, 3, None, True, "0"):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                match_end.build_match_result(1, reason)

    def test_killer_is_preserved_in_death_message(self):
        self.assertEqual(struct.unpack(">II6s", match_end.build_structure_death(3766, 1515)),
                         (3766, 1515, bytes(6)))
        for eid in (-1, 0x100000000, True, 1.5):
            with self.subTest(eid=eid), self.assertRaises(ValueError):
                match_end.build_structure_death(eid, 1515)


@unittest.skipUnless(NATURAL_CACHE.is_file(), "external natural-ending corpus unavailable")
class TestNaturalEndingCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This is the operator's local decode cache, never downloaded test data.
        with NATURAL_CACHE.open("rb") as source:
            cls.frames, cls.locations = pickle.load(source)

    def test_crystal_identity_and_lethal_sequence(self):
        op, snapshot = self.frames[113463]
        self.assertEqual(op, 1010)
        self.assertEqual(struct.unpack_from(">I", snapshot, 8)[0], 3766)
        self.assertAlmostEqual(struct.unpack_from(">f", snapshot, 12)[0], 76.12, places=4)
        hp, max_hp = struct.unpack_from(">ff", snapshot, 36)
        self.assertGreater(hp, 0)
        self.assertEqual(max_hp, 10000)
        damage = sum(struct.unpack_from(">f", payload, 8)[0]
                     for opcode, payload in self.frames[113464:114026]
                     if opcode == 1054 and struct.unpack_from(">I", payload)[0] == 3766)
        self.assertLessEqual(hp + damage, 0)
        self.assertEqual(self.frames[114029],
                         (match_end.OP_CRYSTAL_DESTROYED, match_end.build_crystal_destroyed()))
        self.assertEqual(self.frames[114043],
                         (match_end.OP_STRUCTURE_DEATH, match_end.build_structure_death(3766, 1515)))
        self.assertEqual(self.locations[114025], ("74", 693))

    def test_all_five_turrets_and_crystal_remain_world_entities(self):
        deaths = ((51816, 3761, 14098), (78237, 3762, 21647),
                  (82993, 3763, 1515), (109584, 3764, 1515),
                  (87539, 3765, 23565), (114043, 3766, 1515))
        for index, victim, killer in deaths:
            self.assertEqual(self.frames[index], (match_end.OP_STRUCTURE_DEATH,
                match_end.build_structure_death(victim, killer)))
        victims = {victim for _, victim, _ in deaths}
        for op, payload in self.frames:
            if op in (1035, 1073, 1068):
                self.assertNotIn(struct.unpack_from(">I", payload)[0], victims)
            if op == 1054:
                victim, killer, damage = struct.unpack_from(">IIf", payload)
                self.assertFalse(victim in victims and victim == killer and damage <= -10000)
        for victim in victims - {3766}:
            snapshots = [payload for op, payload in self.frames if op == 1010
                         and struct.unpack_from(">I", payload, 8)[0] == victim]
            self.assertEqual(struct.unpack_from(">f", snapshots[-1], 36)[0], 0)

    def test_winner_follows_statistics_after_natural_crystal_death(self):
        self.assertEqual(self.frames[114823][0], 1165)
        self.assertEqual(len(self.frames[114823][1]), 1614)
        self.assertEqual(self.frames[114824],
                         (match_end.OP_MATCH_RESULT, match_end.build_match_result(1)))


@unittest.skipUnless(SURRENDER_CACHE.is_file(), "external surrender corpus unavailable")
class TestSurrenderCorpus(unittest.TestCase):
    def test_surrender_has_distinct_reason(self):
        with SURRENDER_CACHE.open("rb") as source:
            frames = pickle.load(source)
        self.assertEqual(frames[32625], (match_end.OP_MATCH_RESULT,
            match_end.build_match_result(2, match_end.MatchEndReason.SURRENDER)))


@unittest.skipUnless(NATURAL_FINAL_CHUNK.is_file(), "external VGR timing unavailable")
class TestNaturalEndingTiming(unittest.TestCase):
    def test_immediate_crystal_notice_then_six_second_result_delay(self):
        from server.decode import walk_vgr
        frames, stats = walk_vgr(NATURAL_FINAL_CHUNK)
        self.assertEqual(stats["failures"], 0)
        self.assertEqual(stats["trailing"], 0)
        self.assertEqual([frames[row][1] for row in (693, 697, 711, 1491, 1492)],
                         [1054, 1106, 1072, 1165, 1009])
        self.assertEqual(frames[693][0], frames[697][0])
        self.assertEqual(frames[693][0], frames[711][0])
        seconds = lambda row: struct.unpack(">f", struct.pack(">I", frames[row][0]))[0]
        self.assertAlmostEqual(seconds(1492) - seconds(693),
                               match_end.DESTRUCTION_DELAY_SECONDS, delta=.03)


if __name__ == "__main__":
    unittest.main()
