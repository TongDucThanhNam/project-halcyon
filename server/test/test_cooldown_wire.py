"""1162 grammar, exact native identity, and external replay evidence guards."""
import math
import pickle
import re
import struct
import unittest

from server.paths import research_dir
from server import cooldown_wire as timers
from server import economy

CORPUS_ROOT = research_dir('vg_max')
CORPUS_FILES = ("m2frames.pkl", "m3frames.pkl", "m4frames.pkl", "vgr5frames.pkl")


def recorded_frames():
    # These are operator-owned, already decoded local caches; no wire payload is
    # distributed in the repository. Different historical inspectors used three
    # cache container shapes, but they all retain the same semantic payload.
    for name in CORPUS_FILES:
        with (CORPUS_ROOT / name).open("rb") as source:
            rows = pickle.load(source)
        for index, row in enumerate(rows):
            if isinstance(row, bytes):
                opcode, body = int.from_bytes(row[:2], "big"), row[2:]
            elif len(row) == 4:
                _, _, opcode, body = row
            else:
                opcode, body = row
            yield name, index, opcode, body


def recorded_timers():
    for name, index, opcode, body in recorded_frames():
        if opcode == 1162:
            yield name, index, body


class TestTimerGrammar(unittest.TestCase):
    def test_fractional_remaining_and_full_duration_have_distinct_aligned_fields(self):
        encoded = timers.build_item_timer(1500, timers.ITEM_TAGS["fountain_of_renewal"], 12.25, 75.0)
        self.assertEqual(len(encoded), 22)
        self.assertEqual(struct.unpack_from(">IIff", encoded), (1500, 0x6F056481, 12.25, 75.0))
        self.assertEqual(encoded[16:], bytes((0, 1, 2, 0, 0, 0)))

    def test_ordinary_and_ultimate_learning_readiness_states(self):
        for ultimate in (False, True):
            for learned in (False, True):
                for remaining in (0.0, 3.5):
                    encoded = timers.build_ability_timer(1500, 0x4D70217F, remaining, 10.0,
                                                          ultimate=ultimate, learned=learned)
                    state = timers.parse_timer_tick(encoded).state
                    self.assertEqual(state, bytes((int(learned and remaining == 0), int(learned),
                                                   1, int(ultimate), 1, 0)))

    def test_invalid_cooldown_values_and_lengths_are_rejected(self):
        for bad in (-1.0, math.inf, -math.inf, math.nan):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    timers.build_item_timer(1500, 1, bad, 75.0)
                with self.assertRaises(ValueError):
                    timers.parse_timer_tick(struct.pack(">IIff6s", 1500, 1, 0, bad, bytes(6)))
        for length in (0, 21, 23):
            with self.assertRaises(ValueError):
                timers.parse_timer_tick(bytes(length))

    def test_native_symbols_match_measured_tags_and_display_names_are_not_accepted(self):
        known = {"Ability__Withdraw": 0x022982B5, "Ability__Emote_Taunt": 0xB855D752,
                 "Ability__Emote_Dance": 0x1E275DC1, "Ability__Phinn__A": 0x4D70217F,
                 "Ability__Phinn__B": 0x4E702312, "Ability__Phinn__C": 0x4F7024A5,
                 "Ability__Item__UpgradedReflexBlock": 0x7DF46CAD}
        for symbol, expected in known.items():
            self.assertEqual(timers.native_ability_tag(symbol), expected)
        for invalid in ("Reflex Block", "*Ability__Withdraw*", "Ability__Phinn__A*"):
            with self.assertRaises(ValueError):
                timers.native_ability_tag(invalid)

    def test_catalog_uses_measured_cooldowns_and_native_metadata_tags(self):
        for key, duration in timers.MEASURED_ITEM_COOLDOWNS.items():
            if key in economy.ITEMS_BY_KEY:
                self.assertEqual(economy.ITEMS_BY_KEY[key].cooldown, duration)
        for key in ("sprint_boots", "travel_boots", "halcyon_chargers", "aegis", "atlas_pauldron"):
            self.assertEqual(economy.ITEMS_BY_KEY[key].cooldown_tag, timers.ITEM_TAGS[key])

    def test_both_native_base_shops_accept_own_team_and_reject_opponent(self):
        from server.hero_movement import HeroMovement
        for team, (x, y) in economy.BASE_SHOP_POSITIONS.items():
            self.assertTrue(economy.can_shop(HeroMovement(team=team, x=x, y=y)))
            self.assertFalse(economy.can_shop(HeroMovement(team=3 - team, x=x, y=y)))

    def test_uncaptured_ringo_gets_native_unlearned_abilities_without_donor_identities(self):
        ticks = [timers.parse_timer_tick(body) for body in timers.build_initial_timers(1500, 243)]
        self.assertEqual([tick.tag for tick in ticks[3:]], [0xCAD52059, 0xC9D51EC6, 0xC8D51D33])
        self.assertTrue(all(tick.remaining == tick.duration == 0 for tick in ticks[3:]))
        self.assertEqual([tick.state[3] for tick in ticks[3:]], [1, 0, 0])
        self.assertTrue(all(tick.state[:2] == bytes(2) for tick in ticks[3:]))
        unknown = timers.build_initial_timers(1500, 0xFFFF)
        self.assertEqual(len(unknown), 3)  # only independently known shared identities


@unittest.skipUnless(all((CORPUS_ROOT / name).is_file() for name in CORPUS_FILES),
                     "external decoded replay caches unavailable")
class TestExternalCooldownCorpus(unittest.TestCase):
    def test_complete_initial_bursts_for_all_16_recorded_heroes_match_the_corpus(self):
        first = {}
        pending = None
        for _, _, opcode, body in recorded_frames():
            if opcode in (1010, 1011):
                pending = None
            if opcode == 1011:
                hero_id, _, eid = struct.unpack_from(">III", body)
                if hero_id in timers.MEASURED_INITIAL_TIMERS and hero_id not in first:
                    first[hero_id] = (eid, [])
                    pending = hero_id
            if opcode == 1162 and pending is not None:
                eid, payloads = first[pending]
                if int.from_bytes(body[:4], "big") == eid:
                    payloads.append(body)
        self.assertEqual(set(first), set(timers.MEASURED_INITIAL_TIMERS))
        self.assertEqual({hero_id: len(rows) for hero_id, (_, rows) in first.items()},
                         {244: 8, 245: 8, 253: 8, 254: 7, 257: 7, 258: 7, 267: 7,
                          268: 9, 269: 7, 279: 7, 396: 7, 399: 7, 429: 7, 915: 8, 924: 7, 925: 8})
        for hero_id, (eid, payloads) in first.items():
            self.assertEqual(timers.build_initial_timers(eid, hero_id), payloads, hero_id)

    def test_all_8650_cached_records_roundtrip_or_identify_the_known_damaged_record(self):
        valid, corrupt = 0, []
        for name, index, body in recorded_timers():
            try:
                timer = timers.parse_timer_tick(body)
            except ValueError:
                corrupt.append((name, index, *struct.unpack_from(">II", body)))
                continue
            self.assertEqual(timer.encode(), body, (name, index))
            valid += 1
        self.assertEqual(valid, 8649)
        # Existing m4 cache row has a damaged tag, a negative 1e26 duration and
        # random state bytes. It is evidence corruption, never an emitted timer.
        self.assertEqual(corrupt, [("m4frames.pkl", 401, 1516, 0xD60C0797)])

    def test_all_measured_item_durations_and_readiness_agree_with_live_snapshot_fields(self):
        by_tag = {timers.ITEM_TAGS[key]: key for key in timers.MEASURED_ITEM_COOLDOWNS}
        counts = {key: 0 for key in timers.MEASURED_ITEM_COOLDOWNS}
        cooling = set()
        for _, _, body in recorded_timers():
            tag = int.from_bytes(body[4:8], "big")
            if tag not in by_tag:
                continue
            timer = timers.parse_timer_tick(body)
            key = by_tag[tag]
            self.assertEqual(timer.duration, timers.MEASURED_ITEM_COOLDOWNS[key])
            self.assertLessEqual(timer.remaining, timer.duration)
            self.assertEqual(timer.state[0], int(timer.remaining == 0))
            self.assertEqual(timer.state[2:], bytes((2, 0, 0, 0)))
            counts[key] += 1
            if timer.remaining > 0:
                cooling.add(key)
        self.assertEqual(counts, {"sprint_boots": 254, "travel_boots": 168,
                                 "fountain_of_renewal": 80, "reflex_block": 18,
                                 "crucible": 8, "healing_flask": 816, "vision_totem": 816})
        self.assertTrue({"fountain_of_renewal", "reflex_block", "travel_boots"} <= cooling)

    def test_requested_item_ability_symbols_are_in_their_actual_native_metadata(self):
        names = {"sprint_boots": "SprintBoots", "travel_boots": "TravelBoots",
                 "halcyon_chargers": "HalcyonChargers", "fountain_of_renewal": "FountainOfRenewal",
                 "reflex_block": "ReflexBlock", "crucible": "Crucible", "aegis": "Aegis",
                 "atlas_pauldron": "AtlasPauldron", "healing_flask": "HealingFlask",
                 "vision_totem": "VisionTotem"}
        for key, native_name in names.items():
            path = CORPUS_ROOT / "inst_dump" / f"Item_{native_name}.last.inst.bin"
            if not path.is_file():
                self.skipTest(f"external metadata unavailable: {native_name}")
            # Definitions are bare names; referenced abilities use *name*.
            symbols = re.findall(rb"\*?(Ability__[A-Za-z0-9_]+)\*?\0", path.read_bytes())
            self.assertEqual(symbols, [timers.ITEM_ABILITY_SYMBOLS[key].encode("ascii")], native_name)

    def test_fallback_hero_ability_names_are_verified_against_native_metadata(self):
        for hero_id, name in timers.VERIFIED_HERO_ABILITY_NAMES.items():
            path = CORPUS_ROOT / "inst_dump" / f"{name}.inst.bin"
            if not path.is_file():
                self.skipTest(f"external metadata unavailable: {name}")
            symbols = set(re.findall(rb"Ability__[A-Za-z0-9_]+", path.read_bytes()))
            for slot in "ABC":
                self.assertIn(f"Ability__{name}__{slot}".encode("ascii"), symbols, hero_id)


if __name__ == "__main__":
    unittest.main()
