"""Project Halcyon — T2 match server (Phase 0 stub).

Speaks the match side of the wire via wire.py:

  * accepts the (already gateway-proxied) client connection, auto-detects
    which key candidate the client derived (matchId / empty session string /
    JWT sessionId — the session+0xa8 writer is still an open RE question),
    and logs the c2s join sequence (1000 → 1112/1131/1118/1123 → 1134/1137/
    1133 …), tracking keepalive ticks;
  * answers PLAYER_UUID(1000) with the captured join-opener burst
    (2026-09-06 corpus decode, pcap-ordered): GAME_SETUP(1001) fixture,
    GAME_MODE(1108) fixture, HERO_CATALOG(1107) ×275, SNAPSHOT(1113) —
  * runs the §15.2 heartbeat relay as a SEPARATE listener (s2c ``89 00``
    every interval, c2s ``8a 80 12 34 56 78``), accepting any number of
    duplicated control connections like production.

Honest stub boundary: GAME_SETUP payload and everything the SNAPSHOT carries
beyond its measured shape are placeholders until T3. What IS faithful here:
frame grammar, crypto, opcode values, SNAPSHOT payload size 2590 B, record
stride 161, field offsets (+8 slot, +15 team, +18 eid, +24 handle 32 B,
+104 uuid 36 B), bot uuid sentinel, 2×f32 countdown header (§15.8).
"""
from __future__ import annotations

import os
import select
import socket
import struct
import sys
import threading
import time
import uuid as uuidlib

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import wire
    import hero_catalog
else:
    from . import wire
    from . import hero_catalog


# --------------------------------------------------------------------------
# SNAPSHOT(1114) builder — faithful shape, placeholder content (§15.8)
# --------------------------------------------------------------------------

SNAPSHOT_PAYLOAD_SIZE = 2590   # the 2,592 B wire frames minus the u16 opcode
SNAPSHOT_RECORD_STRIDE = 161
SNAPSHOT_RECORD_COUNT = 6
BOT_UUID_SENTINEL = "__Kindred_Player_Bot__"
GAME_MODE_SOLO_BOTS = b"*GameMode_HF_SoloBots*"


def default_solo_bots_players():
    """(handle, team, eid, uuid) — hero eids per §15.8 (1500 + 1515–1519)."""
    handles = ["Guest", "Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    eids = (1500, 1515, 1516, 1517, 1518, 1519)
    return [(handles[i], 0 if i < 3 else 1, eids[i],
             str(uuidlib.uuid4()) if i == 0 else BOT_UUID_SENTINEL)
            for i in range(SNAPSHOT_RECORD_COUNT)]


def build_snapshot(players=None, countdown=(300.0, 300.0)) -> bytes:
    """Build a 2590 B SNAPSHOT(1114) payload: 2 f32 header + 6×161 records
    + unmapped tail as zeros (§15.8: 1.6 KB of additional world fields)."""
    if players is None:
        players = default_solo_bots_players()
    records = bytearray()
    for slot, (handle, team, eid, uid) in enumerate(players):
        rec = bytearray(SNAPSHOT_RECORD_STRIDE)
        struct.pack_into(">H", rec, 8, slot)       # +8  slot
        rec[15] = team & 0xFF                      # +15 team
        struct.pack_into(">H", rec, 18, eid)       # +18 eid
        name = handle.encode("ascii")[:32]         # +24 handle, 32 B NUL-padded
        rec[24:24 + len(name)] = name
        ident = uid.encode("ascii")[:36]           # +104 uuid, 36 B NUL-padded
        rec[104:104 + len(ident)] = ident
        records += rec
    payload = struct.pack(">ff", *countdown) + bytes(records)
    payload += bytes(SNAPSHOT_PAYLOAD_SIZE - len(payload))
    assert len(payload) == SNAPSHOT_PAYLOAD_SIZE
    return bytes(payload)


# --------------------------------------------------------------------------
# Heartbeat relay (§15.2) — separate lane, never the match socket
# --------------------------------------------------------------------------

class HeartbeatRelay:
    def __init__(self, host="127.0.0.1", port=2112, interval=wire.HEARTBEAT_INTERVAL):
        self.host, self.port, self.interval = host, port, interval
        self.beats_sent = 0
        self.client_beats = 0
        self._stop = threading.Event()
        self._listener = None
        self._conns = []
        self._threads = []

    def start(self):
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()
        self._threads.append(t)

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except OSError:
                break
            self._conns.append(conn)
            t = threading.Thread(target=self._conn_loop, args=(conn,), daemon=True)
            t.start()
            self._threads.append(t)

    def _conn_loop(self, conn):
        conn.setblocking(False)
        next_beat = time.monotonic()
        buf = b""
        try:
            while not self._stop.is_set():
                wait = max(0.0, next_beat - time.monotonic())
                try:
                    readable, _, _ = select.select([conn], [], [], wait)
                except OSError:             # socket closed under us (stop())
                    return
                if readable:
                    try:
                        data = conn.recv(64)
                    except OSError:
                        return
                    if data == b"":               # EOF — client gone
                        return
                    if data:
                        buf += data
                        while len(buf) >= len(wire.HEARTBEAT_C2S):
                            if buf.startswith(wire.HEARTBEAT_C2S):
                                self.client_beats += 1
                                buf = buf[len(wire.HEARTBEAT_C2S):]
                            else:                 # resync on garbage
                                buf = buf[1:]
                if time.monotonic() >= next_beat:
                    try:
                        conn.sendall(wire.HEARTBEAT_S2C)
                    except OSError:
                        return
                    self.beats_sent += 1
                    next_beat += self.interval
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        self._stop.set()
        for s in [self._listener] + self._conns:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


# --------------------------------------------------------------------------
# Match server (T2 stub)
# --------------------------------------------------------------------------

class MatchServer:
    def __init__(self, host="127.0.0.1", match_id: str = "00000000-1111-4222-8333-444455556666",
                 port: int = 0, log=print):
        self.host = host
        self.match_id = match_id
        self.cipher = wire.MatchCipher(match_id)
        self.log = log
        self.keepalive_ticks = []          # parsed u16 ticks, in order
        self.join_sequence = []            # (opcode, payload) of every c2s frame
        self.session_uuid = None
        self._stop = threading.Event()
        self._listener = None
        self._conns = []
        self.port = port                   # 0 = OS-assigned in start()

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))   # port 0 = OS-assigned, dynamic per match
        self._listener.listen(4)
        self.port = self._listener.getsockname()[1]   # dynamic per match (§15.1)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        for s in [self._listener] + self._conns:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except OSError:
                break
            self._conns.append(conn)
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    # -- frame loop --------------------------------------------------------

    def _handle(self, conn):
        # Long idle read: after its join handshakes the client sits silent
        # through the pre-join pick phase (keepalives only start in steady
        # state); a 30 s timeout here killed the join and drove a 30 s
        # client reconnect loop (observed 2026-09-06, gateway_log 10:06-10:09).
        conn.settimeout(300)
        peer = conn.getpeername()
        try:
            key_named = False
            while not self._stop.is_set():
                body = wire.read_frame(conn)
                if body is None:
                    self.log(f"[match] {peer} EOF")
                    return
                if not key_named:
                    # The client's Blowfish key = MD5(SALT || <session+0xa8>),
                    # and which platform write fills session+0xa8 is still an
                    # open RE question. The client's FIRST encrypted frame
                    # names the key it derived: adopt the candidate that
                    # yields a dispatch-range opcode and log which one — the
                    # match itself is the measurement.
                    named = self._adopt_key(body)
                    key_named = True
                    self.log(f"[match] {peer} key candidate matched: {named!r}")
                opcode, payload = wire.decode_body(self.cipher, body)
                self.join_sequence.append((opcode, payload))
                self._dispatch(conn, opcode, payload)
        except (wire.WireError, OSError) as exc:
            self.log(f"[match] {peer} closed: {exc!r}")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    # Candidates for the string at session+0xa8, most likely first:
    #   matchId  — the matchId our platform layer serves (qPM/acceptMatch)
    #   ""       — the session string ctor default (empty SSO string)
    #   JWT sid  — the sessionId inside the synthetic sessionToken
    ALT_KEY_CANDIDATES = ("", "a92371d5-ef49-4cd0-959a-6a7042f074d9")

    def _adopt_key(self, body: bytes) -> str:
        """Pick the cipher whose key decrypts the first c2s frame into the
        dispatch range; keep it for the whole match."""
        for cand in (self.match_id,) + self.ALT_KEY_CANDIDATES:
            probe = wire.MatchCipher(cand)
            try:
                opcode, _ = wire.decode_body(probe, body)
            except wire.WireError:
                continue
            if (opcode == wire.OP.PLAYER_UUID
                    or opcode == wire.OP.KEEPALIVE
                    or wire.DISPATCH_MIN <= opcode <= wire.DISPATCH_MAX):
                self.cipher = probe
                return cand or "<empty string>"
        # Nothing matched — keep the matchId key and let dispatch log the
        # garbage opcode (never weaken the check to fake a pass).
        self.cipher = wire.MatchCipher(self.match_id)
        return "<none — dispatch garbage>"

    def _dispatch(self, conn, opcode, payload):
        if opcode == wire.OP.KEEPALIVE:
            tick = wire.parse_keepalive(payload)
            self.keepalive_ticks.append(tick)
            return  # consumed, no reply (§15.8: tick ≈513/s rising)
        if opcode == wire.OP.PLAYER_UUID:
            self.session_uuid = payload.split(b"\x00", 1)[0].decode("ascii", "replace")
            self.log(f"[match] join: session uuid {self.session_uuid}")
            # Faithful join-opener burst, pcap-ordered (2026-09-06 decode):
            # 1001 GAME_SETUP → 1108 GAME_MODE → 1107 ×catalog → 1113
            # snapshot; the client follows with 1112/1131/1118/1123.
            self._send(conn, wire.OP.GAME_SETUP, hero_catalog.GAME_SETUP_1001_PAYLOAD)
            self._send(conn, wire.OP.GAME_MODE, hero_catalog.GAME_MODE_1108_PAYLOAD)
            for name in hero_catalog.HERO_CATALOG_1107_NAMES:
                self._send(conn, wire.OP.HERO_CATALOG, hero_catalog.catalog_payload(name))
            self._send(conn, 1113, build_snapshot(countdown=(298.86, 300.0)))
            return
        # Join handshakes (1112/1118/1123/1131/1119/1134/1137/1133/1157/1012/1081…)
        # are logged above; replies are T3 work.
        self.log(f"[match] c2s op={opcode} ({len(payload)} B)")

    def _send(self, conn, opcode, payload):
        conn.sendall(wire.encode_message(self.cipher, opcode, payload))


# --------------------------------------------------------------------------
# CLI: stand alone (no gateway) for manual poking
# --------------------------------------------------------------------------

def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Project Halcyon T2 match server (stub)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0, help="0 = dynamic per match (faithful)")
    ap.add_argument("--match-id", default="00000000-1111-4222-8333-444455556666")
    ap.add_argument("--heartbeat-port", type=int, default=2112)
    ap.add_argument("--heartbeat-interval", type=float, default=wire.HEARTBEAT_INTERVAL)
    args = ap.parse_args(argv)

    relay = HeartbeatRelay(args.host, args.heartbeat_port, args.heartbeat_interval)
    relay.start()
    ms = MatchServer(args.host, args.match_id, args.port)
    ms.start()   # port 0 → OS-assigned, reported below
    print(f"match server: {ms.host}:{ms.port} match_id={args.match_id}")
    print(f"heartbeat relay: {relay.host}:{relay.port} every {args.heartbeat_interval}s")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        relay.stop()
        ms.stop()


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
