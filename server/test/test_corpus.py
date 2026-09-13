"""Phase 0 acceptance 2 & 3 — corpus validation (integration).

Skipped automatically when the canonical private corpus is not present.
Its location is selected by server.paths; captured payloads stay outside Git.

  acceptance 2: decode vgfull.pcap with match b9f511e0-… → 32,640 frames,
                100 % coverage, and the exact §15.8 opcode histogram.
  acceptance 3: walk the 25-.vgr corpus → 31,266 frames, zero walk failures.
  roster:       the 2026-09-06 join-exchange decode — the shapes server/
                roster.py builds must match the captured bytes (1006/1113/
                1118 hero selection, snapshot record layout, c2s 1000).
"""
import collections
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.paths import research_dir
from server import decode, roster, wire

VG_MAX = str(research_dir('vg_max'))
VGFULL_PCAP = os.path.join(VG_MAX, "vgfull.pcap")
C2S_BIN = os.path.join(VG_MAX, "c2s.bin")
VGR_DIR = os.path.join(VG_MAX, "vgr", "vgrtmp")
MATCH_B9 = "b9f511e0-11cd-4cfa-ad62-dc8612b8d270"
CORPUS_SESSION_UUID = "ea4c7fda-4b61-481d-abb7-1c757d24ae58"

# §15.8 top-7 histogram for match b9f511e0 (decimal opcodes)
EXPECTED_TOP_OPS = [(1070, 5946), (1067, 5330), (1053, 5090),
                    (1086, 4390), (1016, 3546), (1054, 2104), (1045, 1799)]

_FRAMES_CACHE = None


def _cached_frames():
    """decode_pcap takes tens of seconds — run it once per test session."""
    global _FRAMES_CACHE
    if _FRAMES_CACHE is None:
        _FRAMES_CACHE = decode.decode_pcap(VGFULL_PCAP, MATCH_B9)
    return _FRAMES_CACHE


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), f"corpus missing: {VGFULL_PCAP}")
class TestPcapDecode(unittest.TestCase):
    def test_rebuilt_opener_and_initial_snapshot_match_all_corpus_bytes(self):
        """Regression: shape-only checks missed invented hero IDs and slot prefixes."""
        frames, _ = _cached_frames()
        for opcode, actual in ((1001, roster.build_game_setup()),
                               (1108, roster.build_game_mode())):
            self.assertEqual(actual, next(p for op, p in frames if op == opcode))
        expected = next(p for op, p in frames if op == 1113)
        players = roster.default_solo_bots(CORPUS_SESSION_UUID, MATCH_B9)
        # Display names are configurable; selection defaults and all slot bytes
        # must match independently, not be copied from the expected payload.
        for k, player in enumerate(players):
            base = roster.SNAPSHOT_RECORD_BASE + k * roster.SNAPSHOT_RECORD_STRIDE
            player.handle = expected[base + 17:base + 97].split(b"\0")[0].decode()
        self.assertEqual(roster.build_snapshot(players,
                         countdown=struct.unpack_from(">ff", expected)), expected)

    def test_vgfull_histogram_and_coverage(self):
        frames, info = _cached_frames()
        self.assertIsNotNone(frames, f"decode failed: {info}")
        self.assertEqual(info["nframes"], 32640)       # §15.3/§15.8
        self.assertEqual(info["cov"], 1.0)
        self.assertEqual(info["missed"], 0)
        hist = collections.Counter(op for op, _ in frames)
        self.assertEqual(hist.most_common(7), EXPECTED_TOP_OPS)

    def test_join_roster_shapes(self):
        """The Measured roster field relationships in the corpus."""
        frames, _ = _cached_frames()
        # s2c 1113[0]: 2590 B, record layout at the verified offsets
        snap = next(p for op, p in frames if op == 1113)
        self.assertEqual(len(snap), roster.SNAPSHOT_PAYLOAD_SIZE)
        self.assertEqual(snap[10:12], b"\x00\x00")     # pre-pick flags
        teams, eids = [], []
        for k in range(roster.SNAPSHOT_ROSTER_SIZE):
            rec = snap[16 + k * roster.SNAPSHOT_RECORD_STRIDE:]
            rec = rec[:roster.SNAPSHOT_RECORD_STRIDE]
            teams.append(rec[0])
            eids.append(struct.unpack_from(">H", rec, 3)[0])
            ident = rec[89:125].split(b"\x00", 1)[0].decode("ascii", "replace")
            self.assertEqual(ident,
                             CORPUS_SESSION_UUID if k == 0
                             else roster.BOT_UUID_SENTINEL)
        self.assertEqual(teams, [1, 1, 1, 2, 2, 2])    # team u8, 1-based
        self.assertEqual(eids, [1500, 1515, 1516, 1517, 1518, 1519])
        self.assertEqual(struct.unpack_from(">H", snap, 16 + 1)[0], 0xFFFF)  # unpicked hero
        # empty-slot marker (corpus: ff ff ff ff at +983, stride 161)
        self.assertEqual(snap[983:987], b"\xff\xff\xff\xff")
        self.assertEqual(struct.unpack_from(">I", snap, 987)[0],
                         roster.SNAPSHOT_EMPTY_TOKEN)

        # s2c 1118: acknowledgement of the hero selection, 6 B zero tail
        selection_frame = next(p for op, p in frames if op == 1118)
        self.assertEqual(len(selection_frame), 14)
        hero_id, selection_hash = struct.unpack_from(">II", selection_frame, 0)
        self.assertEqual(selection_frame[8:], bytes(6))
        # the selected hero ID also appears in local 1006 (+164)
        infos = [p for op, p in frames if op == 1006]
        self.assertEqual({len(p) for p in infos}, {roster.PLAYER_INFO_PAYLOAD_SIZE})
        local = next(p for p in infos
                     if p[64:100].decode("ascii", "replace") == CORPUS_SESSION_UUID)
        self.assertEqual(struct.unpack_from(">I", local, 164)[0], hero_id)
        self.assertEqual(struct.unpack_from(">I", local, 160)[0], 1500)
        self.assertEqual(local[0:5], b"Guest")

        # c2s 1000: the client presented the same session uuid (70 B payload)
        if os.path.isfile(C2S_BIN):
            with open(C2S_BIN, "rb") as fh:
                raw = fh.read()
            cipher = wire.MatchCipher(MATCH_B9)
            (ln,) = struct.unpack_from(">H", raw, 136)
            op, payload = wire.decode_body(cipher, raw[138:138 + ln])
            self.assertEqual(op, 1000)
            self.assertEqual(payload[:36].decode(), CORPUS_SESSION_UUID)
            self.assertEqual(payload[36:], bytes(len(payload) - 36))


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), f"corpus missing: {VGFULL_PCAP}")
class TestPostLockExchange(unittest.TestCase):
    """Byte-level checks of the post-lock sequence, match-1 ACK-precise trace
    (2026-09-06): 1123+1119 → echoes + all-locked countdown → 1006×6 + 1132 →
    (client 1134/1137) → world dump. No 1087 spawn batch is emitted yet."""

    def _frames(self):
        frames, info = _cached_frames()
        self.assertIsNotNone(frames, f"decode failed: {info}")
        return frames

    def _committed_players(self, last_snapshot):
        players = roster.default_solo_bots(CORPUS_SESSION_UUID, MATCH_B9)
        for k, player in enumerate(players):
            base = roster.SNAPSHOT_RECORD_BASE + k * roster.SNAPSHOT_RECORD_STRIDE
            player.handle = last_snapshot[base + 17:base + 97].split(b"\0")[0].decode()
        players[0].hero_id = struct.unpack_from(">H", last_snapshot, 17)[0]
        roster.commit_lock(players, struct.unpack_from(">I", last_snapshot, 21)[0])
        return players

    def test_lock_countdown_final_snapshot_matches_all_corpus_bytes(self):
        snaps = [p for op, p in self._frames() if op == 1113]
        last = snaps[-1]
        cd = struct.unpack_from(">ff", last)
        self.assertAlmostEqual(cd[1], 7.0, places=2)        # lock countdown pair
        players = self._committed_players(last)
        self.assertEqual(roster.build_snapshot(players, countdown=cd), last)

    def test_bot_choices_and_commit_hash_come_from_the_corpus(self):
        snaps = [p for op, p in self._frames() if op == 1113]
        last = snaps[-1]
        committed = struct.unpack_from(">I", last, 21)[0]
        for k, (hero_id, selection_hash) in enumerate(roster.BOT_HERO_CHOICES, start=1):
            base = roster.SNAPSHOT_RECORD_BASE + k * roster.SNAPSHOT_RECORD_STRIDE
            self.assertEqual(struct.unpack_from(">H", last, base + 9)[0], hero_id)
            self.assertEqual(struct.unpack_from(">I", last, base + 13)[0], selection_hash)
        # the local committed hash replaced the clicked one (1118: 2fd7245d)
        self.assertEqual(committed, 0x4260123E)

    def test_final_player_info_group(self):
        frames = self._frames()
        infos = [p for op, p in frames if op == 1006][:6]   # the final group
        last = [p for op, p in frames if op == 1113][-1]
        players = self._committed_players(last)
        for player, corpus in zip(players, infos):
            built = roster.build_player_info(player, MATCH_B9)
            self.assertEqual(len(built), len(corpus))
            # the bot instance guid (+180..196) is a shared corpus constant
            # with no known derivation — compared structurally only
            a = built[:180] + bytes(16) + built[196:]
            b = corpus[:180] + bytes(16) + corpus[196:]
            self.assertEqual(a, b, player.handle)

    def test_hero_block_headers_and_world_dump_order(self):
        frames = self._frames()
        ops = [op for op, _ in frames]
        i1132 = ops.index(1132)
        # finalization: 1006×6 immediately before 1132, after the last 1113
        self.assertEqual(ops[i1132 - 6:i1132], [1006] * 6)
        self.assertLess(ops.index(1113), i1132)
        # world dump: 1135 → 1006×6 → 1105 → 1011 + 1162×7 per hero reverse →
        # 1055×6 → 1134 echo → 1137 echo → 1116
        i1135 = ops.index(1135)
        self.assertGreater(i1135, i1132)
        self.assertEqual(ops[i1135 + 1:i1135 + 7], [1006] * 6)
        self.assertEqual(ops[i1135 + 7], 1105)
        block_pos = [i for i, op in enumerate(ops) if op == 1011 and i > i1135]
        self.assertEqual(len(block_pos), 6)
        for j, i in enumerate(block_pos):
            self.assertEqual(ops[i + 1:i + 8], [1162] * 7)
            eid = struct.unpack_from(">I", frames[i][1], 8)[0]
            self.assertEqual(eid, [1519, 1518, 1517, 1516, 1515, 1500][j])  # reverse
        i1055 = next(i for i, op in enumerate(ops) if op == 1055)
        self.assertGreater(i1055, block_pos[-1] + 7)
        self.assertEqual(ops[i1055:i1055 + 6], [1055] * 6)
        self.assertEqual(len(frames[i1055][1]), roster.PLAYER_TAG_PAYLOAD_SIZE)
        self.assertEqual(ops[i1055 + 6], 1134)
        self.assertEqual(ops[i1055 + 7], 1137)
        self.assertEqual(ops[i1055 + 8], 1116)
        # 1119 echo carries the committed hash; 1123/1132/1105/1134 are zeros
        commit = next(p for op, p in frames if op == 1119)
        self.assertEqual(commit, struct.pack(">I", 0x4260123E) + bytes(2))
        for op in (1123, 1132, 1105, 1134):
            payload = next(p for o, p in frames if o == op)
            self.assertEqual(payload, bytes(len(payload)), f"op {op} is zeros")
        # 1137 echo shape: [u16 0][u16 eid=1500][u16 0100]
        ready = next(p for op, p in frames if op == 1137)
        self.assertEqual(ready, bytes.fromhex("000005dc0100"))
        # slot-flags ping: local 0100, bots 0101, empty half zeroed
        ping = next(p for op, p in frames if op == 1116)
        self.assertEqual(len(ping), roster.SLOT_FLAGS_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">IH", ping, 0), (1500, 0x0100))
        for k in range(1, 6):
            self.assertEqual(struct.unpack_from(">IH", ping, k * 6)[1], 0x0101)
        self.assertEqual(ping[36:], bytes(roster.SLOT_FLAGS_PAYLOAD_SIZE - 36))

    def test_hero_block_mapped_fields(self):
        """Header + tail are mapped; the 750 B stat run stays an open gap
        (our zeros differ from the corpus kit numbers by design for now)."""
        frames = self._frames()
        blocks = [p for op, p in frames if op == 1011]
        last = [p for op, p in frames if op == 1113][-1]
        players = self._committed_players(last)
        for player, corpus in zip(reversed(players), blocks):   # reverse order
            built = roster.build_hero_block(player)
            self.assertEqual(built[:18], corpus[:18])
            self.assertEqual(built[742:], corpus[742:])
        # the stat run is the known unmapped region
        self.assertNotEqual(blocks[0][18:742], bytes(742 - 18))


@unittest.skipUnless(os.path.isdir(VGR_DIR), f"corpus missing: {VGR_DIR}")
class TestVgrWalk(unittest.TestCase):
    def test_25_chunks_31266_frames_zero_failures(self):
        frames, per_file = decode.walk_vgr_dir(VGR_DIR)
        self.assertEqual(len(per_file), 25)            # §15.6
        self.assertEqual(len(frames), 31266)
        self.assertEqual(sum(s["failures"] for s in per_file), 0)
        for stats in per_file:
            self.assertEqual(stats["trailing"], 0, stats["path"])
        # decoded-layer sanity: PLAYER_INFO(1006) handle records exist
        hist = collections.Counter(op for _, op, _ in frames)
        self.assertIn(1006, hist)
        self.assertIn(1010, hist)                      # ENTITY_FULL_UPDATE


if __name__ == "__main__":
    unittest.main()
