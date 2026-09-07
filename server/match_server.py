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

import base64
import json
import queue
import os
import re
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
    import hero_movement
    import structures
    import status_effects
    import abilities
    import economy
    import jungle
    import bot_ai
else:
    from . import hero_catalog
    from . import roster
    from . import wave
    from . import wire
    from . import world_tape
    from . import hero_movement
    from . import structures
    from . import status_effects
    from . import abilities
    from . import economy
    from . import jungle
    from . import bot_ai

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


def identity_from_token(token: str) -> str:
    try:
        parts = token.split(".")
        if len(parts) == 3:
            pad = "=" * (-len(parts[1]) % 4)
            data = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
            pid = data.get("player_id") or data.get("playerUuid")
            if pid:
                return str(pid)
            return token
        elif len(parts) == 2:
            pad = "=" * (-len(parts[1]) % 4)
            fragment = base64.urlsafe_b64decode(parts[1] + pad).decode("ascii", "replace")
            match = re.search(r'\{"d":"([0-9a-f]{1,12})', fragment)
            if match:
                return f"devtag:{match.group(1)}"
        return token
    except Exception:
        return token


class SnapshotStream(threading.Thread):
    """Owns shared pick/lock/world simulation state and client streams."""

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
        self.world_entered_at = None
        self.world_had_clients = False
        self.zero_clients_since = None

        # Multi-client tracking: conn -> (player, send_fn)
        self.clients = {}
        self.ready_clients = set()
        self.dumped_conns = set()
        self.hero_sims = {}
        self._clients_lock = threading.Lock()

        # Initialize hero movements for all players
        for p in self.players:
            spawn_pos = roster.HERO_SPAWNS.get(p.eid, (roster.SPAWN_X, roster.SPAWN_Y))
            self.hero_sims[p.eid] = hero_movement.HeroMovement(
                eid=p.eid, team=p.team,
                x=spawn_pos[0], y=spawn_pos[1])
        local_p = self.players[0]
        local_p.is_bot = False
        self.hero_sim = self.hero_sims[local_p.eid]
        self.hero_x = self.hero_sim.x
        self.hero_y = self.hero_sim.y
        self.move_target = None           # (x, y) or None
        self.hero_facing = self.hero_sim.facing   # (cos, sin), unit pair

        if conn is not None and send is not None:
            self.clients[conn] = (local_p, send)

        self.emit_hero_1010 = bool(os.environ.get("HALCYON_HERO_1010"))
        # corpus evidence 2026-09-07: the real server sends only ~37 hero
        # 1070s per match (5 Hz bursts after orders, then silence) while the
        # client walks its own hero locally; a continuous 5 Hz stream may be
        # suppressing the client's locomotion anim. Sparse mode emits a short
        # burst per order and then goes quiet, mirroring the capture.
        self.sparse_1070 = bool(os.environ.get("HALCYON_SPARSE_1070"))
        self.sparse_budget: dict[int, int] = {}
        # Test harness: brief suppression of periodic 1070 position updates for local hero
        # to isolate correction-induced choppiness from client navigation/animation.
        # Preserves 1016 ActionMoveTo, initial anchor 1070, tape bootstrap, and heartbeats.
        self.suppress_periodic_1070_sec = float(os.environ.get("HALCYON_SUPPRESS_PERIODIC_1070_SEC", "0.0"))
        self.suppress_periodic_1070_move = int(os.environ.get("HALCYON_SUPPRESS_PERIODIC_1070_MOVE", "0"))
        self.move_count = 0
        self.suppress_until = 0.0
        self.suppress_active = False
        self.suppressed_1070_count = 0
        # corpus keepalive layer (2026-09-07) — default off behind HALCYON_HERO_KEEPALIVE
        # so test_e2e and pure-sim world loops don't see unexpected 1086/1053 frames
        self.hero_keepalive = bool(os.environ.get("HALCYON_HERO_KEEPALIVE"))
        self.keep_seq = 3203              # measured seq range in the capture
        self.next_ka_45 = 0.0
        self.next_ka_3e = 0.0
        self.next_ka_stat = 0.0
        self.world_tick = 0               # u32 at +8 (1086 deltas will share it)
        self.seq_1010 = 0                 # u8 at +116, +1 per 1010 emitted
        self.tape_frames = None           # loaded lazily on WORLD entry
        self.tape_i = 0
        self.tape_done = False
        self.structures = structures.StructureManager()
        self.world_entities: dict[int, tuple[float, float]] = {}
        for eid, s in self.structures.structures.items():
            self.world_entities[eid] = (s.x, s.y)
        self.status_manager = status_effects.StatusManager()
        self.damage_queue = status_effects.DamageModifierQueue()
        self.economy = economy.EconomyManager()
        self.emit_trickle = bool(os.environ.get("HALCYON_ECONOMY_TRICKLE")) or self.hero_keepalive
        self.jungle = jungle.JungleManager(open_time=0.0)
        self.hero_kits: dict[int, abilities.HeroKit] = {}
        for eid, sim in self.hero_sims.items():
            self.hero_kits[eid] = abilities.create_ringo_kit(sim)
        self.emit_waves = not os.environ.get("HALCYON_NO_WAVE")
        self.enable_bots = bool(os.environ.get("HALCYON_BOTS"))
        self.bot_controllers: dict[int, bot_ai.BotAI] = {}
        if self.enable_bots:
            for p in self.players:
                if p.is_bot:
                    self.bot_controllers[p.eid] = bot_ai.BotAI(p.eid, p.team)
        self.wave_director = None
        self._last_snapshot_at = 0.0
        self._pick_deadline = time.monotonic() + PICK_COUNTDOWN_START

    def stop(self):
        self._stop_event.set()

    def submit(self, opcode, payload, conn=None):
        self.events.put((opcode, payload, conn))

    def add_client(self, conn, session_uuid: str, send):
        """Attach a client connection to this match session.
        Handles both new player slot allocation and reconnection."""
        with self._clients_lock:
            # Match 00000000 is persistent and the guest session uuid is
            # fixed, so every queue-up lands in the reconnect path. A fresh
            # queue is a fresh play session: re-arm the pick countdown so the
            # draft is live instead of pinned at the boot-time expiry.
            # [Deviation from retail: draft length resets per join, not per
            # match formation — deliberate for the persistent solo match.]
            if self.phase == self.PICK:
                self._pick_deadline = time.monotonic() + PICK_COUNTDOWN_START
            # 1. Reconnection: match existing non-bot slot by session_uuid
            existing = next((p for p in self.players if p.uuid == session_uuid and not p.is_bot), None)
            if existing is not None:
                self.clients[conn] = (existing, send)
                self.zero_clients_since = None
                if self.phase == self.WORLD:
                    self.world_had_clients = True
                self.log(f"[match] client reconnected: {session_uuid} -> slot {existing.slot} (eid {existing.eid})")
                if self.phase == self.WORLD:
                    self._dump_reconnect_state(conn, existing, send)
                elif self.phase in (self.LOCKED, self.FINAL):
                    send(wire.OP.GAME_SETUP, roster.build_game_setup(roster.MODE_SOLO_BOTS, existing.eid))
                    send(wire.OP.GAME_MODE, roster.build_game_mode())
                    remaining = max(0.0, self.lock_deadline - time.monotonic()) if self.lock_deadline else 0.0
                    send(wire.OP.SNAPSHOT_JOIN, roster.build_snapshot(self.players, countdown=(remaining, LOCK_COUNTDOWN)))
                elif self.phase == self.PICK:
                    send(wire.OP.GAME_SETUP, roster.build_game_setup(roster.MODE_SOLO_BOTS, existing.eid))
                    send(wire.OP.GAME_MODE, roster.build_game_mode())
                    for name in hero_catalog.HERO_CATALOG_1107_NAMES:
                        send(wire.OP.HERO_CATALOG, hero_catalog.catalog_payload(name))
                    send(wire.OP.SNAPSHOT_JOIN, roster.build_snapshot(self.players, countdown=self._pick_countdown()))
                return existing

            # 2. New human slot: default policy alternates teams [0, 3, 1, 4, 2, 5] for PvP
            if os.environ.get("HALCYON_TEAM_ALLOCATION") == "coop":
                candidate_slots = [0, 1, 2, 3, 4, 5]
            else:
                candidate_slots = [0, 3, 1, 4, 2, 5]

            slot_idx = None
            for idx in candidate_slots:
                if idx < len(self.players) and self.players[idx].is_bot:
                    slot_idx = idx
                    break
            if slot_idx is None:
                slot_idx = next((i for i, p in enumerate(self.players) if p.is_bot), 0)

            player = self.players[slot_idx]
            player.is_bot = False
            player.uuid = session_uuid
            player.handle = f"Player {slot_idx + 1}" if slot_idx != 0 else "Guest"
            player.selection_hash = 0
            player.pick_flags = 0

            self.clients[conn] = (player, send)

            spawn_pos = roster.HERO_SPAWNS.get(player.eid, (roster.SPAWN_X, roster.SPAWN_Y))
            if player.eid not in self.hero_sims:
                self.hero_sims[player.eid] = hero_movement.HeroMovement(
                    eid=player.eid, team=player.team,
                    x=spawn_pos[0], y=spawn_pos[1])
            if player.eid in self.bot_controllers:
                del self.bot_controllers[player.eid]
            if player.eid not in self.hero_kits:
                self.hero_kits[player.eid] = abilities.create_hero_kit(self.hero_sims[player.eid], player.hero_id)

            self.zero_clients_since = None
            if self.phase == self.WORLD:
                self.world_had_clients = True
            self.log(f"[match] new client added: {session_uuid} -> slot {slot_idx} (eid {player.eid}, team {player.team})")

            if self.phase == self.WORLD:
                # Mid-match join (cloned-uuid second device): the lobby opener
                # would leave the client on a dead loading screen — serve the
                # full world dump for this player's eid instead.
                self._dump_reconnect_state(conn, player, send)
            else:
                # Opener burst sent to this client
                send(wire.OP.GAME_SETUP, roster.build_game_setup(roster.MODE_SOLO_BOTS, player.eid))
                send(wire.OP.GAME_MODE, roster.build_game_mode())
                for name in hero_catalog.HERO_CATALOG_1107_NAMES:
                    send(wire.OP.HERO_CATALOG, hero_catalog.catalog_payload(name))
                send(wire.OP.SNAPSHOT_JOIN, roster.build_snapshot(self.players, countdown=self._pick_countdown()))

            # Broadcast updated roster snapshot to all other clients
            for c, (_, s_fn) in list(self.clients.items()):
                if c != conn:
                    try:
                        s_fn(wire.OP.SNAPSHOT_JOIN, roster.build_snapshot(self.players, countdown=self._pick_countdown()))
                    except OSError:
                        pass
            return player

    def remove_client(self, conn):
        with self._clients_lock:
            p_info = self.clients.pop(conn, None)
            self.ready_clients.discard(conn)
            if p_info is not None:
                p = p_info[0]
                self.log(f"[match] client left: slot {p.slot} (eid {p.eid})")
            if not self.clients:
                self.zero_clients_since = time.monotonic()

    # -- frame broadcasting & targeted sending -------------------------------

    def _broadcast(self, opcode: int, payload: bytes):
        dead = []
        with self._clients_lock:
            for conn, (_, send_fn) in list(self.clients.items()):
                try:
                    send_fn(opcode, payload)
                except OSError:
                    dead.append(conn)
            for c in dead:
                self.clients.pop(c, None)
                self.ready_clients.discard(c)
        if self._send is not None and not self.clients:
            try:
                self._send(opcode, payload)
            except OSError:
                pass
        self.frames_sent += 1

    def _send_to(self, conn, opcode: int, payload: bytes):
        if conn is not None:
            with self._clients_lock:
                info = self.clients.get(conn)
                if info is not None:
                    try:
                        info[1](opcode, payload)
                    except OSError:
                        self.clients.pop(conn, None)
                        self.ready_clients.discard(conn)
                    self.frames_sent += 1
                    return
        if self._send is not None:
            try:
                self._send(opcode, payload)
            except OSError:
                pass
            self.frames_sent += 1

    def _broadcast_snapshot(self, countdown):
        self._last_snapshot_at = time.monotonic()
        self._broadcast(wire.OP.SNAPSHOT_JOIN,
                         roster.build_snapshot(self.players, countdown=countdown))

    def _send_snapshot(self, countdown):
        self._broadcast_snapshot(countdown)

    # -- event handlers -----------------------------------------------------

    def _apply_event(self, opcode, payload, conn=None, bot_eid=None):
        if bot_eid is not None:
            player = next((p for p in self.players if p.eid == bot_eid), self.players[0])
        elif conn is not None and conn in self.clients:
            player = self.clients[conn][0]
        else:
            player = self.players[0]

        sim = self.hero_sims.get(player.eid)

        if opcode == wire.OP.JOIN_1112 or opcode == wire.OP.JOIN_1131:
            self._send_to(conn, opcode, roster.build_zero_ack())
        elif opcode == wire.OP.JOIN_1118:
            if player.pick_flags == roster.PICK_FLAG_LOCKED:
                return                       # corpus: no re-pick after lock
            try:
                hero_id, selection_hash = roster.parse_hero_selection(payload)
            except ValueError as exc:
                self.log(f"[match] rejected hero selection: {exc}")
                return
            player.hero_id, player.selection_hash = hero_id, selection_hash
            player.pick_flags = roster.PICK_FLAG_SELECTED
            self._send_to(conn, wire.OP.JOIN_1118, roster.build_hero_selection(player))
            self.log(f"[match] hero selected by slot {player.slot} (eid {player.eid}): id={hero_id} hash={selection_hash:08x}")
            self._broadcast_snapshot(self._pick_countdown())
        elif opcode == wire.OP.BUILD_LOCK:
            if payload != bytes(6) or player.hero_id == roster.UNPICKED_HERO_ID:
                self.log("[match] rejected lock without a valid selection/payload")
                return
            if player.pick_flags == roster.PICK_FLAG_LOCKED:
                return
            player.pick_flags = roster.PICK_FLAG_LOCKED
            self.lock_requested_at = time.monotonic()
            self._broadcast_snapshot(self._pick_countdown())
            self._send_to(conn, wire.OP.BUILD_LOCK, roster.build_zero_ack())
            with self._clients_lock:
                all_locked = all(p.pick_flags == roster.PICK_FLAG_LOCKED for p, _ in self.clients.values()) if self.clients else True
            if all_locked:
                self.locked = True
                if self.commit_hash is not None:
                    self._begin_lock()
        elif opcode == wire.OP.LOCK_COMMIT:
            try:
                commit_h = roster.parse_commit_hash(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1119 commit: {exc}")
                return
            player.selection_hash = commit_h
            if player.slot == 0:
                self.commit_hash = commit_h
            with self._clients_lock:
                all_locked = all(p.pick_flags == roster.PICK_FLAG_LOCKED for p, _ in self.clients.values()) if self.clients else True
            if all_locked and self.phase == self.PICK:
                self.locked = True
                self._begin_lock()
        elif opcode in (wire.OP.SHOP_OPEN, wire.OP.HERO_READY):
            if conn is not None and conn not in self.dumped_conns:
                self._dump_world_to(conn)
                self.dumped_conns.add(conn)
            if self.phase == self.FINAL:
                self._enter_world()
                if opcode == wire.OP.HERO_READY and conn is not None:
                    self.ready_clients.add(conn)
            if (self.dumped or self.phase == self.WORLD) and self.tape_frames == []:
                self._send_to(conn, opcode, payload)
        elif opcode == wire.OP.BUY_CLOSE:
            self.log("[match] c2s 1133 build-select close — world bootstrap "
                     "replays the measured tape; sim is T3 work")
        elif opcode == wire.OP.MOVE_CAST:
            try:
                tx, ty = roster.parse_move(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1012 move: {exc}")
                return
            self.log(f"[match] move target ({tx:.2f}, {ty:.2f}) for eid {player.eid}")
            if player.slot == 0:
                self.move_count += 1
                suppress_sec = self.suppress_periodic_1070_sec
                suppress_move = self.suppress_periodic_1070_move
                cfg_path = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack", "suppress_1070.json")
                if os.path.exists(cfg_path):
                    try:
                        with open(cfg_path, "r") as f:
                            cfg = json.load(f)
                            suppress_sec = float(cfg.get("duration", suppress_sec))
                            suppress_move = int(cfg.get("move", suppress_move))
                    except Exception:
                        pass
                if suppress_sec > 0 and (suppress_move == 0 or suppress_move == self.move_count):
                    now = time.monotonic()
                    self.suppress_until = now + suppress_sec
                    self.suppress_active = True
                    self.suppressed_1070_count = 0
                    self.log(f"[match] move #{self.move_count}: suppressing periodic 1070 for eid {player.eid} for {suppress_sec:.2f}s (until +{suppress_sec:.2f}s)")
                else:
                    self.suppress_active = False
            if self.sparse_1070:
                self.sparse_budget[player.eid] = 6   # ~1.2 s of 5 Hz burst
            if sim is not None and sim.is_alive:
                start_frames = sim.set_target(tx, ty)
                # 1016 ActionMoveTo activates the client's navigation. Its
                # first byte is a compact actor id, NOT an eid: the six hero
                # indices in this roster match the measured slots 0..5.
                self._broadcast(wire.OP.MOVE_TO,
                                roster.build_move_intent(player.slot, tx, ty))
                if not start_frames:
                    # Retargets also carry a correction at the current
                    # position, never the previous order's start position.
                    start_frames = [(wire.OP.POSITION,
                                     roster.build_position(player.eid, sim.x, sim.y))]
                for op, p in start_frames:
                    self._broadcast(op, p)
                if player.slot == 0:
                    self.hero_x = sim.x
                    self.hero_y = sim.y
                    self.hero_facing = sim.facing
                    self.move_target = sim.move_target
        elif opcode == wire.OP.TARGET_ENTITY:
            try:
                target_eid = roster.parse_target_entity(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1060 target entity: {exc}")
                return
            self.log(f"[match] target entity {target_eid} for eid {player.eid}")
            if sim is not None:
                sim.set_target_eid(target_eid)
        elif opcode == wire.OP.LEVELUP_A:
            if len(payload) != 6 or payload[0] not in (0, 1, 2) or payload[1:] != bytes(5):
                return
            if conn is not None:
                self._send_to(conn, wire.OP.LEVELUP_A, payload)
                self._send_to(conn, 1160, struct.pack(">IH", player.eid, 0))
        elif opcode == 1078:  # wire.OP.LEVELUP_B / ABILITY_CAST
            if bot_eid is not None:
                try:
                    slot_idx = roster.parse_ability_cast(payload)
                except ValueError as exc:
                    self.log(f"[match] rejected 1078 ability cast: {exc}")
                    return
                self.log(f"[ability] eid {player.eid} cast ability slot {slot_idx}")
                kit = self.hero_kits.get(player.eid)
                if kit is not None:
                    now = time.monotonic()
                    target_eid = sim.target_eid if sim is not None else None
                    ability_frames = kit.cast_ability(
                        slot=slot_idx,
                        now=now,
                        target_eid=target_eid,
                        target_pos=None,
                        status_manager=getattr(self, "status_manager", None),
                        damage_queue=getattr(self, "damage_queue", None),
                        all_heroes=self.hero_sims,
                        all_minions=self.wave_director.minions if getattr(self, "wave_director", None) else [],
                    )
                    for aop, ap in ability_frames:
                        self._broadcast(aop, ap)
            else:
                if len(payload) != 6 or payload[0] not in (0, 1, 2) or payload[1:] != bytes(5):
                    return
                slot_idx = payload[0]
                kit = self.hero_kits.get(player.eid)
                econ = getattr(self, "economy", None)
                if econ is not None and econ.upgrade_ability(player.eid, slot_idx, kit):
                    if conn is not None:
                        self._send_to(conn, wire.OP.LEVELUP_B, payload)
                    self._broadcast(wire.OP.INVENTORY_SLOT, struct.pack(">II6s", player.eid, slot_idx, bytes(6)))
        elif opcode == wire.OP.SKILLSHOT_CAST:
            try:
                caster, target, x, y, slot_idx, flag = roster.parse_skillshot_cast(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1102 skillshot cast: {exc}")
                return
            self.log(f"[ability] eid {caster} skillshot slot {slot_idx} at ({x:.2f}, {y:.2f}) target {target}")
            kit = self.hero_kits.get(caster)
            if kit is not None:
                now = time.monotonic()
                tgt_eid = target if target != 0xFFFFFFFF else None
                ability_frames = kit.cast_ability(
                    slot=slot_idx,
                    now=now,
                    target_eid=tgt_eid,
                    target_pos=(x, y),
                    status_manager=self.status_manager,
                    damage_queue=self.damage_queue,
                    all_heroes=self.hero_sims,
                    all_minions=self.wave_director.minions if self.wave_director else [],
                )
                for aop, ap in ability_frames:
                    self._broadcast(aop, ap)
        elif opcode == wire.OP.SHOP_BUY:
            try:
                target_eid, item_id = roster.parse_shop_buy(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1081 shop buy: {exc}")
                return
            self.log(f"[economy] eid {target_eid} purchasing item {item_id}")
            hero = self.hero_sims.get(target_eid)
            if hero is not None:
                ok, buy_frames = self.economy.purchase_item(target_eid, item_id, hero)
                if ok:
                    self.log(f"[economy] eid {target_eid} bought item {item_id}, gold remaining: {self.economy.get_or_create(target_eid).gold:.1f}")
                    for bop, bp in buy_frames:
                        self._broadcast(bop, bp)
                else:
                    self.log(f"[economy] eid {target_eid} failed purchase {item_id} (not enough gold or full)")
        elif opcode == wire.OP.ABILITY_UPGRADE:
            try:
                ability_id = roster.parse_ability_upgrade(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1096 ability upgrade: {exc}")
                return
            self.log(f"[ability] eid {player.eid} upgrade ability {ability_id}")
            kit = self.hero_kits.get(player.eid)
            self.economy.upgrade_ability(player.eid, ability_id, kit)

    def _pick_countdown(self):
        remaining = max(0.0, self._pick_deadline - time.monotonic())
        return (remaining, PICK_COUNTDOWN_START)

    def _begin_lock(self, send_commit_ack: bool = True):
        """Corpus: 1113 with the committed hash → 1119 echo → the roster
        locks (bots take their heroes) and the 7.0 s countdown restarts
        with a burst of 8× identical snapshots."""
        if self.commit_hash is None:
            self.commit_hash = self.players[0].selection_hash
            send_commit_ack = False
            self.log("[match] no 1119 commit — locking with the 1118 hash")
        self.players[0].selection_hash = self.commit_hash
        self._broadcast_snapshot(self._pick_countdown())
        if send_commit_ack:
            self._broadcast(wire.OP.LOCK_COMMIT, roster.build_commit_ack(self.commit_hash))
        roster.commit_lock(self.players, self.commit_hash)
        self.phase = self.LOCKED
        self.lock_deadline = time.monotonic() + LOCK_COUNTDOWN
        self.log(f"[match] roster locked (committed hash {self.commit_hash:08x}); "
                 f"countdown {LOCK_COUNTDOWN}s")
        for _ in range(LOCK_BURST):
            self._broadcast_snapshot((LOCK_COUNTDOWN, LOCK_COUNTDOWN))

    def _finalize(self):
        self.phase = self.FINAL
        for p in self.players:
            self._broadcast(wire.OP.PLAYER_INFO, roster.build_player_info(p, self.match_id))
        self._broadcast(wire.OP.ROSTER_FINAL, roster.build_zero_ack())
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
            if frames:
                repaired = world_tape.complete_corpus_bootstrap(frames)
                if len(repaired) > len(frames):
                    self.log(f"[match] completed truncated corpus bootstrap: "
                             f"{len(repaired) - len(frames)} startup 1093 cancellations at +16.672s (in memory)")
                frames = repaired
        except ValueError as exc:
            self.log(f"[match] corrupt world tape ({exc!r}) — ignoring")
            frames = None
        if frames:
            span = frames[-1][0] / 1000.0
            self.log(f"[match] world tape: {len(frames)} frames, "
                     f"{span:.1f}s (corpus bootstrap — sim is T3)")
            # the 1010 seq byte counts every entity full update the client
            # has seen — continue from the tape's tail, not from zero
            self.tape_frames = frames
            self.tape_done = False
            self.seq_1010 = 0
            for _t, b in frames:
                if len(b) >= 2:
                    op = struct.unpack_from(">H", b)[0]
                    if op == wire.OP.ENTITY_FULL_UPDATE:
                        self.seq_1010 += 1
                        if len(b) >= 2 + 24:
                            p = b[2:]
                            eid = struct.unpack_from(">I", p, 8)[0]
                            x, z, y = struct.unpack_from(">fff", p, 12)
                            self.world_entities[eid] = (x, y)
        else:
            self.log(f"[match] no world tape — echo/1055 fallback "
                     f"(expected at {WORLD_TAPE_PATH})")
            self.tape_frames = []
            self.tape_done = True

    def _dump_world_to(self, conn, send_fn=None):
        """Dump world init to a specific client connection."""
        self.dumped = True
        self._load_tape()
        tape = bool(self.tape_frames)
        send = send_fn if send_fn is not None else (lambda op, p: self._send_to(conn, op, p))
        send(wire.OP.MODE_NAME, roster.build_mode_name())
        for p in self.players:
            send(wire.OP.PLAYER_INFO, roster.build_player_info(p, self.match_id))
        send(wire.OP.MODE_PING_1105, roster.build_zero_ack())
        for p in reversed(self.players):
            send(wire.OP.HERO_BLOCK, roster.build_hero_block(p))
            hero_data, donated = roster.hero_init_for(p.hero_id)
            if donated:
                self.log(f"[match] hero id {p.hero_id} unmeasured — donor "
                         f"stat run from {roster.HERO_INIT_DONOR_ID} "
                         "[Open: real 1011 not captured]")
            # an entry whose init-burst 1162s were never captured (e.g. 258:
            # vg5_final starts after the burst) reuses the donor's timers
            timers = hero_data and (hero_data["timers"] if hero_data["timers"]
                                    is not None else
                                    roster.HERO_INIT_DATA[
                                        roster.HERO_INIT_DONOR_ID]["timers"])
            for k in range(roster.TIMERS_PER_HERO):
                if timers and k < len(timers):
                    tag, tail = timers[k]
                    send(wire.OP.TIMER_TICK,
                         roster.build_timer_tick(p.eid, tag, 0.0,
                                                 bytes.fromhex(tail)))
                else:
                    send(wire.OP.TIMER_TICK,
                         roster.build_timer_tick(p.eid, 0, 0.0))
        if not tape:
            for p in self.players:
                send(wire.OP.PLAYER_TAG, roster.build_player_tag(p, self.match_id))
            for sop, sp in self.structures.get_spawn_1010_frames():
                send(sop, sp)
        mode = "tape carries 1055/1087/deltas/echoes" if tape else \
               "1055 derived tags; static structures spawned; no 1087 spawn batch"
        self.log(f"[match] world init dumped to client; {mode}")

    def _dump_world(self):
        """1135, 1006×6, 1105, (1011 + 1162×7) reverse — corpus order."""
        self.dumped = True
        with self._clients_lock:
            active_conns = list(self.clients.keys())
        for conn in active_conns:
            self._dump_world_to(conn)
        if not active_conns:
            self._dump_world_to(None)

    def _enter_world(self):
        """Transition into WORLD simulation phase after ready barrier or fallback."""
        if self.phase == self.WORLD:
            return
        self.phase = self.WORLD
        self.world_entered_at = time.monotonic()
        if not self.clients:
            self.zero_clients_since = time.monotonic()
        self.dumped = True
        self._load_tape()
        tape_base = time.monotonic()
        self.wave_t0 = tape_base
        if self.emit_waves:
            self.wave_director = wave.Director(tape_base, seq_1010=[self.seq_1010])
            self.log(f"[match] minion-wave director armed: wave 1 at "
                     f"+{roster.WAVE_FIRST_SPAWN_AT:.2f}s, interval "
                     f"{roster.WAVE_INTERVAL:.1f}s, 10 minions/wave "
                     f"(eids from {self.wave_director.first_eid})")
        else:
            self.log("[match] HALCYON_NO_WAVE set — no minion waves")

    # -- world phase ---------------------------------------------------------

    def _run_world(self):
        self._load_tape()
        if not self.tape_frames:
            self.tape_done = True     # fallback: live layer only
        tape_base = self.wave_t0
        next_move_tick = time.monotonic() + roster.MOVE_TICK
        next_ping = time.monotonic() + 1.0
        next_full_update = None       # armed when the live layer starts
        while not self._stop_event.is_set():
            now = time.monotonic()
            if not self.clients and self.zero_clients_since is not None:
                timeout = 15.0 if self.world_had_clients else 25.0
                if now - self.zero_clients_since > timeout:
                    self.log(f"[match] no clients connected for {timeout:.1f}s in WORLD — finishing match")
                    self._stop_event.set()
                    break
            if self.wave_director is not None:
                self.wave_director.seq_1010[0] = self.seq_1010
                wave_frames = self.wave_director.pump(now, hero=self.hero_sim)
                self.seq_1010 = self.wave_director.seq_1010[0]
                for op, payload in wave_frames:
                    self._broadcast(op, payload)
                    if op == wire.OP.COMBAT_DELTA:
                        src_eid, tgt_eid, delta = struct.unpack_from(">IIf", payload, 0)
                        if tgt_eid in self.hero_sims:
                            self.log(f"[combat] minion {src_eid} attacked hero {tgt_eid}: {delta:.1f}")
            if not self.tape_done:
                while self.tape_i < len(self.tape_frames):
                    t_ms, body = self.tape_frames[self.tape_i]
                    if tape_base + t_ms / 1000.0 > now:
                        break
                    op = struct.unpack_from(">H", body)[0]
                    self._broadcast(op, body[2:])
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
                    for p in self.players:
                        # every HUMAN hero needs its own 1010 stream (solo
                        # legacy emitted players[0] only; in a duo the second
                        # client's hero would never render movement)
                        if p.is_bot:
                            continue
                        hsim = self.hero_sims.get(p.eid)
                        if hsim is None:
                            continue
                        self.seq_1010 = (self.seq_1010 + 1) & 0xFF
                        self._broadcast(wire.OP.ENTITY_FULL_UPDATE,
                                        roster.build_entity_full_update(
                                            p.eid, self.world_tick,
                                            hsim.x, hsim.y,
                                            self.seq_1010, hsim.facing))
                if now >= next_ping:
                    next_ping = now + 1.0
                    self._broadcast(wire.OP.SLOT_FLAGS_PING,
                                    roster.build_slot_flags(self.players))
                # hero keepalive layer, cadences measured on the corpus match
                # (2026-09-07): 1086 attr 0x45→253 @0.3 s, 0x3e→251 @0.6 s,
                # 1053 pair 6.0@0x0600 + 1.0@0x0800 @1.0 s
                if self.hero_keepalive:
                    eid0 = self.players[0].eid
                    if now >= self.next_ka_45:
                        self.next_ka_45 = now + 0.3
                        self.keep_seq = (self.keep_seq + 1) & 0xFFFF
                        self._broadcast(wire.OP.ENTITY_PROP,
                                        roster.build_entity_prop(eid0, 0x45,
                                                                 self.keep_seq, 253))
                    if now >= self.next_ka_3e:
                        self.next_ka_3e = now + 0.6
                        self.keep_seq = (self.keep_seq + 1) & 0xFFFF
                        self._broadcast(wire.OP.ENTITY_PROP,
                                        roster.build_entity_prop(eid0, 0x3e,
                                                                 self.keep_seq, 251))
                    if now >= self.next_ka_stat:
                        self.next_ka_stat = now + 1.0
                        self._broadcast(wire.OP.ENTITY_STAT,
                                        roster.build_entity_stat(eid0, 6.0, 0x0600))
                        self._broadcast(wire.OP.ENTITY_STAT,
                                        roster.build_entity_stat(eid0, 1.0, 0x0800,
                                                                 w2=0x0100))

            if now >= next_move_tick:
                next_move_tick = now + roster.MOVE_TICK
                if self.enable_bots:
                    for bot_eid, bot in list(self.bot_controllers.items()):
                        bsim = self.hero_sims.get(bot_eid)
                        if bsim is None or not bsim.is_alive:
                            continue
                        bkit = self.hero_kits.get(bot_eid)
                        becon = self.economy.get_or_create(bot_eid)
                        intents = bot.step(
                            now=now,
                            hero=bsim,
                            all_heroes=self.hero_sims,
                            minions=self.wave_director.minions if self.wave_director else [],
                            structures=self.structures.structures,
                            hero_kit=bkit,
                            econ=becon,
                        )
                        for bop, bpayload in intents:
                            self._apply_event(bop, bpayload, bot_eid=bot_eid)

                self._step_heroes(roster.MOVE_TICK, now)
                econ_frames = self.economy.step(
                    roster.MOVE_TICK, now, self.hero_sims, emit_trickle=self.emit_trickle
                )
                for eop, ep in econ_frames:
                    self._broadcast(eop, ep)

            self._pump(timeout=WORLD_PUMP_TICK)

    def _step_hero(self, dt: float, now: float):
        self._step_heroes(dt, now)

    def _step_heroes(self, dt: float, now: float):
        """Advance all active heroes toward their move/attack targets.
        Handles hero movement, basic attack on minions, turrets, and enemy heroes."""
        for eid, sim in list(self.hero_sims.items()):
            target_pos = None
            if sim.target_eid is not None:
                # 1. Target is a minion
                if self.wave_director is not None:
                    target_minion = next((m for m in self.wave_director.minions
                                          if m.eid == sim.target_eid and m.alive), None)
                    if target_minion is not None:
                        target_pos = (target_minion.x, target_minion.y)
                # 2. Target is a structure / world entity
                if target_pos is None and sim.target_eid in self.world_entities:
                    target_pos = self.world_entities[sim.target_eid]
                # 3. Target is an enemy hero (PvP)
                if target_pos is None and sim.target_eid in self.hero_sims:
                    enemy = self.hero_sims[sim.target_eid]
                    if enemy.team != sim.team and enemy.is_alive:
                        target_pos = (enemy.x, enemy.y)
                # 4. Target is a jungle monster
                if target_pos is None and sim.target_eid in self.jungle.monsters:
                    monster = self.jungle.monsters[sim.target_eid]
                    if monster.is_alive:
                        target_pos = (monster.x, monster.y)

            frames = sim.step(dt, now=now, target_pos=target_pos, status_manager=self.status_manager)
            budget = self.sparse_budget.get(eid, 0) if self.sparse_1070 else None
            for op, p in frames:
                if budget is not None and op == wire.OP.POSITION:
                    if budget <= 0:
                        continue          # corpus-mirroring silence window
                    budget -= 1
                    self.sparse_budget[eid] = budget
                if op == wire.OP.POSITION and eid == self.players[0].eid and self.suppress_active:
                    if now < self.suppress_until and sim.is_moving:
                        self.suppressed_1070_count += 1
                        continue          # suppressed periodic correction during transit
                    else:
                        self.suppress_active = False
                        self.log(f"[match] periodic 1070 resumed for eid {eid} after suppressing {self.suppressed_1070_count} frames; sim pos ({sim.x:.2f}, {sim.y:.2f})")
                self._broadcast(op, p)
                # 1018 3D pose rides bot heroes while moving (measured layout
                # in corpus: local hero receives zero 1018, only bots receive 1018).
                if (op == wire.OP.POSITION and self.hero_keepalive
                        and eid != self.players[0].eid):
                    self.keep_seq = (self.keep_seq + 1) & 0xFFFF
                    self._broadcast(wire.OP.ENTITY_POSE_3D,
                                    roster.build_entity_pose_3d(
                                        eid, self.keep_seq,
                                        sim.x, 1.05, -sim.y))
                if op == wire.OP.COMBAT_DELTA:
                    src_eid, tgt_eid, delta = struct.unpack_from(">IIf", p, 0)
                    self.log(f"[combat] hero attack: COMBAT_DELTA {src_eid} -> {tgt_eid}: {delta:.1f}")
                    # Hit minion
                    if self.wave_director is not None and src_eid == sim.eid:
                        minion_damage_frames = self.wave_director.apply_hero_damage_to_minion(
                            tgt_eid, -delta, sim)
                        for mop, mp in minion_damage_frames:
                            self._broadcast(mop, mp)
                            if mop == wire.OP.DESTROY:
                                self.log(f"[economy] hero {sim.eid} killed minion {tgt_eid}! Awarding bounty.")
                                bounty_frames = self.economy.reward_minion_bounty(sim.eid, self.hero_sims)
                                for bop, bp in bounty_frames:
                                    self._broadcast(bop, bp)
                    # Hit turret / structure
                    if tgt_eid in self.structures.structures and src_eid == sim.eid:
                        target_struct = self.structures.structures[tgt_eid]
                        if target_struct.team != sim.team:
                            struct_frames = self.structures.apply_damage(tgt_eid, -delta, src_eid)
                            for sop, sp in struct_frames:
                                self._broadcast(sop, sp)
                            self.log(f"[combat] hero {src_eid} attacked structure {tgt_eid} for {-delta:.1f} (HP: {target_struct.hp:.1f}/{target_struct.max_hp:.1f})")
                    # Hit enemy hero! (PvP combat)
                    if tgt_eid in self.hero_sims and src_eid == sim.eid:
                        enemy_hero = self.hero_sims[tgt_eid]
                        if enemy_hero.team != sim.team:
                            was_alive = enemy_hero.is_alive
                            hero_dmg_frames = enemy_hero.apply_damage(-delta, src_eid, now)
                            for hop, hp in hero_dmg_frames:
                                self._broadcast(hop, hp)
                            self.log(f"[combat] hero {src_eid} hit enemy hero {tgt_eid} for {-delta:.1f}")
                            if was_alive and not enemy_hero.is_alive:
                                self.log(f"[economy] hero {src_eid} killed enemy hero {tgt_eid}! Awarding bounty.")
                                bounty_frames = self.economy.reward_hero_bounty(src_eid, tgt_eid, self.hero_sims)
                                for bop, bp in bounty_frames:
                                    self._broadcast(bop, bp)
                    # Hit jungle monster
                    if tgt_eid in self.jungle.monsters and src_eid == sim.eid:
                        jungle_frames = self.jungle.apply_damage_to_monster(
                            tgt_eid, -delta, sim, now,
                            economy_mgr=self.economy,
                            all_heroes=self.hero_sims,
                        )
                        for jop, jp in jungle_frames:
                            self._broadcast(jop, jp)
                        self.log(f"[combat] hero {src_eid} hit jungle monster {tgt_eid} for {-delta:.1f}")

        # Step jungle camps and monsters
        jungle_frames = self.jungle.step(dt, now, self.hero_sims, economy_mgr=self.economy)
        for jop, jp in jungle_frames:
            self._broadcast(jop, jp)

        # Step static turrets (aggro 1045 + attacks 1054)
        minions = self.wave_director.minions if self.wave_director is not None else []
        turret_frames = self.structures.step(now, self.hero_sims, minions)
        for top, tp in turret_frames:
            self._broadcast(top, tp)

        if self.structures.match_finished:
            self.log(f"[match] MATCH FINISHED! Team {self.structures.winner_team} WINS!")

        # Keep primary hero vars synced for backwards compatibility
        if self.players[0].eid in self.hero_sims:
            p0 = self.hero_sims[self.players[0].eid]
            self.hero_x = p0.x
            self.hero_y = p0.y
            self.hero_facing = p0.facing
            self.move_target = p0.move_target

    def _dump_reconnect_state(self, conn, player, send):
        """Emit full state dump to a reconnecting client."""
        send(wire.OP.GAME_SETUP, roster.build_game_setup(roster.MODE_SOLO_BOTS, player.eid))
        send(wire.OP.GAME_MODE, roster.build_game_mode())
        self._dump_world_to(conn, send_fn=send)
        for eid, sim in self.hero_sims.items():
            send(wire.OP.POSITION, roster.build_position(eid, sim.x, sim.y))
            if sim.hp < sim.max_hp:
                delta = sim.hp - sim.max_hp
                send(wire.OP.ENTITY_STAT, roster.build_hero_stat(eid, delta, stat_type=6))
            if not sim.is_alive:
                send(wire.OP.ENTITY_STATE, roster.build_hero_death_state(eid))
        if self.wave_director is not None:
            for m in self.wave_director.minions:
                if m.alive:
                    send(wire.OP.POSITION, roster.build_position(m.eid, m.x, m.y))
        send(wire.OP.SLOT_FLAGS_PING, roster.build_slot_flags(self.players))

    # -- loop ---------------------------------------------------------------

    def _pump(self, timeout):
        """Process queued c2s events; block up to `timeout` for the first."""
        try:
            opcode, payload, conn = self.events.get(timeout=timeout)
        except queue.Empty:
            return
        self._apply_event(opcode, payload, conn)
        while True:
            try:
                opcode, payload, conn = self.events.get_nowait()
            except queue.Empty:
                return
            self._apply_event(opcode, payload, conn)

    def run(self):
        try:
            self._pick_deadline = time.monotonic() + PICK_COUNTDOWN_START
            while not self._stop_event.is_set():
                if self.phase == self.PICK:
                    self._pump(timeout=SNAPSHOT_INTERVAL)
                    if (self.locked and self.commit_hash is None
                            and self.lock_requested_at is not None
                            and time.monotonic() - self.lock_requested_at > COMMIT_FALLBACK):
                        self._begin_lock()
                    if (self.phase == self.PICK
                            and time.monotonic() - self._last_snapshot_at >= SNAPSHOT_INTERVAL):
                        self._broadcast_snapshot(self._pick_countdown())
                    if (self.phase == self.PICK and not self.locked
                            and time.monotonic() >= self._pick_deadline):
                        self.log("[match] pick countdown expired — auto-locking roster")
                        self._begin_lock()
                elif self.phase == self.LOCKED:
                    self._pump(timeout=LOCK_TICK)
                    remaining = self.lock_deadline - time.monotonic()
                    if remaining <= 0:
                        self._finalize()
                    elif time.monotonic() - self._last_snapshot_at >= LOCK_TICK:
                        self._broadcast_snapshot((remaining, LOCK_COUNTDOWN))
                elif self.phase == self.FINAL:
                    self._pump(timeout=LOCK_TICK)
                    if not self.dumped and time.monotonic() >= self.dump_fallback_at:
                        self.log("[match] ready-barrier fallback timeout — entering WORLD phase")
                        self._enter_world()
                else:
                    self._run_world()
        except OSError:
            pass
        except Exception as exc:
            import traceback
            self.log(f"[match] SnapshotStream unhandled error: {exc!r}\n{traceback.format_exc()}")
        finally:
            with self._clients_lock:
                for c in list(self.clients.keys()):
                    try:
                        c.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        c.close()
                    except OSError:
                        pass
                self.clients.clear()
            if self.conn is not None:
                try:
                    self.conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    self.conn.close()
                except OSError:
                    pass


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
        self.streams = []                  # [self.session]
        self._streams_by_conn = {}
        self._stop = threading.Event()
        self._listener = None
        self._conns = []
        self.port = port                   # 0 = OS-assigned in start()
        self.session = None                # shared SnapshotStream match session
        self._session_lock = threading.Lock()

    def is_stopped(self) -> bool:
        return self._stop.is_set()

    def is_finished(self) -> bool:
        if self._stop.is_set():
            return True
        if self.session is not None:
            if not self.session.is_alive():
                return True
            if getattr(self.session, "structures", None) and self.session.structures.match_finished:
                return True
            if self.session.phase != self.session.WORLD:
                if len(self.session.clients) == 0:
                    return True
            else:
                # WORLD phase:
                # The 4.13 client's world-entry dance closes its draft connection
                # and only then opens the world connection (~8s transition). A 25s
                # grace window is granted. Once clients have joined the world,
                # if all clients subsequently disconnect, 15s grace is given
                # before marking the match finished.
                if len(self.session.clients) == 0:
                    now = time.monotonic()
                    had_clients = getattr(self.session, "world_had_clients", False)
                    since = getattr(self.session, "zero_clients_since", None)
                    if since is None:
                        since = getattr(self.session, "world_entered_at", now)
                    timeout = 15.0 if had_clients else 25.0
                    if now - since > timeout:
                        return True
        return False

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))   # port 0 = OS-assigned, dynamic per match
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]   # dynamic per match (§15.1)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self.session is not None:
            self.session.stop()
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
            if self.session is not None:
                self.session.remove_client(conn)
                # NOTE: a zero-client WORLD is deliberately left running —
                # the client's world-entry dance closes the draft conn before
                # the world conn opens (live 2026-09-07 07:02:39→47), and the
                # headless bot world is the M3 stability scenario. The match
                # ends via structures.match_finished or stack shutdown.
            self._streams_by_conn.pop(conn, None)
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
                      wire.OP.HERO_READY, wire.OP.BUY_CLOSE, wire.OP.MOVE_CAST,
                      wire.OP.TARGET_ENTITY, wire.OP.LEVELUP_A, wire.OP.LEVELUP_B):
            stream = self._streams_by_conn.get(conn)
            if stream is not None:
                stream.submit(opcode, payload, conn=conn)
        # Join handshakes (1112/1118/1123/1131/1119/1134/1137/1133/1157/1081…)
        # and gameplay verbs without a slice yet (1041/1078) are logged above;
        # semantic replies are T3 work.
        self.log(f"[match] c2s op={opcode} ({len(payload)} B)")

    def _serve_join(self, conn):
        """Present unpicked slots; 1118 comes from the client, not this burst."""
        with self._session_lock:
            send = self._sender(conn)
            ident = identity_from_token(self.session_uuid)
            if self.session is None or not self.session.is_alive():
                players = roster.default_solo_bots(ident, self.match_id)
                self.session = SnapshotStream(conn, players, self.match_id, send, self.log)
                self.streams = [self.session]
                self._streams_by_conn[conn] = self.session
                self.session.start()
                # Opener burst for client 1, pcap order: 1001 → 1108 → 1107×275 → 1113[0]
                send(wire.OP.GAME_SETUP,
                     roster.build_game_setup(roster.MODE_SOLO_BOTS, players[0].eid))
                send(wire.OP.GAME_MODE, roster.build_game_mode())
                for name in hero_catalog.HERO_CATALOG_1107_NAMES:
                    send(wire.OP.HERO_CATALOG, hero_catalog.catalog_payload(name))
                send(wire.OP.SNAPSHOT_JOIN,
                     roster.build_snapshot(players, countdown=(298.717, 300.0),
                                           pick_flags=0x0000))
            else:
                self.session.add_client(conn, ident, send)
                self._streams_by_conn[conn] = self.session

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
