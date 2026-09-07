"""Integration tests for live Bot AI match execution in Project Halcyon."""
import os
import shutil
import socket
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import gateway, match_server, roster, wire

MATCH_ID = "00000000-1111-4222-8333-444455556666"
SESSION_UUID = "aaaaaaaa-1111-4111-8111-111111111111"


class TestBotMatchIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["HALCYON_BOTS"] = "1"
        cls.gw = gateway.Gateway("127.0.0.1", port=0, match_id=MATCH_ID,
                                 heartbeat_port=0, heartbeat_interval=0.05)
        cls.gw.start()
        cls.cipher = wire.MatchCipher(MATCH_ID)
        cls.tempdir = tempfile.mkdtemp(prefix="halcyon-botmatch-")
        cls._old = (match_server.WORLD_TAPE_PATH, match_server.LOCK_COUNTDOWN)
        match_server.WORLD_TAPE_PATH = os.path.join(cls.tempdir, "no-tape.bin")
        match_server.LOCK_COUNTDOWN = 0.2

    @classmethod
    def tearDownClass(cls):
        cls.gw.stop()
        shutil.rmtree(cls.tempdir, ignore_errors=True)
        (match_server.WORLD_TAPE_PATH, match_server.LOCK_COUNTDOWN) = cls._old
        os.environ.pop("HALCYON_BOTS", None)

    def _read_message(self, sock, timeout=5.0):
        sock.settimeout(max(0.05, timeout))
        body = wire.read_frame(sock)
        self.assertIsNotNone(body)
        return wire.decode_body(self.cipher, body)

    def _await_op(self, sock, want, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            op, payload = self._read_message(sock, timeout=deadline - time.monotonic())
            if op == want:
                return payload
        self.fail(f"expected opcode {want} not arrived on socket")

    def test_bots_advance_and_broadcast_positions(self):
        """Single human connects, 5 bots spawn, pick, enter world and advance down lane."""
        c = socket.create_connection((self.gw.host, self.gw.port), timeout=5)
        self.addCleanup(c.close)
        c.sendall(wire.build_route_request("127.0.0.1"))
        self.assertEqual(wire.read_frame(c), wire.ROUTE_ACK_BODY)
        c.sendall(wire.encode_message(
            self.cipher, wire.OP.PLAYER_UUID,
            SESSION_UUID.encode("ascii") + bytes(34)))

        # Client gets setup for eid 1500
        setup = self._await_op(c, wire.OP.GAME_SETUP)
        eid = struct.unpack_from(">I", setup, 0)[0]
        self.assertEqual(eid, 1500)

        # Select hero and lock
        sel = struct.pack(">II", 925, 0x2fd7245d) + bytes(6)
        c.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118, sel))
        self._await_op(c, wire.OP.JOIN_1118)

        c.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
        c.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT, struct.pack(">I", 0x2fd7245d)))

        # Await map load signals
        self._await_op(c, wire.OP.ROSTER_FINAL)

        ready_payload = bytes.fromhex("000005dc0100")
        c.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
        c.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready_payload))
        self.assertEqual(self._await_op(c, wire.OP.HERO_READY), ready_payload)

        # In world phase: verify position frames 1070 from bot heroes
        seen_bot_eids = set()
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and len(seen_bot_eids) < 2:
            op, p = self._read_message(c, timeout=deadline - time.monotonic())
            if op == wire.OP.POSITION:
                peid = struct.unpack_from(">I", p, 0)[0]
                if peid in (1515, 1516, 1517, 1518, 1519):
                    seen_bot_eids.add(peid)

        # At least some bots started moving and emitting 1070 position updates
        self.assertTrue(len(seen_bot_eids) > 0, "No bot position frames observed")


if __name__ == "__main__":
    unittest.main()
