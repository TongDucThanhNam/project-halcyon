"""Roster + join-completion encoders — unit tests against corpus-pinned shapes.

Every expected offset/size here was derived from the 2026-09-06 match-1
corpus decode (vgfull.pcap / c2s.bin, uuid b9f511e0-…); the integration
side re-checks the same shapes against the corpus itself in test_corpus.
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import roster

MATCH_ID = "00000000-1111-4222-8333-444455556666"
SESSION_UUID = "ea4c7fda-4b61-481d-abb7-1c757d24ae58"

# Live client Amael selection; also present in the corpus.
CORPUS_1118 = bytes.fromhex("0000039d2fd7245d") + bytes(6)


def _players():
    return roster.default_solo_bots(SESSION_UUID, MATCH_ID)


class TestRosterIdentity(unittest.TestCase):
    def test_local_player_binds_the_session_uuid(self):
        ps = _players()
        self.assertEqual(ps[0].uuid, SESSION_UUID)      # identity binding
        self.assertFalse(ps[0].is_bot)
        for p in ps[1:]:
            self.assertEqual(p.uuid, roster.BOT_UUID_SENTINEL)
            self.assertTrue(p.is_bot)

    def test_solo_bots_teams_and_hero_eids(self):
        ps = _players()
        self.assertEqual([p.team for p in ps], [1, 1, 1, 2, 2, 2])
        self.assertEqual([p.eid for p in ps], [1500, 1515, 1516, 1517, 1518, 1519])
        self.assertEqual([p.handle for p in ps],
                         ["Guest", "Alpha Bot", "Beta Bot", "Gamma Bot",
                          "Delta Bot", "Epsilon Bot"])

    def test_all_slots_start_unpicked_in_every_match(self):
        for match_id in (MATCH_ID, "other-match"):
            ps = roster.default_solo_bots(SESSION_UUID, match_id)
            self.assertEqual([p.hero_id for p in ps], [0xffff] * 6)
            self.assertEqual([p.selection_hash for p in ps],
                             [0] + [roster.SNAPSHOT_EMPTY_TOKEN] * 5)



class TestSnapshot1113(unittest.TestCase):
    def test_payload_size_and_header(self):
        snap = roster.build_snapshot(_players(), countdown=(7.0, 7.0))
        self.assertEqual(len(snap), roster.SNAPSHOT_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">ff", snap, 0), (7.0, 7.0))
        self.assertEqual(snap[8:10], b"\x01\x00")
        self.assertEqual(struct.unpack_from(">H", snap, 10)[0], 0)
        self.assertEqual(snap[12:16], b"\xff\xff\xff\x00")

    def test_record_fields_at_verified_offsets(self):
        snap = roster.build_snapshot(_players())
        for k, p in enumerate(_players()):
            rec = snap[8 + k * 161:8 + (k + 1) * 161]
            self.assertEqual(rec[:2], bytes([1, k]))
            self.assertEqual(rec[8], p.team)
            self.assertEqual(struct.unpack_from(">HHI", rec, 9),
                             (p.hero_id, p.eid, p.selection_hash))
            self.assertEqual(rec[17:97].split(b"\0")[0].decode(), p.handle)
            self.assertEqual(rec[97:161].split(b"\0")[0].decode(), p.uuid)
            self.assertEqual(rec[2:4], bytes(2))
            self.assertEqual(rec[4:8], b"\xff\xff\xff\x00")

    def test_empty_slots_and_padding(self):
        snap = roster.build_snapshot(_players())
        for k in range(6, 16):
            rec = snap[8 + k * 161:8 + (k + 1) * 161]
            self.assertEqual(rec[:2], bytes([0, k]))
            self.assertEqual(rec[4:8], b"\xff\xff\xff\x00")
            self.assertEqual(struct.unpack_from(">HHI", rec, 9),
                             (0xffff, 0xffff, roster.SNAPSHOT_EMPTY_TOKEN))
        self.assertEqual(snap[-6:], bytes(6))

    def test_long_local_identity_is_preserved(self):
        players = roster.default_solo_bots("x" * 62, MATCH_ID)
        snap = roster.build_snapshot(players)
        self.assertEqual(snap[105:169], b"x" * 62 + bytes(2))

    def test_pick_flags_carried(self):
        snap = roster.build_snapshot(_players(), pick_flags=0x0000)
        self.assertEqual(snap[10:12], b"\x00\x00")
        self.assertEqual(struct.unpack_from(">H", snap, 8 + 2)[0], 0x0000)


class TestPlayerInfo1006(unittest.TestCase):
    def test_size_and_identity_fields(self):
        p = _players()[0]
        payload = roster.build_player_info(p, MATCH_ID)
        self.assertEqual(len(payload), roster.PLAYER_INFO_PAYLOAD_SIZE)
        self.assertEqual(payload[0:5], b"Guest")
        self.assertEqual(payload[64:100].decode(), SESSION_UUID)
        self.assertEqual(struct.unpack_from(">I", payload, 160)[0], 1500)
        self.assertEqual(struct.unpack_from(">I", payload, 164)[0], p.hero_id)
        self.assertEqual(struct.unpack_from(">I", payload, 172)[0],
                         roster.PLAYER_INFO_CONST)

    def test_committed_selection_hash_at_168(self):
        """+168 is the committed selection hash u32 (the 'XP f32' reading was
        the same bytes misread; corpus 1006 carries 4260123e there)."""
        p = roster.Player("Guest", 1, 1500, 925, 0x4260123E, SESSION_UUID, False)
        payload = roster.build_player_info(p, MATCH_ID)
        self.assertEqual(struct.unpack_from(">I", payload, 168)[0], 0x4260123E)

    def test_local_tail_union(self):
        """Corpus local tail: 7×FNV("") | ff ff 00 ff | 00 02 01 00 | 00 00 00 01."""
        local = roster.build_player_info(_players()[0], MATCH_ID)
        for k in range(7):   # ability slots unpicked
            self.assertEqual(struct.unpack_from(">I", local, 176 + 4 * k)[0],
                             roster.FNVL_EMPTY)
        self.assertEqual(local[204:208], b"\xff\xff\x00\xff")
        self.assertEqual(local[208:212], b"\x00\x02\x01\x00")
        self.assertEqual(local[212:216], b"\x00\x00\x00\x01")
        self.assertEqual(local[216:], bytes(6))

    def test_bot_tail_union(self):
        """Corpus bot tail: guid 16 B @+180, f1dedae3 @+200, ff ff ff ff,
        00 02 0<team> 00, 01 00 00 00."""
        bot = roster.build_player_info(_players()[1], MATCH_ID)
        self.assertEqual(struct.unpack_from(">I", bot, 176)[0], 0)
        self.assertEqual(len(bot[180:196]), 16)
        self.assertEqual(bot[180:196],
                         roster.build_player_info(_players()[2], MATCH_ID)[180:196])
        self.assertEqual(struct.unpack_from(">I", bot, 200)[0], roster.BOT_CFG_CONST)
        self.assertEqual(bot[204:208], b"\xff\xff\xff\xff")
        self.assertEqual(bot[208:212], b"\x00\x02\x01\x00")
        self.assertEqual(bot[212:216], b"\x01\x00\x00\x00")
        gamma = roster.build_player_info(_players()[3], MATCH_ID)
        self.assertEqual(gamma[210], 2)          # team byte at +210
        self.assertEqual(bot[210], 1)


class TestJoinHandshakes(unittest.TestCase):
    def test_1118_hero_selection_matches_observed_pair(self):
        p = roster.Player("Guest", 1, 1500, 925, 0x2FD7245D, SESSION_UUID, False)
        self.assertEqual(roster.build_hero_selection(p), CORPUS_1118)

    def test_selection_parser_rejects_invalid_shape_and_reserved_id(self):
        self.assertEqual(roster.parse_hero_selection(CORPUS_1118), (925, 0x2fd7245d))
        for payload in (b"", CORPUS_1118[:-1], CORPUS_1118 + b"x",
                        struct.pack(">II", 65535, 0) + bytes(6),
                        struct.pack(">II", 65536, 0) + bytes(6),
                        CORPUS_1118[:-1] + b"x"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                roster.parse_hero_selection(payload)

    def test_hero_block_header(self):
        p = _players()[3]
        block = roster.build_hero_block(p)
        self.assertEqual(len(block), roster.HERO_BLOCK_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">I", block, 0)[0], p.hero_id)
        self.assertEqual(struct.unpack_from(">I", block, 4)[0], p.selection_hash)
        self.assertEqual(struct.unpack_from(">I", block, 8)[0], p.eid)
        self.assertEqual(struct.unpack_from(">I", block, 12)[0], p.team)
        self.assertEqual(block[16:18], b"\xff\xff")
        self.assertEqual(block[741:745], b"\xff\xff\xff\xff")
        self.assertEqual(block[745], p.slot)         # corpus: slot 5 → 05

    def test_unmeasured_hero_gets_donor_stat_run(self):
        # Live evidence 2026-09-07: a zeroed stat run renders the hero but
        # the client never enters its walk animation (glide, hero id 265).
        # Unmeasured heroes reuse the measured donor run — no invented bytes.
        donor = roster.HERO_INIT_DATA[roster.HERO_INIT_DONOR_ID]
        data, donated = roster.hero_init_for(265)          # unmeasured id
        self.assertTrue(donated)
        self.assertEqual(data, donor)
        data, donated = roster.hero_init_for(244)          # measured hero
        self.assertFalse(donated)
        p = roster.Player("Guest", 1, 1500, 265, 0x34BD643E, SESSION_UUID,
                          False)
        block = roster.build_hero_block(p)
        off, hexbytes = next(iter(donor["runs"].items()))
        raw = bytes.fromhex(hexbytes)
        self.assertEqual(block[off:off + len(raw)], raw)   # donor run patched

    def test_corpus_sweep_entries_shape(self):
        # 2026-09-07: the capture corpus re-walk (vg3/vgc2s/vg5_final) added
        # 8 more measured heroes. Every entry must carry non-empty runs, the
        # per-hero 601 content GUID (stable across matches), and either a
        # 7-pair timer list or None (init burst not captured — donor timers).
        for hid in (245, 253, 257, 258, 268, 279, 429, 915):
            entry = roster.HERO_INIT_DATA[hid]
            self.assertTrue(entry["runs"], hid)
            self.assertIn(601, entry["runs"], hid)
            self.assertEqual(len(bytes.fromhex(entry["runs"][601])), 12, hid)
            self.assertTrue(entry["timers"] is None
                            or len(entry["timers"]) == 7, hid)
        # heroes measured in several captures keep the same 601 GUID
        self.assertEqual(roster.HERO_INIT_DATA[924]["runs"][601],
                         "820dd5b366bfd50a09d11ecf")
        self.assertEqual(roster.HERO_INIT_DATA[925]["runs"][601],
                         "1e3304fc948685f56c371076")

    def test_uncaptured_timers_entry_present(self):
        # hero 258 has measured runs but its capture started after the 1162
        # init burst — the entry exists with timers=None (donor timers are
        # substituted by the server, see match_server._dump_world_to).
        data, donated = roster.hero_init_for(258)
        self.assertFalse(donated)
        self.assertIsNone(data["timers"])
        self.assertIn(601, data["runs"])


class TestLockCommitAndWorldInit(unittest.TestCase):
    """Corpus post-lock shapes (match-1 ACK-precise trace, 2026-09-06)."""

    def test_commit_lock_assigns_bots_and_locks_every_slot(self):
        players = _players()
        players[0].hero_id = 925                     # the client's 1118 selection
        roster.commit_lock(players, 0x4260123E)
        self.assertEqual(players[0].selection_hash, 0x4260123E)
        self.assertEqual(players[0].hero_id, 925)    # commit keeps the choice
        self.assertEqual([p.pick_flags for p in players],
                         [roster.PICK_FLAG_LOCKED] * 6)
        self.assertEqual([p.hero_id for p in players[1:]],
                         [h for h, _ in roster.BOT_HERO_CHOICES])
        self.assertEqual([p.selection_hash for p in players[1:]],
                         [h for _, h in roster.BOT_HERO_CHOICES])
        snap = roster.build_snapshot(players, countdown=(7.0, 7.0))
        for k in range(6):
            base = roster.SNAPSHOT_RECORD_BASE + k * roster.SNAPSHOT_RECORD_STRIDE
            self.assertEqual(struct.unpack_from(">H", snap, base + 2)[0],
                             roster.PICK_FLAG_LOCKED)
            self.assertNotEqual(struct.unpack_from(">H", snap, base + 9)[0], 0xffff)

    def test_1119_commit_hash_round_trip(self):
        payload = struct.pack(">I", 0x4260123E) + bytes(2)
        self.assertEqual(roster.parse_commit_hash(payload), 0x4260123E)
        self.assertEqual(roster.build_commit_ack(0x4260123E), payload)
        for bad in (b"", payload + b"\x00", bytes(5), bytes(7)):
            with self.subTest(payload=bad), self.assertRaises(ValueError):
                roster.parse_commit_hash(bad)

    def test_zero_ack_and_hero_ready_ack(self):
        self.assertEqual(roster.build_zero_ack(), bytes(6))
        self.assertEqual(roster.build_hero_ready_ack(1500),
                         bytes.fromhex("000005dc0100"))

    def test_player_tag_shape(self):
        p = _players()[0]
        tag = roster.build_player_tag(p, MATCH_ID)
        self.assertEqual(len(tag), roster.PLAYER_TAG_PAYLOAD_SIZE)
        self.assertEqual(tag, roster.build_player_tag(p, MATCH_ID))   # deterministic
        self.assertEqual(tag[4:], bytes(10))

    def test_slot_flags_ping_layout(self):
        players = _players()
        body = roster.build_slot_flags(players)
        self.assertEqual(len(body), roster.SLOT_FLAGS_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">IH", body, 0), (1500, roster.PICK_FLAG_SELECTED))
        self.assertEqual(struct.unpack_from(">IH", body, 6), (1515, roster.PICK_FLAG_LOCKED))
        for k in range(6, 16):                   # empty half of the 16-slot table
            self.assertEqual(body[k * 6:(k + 1) * 6], bytes(6))

    def test_mode_frames(self):
        self.assertEqual(roster.build_mode_name()[:22], b"*GameMode_HF_SoloBots*")
        self.assertEqual(len(roster.build_mode_name()), 70)
        gm = roster.build_game_mode()
        self.assertEqual(gm[:4], b"\x00\x00\x00\x00")       # 1108 has the u32
        self.assertEqual(gm[4:26], b"*GameMode_HF_SoloBots*")
        self.assertEqual(len(gm), 70)

    def test_game_setup_field_map(self):
        setup = roster.build_game_setup()
        self.assertEqual(len(setup), roster.GAME_SETUP_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">I", setup, 0)[0], 1500)
        self.assertEqual(struct.unpack_from(">I", setup, 4)[0], 1)
        self.assertEqual(setup[10:12], b"\xff\xff")
        self.assertEqual(setup[16:18], b"\x03\x03")
        self.assertEqual(setup[32:54], b"*GameMode_HF_SoloBots*")
        self.assertEqual(struct.unpack_from(">f", setup, 96)[0], 1.0)
        self.assertEqual(setup[100:102], b"\x01\x00")

    def test_timer_tick_shape(self):
        tick = roster.build_timer_tick(1519, 0x1234ABCD, 5.0)
        self.assertEqual(len(tick), roster.TIMER_TICK_PAYLOAD_SIZE)
        eid, tag, pad, value = struct.unpack_from(">IIHf", tick, 0)
        self.assertEqual((eid, tag, pad, value), (1519, 0x1234ABCD, 0, 5.0))


class TestMovementSlice(unittest.TestCase):
    """1070 position / 1012 move — layouts measured on corpus hero 0x5dc."""

    def test_1070_matches_corpus_hero_frame(self):
        # first 1070 of hero 0x5dc after its first 1012 (vgfull.pcap match 1)
        corpus = bytes.fromhex("000005dcc29c5c293f6147ae0000")
        self.assertEqual(len(corpus), roster.POSITION_PAYLOAD_SIZE)
        eid, x, y, pad = struct.unpack(">IffH", corpus)
        self.assertEqual((eid, pad), (1500, 0))
        self.assertEqual((x, y), (roster.SPAWN_X, roster.SPAWN_Y))
        self.assertEqual(roster.build_position(1500, x, y), corpus)

    def test_parse_move_round_trip(self):
        payload = struct.pack(">ff", -75.238, -2.667) + bytes(6)
        x, y = roster.parse_move(payload)
        self.assertEqual((x, y), struct.unpack(">ff", struct.pack(">ff", -75.238, -2.667)))

    def test_parse_move_rejects_bad_payloads(self):
        for bad in (b"", bytes(13), bytes(15),
                    bytes.fromhex("c29679bcc02aa978") + b"" * 6):
            with self.assertRaises(ValueError):
                roster.parse_move(bad)


class TestEntityFullUpdate1010(unittest.TestCase):
    """1010 layout — measured on all 173 corpus frames (match 1, 126 B).

    The proven-field expectations below are corpus frame 1 (eid 0x173,
    tick 3539, first burst at +6.43 s). The corpus never sends 1010 for a
    hero, so the [Open]-marked template fields (+4 class id, +88..95,
    +112..115, +119..121) assert our documented defaults, not corpus bytes.
    """

    # corpus-proven fragments of frame 1 (layout proof only — no full-frame
    # payload is pinned, per the repo's no-raw-payload rule)
    CORPUS_EID = 0x173
    CORPUS_TICK = 3539                      # 00 00 0d d3
    CORPUS_X = struct.unpack(">f", bytes.fromhex("41887ae1"))[0]
    CORPUS_Y = struct.unpack(">f", bytes.fromhex("3ff70a3d"))[0]
    # corpus west-facing pair: bf 7f ff ff (= −0.99999, not −1.0) / 0.0
    FACING_WEST = (struct.unpack(">f", bytes.fromhex("bf7fffff"))[0], 0.0)

    def setUp(self):
        self.body = roster.build_entity_full_update(
            self.CORPUS_EID, self.CORPUS_TICK, self.CORPUS_X, self.CORPUS_Y,
            seq=6, facing=self.FACING_WEST)

    def test_size_and_proven_fields_match_corpus_frame(self):
        self.assertEqual(len(self.body), roster.ENTITY_FULL_UPDATE_PAYLOAD_SIZE)
        self.assertEqual(self.body[0:4], b"\x00\x00\x01\x73")       # eid
        self.assertEqual(self.body[4:8], bytes(4))                  # class id [Open]
        self.assertEqual(self.body[8:12], b"\x00\x00\x0d\xd3")      # tick
        self.assertEqual(self.body[12:24].hex(),
                         "41887ae1" + "3be7a8f8" + "3ff70a3d")      # x z y
        self.assertEqual(struct.unpack_from(">f", self.body, 16)[0],
                         roster.GROUND_Z)
        self.assertEqual(self.body[24:28], b"\xbf\x7f\xff\xff")     # facing cos
        self.assertEqual(self.body[28:32], bytes(4))                # always 0
        self.assertEqual(struct.unpack_from(">f", self.body, 32)[0], 0.0)  # sin
        self.assertEqual(self.body[36:88], bytes(52))               # proven zero
        self.assertEqual(self.body[117], 0x01)                      # 173/173
        self.assertEqual(self.body[118], 0x00)                      # 173/173

    def test_open_template_fields_carry_the_documented_defaults(self):
        self.assertEqual(self.body[88:96], b"\x01" * 8)
        self.assertEqual(self.body[96:112], bytes(16))
        self.assertEqual(self.body[112:116], b"\xff\xff\xff\xff")
        self.assertEqual(self.body[116], 6)                          # seq u8
        self.assertEqual(self.body[119:122], b"\x01\x01\x02")
        self.assertEqual(self.body[122:126], bytes(4))

    def test_hp_variant_matches_match5_122b_layout(self):
        """Match-5 HP variant: 122 B, +36 f32 current HP, +40 f32 maxHP
        (corpus histogram: turret tiers 5000/3000, minion 450); the tail
        template asserts our measured jungle-minion-class choice [Open]."""
        body = roster.build_entity_full_update(0x13b, 3871, -88.75, 2.0,
                                               seq=0x20, hp=(450.0, 450.0))
        self.assertEqual(len(body), roster.ENTITY_FULL_UPDATE_HP_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">ff", body, 36), (450.0, 450.0))
        self.assertEqual(struct.unpack_from(">f", body, 16)[0], roster.GROUND_Z)
        self.assertEqual(body[88:96], b"\x01" * 8)
        self.assertEqual(body[96:104], bytes.fromhex("030f030303030303"))
        self.assertEqual(body[112:116], b"\xff\xff\xff\xff")
        self.assertEqual(body[116], 0x20)
        self.assertEqual(body[119:122], b"\x01\xff\x01")
        self.assertEqual(len(body), roster.ENTITY_FULL_UPDATE_PAYLOAD_SIZE - 4)

    def test_hp_variant_rejects_bad_shape(self):
        with self.assertRaises(ValueError):
            roster.build_entity_full_update(1, 1, 0.0, 0.0, seq=0, hp=(1.0,))

    def test_tick_passthrough_and_seq_wrap(self):
        body = roster.build_entity_full_update(1500, 0x12345678, 0.0, 0.0,
                                               seq=0x105)
        self.assertEqual(struct.unpack_from(">I", body, 8)[0], 0x12345678)
        self.assertEqual(body[116], 0x05)
        ticks = [struct.unpack_from(">I", roster.build_entity_full_update(
            1500, t, 0.0, 0.0, seq=t), 8)[0] for t in (1, 2, 7)]
        self.assertEqual(ticks, sorted(ticks))                       # monotonic

    def test_position_fields_agree_with_1070_repack(self):
        x, y = -78.18000030517578, 0.8799999952316284
        body = roster.build_entity_full_update(1500, 1, x, y, seq=1)
        pos = roster.build_position(1500, x, y)
        self.assertEqual(body[12:16], pos[4:8])              # x f32 identical
        self.assertEqual(body[20:24], pos[8:12])             # y f32 identical

    def test_facing_toward_is_unit_and_defaults_when_stationary(self):
        cos, sin = roster.facing_toward(0.0, 0.0, 3.0, 4.0)
        self.assertAlmostEqual((cos * cos + sin * sin) ** 0.5, 1.0)
        self.assertAlmostEqual(cos, 0.6)
        self.assertAlmostEqual(sin, 0.8)
        self.assertEqual(roster.facing_toward(1.0, 1.0, 1.0, 1.0),
                         roster.FACING_DEFAULT)
        self.assertEqual(roster.FACING_DEFAULT, (0.0, 1.0))          # corpus idle


if __name__ == "__main__":
    unittest.main()
