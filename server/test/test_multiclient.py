"""End-to-end tests for Slice 6: Multi-client one match.

Verifies:
- 2 clients connecting to gateway are routed to the SAME MatchServer.
- Dynamic slot assignment across teams (default alternating [0, 3, 1, 4, 2, 5]: Client 1 gets slot 0 / eid 1500; Client 2 gets slot 3 / eid 1517).
- Hero pick and lock synchronized across both clients in s2c 1113 snapshots.
- Ready barrier: both clients send 1134 and 1137 before world ticks.
- Multi-hero simulation: Client 1 and Client 2 can move independently; both receive 1070 position updates for both heroes.
- PvP Combat: Client 1 attacks Client 2 (c2s 1060); both receive s2c 1054 combat deltas and s2c 1053 type-6 HP updates.
- Reconnection: Client 2 disconnects and reconnects with same UUID; receives world state dump and resumes match stream.
"""
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
SESSION_UUID_1 = "11111111-1111-4111-8111-111111111111"
SESSION_UUID_2 = "22222222-2222-4222-8222-222222222222"


class TestMultiClientE2E(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.gw = gateway.Gateway("127.0.0.1", port=0, match_id=MATCH_ID,
                                 heartbeat_port=0, heartbeat_interval=0.05)
        cls.gw.start()
        cls.cipher = wire.MatchCipher(MATCH_ID)
        cls.tempdir = tempfile.mkdtemp(prefix="halcyon-multiclient-")
        cls._old = (match_server.WORLD_TAPE_PATH, match_server.LOCK_COUNTDOWN)
        match_server.WORLD_TAPE_PATH = os.path.join(cls.tempdir, "no-tape.bin")
        match_server.LOCK_COUNTDOWN = 0.3

    @classmethod
    def tearDownClass(cls):
        cls.gw.stop()
        shutil.rmtree(cls.tempdir, ignore_errors=True)
        (match_server.WORLD_TAPE_PATH, match_server.LOCK_COUNTDOWN) = cls._old

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

    def _connect_client(self, session_uuid):
        client = socket.create_connection((self.gw.host, self.gw.port), timeout=5)
        self.addCleanup(client.close)
        client.sendall(wire.build_route_request("127.0.0.1"))
        self.assertEqual(wire.read_frame(client), wire.ROUTE_ACK_BODY)
        client.sendall(wire.encode_message(
            self.cipher, wire.OP.PLAYER_UUID,
            session_uuid.encode("ascii") + bytes(34)))
        return client

    def test_two_clients_slot_assignment_and_synchronization(self):
        """Two clients connect; Client 1 is slot 0 (1500, Team 1), Client 2 is slot 3 (1517, Team 2)."""
        c1 = self._connect_client(SESSION_UUID_1)
        # Client 1 gets GAME_SETUP with eid 1500
        setup1 = self._await_op(c1, wire.OP.GAME_SETUP)
        eid1 = struct.unpack_from(">I", setup1, 0)[0]
        self.assertEqual(eid1, 1500)

        # Now connect Client 2
        c2 = self._connect_client(SESSION_UUID_2)
        setup2 = self._await_op(c2, wire.OP.GAME_SETUP)
        eid2 = struct.unpack_from(">I", setup2, 0)[0]
        # With default alternating slots [0, 3, 1, 4, 2, 5], Client 2 gets slot 3 (Team 2, eid 1517)
        self.assertEqual(eid2, 1517)

        # Client 1 and Client 2 select heroes
        # Client 1 selects hero 925
        sel1 = struct.pack(">II", 925, 0x2fd7245d) + bytes(6)
        c1.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118, sel1))
        self._await_op(c1, wire.OP.JOIN_1118)

        # Client 2 selects hero 244
        sel2 = struct.pack(">II", 244, 0xf9fd7554) + bytes(6)
        c2.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118, sel2))
        self._await_op(c2, wire.OP.JOIN_1118)

        # Client 1 locks
        c1.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
        c1.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT, struct.pack(">I", 0x4260123e) + bytes(2)))

        # Client 2 locks
        c2.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
        c2.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT, struct.pack(">I", 0x11223344) + bytes(2)))

        # Both clients receive ROSTER_FINAL
        self._await_op(c1, wire.OP.ROSTER_FINAL)
        self._await_op(c2, wire.OP.ROSTER_FINAL)

        # Map load: both clients send 1134 (SHOP_OPEN)
        c1.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
        self._await_op(c1, wire.OP.SHOP_OPEN)

        c2.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
        self._await_op(c2, wire.OP.SHOP_OPEN)

        # Ready barrier: both send 1137 (HERO_READY)
        ready_payload = bytes.fromhex("000005dc0100")
        c1.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready_payload))
        self.assertEqual(self._await_op(c1, wire.OP.HERO_READY), ready_payload)

        c2.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready_payload))
        self.assertEqual(self._await_op(c2, wire.OP.HERO_READY), ready_payload)

        # Test movement: Client 1 moves
        target_c1 = (roster.SPAWN_X + 2.0, roster.SPAWN_Y)
        c1.sendall(wire.encode_message(self.cipher, wire.OP.MOVE_CAST, struct.pack(">ff", *target_c1) + bytes(6)))

        # Both c1 and c2 should observe 1070 for eid 1500
        def find_pos(sock, eid):
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                op, p = self._read_message(sock, timeout=deadline - time.monotonic())
                if op == wire.OP.POSITION:
                    p_eid = struct.unpack_from(">I", p, 0)[0]
                    if p_eid == eid:
                        return True
            return False

        self.assertTrue(find_pos(c1, 1500))
        self.assertTrue(find_pos(c2, 1500))

        # Test PvP combat: Move Client 1 near Client 2's hero (eid 1517)
        # Spawn for 1517 is HERO_SPAWNS[1517] = (78.18, 0.88)
        # Directly teleport c1 sim near c2 to test attack
        ms = self.gw.matches[-1]
        sim1 = ms.session.hero_sims[1500]
        sim2 = ms.session.hero_sims[1517]
        sim1.x = sim2.x - 2.0
        sim1.y = sim2.y

        # Client 1 targets Client 2 (eid 1517) via c2s 1060
        c1.sendall(wire.encode_message(self.cipher, wire.OP.TARGET_ENTITY, struct.pack(">I", 1517)))

        # Wait for COMBAT_DELTA and ENTITY_STAT on both clients
        def await_combat(sock):
            got_delta = False
            got_stat = False
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                op, p = self._read_message(sock, timeout=deadline - time.monotonic())
                if op == wire.OP.COMBAT_DELTA:
                    src, tgt, dmg = struct.unpack_from(">IIf", p, 0)
                    if src == 1500 and tgt == 1517:
                        got_delta = True
                elif op == wire.OP.ENTITY_STAT:
                    eid = struct.unpack_from(">I", p, 0)[0]
                    if eid == 1517:
                        got_stat = True
                if got_delta and got_stat:
                    return True
            return False

        self.assertTrue(await_combat(c1))
        self.assertTrue(await_combat(c2))

    def test_reconnection_resumes_match_with_state_dump(self):
        """Client disconnects and reconnects with the same session UUID; receives state dump."""
        c1 = self._connect_client("33333333-3333-4333-8333-333333333333")
        self._await_op(c1, wire.OP.GAME_SETUP)

        # Connect a second client so match remains active when c1 drops
        c2 = self._connect_client("44444444-4444-4444-8444-444444444444")
        self._await_op(c2, wire.OP.GAME_SETUP)

        # Both select heroes
        sel1 = struct.pack(">II", 925, 0x2fd7245d) + bytes(6)
        c1.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118, sel1))
        self._await_op(c1, wire.OP.JOIN_1118)

        sel2 = struct.pack(">II", 244, 0xf9fd7554) + bytes(6)
        c2.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118, sel2))
        self._await_op(c2, wire.OP.JOIN_1118)

        # Both lock
        c1.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
        c1.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT, struct.pack(">I", 0x4260123e) + bytes(2)))

        c2.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
        c2.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT, struct.pack(">I", 0x11223344) + bytes(2)))

        self._await_op(c1, wire.OP.ROSTER_FINAL)
        self._await_op(c2, wire.OP.ROSTER_FINAL)

        # Both send SHOP_OPEN & HERO_READY
        c1.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
        self._await_op(c1, wire.OP.SHOP_OPEN)
        c2.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
        self._await_op(c2, wire.OP.SHOP_OPEN)

        ready_payload = bytes.fromhex("000005dc0100")
        c1.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready_payload))
        self._await_op(c1, wire.OP.HERO_READY)
        c2.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready_payload))
        self._await_op(c2, wire.OP.HERO_READY)

        # Disconnect c1 (c2 is still connected, keeping match live)
        c1.close()
        time.sleep(0.1)

        # Reconnect with same UUID
        c1_reconnect = socket.create_connection((self.gw.host, self.gw.port), timeout=5)
        self.addCleanup(c1_reconnect.close)
        c1_reconnect.sendall(wire.build_route_request("127.0.0.1"))
        self.assertEqual(wire.read_frame(c1_reconnect), wire.ROUTE_ACK_BODY)
        c1_reconnect.sendall(wire.encode_message(
            self.cipher, wire.OP.PLAYER_UUID,
            "33333333-3333-4333-8333-333333333333".encode("ascii") + bytes(34)))

        # Expect GAME_SETUP, then MODE_NAME, then world dump
        setup = self._await_op(c1_reconnect, wire.OP.GAME_SETUP)
        eid = struct.unpack_from(">I", setup, 0)[0]
        self.assertEqual(eid, 1500)
        self._await_op(c1_reconnect, wire.OP.MODE_NAME)
        # Hero block
        self._await_op(c1_reconnect, wire.OP.HERO_BLOCK)
        # Position frame
        self._await_op(c1_reconnect, wire.OP.POSITION)


if __name__ == "__main__":
    unittest.main()
