"""Local match transport: join, hero pick, lock, and the world-init handoff.

Corpus-measured exchange (vgfull.pcap match 1, 2026-09-06 ACK-precise trace):

  c2s 1000 → opener burst (1001, 1108, 1107×275, 1113[0] flags 0000)
  c2s 1112/1131  → zero-payload echoes (s2c 1112, 1131)
  c2s 1118 (hero, hash) → s2c 1118 echo + 1113 slot 0100 with that pair
  c2s 1123 (lock) → 1113 (slot 0101) + s2c 1123 zero echo
  c2s 1119 [u32 committed hash] → 1113 with the committed hash + s2c 1119
      echo; the roster locks: bots get their hero choices, and the 7.0 s
      countdown restarts with a burst of 8× 1113 at (7.0, 7.0), then ~10 Hz
      down to 0.
  at 0 → 1006×6 (final, committed hashes) + 1132
  c2s 1134/1137 (client map-load done) → world dump: 1135, 1006×6, 1105,
      (1011 + 1162×7) per hero in reverse roster order, 1055×6, 1134/1137
      echoes.

World-entity layer (corpus: 1087 allocations, 1053/1086/1067/1164/1045
deltas, 1010 full updates — measured 0..12.5 s after 1137): replayed from
the tape file produced by the corpus extraction (world_tape.load_tape;
file outside the repo), then the live layer serves c2s 1012 with 1070 for
the local hero entity. Hero-1010 full updates exist behind
HALCYON_HERO_1010=1 only — the corpus (6645 1010s, matches 1+5) never
sends 1010 for a hero, and the live client aborted the match when we did
(2026-09-06); hero state rides 1011 blocks + 1070 + the delta stream.
HALCYON_NO_TAPE=1 skips the tape entirely for a pure-sim world. The first
deterministic sim slice (T3 slice 2) runs lane-minion waves after the tape:
the measured vg5_final spawn sequence (1010 class eb39ce55 → 1016 → 1070 →
1067 states) on the measured 25 s wave grid, kill switch HALCYON_NO_WAVE=1.
The remaining entity simulation (combat, jungle AI, vision) is later T3
work — no invented bytes go out, only measured replays, measured layouts
and sim-computed positions/ticks.
"""
from __future__ import annotations

import queue
import os
import select
import socket
import struct
import sys
import threading
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import hero_catalog
    import roster
    import wave
    import wire
    import world_tape
else:
    from . import hero_catalog
    from . import roster
    from . import wave
    from . import wire
    from . import world_tape

# Re-exports kept for callers of the old stub API (tests, tools).
SNAPSHOT_PAYLOAD_SIZE = roster.SNAPSHOT_PAYLOAD_SIZE
SNAPSHOT_RECORD_STRIDE = roster.SNAPSHOT_RECORD_STRIDE
SNAPSHOT_ROSTER_SIZE = roster.SNAPSHOT_ROSTER_SIZE
BOT_UUID_SENTINEL = roster.BOT_UUID_SENTINEL
GAME_MODE_SOLO_BOTS = roster.MODE_SOLO_BOTS
build_snapshot = roster.build_snapshot

# Captured presentation cadence. No authoritative gameplay runs here yet.
SNAPSHOT_INTERVAL = 0.4           # pick phase (~2.5 Hz, corpus)
LOCK_TICK = 0.1                   # lock countdown ticks at ~10 Hz (corpus)
LOCK_BURST = 8                    # identical 1113 frames at countdown start
PICK_COUNTDOWN_START = 300.0
LOCK_COUNTDOWN = 7.0
COMMIT_FALLBACK = 1.0             # s without c2s 1119 before locking anyway
WORLD_DUMP_FALLBACK = 40.0        # s after finalize before dumping regardless
# (corpus client fires 1134/1137 ~23 s after 1132; a client that skips the
# tutorial-build flow may never send them — the fallback keeps load moving)

# World-entity layer after the dump. The entity world (1087 allocations,
# 1053/1086/1067 deltas, 1010 full updates) is not simulated yet (T3); the
# WORLD phase replays the corpus-measured tape instead, then serves live
# movement: c2s 1012 → 1070 for the local hero entity.
WORLD_TAPE_PATH = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack",
                               "world_tape.bin")
WORLD_PUMP_TICK = 0.05            # s, world-loop pump/tick granularity


class SnapshotStream(threading.Thread):
    """Owns per-connection pick/lock state and all s2c writes after the opener."""

    PICK, LOCKED, FINAL, WORLD = "pick", "locked", "final", "world"

    def __init__(self, conn, players, match_id, send, log=print):
        super().__init__(daemon=True)
        self.conn = conn
        self.players = players
        self.match_id = match_id
        self._send = send
        self.log = log
        self._stop_event = threading.Event()
        self.events = queue.Queue()
        self.frames_sent = 0
        self.phase = self.PICK
        self.locked = False              # c2s 1123 received
        self.commit_hash = None          # c2s 1119 payload
        self.lock_requested_at = None
        self.lock_deadline = None
        self.dump_fallback_at = None
        self.dumped = False
        # movement slice state (local hero entity)
        self.hero_x = roster.SPAWN_X
        self.hero_y = roster.SPAWN_Y
        self.move_target = None           # (x, y) or None
        self.hero_facing = roster.FACING_DEFAULT   # (cos, sin), unit pair
        # Hero-1010 emission is OFF by default: all 6645 corpus 1010s
        # (matches 1+5) carry non-hero eids only, and the live client
        # closed the match socket 1 s after our first hero-1010 (2026-09-06
        # 14:58:18→19, re-queue followed). HALCYON_HERO_1010=1 re-enables
        # the sim slice for A/B work.
        self.emit_hero_1010 = bool(os.environ.get("HALCYON_HERO_1010"))
        # shared entity-write counters, 1010-carried (roster layout map):
        self.world_tick = 0               # u32 at +8 (1086 deltas will share it)
        self.seq_1010 = 0                 # u8 at +116, +1 per 1010 emitted
        self.tape_frames = None           # loaded lazily on WORLD entry
        self.tape_i = 0
        self.tape_done = False
        # lane-minion waves (T3 slice 2): measured vg5_final spawn sequence,
        # scheduled from the world anchor; HALCYON_NO_WAVE=1 disables the
        # whole wave layer (live falsification must be env-switchable)
        self.emit_waves = not os.environ.get("HALCYON_NO_WAVE")
        self.wave_director = None

    def stop(self):
        self._stop_event.set()

    def submit(self, opcode, payload):
        self.events.put((opcode, payload))

    # -- event handlers (all s2c writes happen on this single thread) ------

    def _send_snapshot(self, countdown):
        self._send(wire.OP.SNAPSHOT_JOIN,
                   roster.build_snapshot(self.players, countdown=countdown))
        self.frames_sent += 1

    def _apply_event(self, opcode, payload):
        player = self.players[0]
        if opcode == wire.OP.JOIN_1112 or opcode == wire.OP.JOIN_1131:
            self._send(opcode, roster.build_zero_ack())
        elif opcode == wire.OP.JOIN_1118:
            if self.locked:
                return                       # corpus: no re-pick after lock
            try:
                hero_id, selection_hash = roster.parse_hero_selection(payload)
            except ValueError as exc:
                self.log(f"[match] rejected hero selection: {exc}")
                return
            player.hero_id, player.selection_hash = hero_id, selection_hash
            player.pick_flags = roster.PICK_FLAG_SELECTED
            self._send(wire.OP.JOIN_1118, roster.build_hero_selection(player))
            self.log(f"[match] hero selected: id={hero_id} hash={selection_hash:08x}")
        elif opcode == wire.OP.BUILD_LOCK:
            if payload != bytes(6) or player.hero_id == roster.UNPICKED_HERO_ID:
                self.log("[match] rejected lock without a valid selection/payload")
                return
            if self.locked:
                return
            self.locked = True
            self.lock_requested_at = time.monotonic()
            player.pick_flags = roster.PICK_FLAG_LOCKED
            # corpus: 1113 (0101, clicked hash) → 1123 echo; the committed
            # 1113 follows once (or if) the 1119 commit is applied
            self._send_snapshot(self._pick_countdown())
            self._send(wire.OP.BUILD_LOCK, roster.build_zero_ack())
            if self.commit_hash is not None:
                self._begin_lock()
        elif opcode == wire.OP.LOCK_COMMIT:
            try:
                self.commit_hash = roster.parse_commit_hash(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1119 commit: {exc}")
                return
            if self.locked and self.phase == self.PICK:
                self._begin_lock()
        elif opcode in (wire.OP.SHOP_OPEN, wire.OP.HERO_READY):
            if self.phase == self.FINAL and not self.dumped:
                self._dump_world()
                self.phase = self.WORLD
            if self.dumped and self.tape_frames == []:
                # no-tape fallback: echo verbatim here; with a tape the
                # corpus stream replays the echoes at measured positions
                self._send(opcode, payload)
        elif opcode == wire.OP.BUY_CLOSE:
            self.log("[match] c2s 1133 build-select close — world bootstrap "
                     "replays the measured tape; sim is T3 work")
        elif opcode == wire.OP.MOVE_CAST:
            try:
                self.move_target = roster.parse_move(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1012 move: {exc}")
                return
            self.log(f"[match] move target ({self.move_target[0]:.2f}, "
                     f"{self.move_target[1]:.2f})")

    def _pick_countdown(self):
        remaining = max(0.0, self._pick_deadline - time.monotonic())
        return (remaining, PICK_COUNTDOWN_START)

    def _begin_lock(self, send_commit_ack: bool = True):
        """Corpus: 1113 with the committed hash → 1119 echo → the roster
        locks (bots take their heroes) and the 7.0 s countdown restarts
        with a burst of 8× identical snapshots."""
        if self.commit_hash is None:
            # fallback: a client that never sends 1119 keeps its clicked hash
            self.commit_hash = self.players[0].selection_hash
            send_commit_ack = False
            self.log("[match] no 1119 commit — locking with the 1118 hash")
        self.players[0].selection_hash = self.commit_hash
        self._send_snapshot(self._pick_countdown())
        if send_commit_ack:
            self._send(wire.OP.LOCK_COMMIT, roster.build_commit_ack(self.commit_hash))
        roster.commit_lock(self.players, self.commit_hash)
        self.phase = self.LOCKED
        self.lock_deadline = time.monotonic() + LOCK_COUNTDOWN
        self.log(f"[match] roster locked (committed hash {self.commit_hash:08x}); "
                 f"countdown {LOCK_COUNTDOWN}s")
        for _ in range(LOCK_BURST):
            self._send_snapshot((LOCK_COUNTDOWN, LOCK_COUNTDOWN))

    def _finalize(self):
        self.phase = self.FINAL
        for p in self.players:
            self._send(wire.OP.PLAYER_INFO, roster.build_player_info(p, self.match_id))
        self._send(wire.OP.ROSTER_FINAL, roster.build_zero_ack())
        self.dump_fallback_at = time.monotonic() + WORLD_DUMP_FALLBACK
        self.log("[match] roster finalized: 1006×6 + 1132; awaiting client "
                 "1134/1137 (map load)")

    def _load_tape(self):
        """Load once, before the dump so echo/1055 decisions can use it.
        tape_frames: None = not decided yet; [] = no usable tape;
        [frames] = replay mode. HALCYON_NO_TAPE skips the file entirely —
        the world starts straight at the live layer (pure-sim testing)."""
        if self.tape_frames is not None:
            return
        if os.environ.get("HALCYON_NO_TAPE"):
            self.log("[match] HALCYON_NO_TAPE set — skipping the corpus tape, "
                     "live layer only (1010/1070/1116)")
            self.tape_frames = []
            return
        try:
            frames = world_tape.load_tape(
                WORLD_TAPE_PATH, skip_until_op=wire.OP.ENTITY_DATA)
        except ValueError as exc:
            self.log(f"[match] corrupt world tape ({exc!r}) — ignoring")
            frames = None
        if frames:
            span = frames[-1][0] / 1000.0
            self.log(f"[match] world tape: {len(frames)} frames, "
                     f"{span:.1f}s (corpus bootstrap — sim is T3)")
            self.tape_frames = frames
            # the 1010 seq byte counts every entity full update the client
            # has seen — continue from the tape's tail, not from zero
            self.seq_1010 = sum(
                1 for _t, b in frames
                if struct.unpack_from(">H", b)[0] == wire.OP.ENTITY_FULL_UPDATE)
        else:
            self.log(f"[match] no world tape — echo/1055 fallback "
                     f"(expected at {WORLD_TAPE_PATH})")
            self.tape_frames = []

    def _dump_world(self):
        """1135, 1006×6, 1105, (1011 + 1162×7) reverse — corpus order, with
        the measured per-hero stat runs and timer sets. In tape mode the
        tape itself carries 1055×6, the 1087 allocations, the delta stream
        and the 1134/1137 echoes (all measured, at measured positions);
        without a tape we send our derived 1055s and rely on echoes."""
        self.dumped = True
        self._load_tape()
        tape = bool(self.tape_frames)
        self._send(wire.OP.MODE_NAME, roster.build_mode_name())
        for p in self.players:
            self._send(wire.OP.PLAYER_INFO, roster.build_player_info(p, self.match_id))
        self._send(wire.OP.MODE_PING_1105, roster.build_zero_ack())
        for p in reversed(self.players):
            self._send(wire.OP.HERO_BLOCK, roster.build_hero_block(p))
            hero_data = roster.HERO_INIT_DATA.get(p.hero_id)
            for k in range(roster.TIMERS_PER_HERO):
                if hero_data is not None and k < len(hero_data["timers"]):
                    tag, tail = hero_data["timers"][k]
                    self._send(wire.OP.TIMER_TICK,
                               roster.build_timer_tick(p.eid, tag, 0.0,
                                                       bytes.fromhex(tail)))
                else:
                    self._send(wire.OP.TIMER_TICK,
                               roster.build_timer_tick(p.eid, 0, 0.0))
        if not tape:
            for p in self.players:
                self._send(wire.OP.PLAYER_TAG, roster.build_player_tag(p, self.match_id))
        mode = "tape carries 1055/1087/deltas/echoes" if tape else \
               "1055 derived tags; no 1087 spawn batch"
        self.log(f"[match] world init dumped (1135, 1006×6, 1105, 1011+1162×7 "
                 f"reverse); {mode}")

    # -- world phase ---------------------------------------------------------

    def _run_world(self):
        """Post-dump world: replay the measured entity tape (paced in real
        time), then keep the client fed with 1116 pings, live movement
        (c2s 1012 → 1070 at the corpus cadence) and hero 1010 full updates
        (first one HERO_1010_PERIOD after the live layer starts). The tape
        carries its own 1116 frames, so ours start only once it has played
        out. Lane-minion waves (T3 slice 2) run on the measured 25 s grid
        anchored at the world start — wave 1 lands at +22.97 s, i.e. after
        the 12.5 s tape has finished; HALCYON_NO_WAVE=1 turns them off."""
        self._load_tape()
        if not self.tape_frames:
            self.tape_done = True     # fallback: live layer only
        tape_base = time.monotonic()
        self.wave_t0 = tape_base      # corpus 1137-ack instant = tape t=0
        if self.emit_waves:
            self.wave_director = wave.Director(tape_base, seq_1010=[self.seq_1010])
            self.log(f"[match] minion-wave director armed: wave 1 at "
                     f"+{roster.WAVE_FIRST_SPAWN_AT:.2f}s, interval "
                     f"{roster.WAVE_INTERVAL:.1f}s, 10 minions/wave "
                     f"(eids from {self.wave_director.first_eid})")
        else:
            self.log("[match] HALCYON_NO_WAVE set — no minion waves")
        next_move_tick = time.monotonic() + roster.MOVE_TICK
        next_ping = time.monotonic() + 1.0
        next_full_update = None       # armed when the live layer starts
        while not self._stop_event.is_set():
            now = time.monotonic()
            if self.wave_director is not None:
                # waves anchor at the world start, independent of the tape
                self.wave_director.seq_1010[0] = self.seq_1010
                wave_frames = self.wave_director.pump(now)
                self.seq_1010 = self.wave_director.seq_1010[0]
                for op, payload in wave_frames:
                    self._send(op, payload)
                    self.frames_sent += 1
            if not self.tape_done:
                while self.tape_i < len(self.tape_frames):
                    t_ms, body = self.tape_frames[self.tape_i]
                    if tape_base + t_ms / 1000.0 > now:
                        break
                    op = struct.unpack_from(">H", body)[0]
                    self._send(op, body[2:])
                    self.frames_sent += 1
                    self.tape_i += 1
                if self.tape_i >= len(self.tape_frames):
                    self.tape_done = True
                    next_full_update = now + roster.HERO_1010_PERIOD
                    self.log("[match] world tape complete — live layer "
                             f"(hero 1010 {'ON' if self.emit_hero_1010 else 'OFF'}, "
                             "1116 pings, 1012→1070 movement)")
            else:
                if next_full_update is None:      # no-tape entry
                    next_full_update = now + roster.HERO_1010_PERIOD
                if self.emit_hero_1010 and now >= next_full_update:
                    next_full_update = now + roster.HERO_1010_PERIOD
                    self.world_tick += 1
                    self.seq_1010 = (self.seq_1010 + 1) & 0xFF
                    self._send(wire.OP.ENTITY_FULL_UPDATE,
                               roster.build_entity_full_update(
                                   self.players[0].eid, self.world_tick,
                                   self.hero_x, self.hero_y,
                                   self.seq_1010, self.hero_facing))
                    self.frames_sent += 1
                if now >= next_move_tick:
                    next_move_tick = now + roster.MOVE_TICK
                    self._step_hero(roster.MOVE_TICK)
                if now >= next_ping:
                    next_ping = now + 1.0
                    self._send(wire.OP.SLOT_FLAGS_PING,
                               roster.build_slot_flags(self.players))
                    self.frames_sent += 1
            self._pump(timeout=WORLD_PUMP_TICK)

    def _step_hero(self, dt: float):
        """Advance the local hero toward its 1012 target; 1070 at the corpus
        cadence while moving (client predicts locally, server confirms).
        Each tick publishes the current position, then advances; the arrival
        tick additionally pins the exact target pair (corpus shows same-
        instant duplicate 1070s, so the double send has precedent). Facing
        follows the motion vector and holds after arrival — the 1010 full
        updates carry the same (cos, sin) pair."""
        if self.move_target is None:
            return
        eid = self.players[0].eid

        def publish(x, y):
            self._send(wire.OP.POSITION, roster.build_position(eid, x, y))
            self.frames_sent += 1

        publish(self.hero_x, self.hero_y)
        tx, ty = self.move_target
        self.hero_facing = roster.facing_toward(self.hero_x, self.hero_y, tx, ty)
        dx, dy = tx - self.hero_x, ty - self.hero_y
        dist = (dx * dx + dy * dy) ** 0.5
        step = roster.MOVE_SPEED * dt
        if dist <= step:
            self.hero_x, self.hero_y = tx, ty
            self.move_target = None
            publish(tx, ty)
        else:
            self.hero_x += dx / dist * step
            self.hero_y += dy / dist * step

    # -- loop ---------------------------------------------------------------

    def _pump(self, timeout):
        """Process queued c2s events; block up to `timeout` for the first."""
        try:
            opcode, payload = self.events.get(timeout=timeout)
        except queue.Empty:
            return
        self._apply_event(opcode, payload)
        while True:
            try:
                opcode, payload = self.events.get_nowait()
            except queue.Empty:
                return
            self._apply_event(opcode, payload)

    def run(self):
        try:
            self._pick_deadline = time.monotonic() + PICK_COUNTDOWN_START
            while not self._stop_event.is_set():
                if self.phase == self.PICK:
                    self._pump(timeout=SNAPSHOT_INTERVAL)
                    if (self.locked and self.commit_hash is None
                            and time.monotonic() - self.lock_requested_at > COMMIT_FALLBACK):
                        self._begin_lock()
                    if self.phase == self.PICK:
                        self._send_snapshot(self._pick_countdown())
                elif self.phase == self.LOCKED:
                    self._pump(timeout=LOCK_TICK)
                    remaining = self.lock_deadline - time.monotonic()
                    if remaining <= 0:
                        self._finalize()
                    else:
                        self._send_snapshot((remaining, LOCK_COUNTDOWN))
                elif self.phase == self.FINAL:
                    self._pump(timeout=LOCK_TICK)
                    if not self.dumped and time.monotonic() >= self.dump_fallback_at:
                        self.log("[match] no client 1134/1137 — world-dump fallback")
                        self._dump_world()
                        self.phase = self.WORLD
                else:
                    self._run_world()
        except OSError:
            pass
        finally:
            # shutdown wakes the reader on platforms where close alone does not.
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.conn.close()


# --------------------------------------------------------------------------
# Match server
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
        self.streams = []                  # per-connection SnapshotStream
        self._streams_by_conn = {}
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
        for st in self.streams:
            st.stop()
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
        # No idle read timeout: the client sits silent through the pick phase
        # by design (2026-09-06: a 30 s timeout here killed the join and drove
        # a reconnect loop). Liveness is owned by the SnapshotStream's writes —
        # a dead peer surfaces as a send error there; EOF/reset surface here.
        conn.settimeout(None)
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
            stream = self._streams_by_conn.pop(conn, None)
            if stream is not None:
                stream.stop()
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()

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
            try:
                tick = wire.parse_keepalive(payload)
            except wire.WireError:
                # live 2026-09-06: right after c2s 1133 the client emitted a
                # 6 B op-0 variant (43 35 a8 b4 00 00) mid-world-load; the
                # corpus 2 B tick shape stays canonical, variants are consumed
                # so the match socket survives the world load
                self.log(f"[match] op-0 variant consumed ({len(payload)} B: "
                         f"{payload.hex()})")
                return
            self.keepalive_ticks.append(tick)
            return  # consumed, no reply (§15.8: tick ≈513/s rising)
        if opcode == wire.OP.PLAYER_UUID:
            self.session_uuid = payload.split(b"\x00", 1)[0].decode("ascii", "replace")
            self.log(f"[match] join: session uuid {self.session_uuid}")
            self._serve_join(conn)
            return
        if opcode in (wire.OP.JOIN_1112, wire.OP.JOIN_1118, wire.OP.BUILD_LOCK,
                      wire.OP.LOCK_COMMIT, wire.OP.JOIN_1131, wire.OP.SHOP_OPEN,
                      wire.OP.HERO_READY, wire.OP.BUY_CLOSE, wire.OP.MOVE_CAST):
            stream = self._streams_by_conn.get(conn)
            if stream is not None:
                stream.submit(opcode, payload)
        # Join handshakes (1112/1118/1123/1131/1119/1134/1137/1133/1157/1081…)
        # and gameplay verbs without a slice yet (1041/1078) are logged above;
        # semantic replies are T3 work.
        self.log(f"[match] c2s op={opcode} ({len(payload)} B)")

    def _serve_join(self, conn):
        """Present unpicked slots; 1118 comes from the client, not this burst."""
        if conn in self._streams_by_conn:
            return
        players = roster.default_solo_bots(self.session_uuid, self.match_id)
        send = self._sender(conn)
        # Opener burst, pcap order: 1001 → 1108 → 1107×275 → 1113[0]
        # (the first snapshot carries the pre-pick countdown pair, flags 0000).
        send(wire.OP.GAME_SETUP,
             roster.build_game_setup(roster.MODE_SOLO_BOTS, players[0].eid))
        send(wire.OP.GAME_MODE, roster.build_game_mode())
        for name in hero_catalog.HERO_CATALOG_1107_NAMES:
            send(wire.OP.HERO_CATALOG, hero_catalog.catalog_payload(name))
        send(wire.OP.SNAPSHOT_JOIN,
             roster.build_snapshot(players, countdown=(298.717, 300.0),
                                   pick_flags=0x0000))
        stream = SnapshotStream(conn, players, self.match_id, send, self.log)
        self.streams.append(stream)
        self._streams_by_conn[conn] = stream
        stream.start()

    def _sender(self, conn):
        def send(opcode, payload):
            conn.sendall(wire.encode_message(self.cipher, opcode, payload))
        return send


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
