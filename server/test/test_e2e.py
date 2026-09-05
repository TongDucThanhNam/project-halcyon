"""Phase 0 acceptance 4 — end-to-end: gateway + match server + heartbeat relay.

A synthetic test client completes the real-client flow for a solo-bot lobby:

  route-request (plaintext, names the backend) → gateway spawns a dynamic-port
  match server and proxies → client sends PLAYER_UUID(1000) encrypted →
  server answers GAME_SETUP(1001) → SNAPSHOT(1114, 2590 B payload) →
  heartbeat lane: duplicated 2112-style connections receive 89 00 and their
  8a 80 12 34 56 78 answers are counted. Keepalive op 0 is consumed.
"""
import os
import socket
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import gateway, match_server, wire

MATCH_ID = "00000000-1111-4222-8333-444455556666"
SESSION_UUID = "ea4c7fda-4b61-481d-abb7-1c757d24ae58"


class TestGatewayFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw = gateway.Gateway("127.0.0.1", port=0, match_id=MATCH_ID,
                                 heartbeat_port=0, heartbeat_interval=0.05)
        cls.gw.start()
        cls.cipher = wire.MatchCipher(MATCH_ID)

    @classmethod
    def tearDownClass(cls):
        cls.gw.stop()

    def _read_message(self, sock, timeout=5.0):
        """One encrypted message → (opcode, payload); skips nothing."""
        sock.settimeout(timeout)
        body = wire.read_frame(sock)
        self.assertIsNotNone(body)
        return wire.decode_body(self.cipher, body)

    def test_full_solo_bot_lobby_flow(self):
        gw = self.gw

        # 1. connect to the generic endpoint, send the plaintext route request
        client = socket.create_connection((gw.host, gw.port), timeout=5)
        client.sendall(wire.build_route_request("127.0.0.1"))

        # 2. duplicated heartbeat lane (§15.2: two identical connections)
        hb_socks = [socket.create_connection((gw.host, gw.relay.port), timeout=5)
                    for _ in range(2)]
        hb_received = [b"", b""]
        for i, s in enumerate(hb_socks):
            threading.Thread(target=self._hb_reader, args=(s, hb_received, i),
                             daemon=True).start()
            s.sendall(wire.HEARTBEAT_C2S)

        # 3. join: encrypted PLAYER_UUID(1000) with the session uuid
        client.sendall(wire.encode_message(self.cipher, wire.OP.PLAYER_UUID,
                                           SESSION_UUID.encode("ascii")))

        # 4. GAME_SETUP(1001) — stub payload carries the match id
        seen = {}
        deadline = time.monotonic() + 5.0
        needed = (wire.OP.GAME_SETUP, wire.OP.SNAPSHOT, wire.OP.GAME_MODE)
        while not all(op in seen for op in needed) and time.monotonic() < deadline:
            op, payload = self._read_message(client)
            seen[op] = payload
        self.assertIn(wire.OP.GAME_SETUP, seen)
        # stub payload = match id ASCII; trailing bytes are the §15.4 zero pad
        self.assertEqual(seen[wire.OP.GAME_SETUP].rstrip(b"\x00"),
                         MATCH_ID.encode("ascii"))
        self.assertIn(wire.OP.GAME_MODE, seen)

        # 5. SNAPSHOT(1114): 2590 B payload, 6×161 records, measured offsets
        snap = seen[wire.OP.SNAPSHOT]
        self.assertEqual(len(snap), match_server.SNAPSHOT_PAYLOAD_SIZE)
        hdr_a, hdr_b = struct.unpack_from(">ff", snap, 0)
        self.assertGreater(hdr_a, 0.0)                       # countdown pair
        self.assertGreater(hdr_b, 0.0)
        base = 8
        rec0 = snap[base:base + 161]
        rec1 = snap[base + 161:base + 2 * 161]
        self.assertEqual(rec0[24:29], b"Guest")               # +24 handle
        self.assertEqual(rec1[24:29], b"Alpha")
        self.assertEqual(struct.unpack_from(">H", rec0, 18)[0], 1500)  # +18 eid
        self.assertEqual(struct.unpack_from(">H", rec0, 8)[0], 0)     # +8 slot
        self.assertEqual(rec1[15], 0)                         # +15 team
        self.assertIn(b"__Kindred_Player_Bot__", snap)        # bot sentinel

        # 6. keepalive op 0 consumed server-side, no reply, connection lives
        client.sendall(wire.build_keepalive(self.cipher, 0x0788))
        time.sleep(0.3)
        match = [m for m in gw.matches]
        self.assertTrue(match, "gateway spawned no match server")
        self.assertEqual(match[-1].keepalive_ticks, [0x0788])
        self.assertEqual(match[-1].session_uuid, SESSION_UUID)
        join_ops = [op for op, _ in match[-1].join_sequence]
        self.assertEqual(join_ops[0], wire.OP.PLAYER_UUID)

        # 7. heartbeat lane: both duplicated connections got 89 00 beats
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and min(map(len, hb_received)) < 4:
            time.sleep(0.05)
        for buf in hb_received:
            self.assertGreaterEqual(len(buf), 2)
            self.assertEqual(buf[:2], b"\x89\x00")
            self.assertTrue(all(buf[i:i + 2] == b"\x89\x00" for i in range(0, len(buf), 2)))
        self.assertGreaterEqual(self.gw.relay.client_beats, 2)   # both lanes answered

        # 8. one match spawned on a dynamic OS-assigned port
        self.assertNotEqual(match[-1].port, 0)
        self.assertEqual(gw.routes[-1][0], "127.0.0.1")

        for s in hb_socks:
            s.close()
        client.close()

    @staticmethod
    def _hb_reader(sock, sink, index):
        sock.settimeout(2.0)
        try:
            while True:
                data = sock.recv(16)
                if not data:
                    return
                sink[index] += data
        except OSError:
            return


if __name__ == "__main__":
    unittest.main()
