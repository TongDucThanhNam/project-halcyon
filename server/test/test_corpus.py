"""Phase 0 acceptance 2 & 3 — corpus validation (integration).

Skipped automatically when the canonical corpus is not present (IP rule:
corpus lives outside the repo under $TEMP/vg_max — never copied in).

  acceptance 2: decode vgfull.pcap with match b9f511e0-… → 32,640 frames,
                100 % coverage, and the exact §15.8 opcode histogram.
  acceptance 3: walk the 25-.vgr corpus → 31,266 frames, zero walk failures.
"""
import collections
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import decode

VG_MAX = os.path.join(os.environ.get("TEMP", ""), "vg_max")
VGFULL_PCAP = os.path.join(VG_MAX, "vgfull.pcap")
VGR_DIR = os.path.join(VG_MAX, "vgr", "vgrtmp")
MATCH_B9 = "b9f511e0-11cd-4cfa-ad62-dc8612b8d270"

# §15.8 top-7 histogram for match b9f511e0 (decimal opcodes)
EXPECTED_TOP_OPS = [(1070, 5946), (1067, 5330), (1053, 5090),
                    (1086, 4390), (1016, 3546), (1054, 2104), (1045, 1799)]


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), f"corpus missing: {VGFULL_PCAP}")
class TestPcapDecode(unittest.TestCase):
    def test_vgfull_histogram_and_coverage(self):
        frames, info = decode.decode_pcap(VGFULL_PCAP, MATCH_B9)
        self.assertIsNotNone(frames, f"decode failed: {info}")
        self.assertEqual(info["nframes"], 32640)       # §15.3/§15.8
        self.assertEqual(info["cov"], 1.0)
        self.assertEqual(info["missed"], 0)
        hist = collections.Counter(op for op, _ in frames)
        self.assertEqual(hist.most_common(7), EXPECTED_TOP_OPS)


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
