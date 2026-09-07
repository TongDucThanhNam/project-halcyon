"""Gateway, heartbeat, and the live-verified client-initiated hero pick flow."""
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import gateway, match_server, roster, wire
from server import hero_catalog

MATCH_ID = "00000000-1111-4222-8333-444455556666"
SESSION_UUID = "ea4c7fda-4b61-481d-abb7-1c757d24ae58"
ROSTER_SIZE = roster.SNAPSHOT_ROSTER_SIZE
STRIDE = roster.SNAPSHOT_RECORD_STRIDE


class TestNoTapeFlag(unittest.TestCase):
    """HALCYON_NO_TAPE=1 skips the corpus tape even when a file exists —
    pure-sim world testing without deleting operator artifacts. Hero-1010
    emission is OFF by default (the live client aborted on it, 2026-09-06);
    HALCYON_HERO_1010=1 re-enables the sim slice."""

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="halcyon-notape-")
        self.addCleanup(shutil.rmtree, self.tempdir, ignore_errors=True)

    def _stream(self):
        players = roster.default_solo_bots(SESSION_UUID, MATCH_ID)
        return match_server.SnapshotStream(None, players, MATCH_ID,
                                           lambda op, p: None, log=lambda *a: None)

    def _write_tape(self, path):
        # 1087 body: _load_tape skips until ENTITY_DATA, so the synthetic
        # record must lead with that opcode to survive the load
        body = struct.pack(">H", wire.OP.ENTITY_DATA) + bytes(6)
        with open(path, "wb") as fh:
            fh.write(struct.pack(">IH", 0, len(body)) + body)

    def test_env_set_skips_existing_tape(self):
        stream = self._stream()
        old_path = match_server.WORLD_TAPE_PATH
        old_env = os.environ.get("HALCYON_NO_TAPE")
        match_server.WORLD_TAPE_PATH = os.path.join(self.tempdir, "tape.bin")
        self._write_tape(match_server.WORLD_TAPE_PATH)
        try:
            os.environ["HALCYON_NO_TAPE"] = "1"
            stream._load_tape()
            self.assertEqual(stream.tape_frames, [])
        finally:
            match_server.WORLD_TAPE_PATH = old_path
            if old_env is None:
                os.environ.pop("HALCYON_NO_TAPE", None)
            else:
                os.environ["HALCYON_NO_TAPE"] = old_env

    def test_env_unset_loads_existing_tape(self):
        stream = self._stream()
        old_path = match_server.WORLD_TAPE_PATH
        old_env = os.environ.get("HALCYON_NO_TAPE")
        match_server.WORLD_TAPE_PATH = os.path.join(self.tempdir, "tape.bin")
        self._write_tape(match_server.WORLD_TAPE_PATH)
        os.environ.pop("HALCYON_NO_TAPE", None)
        try:
            stream._load_tape()
            self.assertEqual(len(stream.tape_frames), 1)
        finally:
            match_server.WORLD_TAPE_PATH = old_path
            if old_env is not None:
                os.environ["HALCYON_NO_TAPE"] = old_env

    def test_hero_1010_flag_default_off_env_on(self):
        old = os.environ.get("HALCYON_HERO_1010")
        os.environ.pop("HALCYON_HERO_1010", None)
        try:
            self.assertFalse(self._stream().emit_hero_1010)
            os.environ["HALCYON_HERO_1010"] = "1"
            self.assertTrue(self._stream().emit_hero_1010)
        finally:
            # always clear: a leftover "1" leaks into later worlds' streams
            os.environ.pop("HALCYON_HERO_1010", None)
            if old is not None:
                os.environ["HALCYON_HERO_1010"] = old


class TestGatewayFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw = gateway.Gateway("127.0.0.1", port=0, match_id=MATCH_ID,
                                 heartbeat_port=0, heartbeat_interval=0.05)
        cls.gw.start()
        cls.cipher = wire.MatchCipher(MATCH_ID)
        cls.tempdir = tempfile.mkdtemp(prefix="halcyon-e2e-")

    @classmethod
    def tearDownClass(cls):
        cls.gw.stop()
        shutil.rmtree(cls.tempdir, ignore_errors=True)

    def setUp(self):
        # tests drive the 1116-only world fallback; the operator's corpus
        # tape (if present) must not make frames appear mid-assertion
        self._old_tape_path = match_server.WORLD_TAPE_PATH
        match_server.WORLD_TAPE_PATH = os.path.join(self.tempdir, "no-tape.bin")

    def tearDown(self):
        match_server.WORLD_TAPE_PATH = self._old_tape_path
        # a WORLD match now survives zero clients (world-entry dance) — stop
        # it so the next test gets a fresh draft, not a reconnect dump
        if self.gw.matches:
            self.gw.matches[-1].stop()

    def _read_message(self, sock, timeout=5.0):
        """One encrypted message → (opcode, payload); skips nothing."""
        sock.settimeout(timeout)
        body = wire.read_frame(sock)
        self.assertIsNotNone(body)
        return wire.decode_body(self.cipher, body)

    def _hb_reader(self, sock, sink, index):
        sock.settimeout(2.0)
        try:
            while True:
                data = sock.recv(16)
                if not data:
                    return
                sink[index] += data
        except OSError:
            return

    def test_no_tape_world_serves_1010_with_movement(self):
        """No-tape world with the hero-1010 sim slice enabled (the
        HALCYON_HERO_1010 path; here via a missing tape file — same live
        layer): join → lock → dump → no tape, then the fake client
        receives 1116 pings + 1010 hero full updates and the 1012 → 1016/1070
        movement stays position-consistent with the 1010s."""
        old_period = roster.HERO_1010_PERIOD
        old_countdown = match_server.LOCK_COUNTDOWN
        old_flag = os.environ.get("HALCYON_HERO_1010")
        roster.HERO_1010_PERIOD = 0.3
        match_server.LOCK_COUNTDOWN = 0.3
        os.environ["HALCYON_HERO_1010"] = "1"
        try:
            client = socket.create_connection((self.gw.host, self.gw.port),
                                              timeout=5)
            self.addCleanup(client.close)
            client.sendall(wire.build_route_request("127.0.0.1"))
            self.assertEqual(wire.read_frame(client), wire.ROUTE_ACK_BODY)
            client.sendall(wire.encode_message(
                self.cipher, wire.OP.PLAYER_UUID,
                SESSION_UUID.encode("ascii") + bytes(34)))

            def read_pick(pred, timeout=8.0, strict=True):
                """Pick-phase reader: by default everything but the awaited
                frame must be a 1113 snapshot; strict=False allows the
                dump/finalize frame zoo through."""
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    op, payload = self._read_message(
                        client, timeout=deadline - time.monotonic())
                    if pred(op, payload):
                        return op, payload
                    if strict:
                        self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
                self.fail("expected pick-phase frame not arrived")

            def read_world(pred, timeout=5.0):
                """World-phase reader: skips (and shape-checks) 1116/1010;
                1070 frames pass through for the pred to collect."""
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    op, payload = self._read_message(
                        client, timeout=max(0.05, deadline - time.monotonic()))
                    if pred(op, payload):
                        return op, payload
                    self.assertIn(op, (wire.OP.SLOT_FLAGS_PING,
                                       wire.OP.ENTITY_FULL_UPDATE,
                                       wire.OP.POSITION,
                                       wire.OP.ENTITY_STATE))
                    if op == wire.OP.SLOT_FLAGS_PING:
                        self.assertEqual(len(payload),
                                         roster.SLOT_FLAGS_PAYLOAD_SIZE)
                self.fail("expected world frame not arrived")

            read_pick(lambda op, p: op == wire.OP.SNAPSHOT_JOIN, strict=False)
            selection = struct.pack(">II", 925, 0x2fd7245d) + bytes(6)
            client.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118,
                                               selection))
            read_pick(lambda op, p: op == wire.OP.JOIN_1118)
            client.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK,
                                               bytes(6)))
            client.sendall(wire.encode_message(
                self.cipher, wire.OP.LOCK_COMMIT,
                struct.pack(">I", 0x4260123e) + bytes(2)))
            finals = []

            def _count_final(op, payload):
                if op == wire.OP.PLAYER_INFO:
                    finals.append(payload)
                    return False
                return op == wire.OP.ROSTER_FINAL

            read_pick(_count_final, strict=False)
            self.assertEqual(len(finals), 6)                 # 1006×6 then 1132

            # client map-load done: 1134 → dump (no-tape: derived 1055s, no
            # 1087 batch) → 1134 echo; 1137 → verbatim echo
            blocks = []
            saw = []

            def _await_echo(op, payload):
                saw.append(op)
                if op == wire.OP.HERO_BLOCK:
                    blocks.append(payload)
                return op == wire.OP.SHOP_OPEN

            client.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN,
                                               bytes(6)))
            read_pick(_await_echo, strict=False)
            self.assertEqual(len(blocks), 6)
            self.assertEqual(saw[-1], wire.OP.SHOP_OPEN)
            ready = bytes.fromhex("000005dc0100")
            client.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY,
                                               ready))
            op, payload = read_world(lambda op, p: op == wire.OP.HERO_READY)
            self.assertEqual(payload, ready)

            # world is live (no tape): first hero 1010 at spawn
            full = []
            op, first = read_world(lambda op, p: op == wire.OP.ENTITY_FULL_UPDATE)
            self.assertEqual(len(first), roster.ENTITY_FULL_UPDATE_PAYLOAD_SIZE)
            eid = struct.unpack_from(">I", first, 0)[0]
            tick = struct.unpack_from(">I", first, 8)[0]
            x, z, y = struct.unpack_from(">fff", first, 12)
            self.assertEqual(eid, 1500)
            self.assertEqual((tick, x, y),
                             (1, roster.SPAWN_X, roster.SPAWN_Y))
            self.assertEqual(z, roster.GROUND_Z)
            self.assertEqual(first[116], 1)                  # seq u8

            # movement: 1010s and 1070s stay position-consistent
            target = (roster.SPAWN_X + 2.0, roster.SPAWN_Y)
            client.sendall(wire.encode_message(
                self.cipher, wire.OP.MOVE_CAST,
                struct.pack(">ff", *target) + bytes(6)))
            positions = []
            move_targets = []
            last_1010 = (tick, first[116])

            def _collect(op, payload):
                nonlocal last_1010
                if op == wire.OP.MOVE_TO:
                    self.assertEqual(positions, [], "1016 must precede the first correction")
                    self.assertEqual(payload, struct.pack(">Bff", 0, *target) + bytes(5))
                    move_targets.append(payload)
                    self.assertEqual(len(move_targets), 1, "one activation per input")
                    return True
                if op == wire.OP.POSITION:
                    self.assertEqual(len(move_targets), 1)
                    peid, px, py, pad = struct.unpack(">IffH", payload)
                    self.assertEqual((peid, pad), (1500, 0))
                    positions.append((px, py))
                elif op == wire.OP.ENTITY_FULL_UPDATE:
                    ptick = struct.unpack_from(">I", payload, 8)[0]
                    px, pz, py = struct.unpack_from(">fff", payload, 12)
                    self.assertEqual(py, roster.SPAWN_Y)
                    self.assertGreater(ptick, last_1010[0])   # monotonic tick
                    self.assertEqual((last_1010[1] + 1) & 0xFF, payload[116])
                    last_1010 = (ptick, payload[116])
                    # along the walked segment, never beyond the target
                    self.assertGreaterEqual(px, roster.SPAWN_X)
                    self.assertLessEqual(px, target[0])
                    return px == target[0] and py == target[1]
                return False

            # Consume and validate the activation explicitly; subsequent 1016s
            # remain unexpected rather than being added to a skip whitelist.
            op, _ = read_world(_collect, timeout=5.0)
            self.assertEqual(op, wire.OP.MOVE_TO)
            op, _ = read_world(_collect, timeout=5.0)
            self.assertEqual(op, wire.OP.ENTITY_FULL_UPDATE)
            self.assertTrue(positions, "no 1070 frames after 1012")
            self.assertEqual(positions[0], (roster.SPAWN_X, roster.SPAWN_Y))
            self.assertEqual(positions[-1], target)
            walked = [roster.SPAWN_X] + [px for px, _ in positions]
            self.assertEqual(walked, sorted(walked))          # monotone approach
            # the exact-target 1010 (arrival pinned the pair) closed the loop;
            # its tick index depends on how many 0.3 s periods the 0.4 s walk
            # spanned — only monotonicity is deterministic here
            self.assertGreaterEqual(last_1010[0], 2)
        finally:
            roster.HERO_1010_PERIOD = old_period
            match_server.LOCK_COUNTDOWN = old_countdown
            if old_flag is None:
                os.environ.pop("HALCYON_HERO_1010", None)
            else:
                os.environ["HALCYON_HERO_1010"] = old_flag

    def test_full_solo_bot_lobby_flow(self):
        gw = self.gw

        # 1. connect to the generic endpoint, send the plaintext route request
        client = socket.create_connection((gw.host, gw.port), timeout=5)
        self.addCleanup(client.close)
        client.sendall(wire.build_route_request("127.0.0.1"))

        # 2. gateway route-ack: plaintext [u16 3][00 06 00] before anything
        #    else (the real client fires its 1000 only after this frame)
        ack = wire.read_frame(client)
        self.assertEqual(ack, wire.ROUTE_ACK_BODY)

        # 3. duplicated heartbeat lane (§15.2: two identical connections)
        hb_socks = [socket.create_connection((gw.host, gw.relay.port), timeout=5)
                    for _ in range(2)]
        hb_received = [b"", b""]
        for i, s in enumerate(hb_socks):
            self.addCleanup(s.close)
            threading.Thread(target=self._hb_reader, args=(s, hb_received, i),
                             daemon=True).start()
            s.sendall(wire.HEARTBEAT_C2S)

        # 4. join: encrypted PLAYER_UUID(1000) with the session uuid — the
        #    identity the roster must bind (corpus c2s 1000: uuid + 34 zero)
        client.sendall(wire.encode_message(self.cipher, wire.OP.PLAYER_UUID,
                                           SESSION_UUID.encode("ascii") + bytes(34)))
        #    the real client follows with 1112 + 1131; both get zero echoes
        client.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1112, bytes(6)))
        client.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1131, bytes(6)))

        # 5. opener burst in captured order: 1001 → 1108 → 1107 ×275 → 1113[0]
        seen = {}                               # opcode → payload
        order = []                              # opcode sequence
        catalog = 0
        deadline = time.monotonic() + 10.0
        while (wire.OP.SNAPSHOT_JOIN not in seen
               and len(order) < 300
               and time.monotonic() < deadline):
            op, payload = self._read_message(client)
            order.append(op)
            if op == wire.OP.HERO_CATALOG:
                catalog += 1
            else:
                seen[op] = payload
        self.assertIn(wire.OP.GAME_SETUP, seen)
        self.assertIn(wire.OP.GAME_MODE, seen)
        self.assertEqual(catalog, len(hero_catalog.HERO_CATALOG_1107_NAMES))
        self.assertEqual(order[0], wire.OP.GAME_SETUP)          # pcap order
        self.assertEqual(order[1], wire.OP.GAME_MODE)
        self.assertEqual(order[2 + catalog], wire.OP.SNAPSHOT_JOIN)
        self.assertIn(b"*GameMode_HF_SoloBots*", seen[wire.OP.GAME_SETUP])
        self.assertIn(b"*GameMode_HF_SoloBots*", seen[wire.OP.GAME_MODE])
        self.assertEqual(len(seen[wire.OP.GAME_SETUP]),
                         roster.GAME_SETUP_PAYLOAD_SIZE)        # corpus shape

        # 6. SNAPSHOT[0]: 2590 B, pre-pick countdown pair, flags 0000
        snap0 = seen[wire.OP.SNAPSHOT_JOIN]
        self.assertEqual(len(snap0), match_server.SNAPSHOT_PAYLOAD_SIZE)
        hdr_a, hdr_b = struct.unpack_from(">ff", snap0, 0)
        self.assertAlmostEqual(hdr_a, 298.717, places=3)   # pre-pick pair
        self.assertEqual(hdr_b, 300.0)
        self.assertEqual(snap0[10:12], b"\x00\x00")
        rec0 = snap0[16:16 + STRIDE]
        self.assertEqual(rec0[0], 1)                              # team (1-based)
        self.assertEqual(rec0[9:14], b"Guest")                    # +9 handle
        self.assertEqual(rec0[89:125].decode(), SESSION_UUID)     # +89 uuid
        self.assertEqual(struct.unpack_from(">H", rec0, 3)[0], 1500)
        self.assertEqual(rec0[154], 1)                            # slot
        self.assertIn(roster.BOT_UUID_SENTINEL.encode(), snap0)

        # s2c 1112/1131 echoes ride after the opener burst (corpus: +0.78 s).
        # The 2.5 Hz pick stream may interleave a snapshot between events
        # that land in different pump windows — skip those; the echo contract
        # itself (opcode + 6 B zeros) is still asserted exactly.
        for echo_op in (wire.OP.JOIN_1112, wire.OP.JOIN_1131):
            for _ in range(5):
                op, payload = self._read_message(client)
                if op == echo_op:
                    self.assertEqual(payload, bytes(6))
                    break
                self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
            else:
                self.fail(f"no {echo_op} echo among the pick-phase frames")

        # No invented hero ID, unsolicited 1118 or gameplay dump during pick.
        self.assertEqual(struct.unpack_from(">H", snap0, 17)[0], 0xffff)
        for _ in range(5):
            op, snapshot = self._read_message(client)
            self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
            self.assertEqual(struct.unpack_from(">H", snapshot, 17)[0], 0xffff)
            self.assertEqual(snapshot[10:12], bytes(2))

        # The real client initiates 1118, and can change its selected hero.
        for hero_id, selection_hash in ((925, 0x2fd7245d), (244, 0xf9fd7554)):
            selection = struct.pack(">II", hero_id, selection_hash) + bytes(6)
            client.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118, selection))
            for _ in range(10):
                op, payload = self._read_message(client)
                if op == wire.OP.JOIN_1118:
                    self.assertEqual(payload, selection)
                    break
                self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
            else:
                self.fail("client selection was not acknowledged")
            op, snapshot = self._read_message(client)
            self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
            self.assertEqual(struct.unpack_from(">H", snapshot, 17)[0], hero_id)
            self.assertEqual(struct.unpack_from(">I", snapshot, 21)[0], selection_hash)
            self.assertEqual(snapshot[10:12], b"\x01\x00")   # selected, unlocked

        # 7. Lock, corpus order: c2s 1123 + c2s 1119 (committed hash) arrive
        #    together; server answers 1113(0101, clicked hash) → 1123 echo →
        #    1113(committed hash) → 1119 echo → 8× 1113 burst, all slots locked.
        old_countdown = match_server.LOCK_COUNTDOWN
        match_server.LOCK_COUNTDOWN = 0.5      # timing only, assertions unchanged
        try:
            committed = 0x4260123e             # corpus committed value
            client.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK, bytes(6)))
            client.sendall(wire.encode_message(
                self.cipher, wire.OP.LOCK_COMMIT, struct.pack(">I", committed) + bytes(2)))

            op, snapshot = self._read_message(client)
            self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
            self.assertEqual(snapshot[10:12], b"\x01\x01")       # local locked
            self.assertEqual(snapshot[171:173], bytes(2))        # bots still unpicked
            op, payload = self._read_message(client)
            self.assertEqual((op, payload), (wire.OP.BUILD_LOCK, bytes(6)))
            op, snapshot = self._read_message(client)
            self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
            self.assertEqual(struct.unpack_from(">I", snapshot, 21)[0], committed)
            op, payload = self._read_message(client)
            self.assertEqual(op, wire.OP.LOCK_COMMIT)
            self.assertEqual(payload, struct.pack(">I", committed) + bytes(2))
            for _ in range(match_server.LOCK_BURST):
                op, snapshot = self._read_message(client)
                self.assertEqual(op, wire.OP.SNAPSHOT_JOIN)
                self.assertEqual(struct.unpack_from(">ff", snapshot),
                                 (match_server.LOCK_COUNTDOWN, match_server.LOCK_COUNTDOWN))
                for k in range(ROSTER_SIZE):
                    base = 8 + k * STRIDE
                    self.assertEqual(struct.unpack_from(">H", snapshot, base + 2)[0],
                                     0x0101)
                    self.assertNotEqual(struct.unpack_from(">H", snapshot, base + 9)[0],
                                        0xffff)

            # countdown drains → 1006×6 (final, committed hashes) + 1132
            while True:
                op, payload = self._read_message(client)
                if op != wire.OP.SNAPSHOT_JOIN:
                    break
                self.assertLessEqual(struct.unpack_from(">f", payload)[0],
                                     match_server.LOCK_COUNTDOWN)
            finals = [payload]
            for _ in range(5):
                op, payload = self._read_message(client)
                self.assertEqual(op, wire.OP.PLAYER_INFO)
                finals.append(payload)
            self.assertEqual({len(f) for f in finals}, {roster.PLAYER_INFO_PAYLOAD_SIZE})
            self.assertEqual(struct.unpack_from(">I", finals[0], 168)[0], committed)
            self.assertEqual([struct.unpack_from(">I", f, 164)[0] for f in finals],
                             [244] + [h for h, _ in roster.BOT_HERO_CHOICES])
            op, payload = self._read_message(client)
            self.assertEqual((op, payload), (wire.OP.ROSTER_FINAL, bytes(6)))

            # 8. client map-load done → 1134; server dumps world init, echoes
            #    the frame, then pings 1116 (corpus: echoes precede the ping)
            client.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN, bytes(6)))
            dump = []
            op = None
            while op != wire.OP.SHOP_OPEN:
                op, payload = self._read_message(client)
                dump.append((op, payload))
            self.assertEqual(dump[0][0], wire.OP.MODE_NAME)
            self.assertEqual([o for o, _ in dump[1:7]], [wire.OP.PLAYER_INFO] * 6)
            self.assertEqual(dump[7][0], wire.OP.MODE_PING_1105)
            self.assertEqual(dump[7][1], bytes(6))
            block_ops = [o for o, _ in dump]
            blocks = [i for i, o in enumerate(block_ops) if o == wire.OP.HERO_BLOCK]
            self.assertEqual(len(blocks), 6)
            self.assertEqual(block_ops[blocks[0] + 1:blocks[0] + 8],
                             [wire.OP.TIMER_TICK] * 7)
            first_block = dump[blocks[0]][1]
            self.assertEqual(len(first_block), roster.HERO_BLOCK_PAYLOAD_SIZE)
            self.assertEqual(struct.unpack_from(">I", first_block, 8)[0], 1519)  # reverse
            self.assertEqual(struct.unpack_from(">I", first_block, 0)[0],
                             roster.BOT_HERO_CHOICES[-1][0])
            tags = [p for o, p in dump if o == wire.OP.PLAYER_TAG]
            self.assertEqual(len(tags), 6)
            for t in tags:
                self.assertEqual(len(t), roster.PLAYER_TAG_PAYLOAD_SIZE)
            # 1134 echo (consumed by the loop above) then the first 1116 ping
            self.assertEqual(dump[-1], (wire.OP.SHOP_OPEN, bytes(6)))
            op, ping = self._read_message(client)
            self.assertEqual(op, wire.OP.SLOT_FLAGS_PING)
            self.assertEqual(len(ping), roster.SLOT_FLAGS_PAYLOAD_SIZE)
            self.assertEqual(struct.unpack_from(">IH", ping, 0), (1500, 0x0100))
            self.assertEqual(struct.unpack_from(">IH", ping, 6), (1515, 0x0101))

            # 9. 1137 echo verbatim (corpus s2c 00 00 05 dc 01 00)
            ready = bytes.fromhex("000005dc0100")
            client.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY, ready))
            op, payload = self._read_message(client)
            self.assertEqual((op, payload), (wire.OP.HERO_READY, ready))

            # 9b. movement slice: c2s 1012 → 1070 stream for eid 1500 from
            #     the corpus spawn toward the target; arrival ends the stream
            #     (2 u at the measured 5 u/s ≈ 0.4 s of travel)
            target = (roster.SPAWN_X + 2.0, roster.SPAWN_Y)
            client.sendall(wire.encode_message(
                self.cipher, wire.OP.MOVE_CAST,
                struct.pack(">ff", *target) + bytes(6)))
            seen = []
            move_targets = []
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                try:
                    op, payload = self._read_message(client, timeout=0.8)
                except (AssertionError, TimeoutError):
                    break                       # quiet: movement finished
                if op == wire.OP.MOVE_TO:
                    self.assertEqual(seen, [], "1016 must precede the first correction")
                    self.assertEqual(payload, struct.pack(">Bff", 0, *target) + bytes(5))
                    move_targets.append(payload)
                    self.assertEqual(len(move_targets), 1, "one activation per input")
                elif op == wire.OP.POSITION:
                    self.assertEqual(len(move_targets), 1)
                    self.assertEqual(len(payload), roster.POSITION_PAYLOAD_SIZE)
                    eid, x, y, pad = struct.unpack(">IffH", payload)
                    self.assertEqual((eid, pad), (1500, 0))
                    seen.append((x, y))
                elif op == wire.OP.ENTITY_STATE:
                    pass
                else:
                    self.assertEqual(op, wire.OP.SLOT_FLAGS_PING)  # 1116-only world
            self.assertEqual(len(move_targets), 1)
            self.assertTrue(seen, "no 1070 position frames after 1012")
            self.assertEqual(seen[0], (roster.SPAWN_X, roster.SPAWN_Y))
            self.assertEqual(seen[-1], target)
            walked = [roster.SPAWN_X] + [x for x, _ in seen]
            self.assertEqual(walked, sorted(walked))           # monotone approach
            self.assertGreaterEqual(len(seen), 2)
        finally:
            match_server.LOCK_COUNTDOWN = old_countdown

        # 11. keepalive op 0 consumed server-side, no reply, connection lives
        client.sendall(wire.build_keepalive(self.cipher, 0x0788))
        time.sleep(0.3)
        match = [m for m in gw.matches]
        self.assertTrue(match, "gateway spawned no match server")
        self.assertEqual(match[-1].keepalive_ticks, [0x0788])
        self.assertEqual(match[-1].session_uuid, SESSION_UUID)
        join_ops = [op for op, _ in match[-1].join_sequence]
        self.assertEqual(join_ops[0], wire.OP.PLAYER_UUID)

        # 12. heartbeat lane: both duplicated connections got 89 00 beats
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and min(map(len, hb_received)) < 4:
            time.sleep(0.05)
        for buf in hb_received:
            self.assertGreaterEqual(len(buf), 2)
            self.assertEqual(buf[:2], b"\x89\x00")
            self.assertTrue(all(buf[i:i + 2] == b"\x89\x00" for i in range(0, len(buf), 2)))
        self.assertGreaterEqual(self.gw.relay.client_beats, 2)   # both lanes answered

        # 13. one match spawned on a dynamic OS-assigned port
        self.assertNotEqual(match[-1].port, 0)
        self.assertEqual(gw.routes[-1][0], "127.0.0.1")

        for s in hb_socks:
            s.close()
        client.close()


class TestKeyAutoDetection(unittest.TestCase):
    """The session+0xa8 writer is an open RE question; the client's first
    encrypted frame names the key it derived. Whatever key the client used,
    the server must adopt it — the match is the measurement."""

    @classmethod
    def setUpClass(cls):
        cls.gw = gateway.Gateway("127.0.0.1", port=0, match_id=MATCH_ID,
                                 heartbeat_port=0, heartbeat_interval=0.05)
        cls.gw.start()

    @classmethod
    def tearDownClass(cls):
        cls.gw.stop()

    def _exchange(self, client_key_id):
        client = socket.create_connection((self.gw.host, self.gw.port), timeout=5)
        client.sendall(wire.build_route_request("127.0.0.1"))
        self.assertEqual(wire.read_frame(client), wire.ROUTE_ACK_BODY)
        cipher = wire.MatchCipher(client_key_id)
        client.sendall(wire.encode_message(cipher, wire.OP.PLAYER_UUID,
                                           SESSION_UUID.encode("ascii")))
        # the reply must come back under the SAME key the client used
        body = wire.read_frame(client)
        self.assertIsNotNone(body)
        op, payload = wire.decode_body(cipher, body)
        self.assertEqual(op, wire.OP.GAME_SETUP)
        match = self.gw.matches[-1]
        self.assertEqual(match.session_uuid, SESSION_UUID)
        client.close()
        return match

    def test_client_using_match_id_key(self):
        match = self._exchange(MATCH_ID)
        self.assertEqual(match.cipher.key, wire.key_for(MATCH_ID))

    def test_client_using_empty_session_string_key(self):
        # session+0xa8 never filled: the ctor-default empty SSO string
        match = self._exchange("")
        self.assertEqual(match.cipher.key, wire.key_for(""))
        self.assertNotEqual(match.cipher.key, wire.key_for(MATCH_ID))


class TestWaveE2E(unittest.TestCase):
    """T3 slice 2: the no-tape world spawns the measured lane-minion wave —
    10 minions (5 right/left pairs) with the corpus spawn sequence
    1010 → 1016 → 1070(B) → 1070(A) → 1067(00) → 1067(0f), then walking
    1070s. HALCYON_NO_WAVE=1 must silence the whole layer. Corpus timing is
    unit-pinned in test_wave; here the schedule constants are shrunk so the
    socket flow runs in seconds."""

    @classmethod
    def setUpClass(cls):
        cls.gw = gateway.Gateway("127.0.0.1", port=0, match_id=MATCH_ID,
                                 heartbeat_port=0, heartbeat_interval=0.05)
        cls.gw.start()
        cls.cipher = wire.MatchCipher(MATCH_ID)
        cls.tempdir = tempfile.mkdtemp(prefix="halcyon-wave-")
        cls._old = (match_server.WORLD_TAPE_PATH, match_server.LOCK_COUNTDOWN,
                    roster.WAVE_FIRST_SPAWN_AT, roster.WAVE_PAIR_OFFSETS,
                    roster.WAVE_STATE_DELAY, roster.MINION_POSITION_PERIOD,
                    roster.MINION_SPEED, roster.WAVE_INTERVAL)
        match_server.WORLD_TAPE_PATH = os.path.join(cls.tempdir, "no-tape.bin")
        match_server.LOCK_COUNTDOWN = 0.3
        roster.WAVE_FIRST_SPAWN_AT = 0.5
        roster.WAVE_PAIR_OFFSETS = (0.00, 0.20, 0.40, 0.60, 0.80)
        roster.WAVE_STATE_DELAY = 0.02
        roster.MINION_POSITION_PERIOD = 0.3
        roster.MINION_SPEED = 30.0
        roster.WAVE_INTERVAL = 10.0

    @classmethod
    def tearDownClass(cls):
        cls.gw.stop()
        shutil.rmtree(cls.tempdir, ignore_errors=True)
        (match_server.WORLD_TAPE_PATH, match_server.LOCK_COUNTDOWN,
         roster.WAVE_FIRST_SPAWN_AT, roster.WAVE_PAIR_OFFSETS,
         roster.WAVE_STATE_DELAY, roster.MINION_POSITION_PERIOD,
         roster.MINION_SPEED, roster.WAVE_INTERVAL) = cls._old

    def tearDown(self):
        # same isolation as TestGatewayFlow: world matches outlive their
        # clients now, so each test stops the match it used
        if self.gw.matches:
            self.gw.matches[-1].stop()

    def _read_message(self, sock, timeout=5.0):
        """One encrypted message → (opcode, payload); skips nothing."""
        sock.settimeout(max(0.05, timeout))
        body = wire.read_frame(sock)
        self.assertIsNotNone(body)
        return wire.decode_body(self.cipher, body)

    def _join_to_world(self, client):
        """Route → join → pick → lock → dump → WORLD; returns after the
        1137 echo (the world is live). Any pick-phase frame zoo is skipped —
        only the awaited frame ends each stage (the existing suite's
        strict=False convention)."""
        client.sendall(wire.build_route_request("127.0.0.1"))
        self.assertEqual(wire.read_frame(client), wire.ROUTE_ACK_BODY)
        client.sendall(wire.encode_message(
            self.cipher, wire.OP.PLAYER_UUID,
            SESSION_UUID.encode("ascii") + bytes(34)))

        def await_op(want, timeout=8.0):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                op, payload = self._read_message(
                    client, timeout=deadline - time.monotonic())
                if op == want:
                    return payload
            self.fail(f"expected opcode {want} not arrived")

        await_op(wire.OP.SNAPSHOT_JOIN)                  # opener → snapshot
        selection = struct.pack(">II", 925, 0x2fd7245d) + bytes(6)
        client.sendall(wire.encode_message(self.cipher, wire.OP.JOIN_1118,
                                           selection))
        await_op(wire.OP.JOIN_1118)                      # pick echo
        client.sendall(wire.encode_message(self.cipher, wire.OP.BUILD_LOCK,
                                           bytes(6)))
        client.sendall(wire.encode_message(
            self.cipher, wire.OP.LOCK_COMMIT,
            struct.pack(">I", 0x4260123e) + bytes(2)))
        finals = []
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:               # lock countdown → finals
            op, payload = self._read_message(
                client, timeout=deadline - time.monotonic())
            if op == wire.OP.PLAYER_INFO:
                finals.append(payload)
            elif op == wire.OP.ROSTER_FINAL:
                break
        self.assertEqual(len(finals), 6)                 # 1006×6 then 1132

        # client map-load done: 1134 → dump → 1134 echo; 1137 → verbatim echo
        client.sendall(wire.encode_message(self.cipher, wire.OP.SHOP_OPEN,
                                           bytes(6)))
        await_op(wire.OP.SHOP_OPEN)
        ready = bytes.fromhex("000005dc0100")
        client.sendall(wire.encode_message(self.cipher, wire.OP.HERO_READY,
                                           ready))
        self.assertEqual(await_op(wire.OP.HERO_READY, timeout=5.0), ready)

    def _read_wave_stream(self, client, seconds):
        """Collect minion-layer frames for a while; only 1116 pings may
        interleave. 1054/1073/1035 are part of the live stream now — the
        walkers meet and fight inside this window (combat layer)."""
        allowed = {wire.OP.SLOT_FLAGS_PING, wire.OP.ENTITY_FULL_UPDATE,
                   wire.OP.POSITION, wire.OP.ENTITY_STATE, wire.OP.ENTITY_FLOAT,
                   wire.OP.COMBAT_DELTA, wire.OP.DESTROY, wire.OP.DESPAWN}
        out = []
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                op, payload = self._read_message(
                    client, timeout=deadline - time.monotonic())
            except (socket.timeout, TimeoutError):
                break
            self.assertIn(op, allowed)
            if op != wire.OP.SLOT_FLAGS_PING:
                out.append((op, payload))
        return out

    def test_wave_spawn_sequence_and_movement(self):
        client = socket.create_connection((self.gw.host, self.gw.port),
                                          timeout=5)
        self.addCleanup(client.close)
        self._join_to_world(client)
        frames = self._read_wave_stream(client, 6.0)
        ops = [op for op, _ in frames]

        # first pair: the corpus burst order
        self.assertEqual(ops[:10],
                         [wire.OP.ENTITY_FULL_UPDATE, wire.OP.ENTITY_FLOAT,
                          wire.OP.POSITION, wire.OP.ENTITY_FULL_UPDATE,
                          wire.OP.ENTITY_FLOAT, wire.OP.POSITION,
                          wire.OP.POSITION, wire.OP.POSITION,
                          wire.OP.ENTITY_STATE, wire.OP.ENTITY_STATE])
        spawn0 = frames[0][1]
        self.assertEqual(len(spawn0), roster.ENTITY_FULL_UPDATE_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">I", spawn0, 0)[0], 366)
        self.assertEqual(struct.unpack_from(">I", spawn0, 4)[0],
                         roster.LANE_MINION_CLASS)
        self.assertEqual(struct.unpack_from(">I", spawn0, 8)[0], 4610)
        self.assertEqual(spawn0[116], 1)                 # seq: tape-less → 1
        spawn1 = frames[3][1]
        self.assertEqual(struct.unpack_from(">I", spawn1, 8)[0], 4611)
        self.assertEqual(spawn1[116], 2)
        # 10 minions, eids sequential, spawners = wave-1 measured set
        spawns = [p for op, p in frames if op == wire.OP.ENTITY_FULL_UPDATE]
        self.assertEqual(
            len(spawns), 10,
            msg=[(struct.unpack_from(">I", p, 0)[0],
                  struct.unpack_from(">I", p, 8)[0]) for p in spawns])
        self.assertEqual([struct.unpack_from(">I", p, 8)[0] for p in spawns],
                         list(range(4610, 4620)))
        self.assertEqual([struct.unpack_from(">I", p, 0)[0] for p in spawns],
                         [s for s in roster.LANE_SPAWNER_EIDS for _ in (0, 1)])
        # 20 1067s; per minion exactly one SPAWNED (00) then one MOVING (0f)
        # — the corpus emits each pair's moving states WAVE_STATE_DELAY after
        # its own spawn, so the flat order interleaves across pairs
        states = [p for op, p in frames if op == wire.OP.ENTITY_STATE]
        self.assertEqual(len(states), 20)
        state_hist = {}
        for p in states:
            state_hist.setdefault(struct.unpack_from(">I", p, 0)[0], []) \
                     .append(p[6])
        self.assertEqual(set(state_hist), set(range(4610, 4620)))
        for hist in state_hist.values():
            self.assertEqual(hist, [roster.ENTITY_STATE_SPAWNED,
                                    roster.ENTITY_STATE_MOVING])
        # walking: eid 4610 advances toward its first lane point (x drops
        # from 71.28), then rests at the lane end (speed-patched 30 u/s)
        path = [struct.unpack_from(">ff", p, 4)
                for op, p in frames if op == wire.OP.POSITION
                and struct.unpack_from(">I", p, 0)[0] == 4610]
        self.assertGreaterEqual(len(path), 4)
        self.assertAlmostEqual(path[0][0], roster.LANE_SPAWN_RIGHT[0], places=3)
        self.assertLess(path[-1][0], 65.62)              # past the first node
        self.assertEqual((round(path[-1][0], 2), round(path[-1][1], 2)),
                         (round(roster.LANE_PATH_RIGHT[-1][0], 2),
                          round(roster.LANE_PATH_RIGHT[-1][1], 2)))

    def test_no_wave_env_kills_the_layer(self):
        old = os.environ.get("HALCYON_NO_WAVE")
        os.environ["HALCYON_NO_WAVE"] = "1"
        try:
            client = socket.create_connection((self.gw.host, self.gw.port),
                                              timeout=5)
            self.addCleanup(client.close)
            self._join_to_world(client)
            frames = self._read_wave_stream(client, 3.0)
            self.assertEqual(frames, [])                 # 1116-only world
        finally:
            if old is None:
                os.environ.pop("HALCYON_NO_WAVE", None)
            else:
                os.environ["HALCYON_NO_WAVE"] = old


if __name__ == "__main__":
    unittest.main()
