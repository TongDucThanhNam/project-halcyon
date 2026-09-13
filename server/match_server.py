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
from functools import lru_cache, wraps

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
    import combat
    import navigation
    import hero_balance
    import items
    import match_end
    import attack_wire
    import projectile_wire
    import skye_wire
    import cooldown_wire
    import item_input
    import lifecycle_wire
    import entity_spawn
    import ability_wire
    import shop_wire
    import recall_wire
    import level_wire
    import vision
    from sandbox_qa import SandboxQA
    from actor_slots import ActorSlots
    from paths import stack_dir
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
    from . import combat, items, navigation, hero_balance, match_end, attack_wire, projectile_wire, skye_wire, cooldown_wire
    from . import item_input, lifecycle_wire, entity_spawn, ability_wire, shop_wire, recall_wire, level_wire, vision
    from .sandbox_qa import SandboxQA
    from .actor_slots import ActorSlots
    from .paths import stack_dir

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
WORLD_TAPE_PATH = str(stack_dir() / "world_tape.bin")
SIM_TICK = 0.05
WORLD_PUMP_TICK = 0.05            # s, world-loop pump/tick granularity


@lru_cache(maxsize=1)
def _map_navigation():
    return navigation.load_halcyon_navmesh()


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


def _state_locked(method):
    """Serialize transport attachment and fixed-step state without changing dt."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return locked


class SnapshotStream(threading.Thread):
    """Owns shared pick/lock/world simulation state and client streams."""

    PICK, LOCKED, FINAL, WORLD = "pick", "locked", "final", "world"

    def __init__(self, conn, players, match_id, send, log=print, *, navigation_mesh=None):
        super().__init__(daemon=True)
        self.conn = conn
        self.players = players
        self.match_id = match_id
        self._send = send
        self.log = log
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()
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
        self._completed_bootstrap_conns = set()
        self._resource_catchup = {}
        self._last_death_frames = {}
        self.hero_sims = {}
        self.navigation = _map_navigation() if navigation_mesh is None else navigation_mesh
        self.actor_slots = ActorSlots()
        for player in players:
            self.actor_slots.register(player.eid, player.slot)
        self._last_position_at = {}
        self._clients_lock = threading.Lock()

        # Initialize hero movements for all players
        for p in self.players:
            spawn_pos = roster.HERO_SPAWNS.get(p.eid, (roster.SPAWN_X, roster.SPAWN_Y))
            self.hero_sims[p.eid] = hero_movement.HeroMovement(
                eid=p.eid, team=p.team,
                x=spawn_pos[0], y=spawn_pos[1], navigation=self.navigation)
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
        self.sim_tick = 0
        self.sim_time = 0.0
        self._match_result_at_tick = None
        self.result_sent = False
        self.attacks = combat.BasicAttackEngine()
        self.world_tick = 0               # u32 at +8 (1086 deltas will share it)
        self.seq_1010 = 0                 # u8 at +116, +1 per 1010 emitted
        self.tape_frames = None           # loaded lazily on WORLD entry
        self.tape_i = 0
        self.tape_done = False
        self.structures = structures.StructureManager()
        self.world_entities: dict[int, tuple[float, float]] = {}
        for eid, s in self.structures.structures.items():
            self.world_entities[eid] = (s.x, s.y)
        # Share one effect-identity range across buffs, projectiles and spell
        # actors. Only actual actors additionally allocate a compact slot.
        self._next_buff_instance = 2_000_000
        self.status_manager = status_effects.StatusManager(
            instance_allocator=self._allocate_buff_instance)
        self.skye_volleys = skye_wire.VolleyPresentation(self.actor_slots, self._allocate_buff_instance)
        self.damage_queue = status_effects.DamageModifierQueue()
        self.economy = economy.EconomyManager()
        self.items = items.ItemManager(self.economy, self.status_manager)
        self.shop_presentation = shop_wire.ShopPresentation(
            self.status_manager, self._allocate_buff_instance)
        self.recall_presentation = recall_wire.RecallPresentation(self.status_manager)
        self.qa = SandboxQA.from_environment()
        self.vision = vision.Vision(actor_slots=self.actor_slots)
        self.emit_trickle = True
        self.jungle = jungle.JungleManager(open_time=0.0, navigation=self.navigation,
            status_manager=self.status_manager,
            experimental_capture=bool(os.environ.get("HALCYON_EXPERIMENTAL_CAPTURE")),
            actor_slots=self.actor_slots)
        self._jungle_published = False
        self.hero_kits: dict[int, abilities.HeroKit] = {}
        for eid, sim in self.hero_sims.items():
            self.hero_kits[eid] = self._new_hero_kit(sim, roster.UNPICKED_HERO_ID)
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
        # A reconnect dump must describe one tick. Never hold _clients_lock
        # across callbacks that may send or broadcast additional frames.
        with self._state_lock:
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
                slot_idx = next((i for i, p in enumerate(self.players) if p.is_bot), None)
            if slot_idx is None:
                raise ValueError("match has no available player slot")

            player = self.players[slot_idx]
            player.is_bot = False
            player.uuid = session_uuid
            player.handle = f"Player {slot_idx + 1}" if slot_idx != 0 else "Guest"
            if self.phase == self.PICK:
                player.selection_hash = 0
                player.pick_flags = 0

            self.clients[conn] = (player, send)

            spawn_pos = roster.HERO_SPAWNS.get(player.eid, (roster.SPAWN_X, roster.SPAWN_Y))
            if player.eid not in self.hero_sims:
                self.hero_sims[player.eid] = hero_movement.HeroMovement(
                    eid=player.eid, team=player.team,
                    x=spawn_pos[0], y=spawn_pos[1], navigation=self.navigation)
            if player.eid in self.bot_controllers:
                del self.bot_controllers[player.eid]
            if player.eid not in self.hero_kits:
                self.hero_kits[player.eid] = self._new_hero_kit(self.hero_sims[player.eid], player.hero_id)

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

    @_state_locked
    def remove_client(self, conn):
        with self._clients_lock:
            p_info = self.clients.pop(conn, None)
            self.ready_clients.discard(conn)
            self.dumped_conns.discard(conn)
            self._completed_bootstrap_conns.discard(conn)
            self._resource_catchup.pop(conn, None)
            if p_info is not None:
                p = p_info[0]
                self.log(f"[match] client left: slot {p.slot} (eid {p.eid})")
            if not self.clients:
                self.zero_clients_since = time.monotonic()

    # -- frame broadcasting & targeted sending -------------------------------

    def _new_hero_kit(self, sim, hero_id, *, hero_name=None):
        kit = abilities.create_hero_kit(sim, hero_id, hero_name=hero_name)
        if hasattr(kit, "volley_presentation"):
            kit.volley_presentation = self.skye_volleys.start
        if hasattr(kit, "additional_targets"):
            kit.additional_targets = lambda: self.structures.structures.values()
        return kit

    def _allocate_buff_instance(self):
        instance = self._next_buff_instance
        if instance > 0xffffffff:
            raise RuntimeError("buff instance ID space exhausted")
        self._next_buff_instance += 1
        return instance

    def _drain_effect_frames(self):
        for eid in tuple(self.recall_presentation.active):
            hero = self.hero_sims.get(eid)
            if hero is None or hero.recall_completes_at is None:
                self.recall_presentation.cancel(eid, self.sim_time)
        self._emit_frames(self.status_manager.drain_frames())

    @_state_locked
    def _broadcast(self, opcode: int, payload: bytes, *, bootstrap=False, resource_credit=False):
        if opcode == wire.OP.ENTITY_DEATH and len(payload) == 14:
            eid = struct.unpack_from(">I", payload)[0]
            self._last_death_frames[eid] = payload
            self.status_manager.clear_target(eid, now=self.sim_time)
        elif opcode in (wire.OP.ENTITY_REVIVE, wire.OP.DESPAWN) and len(payload) >= 4:
            self._last_death_frames.pop(struct.unpack_from(">I", payload)[0], None)
        dead = []
        with self._clients_lock:
            for conn, (_, send_fn) in list(self.clients.items()):
                if bootstrap and conn in self._completed_bootstrap_conns:
                    continue
                try:
                    outgoing = payload
                    if resource_credit and opcode == wire.OP.ENTITY_STAT:
                        eid, amount, channel = struct.unpack_from(">IfB", payload)
                        credited = self._resource_catchup.get(conn, {}).pop((eid, channel), 0.0)
                        if credited:
                            outgoing = roster.build_hero_stat(eid, amount - credited, channel,
                                                              tail=payload[9:])
                    send_fn(opcode, outgoing)
                except OSError:
                    dead.append(conn)
            for c in dead:
                self.clients.pop(c, None)
                self.ready_clients.discard(c)
                self.dumped_conns.discard(c)
                self._completed_bootstrap_conns.discard(c)
                self._resource_catchup.pop(c, None)
        if self._send is not None and not self.clients:
            try:
                self._send(opcode, payload)
            except OSError:
                pass
        self.frames_sent += 1

    @_state_locked
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
                        self.dumped_conns.discard(conn)
                        self._completed_bootstrap_conns.discard(conn)
                        self._resource_catchup.pop(conn, None)
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

    @_state_locked
    def _apply_event(self, opcode, payload, conn=None, bot_eid=None):
        try:
            return self._apply_event_impl(opcode, payload, conn, bot_eid)
        finally:
            self._drain_effect_frames()

    def _apply_event_impl(self, opcode, payload, conn=None, bot_eid=None):
        if conn is not None and conn not in self.clients:
            return  # A queued packet from a detached socket has no player authority.
        if bot_eid is not None:
            player = next((p for p in self.players if p.eid == bot_eid), self.players[0])
        elif conn is not None and conn in self.clients:
            player = self.clients[conn][0]
        else:
            player = self.players[0]

        sim = self.hero_sims.get(player.eid)
        if self.structures.match_finished and opcode in (
                wire.OP.MOVE_CAST, wire.OP.TARGET_ENTITY, wire.OP.LEVELUP_B,
                wire.OP.TARGETLESS_CAST, wire.OP.GROUND_CAST, wire.OP.SKILLSHOT_CAST,
                wire.OP.SHOP_BUY, wire.OP.ITEM_USE):
            return

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
                if self.phase == self.WORLD:
                    self._dump_reconnect_state(conn, player,
                        lambda op, body: self._send_to(conn, op, body), include_setup=False)
                else:
                    self._dump_world_to(conn)
            if self.phase == self.FINAL:
                self._enter_world()
            if opcode == wire.OP.HERO_READY and conn is not None:
                self.ready_clients.add(conn)
            if ((self.dumped or self.phase == self.WORLD)
                    and (self.tape_frames == [] or conn in self._completed_bootstrap_conns)):
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
                cfg_path = str(stack_dir() / "suppress_1070.json")
                if os.path.exists(cfg_path):
                    try:
                        with open(cfg_path, "r") as f:
                            cfg = json.load(f)
                            suppress_sec = float(cfg.get("duration", suppress_sec))
                            suppress_move = int(cfg.get("move", suppress_move))
                    except Exception:
                        pass
                if suppress_sec > 0 and (suppress_move == 0 or suppress_move == self.move_count):
                    now = self.sim_time
                    self.suppress_until = now + suppress_sec
                    self.suppress_active = True
                    self.suppressed_1070_count = 0
                    self.log(f"[match] move #{self.move_count}: suppressing periodic 1070 for eid {player.eid} for {suppress_sec:.2f}s (until +{suppress_sec:.2f}s)")
                else:
                    self.suppress_active = False
            if self.sparse_1070:
                self.sparse_budget[player.eid] = 6   # ~1.2 s of 5 Hz burst
            if sim is not None and sim.is_alive:
                kit = getattr(self, "hero_kits", {}).get(player.eid)
                if kit is not None:
                    kit.interrupt_channel(self.sim_time)
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
            if bot_eid is not None and player.is_bot:
                try:
                    slot_idx = roster.parse_ability_cast(payload)
                except ValueError as exc:
                    self.log(f"[match] rejected 1078 ability cast: {exc}")
                    return
                self.log(f"[ability] eid {player.eid} cast ability slot {slot_idx}")
                kit = self.hero_kits.get(player.eid)
                if kit is not None:
                    now = self.sim_time
                    target_eid = sim.target_eid if sim is not None else None
                    ability_frames = kit.cast_ability(
                        slot=slot_idx,
                        now=now,
                        target_eid=target_eid,
                        target_pos=None,
                        status_manager=getattr(self, "status_manager", None),
                        damage_queue=getattr(self, "damage_queue", None),
                        all_heroes=self.hero_sims,
                        all_minions=self._ability_targets(),
                        damage_callback=self._deal_damage,
                    )
                    self._emit_frames(ability_frames)
            else:
                if len(payload) != 6 or payload[0] not in (0, 1, 2) or payload[1:] != bytes(5):
                    return
                slot_idx = payload[0]
                kit = self.hero_kits.get(player.eid)
                econ = getattr(self, "economy", None)
                if econ is not None and econ.upgrade_ability(player.eid, slot_idx, kit):
                    if conn is not None:
                        self._send_to(conn, wire.OP.LEVELUP_B, payload)
                    self._emit_frames(self._learned_ability_frames(player.eid, slot_idx))
        elif opcode in (wire.OP.TARGETLESS_CAST, wire.OP.GROUND_CAST):
            try:
                if opcode == wire.OP.TARGETLESS_CAST:
                    target_eid, action, flags = roster.parse_targetless_cast(payload)
                    target_pos = None
                else:
                    x, y, action, flags = roster.parse_ground_cast(payload)
                    target_eid, target_pos = None, (x, y)
            except ValueError as exc:
                self.log(f"[match] rejected cast: {exc}")
                return
            if flags != 0:
                return
            slot = ability_wire.hero_slot_for_action(player.hero_id, action)
            if slot in (0, 1, 2):
                kit = self.hero_kits.get(player.eid)
                if kit is not None:
                    self._emit_frames(kit.cast_ability(
                        slot, self.sim_time, target_eid=target_eid, target_pos=target_pos,
                        status_manager=self.status_manager, damage_queue=self.damage_queue,
                        all_heroes=self.hero_sims,
                        all_minions=self._ability_targets(),
                        damage_callback=self._deal_damage,
                        cast_callback=self.items.on_ability_cast))
            elif (action == ability_wire.hero_action_variant(player.hero_id, "recall")
                  and opcode == wire.OP.TARGETLESS_CAST and target_eid is None):
                if sim is not None and sim.is_alive and self.status_manager.can_cast(sim.eid, self.sim_time):
                    self.hero_kits[sim.eid].interrupt_channel(self.sim_time)
                    self._emit_frames(sim.start_recall(self.sim_time))
                    self.recall_presentation.start(sim.eid, self.sim_time)
                    action = ability_wire.hero_action_variant(player.hero_id, "recall")
                    if action is not None:
                        self._broadcast(wire.OP.TARGET_ACQUIRE,
                                        ability_wire.build_target_cast(sim.eid, None, action))
            else:
                kit = self.hero_kits.get(player.eid)
                cancel = getattr(kit, "cancel_native_action", None)
                cancelled = (cancel(action, self.sim_time, status_manager=self.status_manager)
                             if cancel is not None else None)
                if cancelled is not None:
                    self._emit_frames(cancelled)
                    self._drain_effect_frames()
                else:
                    self.log(f"[match] unmapped native action {action}: {payload.hex()}")
        elif opcode == wire.OP.SKILLSHOT_CAST:
            try:
                caster, target, x, y, slot_idx, flag = roster.parse_skillshot_cast(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1102 skillshot cast: {exc}")
                return
            self.log(f"[ability] eid {caster} skillshot slot {slot_idx} at ({x:.2f}, {y:.2f}) target {target}")
            if caster != player.eid:
                return
            slot_idx = ability_wire.hero_slot_for_action(player.hero_id, slot_idx)
            if slot_idx is None:
                return
            kit = self.hero_kits.get(caster)
            if kit is not None:
                now = self.sim_time
                tgt_eid = target if target != 0xFFFFFFFF else None
                ability_frames = kit.cast_ability(
                    slot=slot_idx,
                    now=now,
                    target_eid=tgt_eid,
                    target_pos=(x, y),
                    status_manager=self.status_manager,
                    damage_queue=self.damage_queue,
                    all_heroes=self.hero_sims,
                    all_minions=self._ability_targets(),
                    damage_callback=self._deal_damage,
                )
                self._emit_frames(ability_frames)
        elif opcode == wire.OP.SHOP_BUY:
            try:
                target_eid, item_id = roster.parse_shop_buy(payload)
            except ValueError as exc:
                self.log(f"[match] rejected 1081 shop buy: {exc}")
                return
            self.log(f"[economy] eid {target_eid} purchasing item {item_id}")
            if target_eid != player.eid:
                return
            hero = self.hero_sims.get(target_eid)
            if hero is not None:
                ok, buy_frames = self.economy.purchase_item(target_eid, item_id, hero)
                if ok:
                    self.log(f"[economy] eid {target_eid} bought item {item_id}, gold remaining: {self.economy.get_or_create(target_eid).gold:.1f}")
                    for bop, bp in buy_frames:
                        self._broadcast(bop, bp)
                else:
                    self.log(f"[economy] eid {target_eid} failed purchase {item_id} (not enough gold or full)")
        elif opcode == wire.OP.ITEM_USE:
            try:
                request = item_input.parse_item_input(opcode, payload)
                econ = self.economy.players.get(player.eid)
                slot = None if econ is None else item_input.resolve_inventory_slot(
                    econ.inventory_instances, request.instance_id)
            except ValueError as exc:
                self.log(f"[match] rejected item use: {exc}")
                return
            if slot is None:
                return
            # The corpus echoes cooldown-time duplicate clicks too. This
            # acknowledges an owned request; ItemManager decides its outcome.
            self._send_to(conn, wire.OP.ITEM_USE, payload)
            self.activate_item(player.eid, slot)

    def _pick_countdown(self):
        remaining = max(0.0, self._pick_deadline - time.monotonic())
        return (remaining, PICK_COUNTDOWN_START)

    @_state_locked
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

    @_state_locked
    def _finalize(self):
        for player in self.players:
            sim = self.hero_sims[player.eid]
            hero_balance.configure_hero(sim, player.hero_id)
            self.hero_kits[player.eid] = self._new_hero_kit(
                sim, player.hero_id, hero_name=sim.hero_name)
            self.hero_kits[player.eid].on_cast = self.items.on_ability_cast
        self.phase = self.FINAL
        for p in self.players:
            self._broadcast(wire.OP.PLAYER_INFO, roster.build_player_info(p, self.match_id))
        self._broadcast(wire.OP.ROSTER_FINAL, roster.build_zero_ack())
        self.dump_fallback_at = time.monotonic() + WORLD_DUMP_FALLBACK
        self.log("[match] roster finalized: 1006×6 + 1132; awaiting client "
                 "1134/1137 (map load)")

    @_state_locked
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
                        self.actor_slots.observe(op, b[2:])
                        self.seq_1010 = b[118]
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

    @_state_locked
    def _dump_world_to(self, conn, send_fn=None, *, reconnect=False):
        """Dump world init to a specific client connection."""
        if conn is not None and conn in self.dumped_conns:
            return
        self.dumped = True
        self._load_tape()
        tape = bool(self.tape_frames)
        send = send_fn if send_fn is not None else (lambda op, p: self._send_to(conn, op, p))
        send(wire.OP.MODE_NAME, roster.build_mode_name())
        for p in self.players:
            send(wire.OP.PLAYER_INFO, roster.build_player_info(p, self.match_id))
        send(wire.OP.MODE_PING_1105, roster.build_zero_ack())
        for p in reversed(self.players):
            block = roster.build_hero_block(p)
            if reconnect:
                block = bytearray(block)
                sim = self.hero_sims[p.eid]
                econ = self.economy.get_or_create(p.eid)
                equipment = econ.get_total_item_stats()
                # Absolute current/max resources are decoded 1011 fields. A
                # fresh renderer has no previous HP/energy baseline to delta.
                for offset, value in ((42, sim.hp), (46, sim.max_hp - equipment["max_hp"]),
                                      (122, sim.energy), (126, sim.max_energy - equipment["max_energy"])):
                    struct.pack_into(">f", block, offset, value)
                # Replayed 1082 rank allocations consume one point each.
                allocated = sum(self.hero_kits[p.eid].ranks.values())
                for offset, value in ((294, econ.level), (314, econ.ability_points + allocated),
                                      (318, level_wire.within_level_xp(econ.xp, econ.level)),
                                      (322, level_wire.next_level_requirement(econ.level))):
                    struct.pack_into(">f", block, offset, value)
                block = bytes(block)
            send(wire.OP.HERO_BLOCK, block)
            hero_data, donated = roster.hero_init_for(p.hero_id)
            if donated:
                self.log(f"[match] hero id {p.hero_id} unmeasured — donor "
                         f"stat run from {roster.HERO_INIT_DONOR_ID} "
                         "[Open: real 1011 not captured]")
            for payload in cooldown_wire.build_initial_timers(p.eid, p.hero_id):
                send(wire.OP.TIMER_TICK, payload)
        if not tape and not reconnect:
            for p in self.players:
                send(wire.OP.PLAYER_TAG, roster.build_player_tag(p, self.match_id))
            for sop, sp in self.structures.get_spawn_1010_frames(actor_slots=self.actor_slots):
                send(sop, sp)
                self.seq_1010 = sp[116]
            seq = [self.seq_1010]
            for sop, sp in self.jungle.get_spawn_frames(seq_1010=seq, actor_slots=self.actor_slots):
                send(sop, sp)
            self.seq_1010 = seq[0]
            self._jungle_published = True
        if conn is not None:
            self.dumped_conns.add(conn)
        mode = "tape carries 1055/1087/deltas/echoes" if tape else \
               "1055 derived tags; static structures spawned; no 1087 spawn batch"
        self.log(f"[match] world init dumped to client; {mode}")

    @_state_locked
    def _dump_world(self):
        """1135, 1006×6, 1105, (1011 + 1162×7) reverse — corpus order."""
        self.dumped = True
        with self._clients_lock:
            active_conns = list(self.clients.keys())
        for conn in active_conns:
            self._dump_world_to(conn)
        if not active_conns:
            self._dump_world_to(None)

    @_state_locked
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
            self.wave_director = wave.Director(0.0, seq_1010=[self.seq_1010], actor_slots=self.actor_slots)
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
        next_move_tick = time.monotonic() + SIM_TICK
        next_ping = time.monotonic() + 1.0
        next_full_update = None       # armed when the live layer starts
        while not self._stop_event.is_set():
            with self._state_lock:
                now = time.monotonic()
                if not self.clients and self.zero_clients_since is not None:
                    timeout = 15.0 if self.world_had_clients else 25.0
                    if now - self.zero_clients_since > timeout:
                        self.log(f"[match] no clients connected for {timeout:.1f}s in WORLD — finishing match")
                        self._stop_event.set()
                        break
                if not self.tape_done:
                    while self.tape_i < len(self.tape_frames):
                        t_ms, body = self.tape_frames[self.tape_i]
                        if tape_base + t_ms / 1000.0 > now:
                            break
                        op = struct.unpack_from(">H", body)[0]
                        self._broadcast(op, body[2:], bootstrap=True)
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
                            self.seq_1010 = self.actor_slots.allocate(p.eid)
                            self._broadcast(wire.OP.ENTITY_FULL_UPDATE,
                                            roster.build_entity_full_update(
                                                p.eid, self.world_tick,
                                                hsim.x, hsim.y,
                                                self.seq_1010, hsim.facing))
                    if now >= next_ping:
                        next_ping = now + 1.0
                        self._broadcast(wire.OP.SLOT_FLAGS_PING,
                                        roster.build_slot_flags(self.players))

                while now >= next_move_tick and not self._stop_event.is_set():
                    # Loading clients must receive their ready echo before live
                    # resources, actors or combat can reference the loaded world.
                    if self.tape_done and (self.ready_clients or not self.clients):
                        if self.tape_done and not self._jungle_published:
                            seq = [self.seq_1010]
                            self._emit_frames(self.jungle.get_spawn_frames(seq_1010=seq,
                                                                          actor_slots=self.actor_slots))
                            self.seq_1010 = seq[0]
                            self._jungle_published = True
                        self.advance_simulation()
                    next_move_tick += SIM_TICK

            self._pump(timeout=WORLD_PUMP_TICK)

    def _step_hero(self, dt: float, now: float):
        self._step_heroes(dt, now)

    def _entities(self):
        entities = dict(self.hero_sims)
        entities.update(self.structures.structures)
        entities.update(self.jungle.monsters)
        if self.wave_director is not None:
            entities.update((m.eid, m) for m in self.wave_director.minions)
        return entities

    def _ability_targets(self):
        """Lane and jungle creatures share the same ability hitbox queries."""
        creatures = list(self.jungle.monsters.values())
        if self.wave_director is not None:
            creatures.extend(self.wave_director.minions)
        return creatures

    def _deal_damage(self, source, target, raw, damage_type, now, *, basic=False, proc=False):
        """Resolve one hit once, then publish its result and award its kill."""
        if raw <= 0 or not combat.alive(target) or self.structures.match_finished:
            return []
        if combat.team(source) == combat.team(target):
            return []
        victim_eid = target.eid
        dtype = status_effects.DamageType(damage_type)
        frames = []
        victim_kit = self.hero_kits.get(target.eid)
        if victim_kit is not None:
            raw, reactions = victim_kit.modify_incoming_damage(
                raw, now, status_manager=self.status_manager)
            frames.extend(reactions)
        reaction_count = len(frames)
        config = getattr(target, "config", target)
        ctx = status_effects.DamageContext(
            source_eid=source.eid, target_eid=target.eid, damage_type=dtype,
            raw_amount=raw, now=now,
            armor=getattr(target, "armor", getattr(config, "armor", 0)),
            shield=getattr(target, "shield", getattr(config, "shield", 0)),
            armor_pierce=getattr(source, "armor_pierce", 0),
            shield_pierce=getattr(source, "shield_pierce", 0),
            damage_reduction=getattr(target, "damage_reduction", 0))
        damage = self.damage_queue.resolve(ctx).final_damage
        landed_damage = damage
        source_is_hero = source.eid in self.hero_sims
        if target.eid in self.hero_sims:
            self.items.before_damage(target, damage, now)
        damage, _ = self.status_manager.absorb_damage_with_barrier(target.eid, damage, now)
        if damage <= 0:
            # A barrier absorbs damage, not the contact. Consume/apply on-hit
            # effects once even when this component removes no actual HP.
            if landed_damage > 0:
                if target.eid in self.hero_sims:
                    target.cancel_recall()
                    if source_is_hero:
                        frames.extend(self.structures.on_hero_damaged(source, target))
                frames.extend(self._on_hit_effects(source, target, dtype, now,
                                                   basic=basic, proc=proc))
            return frames
        minions = self.wave_director.minions if self.wave_director else []
        if target.eid in self.structures.structures:
            frames.extend(self.structures.apply_damage(target.eid, damage, source.eid,
                                                  source_is_hero=source_is_hero, minions=minions))
            if self.structures.match_finished and self._match_result_at_tick is None:
                self._match_result_at_tick = self.sim_tick + round(6.0 / SIM_TICK)
            return frames
        if target.eid in self.hero_sims:
            before = target.hp
            # 1054 already changes the victim's HP. A second 1053 health
            # delta would subtract the same hit twice on the real client.
            frames.extend((op, payload) for op, payload in
                target.apply_damage(damage, source.eid, now, damage_type="true")
                if not (op == wire.OP.ENTITY_STAT and payload[8] == roster.STAT_HEALTH))
            damage = before - target.hp
            if source_is_hero and damage > 0:
                frames.extend(self.structures.on_hero_damaged(source, target))
            if source_is_hero and not target.is_alive:
                frames.extend(self.economy.reward_hero_bounty(source.eid, target.eid, self.hero_sims))
        elif target.eid in self.jungle.monsters and source_is_hero:
            frames.extend(self.jungle.apply_damage_to_monster(
                target.eid, damage, source, now, self.economy, self.hero_sims))
        else:
            target.hp = max(0, target.hp - damage)
            if source_is_hero and self.wave_director:
                self.wave_director.on_minion_damaged_by_hero(target.eid, source)
            if target.hp <= 0:
                if target.eid in self.jungle.monsters:
                    frames.extend(self.jungle.on_monster_death(target, source.eid, now))
                elif self.wave_director is not None and isinstance(target, wave.Minion):
                    frames.extend(self.wave_director.on_minion_death(target, source.eid, now))
                else:
                    target.alive = False
                    frames.extend([(wire.OP.DESTROY, roster.build_destroy(target.eid)),
                                   (wire.OP.DESPAWN, roster.build_despawn(target.eid))])
                    self.actor_slots.release(target.eid)
                if source_is_hero:
                    frames.extend(self.economy.reward_minion_bounty(source.eid, self.hero_sims))
        # The damage event precedes the HP/death/kill reward result, once per hit.
        frames.insert(reaction_count, (wire.OP.COMBAT_DELTA, roster.build_combat_delta(
            source.eid, victim_eid, -damage,
            tail=roster.COMBAT_DELTA_HERO_TAIL if basic else roster.COMBAT_DELTA_TAIL)))
        frames.extend(self._on_hit_effects(source, target, dtype, now, basic=basic, proc=proc))
        return frames

    def _on_hit_effects(self, source, target, dtype, now, *, basic, proc):
        frames = []
        if source.eid in self.hero_sims and not proc:
            if dtype in (status_effects.DamageType.CRYSTAL,
                         status_effects.DamageType.SHIELD_PIERCING_CRYSTAL):
                self.items.on_crystal_damage(source, target, now)
            if basic:
                frames.extend(self.items.on_basic_attack(source, target, now,
                    lambda a, b, amount, kind, t: self._deal_damage(a, b, amount, kind, t, proc=True)))
                kit = self.hero_kits.get(source.eid)
                if kit is not None and hasattr(kit, "on_basic_attack"):
                    frames.extend(kit.on_basic_attack(target, now,
                        status_manager=self.status_manager, damage_queue=self.damage_queue,
                        damage_callback=self._deal_damage))
                frames.extend(self.jungle.on_basic_attack(source, target, now,
                    lambda a, b, amount, kind, t: self._deal_damage(a, b, amount, kind, t, proc=True)))
        return frames

    def _emit_frames(self, frames):
        for frame in frames:
            opcode, payload = frame
            if getattr(frame, "resource_credit", False):
                self._broadcast(opcode, payload, resource_credit=True)
            else:
                self._broadcast(opcode, payload)

    def _learned_ability_frames(self, eid, slot):
        kit = self.hero_kits[eid]
        ability = kit.abilities[slot]
        frames = []
        if ability.native_action is not None:
            frames.append((wire.OP.INVENTORY_SLOT,
                           roster.build_inventory_slot(eid, ability.native_action)))
        if ability.tag_inst is not None:
            duration = ability.cooldown / (1 + max(0.0, self.hero_sims[eid].cooldown_reduction))
            frames.append((wire.OP.TIMER_TICK, cooldown_wire.build_ability_timer(
                eid, ability.tag_inst, max(0.0, kit.cooldowns.get(slot, 0.0) - self.sim_time),
                duration, ultimate=int(slot) == 2, learned=True)))
        return frames

    def _begin_basic_attack(self, source, target):
        ordinal = getattr(source, "attack_animation_ordinal", 0)
        kit = self.hero_kits.get(source.eid)
        variant = kit.basic_attack_variant(self.sim_time) if kit is not None else None
        if variant is None:
            variant = attack_wire.basic_variant_for(getattr(source, "hero_id", None), ordinal)
        if variant is not None:
            self._emit_frames(attack_wire.build_attack_start_frames(
                source.eid, target.eid, variant, source.x, source.y))
            source.attack_animation_ordinal = ordinal + 1
        return variant

    def _target_projectile_frames(self, source, target, profile):
        if profile is None:
            return []
        source_slot = self.actor_slots.by_eid.get(source.eid)
        target_slot = self.actor_slots.by_eid.get(target.eid)
        if source_slot is None or target_slot is None:
            return []
        return [(projectile_wire.OP_TARGET_PROJECTILE, projectile_wire.build_target_projectile(
            self._allocate_buff_instance(), profile, source_slot, target_slot))]

    def _release_basic_projectile(self, source, target, projectile):
        profile = projectile_wire.hero_projectile(
            getattr(source, "hero_id", None), projectile.presentation_variant)
        self._emit_frames(self._target_projectile_frames(source, target, profile))

    def _release_minion_projectile(self, source, target, variant):
        profile = projectile_wire.minion_projectile(target.eid in self.hero_sims)
        return self._target_projectile_frames(source, target, profile)

    def _basic_attack_damage_profile(self, source, target):
        kit = self.hero_kits.get(source.eid)
        profile = getattr(kit, "basic_attack_damage_profile", None)
        result = profile() if profile is not None else None
        return result if result is not None else (source.attack_damage, "weapon")

    def _step_heroes(self, dt: float, now: float):
        """One deterministic gameplay slice; `now` is elapsed match time."""
        if self.structures.match_finished:
            return
        entities = self._entities()
        # Existing projectiles advance before new shots release this tick.
        for impact in self.attacks.step_projectiles(dt, entities):
            source, target = entities.get(impact.source_eid), entities.get(impact.target_eid)
            if source is not None and target is not None:
                self._emit_frames(self._deal_damage(source, target, impact.damage, impact.damage_type, now, basic=True))
        # Publish C field phase changes before the kit can emit their damage.
        self._emit_frames(self.skye_volleys.step(now))
        for eid, sim in sorted(self.hero_sims.items()):
            sim.match_elapsed = now
            kit = self.hero_kits.get(eid)
            prepare_movement = getattr(kit, "prepare_movement", None)
            if prepare_movement is not None:
                prepare_movement(now, status_manager=self.status_manager)
            target = entities.get(sim.target_eid)
            if target is not None and (not combat.alive(target) or combat.team(target) == sim.team):
                target = None
            target_pos = (target.x, target.y) if target is not None else None
            for opcode, payload in sim.step(dt, now=now, target_pos=target_pos,
                                             status_manager=self.status_manager):
                if opcode == wire.OP.POSITION and sim.is_moving:
                    if eid == self.players[0].eid and self.suppress_active:
                        if now < self.suppress_until:
                            self.suppressed_1070_count += 1
                            continue
                        self.suppress_active = False
                    if now - self._last_position_at.get(eid, -1.0) < roster.MOVE_TICK - 1e-9:
                        continue
                    self._last_position_at[eid] = now
                self._broadcast(opcode, payload)
            for impact in self.attacks.step_attacker(sim, target, now, self.status_manager,
                                                    on_windup=self._begin_basic_attack,
                                                    on_release=self._release_basic_projectile,
                                                    damage_profile=self._basic_attack_damage_profile):
                self._emit_frames(self._deal_damage(sim, target, impact.damage, impact.damage_type, now, basic=True))
            if hasattr(sim, "tick_lifecycle"):
                lifecycle_frames = sim.tick_lifecycle(dt, now, match_elapsed=now,
                                                      status_manager=self.status_manager)
                if getattr(sim, "last_recall_completed_at", None) == now:
                    heights = getattr(recall_wire, "RETURN_HEIGHTS_BY_EID", {}).get(sim.eid)
                    if heights is None:
                        heights = getattr(recall_wire, "RETURN_HEIGHTS", {}).get(sim.team)
                    coordinates = (dict(x=sim.x, y=sim.y, effect_height=heights[0],
                                        relocation_height=heights[1]) if heights else {})
                    self._emit_frames(self.recall_presentation.complete(sim.eid, now, **coordinates))
                self._emit_frames(lifecycle_frames)
            kit = self.hero_kits.get(eid)
            if kit is not None:
                self._emit_frames(kit.step(now, status_manager=self.status_manager,
                    damage_queue=self.damage_queue, all_heroes=self.hero_sims,
                    all_minions=self._ability_targets(),
                    damage_callback=self._deal_damage))
        self._emit_frames(self.items.step(now, self.hero_sims, entities,
            damage_callback=lambda a, b, amount, kind, t: self._deal_damage(a, b, amount, kind, t, proc=True)))
        self.jungle.seq_1010[0] = self.seq_1010
        self._emit_frames(self.jungle.step(dt, now, self.hero_sims, economy_mgr=self.economy,
            damage_callback=lambda a, b, amount, kind, t: self._deal_damage(a, b, amount, kind, t, proc=True),
            structures=self.structures, navigation=self.navigation, status_manager=self.status_manager))
        self.seq_1010 = self.jungle.seq_1010[0]
        minions = self.wave_director.minions if self.wave_director else []
        if self.jungle.active_kraken is not None and self.jungle.active_kraken.is_alive:
            minions = list(minions) + [self.jungle.active_kraken]
        self._emit_frames(self.structures.step(now, self.hero_sims, minions,
                                               damage_callback=self._deal_damage))
        self._emit_frames(self.shop_presentation.step(now, self.hero_sims))
        self._emit_frames(self.vision.update(now, self._entities()))
        self.status_manager.clean_expired(now)
        if self.structures.match_finished:
            self.log(f"[match] MATCH FINISHED! Team {self.structures.winner_team} WINS!")
        primary = self.hero_sims.get(self.players[0].eid)
        if primary is not None:
            self.hero_x, self.hero_y = primary.x, primary.y
            self.hero_facing, self.move_target = primary.facing, primary.move_target

    @_state_locked
    def activate_item(self, eid, slot):
        """Validated item-slot intent; wire slot binding is supplied by the decoder."""
        result = self.items.activate(eid, slot, self.sim_time, self.hero_sims, self._entities())
        self._emit_frames(result.frames(eid))
        self._drain_effect_frames()
        return result

    @_state_locked
    def advance_simulation(self):
        """Run one 50 ms tick; OS scheduling changes when, never how much."""
        if self.qa is not None:
            self.qa.pump(self)
        if self.structures.match_finished:
            if self._match_result_at_tick is None:
                self._match_result_at_tick = self.sim_tick + round(6.0 / SIM_TICK)
            self.sim_tick += 1
            self.sim_time = self.sim_tick * SIM_TICK
            if not self.result_sent and self.sim_tick >= self._match_result_at_tick:
                self._broadcast(wire.OP.MATCH_RESULT,
                    match_end.build_match_result(self.structures.winner_team))
                self.result_sent = True
            return
        self.sim_tick += 1
        self.sim_time = self.sim_tick * SIM_TICK
        if self.wave_director is not None:
            self.wave_director.seq_1010[0] = self.seq_1010
            self._emit_frames(self.wave_director.pump(self.sim_time, hero=self.hero_sim,
                structures=self.structures, navigation=self.navigation,
                status_manager=self.status_manager, damage_callback=self._deal_damage,
                on_projectile_release=self._release_minion_projectile,
                all_heroes=self.hero_sims))
            self.seq_1010 = self.wave_director.seq_1010[0]
        if self.enable_bots:
            for bot_eid, bot in sorted(self.bot_controllers.items()):
                hero = self.hero_sims.get(bot_eid)
                if hero is None or not hero.is_alive:
                    continue
                for opcode, payload in bot.step(
                        now=self.sim_time, hero=hero, all_heroes=self.hero_sims,
                        minions=self.wave_director.minions if self.wave_director else [],
                        structures=self.structures.structures,
                        hero_kit=self.hero_kits.get(bot_eid), econ=self.economy.get_or_create(bot_eid)):
                    self._apply_event(opcode, payload, bot_eid=bot_eid)
        self._step_heroes(SIM_TICK, self.sim_time)
        self._drain_effect_frames()
        for opcode, payload in self.economy.step(SIM_TICK, self.sim_time, self.hero_sims,
                                                emit_trickle=self.emit_trickle):
            # Reconnect included resources accumulated since the last coarse
            # flush. Deduct that prior credit only from this pending batch,
            # never from subsequent purchases, bounties, or combat deltas.
            self._broadcast(opcode, payload, resource_credit=(opcode == wire.OP.ENTITY_STAT
                and payload[8] in (roster.STAT_GOLD, roster.STAT_EXPERIENCE)))

    def _reconnect_bootstrap(self, send):
        """Recreate measured bootstrap allocations without replaying old combat.

        Past 1053 resources, 1085 purchases, 1086 timed buffs, target orders,
        and ready echoes are not current state. The authoritative overlays
        below replace those channels; a client receives its own ready echo.
        """
        created = set()
        for _at, body in self.tape_frames or []:
            opcode = struct.unpack_from(">H", body)[0]
            payload = body[2:]
            if opcode == wire.OP.ENTITY_FULL_UPDATE and len(payload) == 126:
                created.add(struct.unpack_from(">I", payload, 8)[0])
                send(opcode, payload)
            elif opcode in (wire.OP.ENTITY_DATA, wire.OP.PLAYER_TAG,
                            wire.OP.ENTITY_VISIBILITY, 1093):
                send(opcode, payload)
        if not self.tape_frames:
            for p in self.players:
                send(wire.OP.PLAYER_TAG, roster.build_player_tag(p, self.match_id))
        for opcode, payload in self.structures.get_spawn_1010_frames(actor_slots=self.actor_slots):
            if struct.unpack_from(">I", payload, 8)[0] not in created:
                send(opcode, payload)

    def _reconnect_hero_state(self, player, send):
        """Restore resources, inventory, learned skills and current cooldowns."""
        credited = {}
        for p in self.players:
            eid, sim = p.eid, self.hero_sims[p.eid]
            baseline = roster.build_hero_block(p)
            # HP/maxHP and energy/maxEnergy were absolute in this client's
            # single1011. The remaining decoded attributes are additive1052.
            attrs = ((4, sim.attack_damage - struct.unpack_from(">f", baseline, 214)[0]),
                     (7, sim.armor - struct.unpack_from(">f", baseline, 190)[0]),
                     (8, sim.shield - struct.unpack_from(">f", baseline, 202)[0]),
                     (5, sim.crystal_power),
                     (3, sim.energy_regen - getattr(sim, "base_energy_regen", sim.energy_regen)),
                     (15, getattr(sim, "bonus_attack_speed", 0.0) / 100.0),
                     (25, getattr(sim, "cooldown_reduction", 0.0)))
            for attribute, amount in attrs:
                if abs(amount) > 1e-6:
                    send(1052, roster.build_entity_attribute(eid, amount, attribute))
            econ = self.economy.players.get(eid)
            if econ is not None:
                equipment = econ.get_total_item_stats()
                for attribute, amount in ((0, equipment["max_hp"]), (2, equipment["max_energy"])):
                    if amount:
                        send(1052, roster.build_entity_attribute(eid, amount, attribute))
                send(wire.OP.ENTITY_STAT, roster.build_hero_stat(
                    eid, econ.gold - economy.START_GOLD, roster.STAT_GOLD))
                credited[eid, roster.STAT_GOLD] = self.economy._pending_gold.get(eid, 0.0)
                credited[eid, roster.STAT_EXPERIENCE] = self.economy._pending_xp.get(eid, 0.0)
                for opcode, payload in econ.default_item_frames(self.sim_time):
                    send(opcode, payload)
                for item, instance in zip(econ.inventory, econ.inventory_instances):
                    if item is None or instance is None:
                        continue
                    send(wire.OP.INVENTORY_ITEM, roster.build_item_inventory(eid, item.id, instance))
                for opcode, payload in self.items.cooldown_frames(eid, self.sim_time):
                    send(opcode, payload)
            kit = self.hero_kits.get(eid)
            if kit is not None:
                for slot, ability in sorted(kit.abilities.items()):
                    rank = kit.ranks.get(slot, 0)
                    for _ in range(rank):
                        if eid == player.eid:
                            send(wire.OP.LEVELUP_B, bytes((int(slot),)) + bytes(5))
                        if ability.native_action is not None:
                            send(wire.OP.INVENTORY_SLOT, roster.build_inventory_slot(eid, ability.native_action))
                    if ability.tag_inst is not None:
                        duration = ability.cooldown / (1.0 + max(0.0, getattr(sim, "cooldown_reduction", 0.0)))
                        send(wire.OP.TIMER_TICK, cooldown_wire.build_ability_timer(
                            eid, ability.tag_inst, max(0.0, kit.cooldowns.get(slot, 0.0) - self.sim_time),
                            duration, ultimate=int(slot) == 2, learned=rank > 0))
            if sim.is_alive and sim.is_moving and sim.move_target is not None:
                send(wire.OP.MOVE_TO, roster.build_move_intent(p.slot, *sim.move_target))
            send(wire.OP.POSITION, roster.build_position(eid, sim.x, sim.y))
            if not sim.is_alive:
                death = self._last_death_frames.get(eid)
                if death is not None:
                    send(wire.OP.ENTITY_DEATH, death)
                if sim.respawn_at is not None:
                    send(wire.OP.RESPAWN_TIMER, lifecycle_wire.build_respawn_countdown(
                        eid, max(0.0, sim.respawn_at - self.sim_time)))
                if sim.corpse_hidden:
                    send(lifecycle_wire.OP_HERO_CORPSE_HIDE, lifecycle_wire.build_hero_corpse_hide(eid))
                if sim.respawn_relocated:
                    send(lifecycle_wire.OP_HERO_RESPAWN,
                         lifecycle_wire.build_hero_respawn(eid, sim.spawn_x, sim.spawn_y))
        return credited

    @_state_locked
    def _dump_reconnect_state(self, conn, player, send, *, include_setup=True):
        """Send one coherent catchup: creation before state, position or death."""
        if conn in self.dumped_conns:
            return
        if include_setup:
            send(wire.OP.GAME_SETUP, roster.build_game_setup(roster.MODE_SOLO_BOTS, player.eid))
            send(wire.OP.GAME_MODE, roster.build_game_mode())
        self._dump_world_to(conn, send_fn=send, reconnect=True)
        self._reconnect_bootstrap(send)
        for opcode, payload in self.structures.get_state_1010_frames(actor_slots=self.actor_slots):
            send(opcode, payload)
        for structure in self.structures.structures.values():
            if not structure.is_alive and structure.eid in self._last_death_frames:
                send(wire.OP.ENTITY_DEATH, self._last_death_frames[structure.eid])
        if self._jungle_published:
            for frames in (self.jungle.get_spawn_frames(actor_slots=self.actor_slots),
                           self.jungle.get_state_1010_frames(
                               catalog=self.structures.spawn_catalog, actor_slots=self.actor_slots),
                           self.jungle.get_death_frames()):
                for opcode, payload in frames:
                    send(opcode, payload)
        if self.wave_director is not None:
            for frames in (self.wave_director.get_spawn_frames(self.sim_time, actor_slots=self.actor_slots),
                           self.wave_director.get_state_1010_frames(self.sim_time, actor_slots=self.actor_slots),
                           self.wave_director.get_death_frames(self.sim_time)):
                for opcode, payload in frames:
                    send(opcode, payload)
        self._resource_catchup[conn] = self._reconnect_hero_state(player, send)
        for opcode, payload in self.status_manager.snapshot_frames(self.sim_time):
            send(opcode, payload)
        for opcode, payload in self.shop_presentation.snapshot_frames(self.sim_time):
            send(opcode, payload)
        for opcode, payload in self.vision.snapshot_frames():
            send(opcode, payload)
        if self.structures.match_finished:
            send(wire.OP.CRYSTAL_DESTROYED, match_end.build_crystal_destroyed())
            if self.result_sent:
                send(wire.OP.MATCH_RESULT, match_end.build_match_result(self.structures.winner_team))
        send(wire.OP.SLOT_FLAGS_PING, roster.build_slot_flags(self.players))
        self._completed_bootstrap_conns.add(conn)

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
        except OSError as exc:
            if not self._stop_event.is_set():
                import traceback
                self.log(f"[match] SnapshotStream I/O failure: {exc!r}\n{traceback.format_exc()}")
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
        self._trace_path = None
        self._trace_lock = threading.Lock()
        if os.environ.get("HALCYON_TRACE_WIRE"):
            # Wire captures are QA evidence, not portable runtime inputs.
            trace_dir = os.path.join(os.environ["TEMP"], "halcyon_stack")
            os.makedirs(trace_dir, exist_ok=True)
            self._trace_path = os.path.join(trace_dir, f"wire-{time.time_ns()}.jsonl")
            self.log(f"[match] local wire trace: {self._trace_path}")

    def _trace_frame(self, direction, conn, opcode, payload):
        if self._trace_path is None or opcode in (wire.OP.PLAYER_UUID, wire.OP.KEEPALIVE):
            return
        record = {"time": time.time(), "direction": direction, "connection": id(conn),
                  "opcode": opcode, "payload": payload.hex()}
        with self._trace_lock, open(self._trace_path, "a", encoding="ascii") as output:
            output.write(json.dumps(record, separators=(",", ":")) + "\n")

    def is_stopped(self) -> bool:
        return self._stop.is_set()

    def is_finished(self) -> bool:
        if self._stop.is_set():
            return True
        if self.session is not None:
            if not self.session.is_alive():
                return True
            if getattr(self.session, "result_sent", False):
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
        self._trace_frame("c2s", conn, opcode, payload)
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
                      wire.OP.TARGET_ENTITY, wire.OP.LEVELUP_A, wire.OP.LEVELUP_B,
                      wire.OP.TARGETLESS_CAST, wire.OP.GROUND_CAST, wire.OP.SKILLSHOT_CAST,
                      wire.OP.SHOP_BUY, wire.OP.ITEM_USE):
            stream = self._streams_by_conn.get(conn)
            if stream is not None:
                stream.submit(opcode, payload, conn=conn)
        # Join handshakes (1112/1118/1123/1131/1119/1134/1137/1133/1157/1081…)
        # and gameplay verbs without a slice yet (1041/1078) are logged above;
        # semantic replies are T3 work.
        detail = f" payload={payload.hex()}" if 1000 < opcode < 1110 and len(payload) <= 22 else ""
        self.log(f"[match] c2s op={opcode} ({len(payload)} B){detail}")

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
            self._trace_frame("s2c", conn, opcode, payload)
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
