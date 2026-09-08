"""End-to-end tests for Slice 6: Multi-client one match.

Verifies:
- 2 clients connecting to gateway are routed to the SAME MatchServer.
- Dynamic slot assignment across teams (default alternating [0, 3, 1, 4, 2, 5]: Client 1 gets slot 0 / eid 1500; Client 2 gets slot 3 / eid 1517).
- Hero pick and lock synchronized across both clients in s2c 1113 snapshots.
- Ready barrier: both clients send 1134 and 1137 before world ticks.
- Multi-hero simulation: Client 1 and Client 2 can move independently; both receive 1070 position updates for both heroes.
- PvP Combat: Client 1 attacks Client 2 (c2s 1060); both receive s2c 1054 combat deltas and s2c 1053 type-0 HP updates.
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

    def _stop_last_match(self):
        if self.gw.matches:
            self.gw.matches[-1].stop()

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
        # A WORLD-phase match survives zero clients now (world-entry dance),
        # so stop the match this test used or the next test would reconnect
        # into its leftover world.
        self.addCleanup(self._stop_last_match)
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
        sim1.teleport(-5.0, 5.0)
        sim2.teleport(-3.5, 5.0)

        # Client 1 targets Client 2 (eid 1517) via c2s 1060
        c1.sendall(wire.encode_message(self.cipher, wire.OP.TARGET_ENTITY, struct.pack(">I", 1517)))

        # Each client receives the same victim-first HP-changing combat event.
        # A separate 1053 HP delta would double-subtract that hit on the client.
        hp_before = sim2.hp
        def await_combat(sock):
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                op, p = self._read_message(sock, timeout=deadline - time.monotonic())
                if op == wire.OP.COMBAT_DELTA:
                    tgt, src, dmg = struct.unpack_from(">IIf", p, 0)
                    if src == 1500 and tgt == 1517:
                        self.assertLess(dmg, 0)
                        return True
            return False

        self.assertTrue(await_combat(c1))
        self.assertTrue(await_combat(c2))
        self.assertLess(sim2.hp, hp_before)

    def test_world_entry_second_connection_reconnects_same_slot(self):
        """The 4.13 client opens a SECOND match connection for world entry
        while its draft connection is still alive (2026-09-07 live log).
        Same session uuid while the first socket is live must reconnect to
        the SAME hero, never allocate a second slot."""
        c1 = self._connect_client(SESSION_UUID_1)
        setup1 = self._await_op(c1, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup1, 0)[0], 1500)

        c_world = self._connect_client(SESSION_UUID_1)   # same uuid, c1 live
        setup_w = self._await_op(c_world, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup_w, 0)[0], 1500)

        # No new slot was consumed: the next distinct client gets slot 3
        c2 = self._connect_client(SESSION_UUID_2)
        setup2 = self._await_op(c2, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup2, 0)[0], 1517)

    def test_new_uuid_midworld_join_gets_world_dump(self):
        """A distinct device (own session uuid) joining while the match is
        already in the world phase receives a full world dump for its own
        new eid instead of the lobby opener."""
        c1 = self._connect_client(SESSION_UUID_1)
        self._await_op(c1, wire.OP.GAME_SETUP)
        c2 = self._connect_client(SESSION_UUID_2)
        setup2 = self._await_op(c2, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup2, 0)[0], 1517)

        for sock in (c1, c2):
            sock.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118,
                          struct.pack(">II", 925, 0x2fd7245d) + bytes(6)))
            self._await_op(sock, wire.OP.JOIN_1118)
            sock.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
            sock.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT,
                          struct.pack(">I", 0x2fd7245d)))
        # ROSTER_FINAL arrives once every human has locked
        self._await_op(c1, wire.OP.ROSTER_FINAL)
        self._await_op(c2, wire.OP.ROSTER_FINAL)
        for sock in (c1, c2):
            sock.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
            self._await_op(sock, wire.OP.SHOP_OPEN)
            sock.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY,
                          bytes.fromhex("000005dc0100")))
            self.assertEqual(self._await_op(sock, wire.OP.HERO_READY),
                             bytes.fromhex("000005dc0100"))

        # Match is now in the world phase; a third device joins
        c3 = self._connect_client("55555555-5555-4555-8555-555555555555")
        setup3 = self._await_op(c3, wire.OP.GAME_SETUP)
        eid3 = struct.unpack_from(">I", setup3, 0)[0]
        self.assertNotIn(eid3, (1500, 1517))
        self._await_op(c3, wire.OP.MODE_NAME)
        self._await_op(c3, wire.OP.HERO_BLOCK)
        self._await_op(c3, wire.OP.POSITION)

        # The existing clients stay in the world stream (movement → 1070)
        c1.sendall(wire.encode_message(
            self.cipher, wire.OP.MOVE_CAST,
            struct.pack(">ff", roster.SPAWN_X + 2.0, roster.SPAWN_Y) + bytes(6)))
        self._await_op(c1, wire.OP.POSITION)

    def test_second_mapready_client_gets_own_world_dump(self):
        """In a duo the second 1134 arrives after the first client's dump
        flipped the phase to WORLD; the second client must still get its own
        world-init dump (2026-09-07 live duo: one "world init dumped" line
        for two 1134 pairs — the undumped client quit to menu)."""
        c1 = self._connect_client(SESSION_UUID_1)
        self._await_op(c1, wire.OP.GAME_SETUP)
        c2 = self._connect_client(SESSION_UUID_2)
        self._await_op(c2, wire.OP.GAME_SETUP)
        for sock in (c1, c2):
            sock.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118,
                          struct.pack(">II", 925, 0x2fd7245d) + bytes(6)))
            self._await_op(sock, wire.OP.JOIN_1118)
            sock.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
            sock.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT,
                          struct.pack(">I", 0x2fd7245d)))
        self._await_op(c1, wire.OP.ROSTER_FINAL)
        self._await_op(c2, wire.OP.ROSTER_FINAL)

        ready = bytes.fromhex("000005dc0100")
        c1.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
        c1.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready))
        self._await_op(c1, wire.OP.HERO_READY)

        # c2's 1134 lands after the phase flipped to WORLD — it must carry
        # its own init dump (MODE_NAME is the dump's first frame) before the
        # no-tape echo of 1134.
        c2.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
        saw_dump = False
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            op, _ = self._read_message(c2, timeout=deadline - time.monotonic())
            if op == wire.OP.MODE_NAME:
                saw_dump = True
            if op == wire.OP.SHOP_OPEN:
                break
        self.assertTrue(saw_dump, "second map-ready client got no world dump")

    def test_hero_1010_full_updates_cover_every_human(self):
        """With the hero-1010 layer enabled, every HUMAN hero gets its own
        1010 full update stream — solo legacy emitted players[0] only, so a
        duo's second hero would never render movement."""
        os.environ["HALCYON_HERO_1010"] = "1"
        self.addCleanup(os.environ.pop, "HALCYON_HERO_1010", None)
        c1 = self._connect_client(SESSION_UUID_1)
        self._await_op(c1, wire.OP.GAME_SETUP)
        c2 = self._connect_client(SESSION_UUID_2)
        self._await_op(c2, wire.OP.GAME_SETUP)
        for sock in (c1, c2):
            sock.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118,
                          struct.pack(">II", 925, 0x2fd7245d) + bytes(6)))
            self._await_op(sock, wire.OP.JOIN_1118)
            sock.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
            sock.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT,
                          struct.pack(">I", 0x2fd7245d)))
        self._await_op(c1, wire.OP.ROSTER_FINAL)
        self._await_op(c2, wire.OP.ROSTER_FINAL)
        ready = bytes.fromhex("000005dc0100")
        for sock in (c1, c2):
            sock.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
            self._await_op(sock, wire.OP.SHOP_OPEN)
            sock.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready))
            self._await_op(sock, wire.OP.HERO_READY)

        seen = set()
        deadline = time.monotonic() + roster.HERO_1010_PERIOD + 4.0
        while time.monotonic() < deadline and seen != {1500, 1517}:
            op, p = self._read_message(c1, timeout=deadline - time.monotonic())
            if op == wire.OP.ENTITY_FULL_UPDATE:
                seen.add(struct.unpack_from(">I", p, 0)[0])
        self.assertEqual(seen, {1500, 1517},
                         "1010 full updates did not cover both human heroes")

    def test_same_player_two_token_encodings_one_slot(self):
        """The client presents its identity under different JSON encodings of
        the same JWT payload (live 2026-09-07 08:26: draft join and its
        second connection carried spaced vs compact encodings and were
        counted as two players). Identity = the player_id claim, so both
        encodings must map to ONE slot."""
        import base64
        import json

        def b64(obj):
            raw = json.dumps(obj, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        pid = "3642548e-0bf8-4407-b20b-6c4cdb921cee"
        compact = f"hdr.{b64({'player_id': pid, 'session_id': 's1'})}.sig"
        spaced_payload = json.dumps({"player_id": pid, "session_id": "s2"},
                                    separators=(", ", ": ")).encode()
        spaced_b64 = base64.urlsafe_b64encode(spaced_payload).decode().rstrip("=")
        spaced = f"hdr.{spaced_b64}.sig"
        self.assertNotEqual(compact, spaced)
        self.assertEqual(match_server.identity_from_token(compact), pid)
        self.assertEqual(match_server.identity_from_token(spaced), pid)

        c1 = self._connect_client(compact)
        setup1 = self._await_op(c1, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup1, 0)[0], 1500)
        # the same device's second connection must reconnect, not eat a slot
        c1b = self._connect_client(spaced)
        setup1b = self._await_op(c1b, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup1b, 0)[0], 1500)
        # and the next DISTINCT player still gets the second slot
        c2 = self._connect_client(SESSION_UUID_2)
        setup2 = self._await_op(c2, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup2, 0)[0], 1517)

    def test_world_survives_full_disconnect_for_world_conn(self):
        """The client's world-entry dance closes its draft connection BEFORE
        opening the world connection (live 2026-09-07: drafts EOF 07:02:39,
        world conn 07:02:47). A WORLD-phase match with zero clients must
        survive so the world conn reconnects into it — never a fresh draft
        opener (which made the client quit to menu)."""
        c1 = self._connect_client(SESSION_UUID_1)
        self._await_op(c1, wire.OP.GAME_SETUP)
        c2 = self._connect_client(SESSION_UUID_2)
        self._await_op(c2, wire.OP.GAME_SETUP)
        for sock in (c1, c2):
            sock.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118,
                          struct.pack(">II", 925, 0x2fd7245d) + bytes(6)))
            self._await_op(sock, wire.OP.JOIN_1118)
            sock.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
            sock.sendall(wire.encode_message(self.cipher, wire.OP.LOCK_COMMIT,
                          struct.pack(">I", 0x2fd7245d)))
        self._await_op(c1, wire.OP.ROSTER_FINAL)
        self._await_op(c2, wire.OP.ROSTER_FINAL)
        ready = bytes.fromhex("000005dc0100")
        for sock in (c1, c2):
            sock.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
            self._await_op(sock, wire.OP.SHOP_OPEN)
            sock.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready))
            self._await_op(sock, wire.OP.HERO_READY)

        ms = self.gw.matches[-1]
        self.assertEqual(ms.session.phase, ms.session.WORLD)

        # both draft conns drop; 8 s later the world conn arrives
        c1.close()
        c2.close()
        time.sleep(0.3)
        c1w = self._connect_client(SESSION_UUID_1)
        setup = self._await_op(c1w, wire.OP.GAME_SETUP)
        self.assertEqual(struct.unpack_from(">I", setup, 0)[0], 1500)
        self.assertEqual(self._read_message(c1w)[0], wire.OP.GAME_MODE)
        # next frame discriminates reconnect (MODE_NAME world dump) from a
        # fresh draft opener (HERO_CATALOG 1107 burst)
        self.assertEqual(self._read_message(c1w)[0], wire.OP.MODE_NAME)

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
