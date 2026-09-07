"""Synthetic measurement gates: do not turn duplicate frames or packets into FPS/jitter."""
import struct
import tempfile
from pathlib import Path
import unittest

from Tools.measure_adb_smoothness import frame_summary, movement_summary, timed_packets
from server import wire

MATCH_ID = "00000000-1111-4222-8333-444455556666"


class TestFrameTiming(unittest.TestCase):
    def test_repeated_dumps_pending_fences_and_shared_vsync_are_not_frames(self):
        rows = [(1, 1_000_000_000, 990_000_000),
                (2, 1_020_000_000, 1_010_000_000),
                (3, 1_020_000_000, 1_011_000_000),
                (4, 1_040_000_000, 1_030_000_000)]
        result = frame_summary(rows + rows + [(0, 0, 0), (5, 2**63 - 1, 6)])
        self.assertEqual(result["present"]["unique_frames"], 3)
        self.assertEqual(result["present"]["fps"], 50)
        self.assertEqual(result["ready"]["unique_frames"], 4)

    def test_long_present_gap_is_retained(self):
        result = frame_summary([(1, 1_000_000_000, 1), (2, 1_100_000_000, 2)])
        self.assertEqual(result["present"]["fps"], 10)
        self.assertEqual(result["present"]["gaps_over_50ms"], 1)
        self.assertIsNone(frame_summary([])["present"]["fps"])


class TestTimedPackets(unittest.TestCase):
    def capture(self, segments):
        # Ethernet + IPv4 + TCP, own loopback endpoints, synthetic encrypted data.
        out = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
        for micros, seq, body in segments:
            ip = bytearray(20)
            ip[0], ip[9] = 0x45, 6
            struct.pack_into(">H", ip, 2, 40 + len(body))
            ip[12:20] = b"\x7f\0\0\1" * 2
            tcp = bytearray(20)
            struct.pack_into(">HHI", tcp, 0, 7103, 12345, seq)
            tcp[12] = 0x50
            packet = bytes(12) + b"\x08\0" + ip + tcp + body
            out += struct.pack("<IIII", 100, micros, len(packet), len(packet)) + packet
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pcap"
            path.write_bytes(out)
            return timed_packets(path, 7103, MATCH_ID)

    def test_split_coalesced_and_retransmitted_frames_keep_completion_times(self):
        cipher = wire.MatchCipher(MATCH_ID)
        a = wire.encode_message(cipher, 1016, struct.pack(">Bff", 0, 10., 2.) + bytes(5))
        b = wire.encode_message(cipher, 1070, struct.pack(">IffH", 1500, 1., 2., 0))
        frames = self.capture([(100000, 100, a[:7]),
                               (120000, 107, a[7:] + b),
                               (300000, 100, a)])
        self.assertEqual([f[:3] for f in frames], [(100.12, "s2c", 1016), (100.12, "s2c", 1070)])

    def test_missing_bytes_fail_instead_of_resynchronizing(self):
        with self.assertRaises(KeyError):
            self.capture([(0, 100, b"ab"), (100, 104, b"cd")])


class TestMovementTiming(unittest.TestCase):
    def test_initial_anchor_and_duplicate_arrival_are_separate_from_periodic_jitter(self):
        target = (1., "s2c", 1016, struct.pack(">Bff", 0, 2., 0.) + bytes(5))
        frames = [target] + [(t, "s2c", 1070, struct.pack(">IffH", 1500, x, 0., 0))
            for t, x in ((1., 0.), (1.05, 1.), (1.25, 2.), (1.25, 2.))]
        move = movement_summary(frames)["moves"][0]
        self.assertEqual(move["duplicate_positions"], 1)
        self.assertEqual(move["backward_corrections"], 0)
        self.assertTrue(move["arrived"])
        self.assertEqual(move["periodic_correction_interval_ms"]["count"], 1)
        self.assertAlmostEqual(move["periodic_correction_interval_ms"]["median"], 200)


if __name__ == "__main__":
    unittest.main()
