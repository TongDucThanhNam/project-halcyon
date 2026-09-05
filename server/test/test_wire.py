"""Phase 0 acceptance 1 — wire.py unit tests (no corpus, no sockets).

Golden vectors are the published, corpus-verified constants from
Docs/Teardown/vainglory-protocol-wire.md §15.4:
  match b9f511e0-11cd-4cfa-ad62-dc8612b8d270 → key 8022d4cab1243a338ed24bc1e6c0f8fa
  BF(key, 00…00) on the wire → 40 fa 87 7b 09 c4 b4 2e
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import wire

MATCH_B9 = "b9f511e0-11cd-4cfa-ad62-dc8612b8d270"
KEY_B9 = "8022d4cab1243a338ed24bc1e6c0f8fa"
ZERO_BLOCK_WIRE = "40fa877b09c4b42e"


class TestKeyDerivation(unittest.TestCase):
    def test_golden_key_from_capture(self):
        self.assertEqual(wire.key_for(MATCH_B9).hex(), KEY_B9)

    def test_golden_zero_block_pattern(self):
        # §15.4: BF(key, 00…0) = the observed repeating wire pattern
        cipher = wire.MatchCipher(MATCH_B9)
        self.assertEqual(cipher.encrypt(b"\x00" * 8).hex(), ZERO_BLOCK_WIRE)
        self.assertEqual(cipher.decrypt(bytes.fromhex(ZERO_BLOCK_WIRE)), b"\x00" * 8)

    def test_keys_differ_per_match(self):
        self.assertNotEqual(wire.key_for("aaaa"), wire.key_for("bbbb"))


class TestCryptoRoundTrip(unittest.TestCase):
    def setUp(self):
        self.cipher = wire.MatchCipher(MATCH_B9)

    def test_body_round_trip_8_aligned(self):
        for size in (8, 16, 128, 2592):
            body = bytes((i * 7 + 3) & 0xFF for i in range(size))
            self.assertEqual(self.cipher.decrypt(self.cipher.encrypt(body)), body)

    def test_encrypt_pads_to_block_multiple(self):
        ct = self.cipher.encrypt(b"\x01\x02\x03")
        self.assertEqual(len(ct), 8)
        self.assertEqual(self.cipher.decrypt(ct)[:3], b"\x01\x02\x03")

    def test_decrypt_rejects_unaligned(self):
        with self.assertRaises(wire.WireError):
            self.cipher.decrypt(b"\x01" * 7)

    def test_ecb_zero_pad_is_deterministic(self):
        a = self.cipher.encrypt(b"\x00" * 8)
        b = self.cipher.encrypt(b"\x00" * 8)
        self.assertEqual(a, b)  # ECB: identical blocks → identical ciphertext


class TestMessages(unittest.TestCase):
    def setUp(self):
        self.cipher = wire.MatchCipher(MATCH_B9)

    def test_message_round_trip_byte_identical(self):
        # acceptance 1: a frame through enc/dec comes back byte-identically
        payload = b"\x11" * 14                     # 2 + 14 = 16, block-aligned
        raw = wire.encode_message(self.cipher, wire.OP.GAME_SETUP, payload)
        (length,) = struct.unpack(">H", raw[:2])
        self.assertEqual(length, 16)
        op, got = wire.decode_body(self.cipher, raw[2:])
        self.assertEqual(op, wire.OP.GAME_SETUP)
        self.assertEqual(got, payload)

    def test_snapshot_sized_message_round_trip(self):
        payload = bytes(2590)
        raw = wire.encode_message(self.cipher, wire.OP.SNAPSHOT, payload)
        op, got = wire.decode_body(self.cipher, raw[2:])
        self.assertEqual(op, wire.OP.SNAPSHOT)
        self.assertEqual(len(got), 2590)          # opcode(2) + payload(2590) = wire body 2592

    def test_keepalive_bytes_match_capture(self):
        # c2s_map.txt: decrypted keepalive body = 00 00 46 d6 07 88 00 00
        raw = wire.build_keepalive(self.cipher, 0x0788)
        (length,) = struct.unpack(">H", raw[:2])
        self.assertEqual(length, 8)
        clear = self.cipher.decrypt(raw[2:])
        self.assertEqual(clear, bytes.fromhex("000046d607880000"))
        self.assertEqual(wire.parse_keepalive(clear[2:]), 0x0788)

    def test_dispatch_range(self):
        self.assertTrue(wire.DISPATCH_MIN <= wire.OP.GAME_SETUP <= wire.DISPATCH_MAX)
        self.assertTrue(wire.DISPATCH_MIN <= wire.OP.TIMER_TICK <= wire.DISPATCH_MAX)


class TestFraming(unittest.TestCase):
    def test_frame_layout(self):
        self.assertEqual(wire.frame(b"abcd"), b"\x00\x04abcd")

    def test_frame_rejects_oversized(self):
        with self.assertRaises(wire.WireError):
            wire.frame(b"x" * 0x10000)

    def test_reader_whole_and_fragmented(self):
        reader = wire.FrameReader()
        blob = wire.frame(b"12345678") + wire.frame(b"ab")
        self.assertEqual(reader.feed(blob), [b"12345678", b"ab"])
        # byte-at-a-time feeding of the same frames
        reader2 = wire.FrameReader()
        got = []
        for i in range(len(blob)):
            got.extend(reader2.feed(blob[i:i + 1]))
        self.assertEqual(got, [b"12345678", b"ab"])

    def test_reader_partial_frame_waits(self):
        reader = wire.FrameReader()
        self.assertEqual(reader.feed(b"\x00\x08ab"), [])
        self.assertEqual(reader.feed(b"cdef"), [])
        self.assertEqual(reader.feed(b"gh"), [b"abcdefgh"])

    def test_reader_eof_is_noop_not_spin(self):
        # regression for the mock_gcp.py hang: EOF must not produce frames
        reader = wire.FrameReader()
        self.assertEqual(reader.feed(b""), [])
        self.assertEqual(reader.feed(b""), [])

    def test_reader_cap(self):
        reader = wire.FrameReader(max_body=64)
        with self.assertRaises(wire.WireError):
            reader.feed(b"\x01\x00" + b"x")   # declares 256 B body > cap


class TestRouteRequest(unittest.TestCase):
    def test_round_trip(self):
        raw = wire.build_route_request("34.53.88.87")
        (length,) = struct.unpack(">H", raw[:2])
        self.assertEqual(length, 134)                      # §15.1/§15.5: 134 B body
        self.assertEqual(len(raw), 136)
        self.assertEqual(wire.parse_route_request(raw[2:]), "34.53.88.87")

    def test_body_shape(self):
        body = wire.build_route_request("10.0.0.9")[2:]
        self.assertEqual(body[:2], b"\x00\x05")            # tag
        self.assertEqual(body[2:10], b"10.0.0.9")
        self.assertEqual(body[10:], b"\x00" * (134 - 10))  # zero pad

    def test_rejects_wrong_size_and_tag(self):
        with self.assertRaises(wire.WireError):
            wire.parse_route_request(b"\x00\x05abc\x00")   # not 134 B
        bad = bytearray(wire.build_route_request("1.2.3.4")[2:])
        bad[0:2] = b"\x00\x06"
        with self.assertRaises(wire.WireError):
            wire.parse_route_request(bytes(bad))


class TestHeartbeatConstants(unittest.TestCase):
    def test_literals(self):
        self.assertEqual(wire.HEARTBEAT_S2C, b"\x89\x00")
        self.assertEqual(wire.HEARTBEAT_C2S, b"\x8a\x80\x12\x34\x56\x78")


if __name__ == "__main__":
    unittest.main()
