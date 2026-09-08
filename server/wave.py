"""Deterministic lane waves using measured spawn grammar and sandbox rules.

The original corpus composition remains in roster.MINION_PAIR_CLASSES. The
accepted sandbox brief instead requests three melee units, two 6.5-range units
and a periodic siege unit. Its cadence and stat growth are explicit policy,
not claims that those numbers have been measured on the target client.
"""
from __future__ import annotations

from . import jungle
from . import roster
from .hero_movement import HeroMovement
from .actor_slots import ActorSlots
from .attack_wire import (build_attack_start, MELEE_MINION_BASIC_VARIANTS,
                          RANGED_MINION_BASIC_VARIANTS)
from .lifecycle_wire import build_hero_death
from .navigation import SCALE, fixed
from dataclasses import dataclass, field
import heapq
import math


SANDBOX_MINION_PROFILES = (
    ('lead_melee', 450.0, 19.4, 2.0, 0.6, 0.0),
    ('melee', 450.0, 27.8, 2.0, 0.6, 1.0),
    ('melee', 450.0, 27.8, 2.0, 0.6, 2.0),
    ('ranged', 350.0, 50.0, 6.5, 0.6, 5.0),
    ('ranged', 350.0, 50.0, 6.5, 0.6, 8.0),
)
SIEGE_PROFILE = ('siege', 1000.0, 80.0, 6.5, 1.2, 10.0)
SANDBOX_SPAWNERS = (366, 366, 366, 365, 365)


@dataclass(frozen=True)
class WaveRules:
    siege_every: int = 3
    siege_offset: float = 4.8
    siege_spawner: int = 367  # Decoded registry: HF_Minion_Siege (368 is captain).
    hp_growth_per_minute: float = 0.10
    damage_growth_per_minute: float = 0.05
    ally_spacing: float = 0.75
    aggro_range: float = 8.0
    corpse_duration: float = 3.8  # 83 native lane deaths: receive gaps 3.759..3.861 s.
    # Empirical approximation of first native attacks, not recovered release
    # or projectile-speed constants. The authoritative clock is 20 Hz.
    melee_contact_delay: float = 0.50
    ranged_contact_delay: float = 1.35
    # Native ranged/siege 1045 -> 1037 samples cluster around 0.5 s.
    # Keep the empirical 1.35 s contact policy while exposing real release.
    ranged_release_delay: float = 0.50

    def __post_init__(self):
        for delay in (self.melee_contact_delay, self.ranged_contact_delay, self.ranged_release_delay):
            if not math.isfinite(delay) or delay <= 0 or not math.isclose(delay * 20, round(delay * 20), abs_tol=1e-9):
                raise ValueError('minion contact delays must be positive multiples of 50 ms')
        if self.ranged_release_delay > self.ranged_contact_delay:
            raise ValueError('ranged release cannot follow its contact deadline')


@dataclass(order=True)
class PendingMinionContact:
    due_tick: int
    serial: int
    source: object = field(compare=False)
    target: object = field(compare=False)
    source_eid: int = field(compare=False)
    target_eid: int = field(compare=False)
    damage: float = field(compare=False)
    release_tick: int | None = field(compare=False, default=None)
    variant: int = field(compare=False, default=0)
    released: bool = field(compare=False, default=False)
    interrupt_serial: int = field(compare=False, default=0)

OP_SPAWN_1010 = 1010
OP_INTENT_1016 = 1016
OP_STATE_1067 = 1067
OP_POSITION_1070 = 1070
OP_COMBAT_1054 = 1054
OP_DESTROY_1073 = 1073
OP_DESPAWN_1035 = 1035


class Minion:
    """One lane minion: spawn schedule, walk state, publish cadence, class stats, hp."""

    __slots__ = ("eid", "side", "spawn_at", "_x", "_y", "path", "seg",
                 "next_position_at", "_last_step", "hp", "max_hp", "target",
                 "target_hero", "next_attack_at", "alive", "pair_index",
                 "minion_class", "attack_damage", "attack_range",
                 "attack_cooldown", "stop_offset", "_move_remainder",
                 "_pursuit", "_pursuit_destination", "has_engaged", "navigation",
                 "attack_ordinal", "_move_destination")

    def __init__(self, eid: int, side: int, spawn_at: float, pair_index: int = 0,
                 *, match_elapsed=0.0, rules=None, corpus_profile=False):
        self.eid = eid
        self.side = side                        # 1067 side byte (01|02)
        self.spawn_at = spawn_at
        self.pair_index = pair_index

        rules = rules or WaveRules()
        profiles = roster.MINION_PAIR_CLASSES if corpus_profile else SANDBOX_MINION_PROFILES
        cfg = SIEGE_PROFILE if pair_index == 5 and not corpus_profile else profiles[pair_index % len(profiles)]
        self.minion_class = cfg[0]
        minute = max(0, int(match_elapsed // 60))
        self.max_hp = cfg[1] * (1 + minute * rules.hp_growth_per_minute)
        self.hp = self.max_hp
        self.attack_damage = cfg[2] * (1 + minute * rules.damage_growth_per_minute)
        self.attack_range = cfg[3]
        self.attack_cooldown = cfg[4]
        self.stop_offset = cfg[5]

        right = side == roster.ENTITY_STATE_SIDE_RIGHT
        self.x, self.y = (roster.LANE_SPAWN_RIGHT if right
                          else roster.LANE_SPAWN_LEFT)
        raw_path = roster.LANE_PATH_RIGHT if right else roster.LANE_PATH_LEFT
        self.path = roster.trim_polyline(raw_path, self.stop_offset)
        self.seg = 0                            # walking toward path[seg]
        self.next_position_at = spawn_at + roster.MINION_POSITION_PERIOD
        self._last_step = spawn_at
        self.target: "Minion | None" = None
        self.target_hero = None                 # hero attacker (aggro phản đòn)
        self.next_attack_at: float | None = None
        self.attack_ordinal = 0
        self.alive = True
        self._move_remainder = 0
        self._pursuit = self._pursuit_destination = None
        self._move_destination = None
        self.navigation = None
        self.has_engaged = False

    @property
    def x(self):
        return self._x / SCALE

    @x.setter
    def x(self, value):
        self._x = fixed(value)

    @property
    def y(self):
        return self._y / SCALE

    @y.setter
    def y(self, value):
        self._y = fixed(value)

    @property
    def position_fixed(self):
        return self._x, self._y

    @property
    def team(self):
        return self.side

    @property
    def is_alive(self):
        return self.alive

    @is_alive.setter
    def is_alive(self, value):
        self.alive = value

    def step_to(self, now: float):
        """Advance the walk to `now`; the walk starts at spawn_at, so the
        first step covers exactly the elapsed slice (never the pre-spawn
        gap). Position is pure (path, dt, speed)."""
        if now <= self._last_step:
            return
        if not self.arrived:
            self.step(now - self._last_step)
        self._last_step = now

    def step(self, dt: float, speed_multiplier=1.0):
        budget, self._move_remainder = divmod(fixed(roster.MINION_SPEED * speed_multiplier) * fixed(dt) + self._move_remainder, SCALE)
        while budget > 0 and self.seg < len(self.path):
            tx, ty = map(fixed, self.path[self.seg])
            dx, dy = tx - self._x, ty - self._y
            squared = dx * dx + dy * dy
            dist = math.isqrt(squared)
            if dist * dist < squared:
                dist += 1
            if dist <= budget:
                self._x, self._y = tx, ty
                budget -= dist
                self.seg += 1
            else:
                nx = self._x + (abs(dx) * budget // dist) * (1 if dx >= 0 else -1)
                ny = self._y + (abs(dy) * budget // dist) * (1 if dy >= 0 else -1)
                if self.navigation is not None:
                    nx, ny = map(fixed, self.navigation.clamp_segment((self.x, self.y), (nx / SCALE, ny / SCALE)))
                self._x, self._y = nx, ny
                budget = 0

    def pursue(self, target, dt, speed_multiplier=1.0):
        destination = (target.x, target.y)
        if self._pursuit is None:
            self._pursuit = HeroMovement(eid=self.eid, x=self.x, y=self.y, navigation=self.navigation)
        mover = self._pursuit
        mover.navigation, mover.base_speed = self.navigation, roster.MINION_SPEED * speed_multiplier
        if (mover.x, mover.y) != (self.x, self.y):
            mover.teleport(self.x, self.y)
        changed = self._pursuit_destination is None or math.dist(destination, self._pursuit_destination) >= 0.25
        if changed or not mover.is_moving:
            mover.set_target(*destination)
            self._pursuit_destination = destination
        distance = math.dist((self.x, self.y), destination)
        if len(mover.waypoints) == 1 and dt:
            mover.base_speed = min(mover.base_speed, max(0.0, distance - self.attack_range) / dt)
        mover.step(dt)
        self.x, self.y = mover.x, mover.y

    @property
    def arrived(self) -> bool:
        return self.seg >= len(self.path)


class Director:
    """Schedules waves and produces the s2c payloads, deterministically.

    `now` is the caller's monotonic clock; `t0` anchors the world (the
    corpus 1137-ack instant — the tape's t=0). `actor_slots` is shared with
    the rest of the stream. The legacy `seq_1010` list reports the last
    assignment; it must never be used as a wrapping allocation counter.
    """

    def __init__(self, t0: float, first_eid: int = roster.LANE_MINION_FIRST_EID,
                 seq_1010: list[int] | None = None,
                 combat: bool = True, *, rules=None, navigation=None, corpus_profile=False,
                 actor_slots=None):
        self.t0 = t0
        self.first_eid = first_eid
        self.combat = combat          # False = slice-2 walk/heartbeat only
        self.seq_1010 = seq_1010 if seq_1010 is not None else [0]
        self.actor_slots = actor_slots or ActorSlots.from_legacy_tail(self.seq_1010[0])
        self.next_minion = first_eid
        self.wave_index = 0
        self.pending_pairs: list[tuple[float, int]] = []   # (due, pair)
        self.minions: list[Minion] = []
        self.pending_states: list[tuple[float, Minion]] = []
        self.pending_removals = {}
        self.spawned = 0
        self._last_now = t0
        self.rules = rules or WaveRules()
        self.navigation = navigation
        self.corpus_profile = corpus_profile
        self._navigation_routes = {}
        self._state_catalog = None
        self.pending_contacts: list[PendingMinionContact] = []
        self._contact_serial = 0

    # -- pair emission (corpus raw-burst order) ------------------------------

    def _spawn_pair(self, due: float, pair: int):
        frames: list[tuple[int, bytes]] = []
        pair_minions = []
        for side in (roster.ENTITY_STATE_SIDE_RIGHT,
                     roster.ENTITY_STATE_SIDE_LEFT):
            m = Minion(self.next_minion, side, due, pair_index=pair,
                       match_elapsed=max(0.0, due - self.t0), rules=self.rules,
                       corpus_profile=self.corpus_profile)
            self._attach_navigation(m)
            self.next_minion += 1
            self.minions.append(m)
            pair_minions.append(m)
        right, left = pair_minions
        for m in (right, left):
            seq = self.actor_slots.allocate(m.eid)
            self.seq_1010[0] = seq
            spawner = (roster.LANE_SPAWNER_EIDS[pair % len(roster.LANE_SPAWNER_EIDS)] if self.corpus_profile
                       else self.rules.siege_spawner if pair == 5 else SANDBOX_SPAWNERS[pair])
            frames.append((OP_SPAWN_1010, roster.build_minion_spawn_1010(
                spawner, m.eid, m.x, m.y, seq, m.side)))
            frames.extend(self._publish_move_intent(m, m.path[0]))
            frames.append((OP_POSITION_1070,
                           roster.build_position(m.eid, m.x, m.y)))
        for m in (left, right):
            ax, ay = roster.LANE_POINT_A
            if m.side == roster.ENTITY_STATE_SIDE_LEFT:
                ax = -ax
            frames.append((OP_POSITION_1070,
                           roster.build_position(m.eid, ax, ay)))
        for m in (left, right):
            frames.append((OP_STATE_1067, roster.build_entity_state(
                m.eid, m.side, roster.ENTITY_STATE_SPAWNED)))
            self.pending_states.append((due + roster.WAVE_STATE_DELAY, m))
        return frames

    def _attach_navigation(self, minion):
        if self.navigation is None or minion.navigation is self.navigation:
            return
        minion.navigation = self.navigation
        key = minion.side, minion.stop_offset
        if key not in self._navigation_routes:
            origin, route = (minion.x, minion.y), []
            for destination in minion.path:
                segment = self.navigation.find_path(origin, destination)
                if segment:
                    route.extend(segment)
                    origin = segment[-1]
            self._navigation_routes[key] = tuple(route)
        minion.path = list(self._navigation_routes[key])
        minion.seg = 0

    def _archetype(self, minion):
        pair = minion.pair_index
        if self.corpus_profile:
            return roster.LANE_SPAWNER_EIDS[pair % len(roster.LANE_SPAWNER_EIDS)]
        return self.rules.siege_spawner if pair == 5 else SANDBOX_SPAWNERS[pair]

    def _publish_move_intent(self, minion, destination):
        """Update the client's actual travel goal, including a stop at self.

        1070 corrects position without replacing the previous 1016 goal. A
        minion otherwise walks back toward its first spawn waypoint between
        later corrections. Keep the current goal on the coordinate lattice so
        stationary actors do not restart their order every simulation tick.
        """
        destination = tuple(map(fixed, destination))
        if destination == minion._move_destination:
            return []
        minion._move_destination = destination
        slot = self.actor_slots.allocate(minion.eid)
        return [(OP_INTENT_1016, roster.build_move_intent(
            slot, *(coordinate / SCALE for coordinate in destination)))]

    def _present_at(self, now):
        now = self._last_now if now is None else now
        return sorted((m for m in self.minions if m.spawn_at <= now and
                       (m.alive or m.eid in self.pending_removals)), key=lambda m: m.eid)

    def get_spawn_frames(self, now=None, *, actor_slots=None):
        """Recreate living minions and retained corpses, retaining EIDs and slots.

        This is a read of live state, not a new wave: no scheduling, movement,
        HP, cooldown, or minion identity changes occur. Movement refers only
        to the newly created actor's assigned compact slot.
        """
        slots = actor_slots if actor_slots is not None else self.actor_slots
        frames = []
        for minion in self._present_at(now):
            slot = slots.allocate(minion.eid)
            frames.append((OP_SPAWN_1010, roster.build_minion_spawn_1010(
                self._archetype(minion), minion.eid, minion.x, minion.y, slot, minion.side)))
            if not minion.alive:
                continue
            destination = (tuple(coordinate / SCALE for coordinate in minion._move_destination)
                           if minion._move_destination is not None else None)
            focus = minion.target_hero or minion.target
            stopped_at_target = focus is not None and getattr(focus, 'is_alive', getattr(focus, 'alive', False)) and self._in_attack_range(minion, focus)
            if not stopped_at_target and minion._pursuit_destination is not None:
                stopped_at_target = math.dist((minion.x, minion.y), minion._pursuit_destination) <= minion.attack_range + 0.000002
            if destination is None and not stopped_at_target:
                if minion._pursuit is not None and minion._pursuit.waypoints:
                    destination = minion._pursuit.waypoints[0]
                elif minion.seg < len(minion.path):
                    destination = minion.path[minion.seg]
            if destination is not None:
                frames.append((OP_INTENT_1016, roster.build_move_intent(slot, *destination)))
            frames.append((OP_POSITION_1070, roster.build_position(minion.eid, minion.x, minion.y)))
            frames.append((OP_STATE_1067, roster.build_entity_state(minion.eid, minion.side, roster.ENTITY_STATE_SPAWNED)))
            frames.append((OP_STATE_1067, roster.build_entity_state(minion.eid, minion.side, roster.ENTITY_STATE_MOVING)))
        return frames

    def get_state_1010_frames(self, now=None, *, actor_slots=None, catalog=None):
        """Live HP/maxHP in the measured122-byte VGR snapshot form.

        Create actors first. Sending this replay snapshot form to a live
        reconnect is an explicit client integration experiment.
        """
        from .entity_spawn import load_native_actor_catalog
        slots = actor_slots if actor_slots is not None else self.actor_slots
        self._state_catalog = catalog or self._state_catalog or load_native_actor_catalog()
        return [(OP_SPAWN_1010, self._state_catalog.build(self._archetype(m), m.eid, m.x, m.y,
                    slots.allocate(m.eid), team=m.side, snapshot=True, hp=(max(0.0, m.hp), m.max_hp)))
                for m in self._present_at(now)]

    def get_death_frames(self, now=None):
        """After reconnect creation and HP snapshots, restore retained corpses."""
        return [(1072, build_hero_death(m.eid, self.pending_removals[m.eid][2]))
                for m in self._present_at(now) if not m.alive and m.eid in self.pending_removals]

    def on_minion_death(self, victim, killer_eid, now):
        """Emit native death now; keep the actor and its slot until corpse removal."""
        if not victim.alive:
            return []
        victim.hp, victim.alive = 0.0, False
        victim.target = victim.target_hero = None
        victim.next_attack_at = None
        self.pending_removals[victim.eid] = (now + self.rules.corpse_duration, victim, killer_eid)
        return [(1072, build_hero_death(victim.eid, killer_eid))]

    def _flush_removals(self, now):
        frames = []
        for eid, (due, _, _) in sorted(self.pending_removals.items(), key=lambda item: (item[1][0], item[0])):
            if due > now:
                continue
            frames.extend(((OP_DESTROY_1073, roster.build_destroy(eid)),
                           (OP_DESPAWN_1035, roster.build_despawn(eid))))
            self.actor_slots.release(eid)
            del self.pending_removals[eid]
        return frames

    # -- pump ----------------------------------------------------------------

    def pump(self, now: float, hero: "Any | None" = None, *, structures=None,
             navigation=None, status_manager=None, damage_callback=None, all_heroes=None,
             on_projectile_release=None):
        """Return every frame due at `now`, in corpus emission order."""
        out: list[tuple[int, bytes]] = self._flush_removals(now)
        self._last_now = now
        if navigation is not None and navigation is not self.navigation:
            self.navigation = navigation
            self._navigation_routes.clear()

        first_at = self.t0 + roster.WAVE_FIRST_SPAWN_AT
        while first_at + roster.WAVE_INTERVAL * self.wave_index <= now:
            wave_start = first_at + roster.WAVE_INTERVAL * self.wave_index
            for pair, off in enumerate(roster.WAVE_PAIR_OFFSETS):
                self.pending_pairs.append((wave_start + off, pair))
            if not self.corpus_profile and self.rules.siege_every > 0 and (self.wave_index + 1) % self.rules.siege_every == 0:
                self.pending_pairs.append((wave_start + self.rules.siege_offset, 5))
            self.wave_index += 1

        while self.pending_pairs and self.pending_pairs[0][0] <= now:
            due, pair = self.pending_pairs.pop(0)
            out += self._spawn_pair(due, pair)
            self.spawned += 1

        due_states = [i for i in self.pending_states if i[0] <= now]
        if due_states:
            self.pending_states = [i for i in self.pending_states if i[0] > now]
            for _, m in due_states:
                if m.alive:
                    out.append((OP_STATE_1067, roster.build_entity_state(
                        m.eid, m.side, roster.ENTITY_STATE_MOVING)))

        fighters = [m for m in self.minions if m.alive and m.spawn_at <= now]
        for m in self.minions:
            if not m.alive or now < m.spawn_at:
                continue
            self._attach_navigation(m)
            focus = self._select_target(m, fighters, structures) if self.combat else None
            before, previous_seg = (m.x, m.y), m.seg
            dt = max(0.0, now - m._last_step)
            m._last_step = now  # Stopped/CC time must never become later travel.
            can_move = status_manager is None or status_manager.can_move(m.eid, now)
            multiplier = status_manager.get_speed_multiplier(m.eid, now) if status_manager is not None else 1.0
            if status_manager is not None:
                dx, dy = status_manager.get_knockback_displacement(m.eid, dt, now)
                if dx or dy:
                    endpoint = (m.x + dx, m.y + dy)
                    if self.navigation is not None:
                        endpoint = self.navigation.clamp_segment(before, endpoint)
                    m.x, m.y = endpoint
            if can_move and dt:
                if focus is not None:
                    if not self._in_attack_range(m, focus):
                        m.pursue(focus, dt, multiplier)
                elif not m.arrived:
                    m.step(dt, multiplier)
            # Preserve spawn staggering at a combat front: do not walk into
            # the occupied disc of the next ally. The front advances on death.
            if (m.x, m.y) != before and self.rules.ally_spacing > 0:
                for ally in fighters:
                    if ally is m or not ally.alive or ally.side != m.side:
                        continue
                    old_distance = self._dist_pos(ally, *before)
                    if self._dist(m, ally) < self.rules.ally_spacing and old_distance >= self.rules.ally_spacing:
                        m.x, m.y = before
                        m.seg = previous_seg
                        break
            order_frames = []
            if dt or not can_move:
                # Publish the next reachable waypoint only while the actor
                # actually advances. Range stops, CC and ally obstruction all
                # need a current-position goal to stop client interpolation.
                destination = (m.x, m.y)
                if can_move and (m.x, m.y) != before:
                    if focus is not None:
                        if not self._in_attack_range(m, focus) and m._pursuit.waypoints:
                            destination = m._pursuit.waypoints[0]
                    elif not m.arrived:
                        destination = m.path[m.seg]
                order_frames = self._publish_move_intent(m, destination)
                out.extend(order_frames)
            if order_frames or m.seg != previous_seg or now >= m.next_position_at:
                out.append((OP_POSITION_1070,
                            roster.build_position(m.eid, m.x, m.y)))
                m.next_position_at = now + roster.MINION_POSITION_PERIOD

        out += self._combat(now, hero, structures=structures,
                            status_manager=status_manager, damage_callback=damage_callback,
                            all_heroes=all_heroes, on_projectile_release=on_projectile_release)
        return out

    def _select_target(self, minion, fighters, structures=None):
        hero = minion.target_hero
        if hero is not None:
            if not hero.is_alive or hero.team == minion.side or jungle.JungleManager.is_in_brush(hero.x, hero.y) or self._dist(minion, hero) > max(6.0, minion.attack_range):
                minion.target_hero = None
            else:
                return hero
        if minion.target is not None and (not minion.target.alive or self._dist(minion, minion.target) > self.rules.aggro_range + 2):
            minion.target = None
        if minion.target is None:
            foes = [other for other in fighters if other.alive and other.side != minion.side
                    and self._dist(minion, other) <= max(self.rules.aggro_range, minion.attack_range)]
            if not foes and structures is None and (minion.arrived or minion.has_engaged):
                # A standalone lane has no next structure to march toward.
                # Survivors must close the next enemy formation instead of
                # parking outside aggro range and blocking every later wave.
                foes = [other for other in fighters if other.alive and other.side != minion.side]
            if foes:
                minion.target = min(foes, key=lambda other: (self._dist(minion, other), other.eid))
        if minion.target is not None:
            minion.has_engaged = True
            return minion.target
        if structures is not None and (minion.arrived or minion.has_engaged):
            targets = [s for s in structures.structures.values() if s.is_alive and s.team != minion.side and structures.is_vulnerable(s.eid)]
            if targets:
                return min(targets, key=lambda s: (s.tier, self._dist(minion, s), s.eid))
        return None

    # -- combat (slice 3 & 5, corpus-measured constants) --------------------

    def _contact_clock(self, now, *, round_up=False):
        # Integer microseconds avoid float multiplication moving an exact
        # simulation tick across its boundary. Off-tick starts round forward.
        elapsed_us = round((now - self.t0) * 1_000_000)
        return (elapsed_us + (49_999 if round_up else 0)) // 50_000

    def _resolve_contacts(self, now, hero=None, *, structures=None, damage_callback=None, all_heroes=None,
                          on_projectile_release=None, status_manager=None):
        out = []
        if not self.pending_contacts:
            return out
        tick = self._contact_clock(now)
        actors = {m.eid: m for m in self.minions if m.spawn_at <= now}
        def valid(pending):
            minion, target = pending.source, pending.target
            if minion.eid != pending.source_eid:
                return False
            owner = actors.get(pending.source_eid)
            # Windup needs its living original source. Once 1037 is released,
            # source death/removal and movement cannot recall the projectile.
            # A different actor reusing the source EID never inherits it.
            if (not pending.released and (not minion.alive or owner is not minion)
                    or pending.released and owner is not None and owner is not minion):
                return False
            if not pending.released and status_manager is not None:
                if (not status_manager.can_attack(minion.eid, now)
                        or status_manager.get_attack_interrupt_serial(minion.eid) != pending.interrupt_serial):
                    return False
            if target.eid != pending.target_eid or not getattr(target, 'is_alive', getattr(target, 'alive', False)):
                return False
            if isinstance(target, Minion):
                return actors.get(pending.target_eid) is target
            if isinstance(target, HeroMovement):
                return all_heroes is None or all_heroes.get(pending.target_eid) is target
            return structures is not None and structures.structures.get(pending.target_eid) is target

        # Observe cancellation before release/contact, so revival cannot
        # resurrect an attack whose windup or original target was lost.
        retained = [pending for pending in self.pending_contacts if valid(pending)]
        if len(retained) != len(self.pending_contacts):
            self.pending_contacts = retained
            heapq.heapify(self.pending_contacts)
        events = [(pending.release_tick, pending.serial, 0, pending)
                  for pending in self.pending_contacts
                  if not pending.released and pending.release_tick is not None
                  and pending.release_tick <= tick]
        while self.pending_contacts and self.pending_contacts[0].due_tick <= tick:
            pending = heapq.heappop(self.pending_contacts)
            events.append((pending.due_tick, pending.serial, 1, pending))
        # A melee contact can kill a ranged attacker on its release tick.
        # Keep the shared deadline/attack-start order across both event kinds.
        cancelled = set()
        for _, _, is_contact, pending in sorted(events):
            if pending.serial in cancelled or not valid(pending):
                cancelled.add(pending.serial)
                continue
            minion, target = pending.source, pending.target
            if not is_contact:
                pending.released = True
                if on_projectile_release is not None:
                    out.extend(on_projectile_release(minion, target, pending.variant))
                continue
            if damage_callback is not None:
                out.extend(damage_callback(minion, target, pending.damage, 'weapon', now))
            elif structures is not None and structures.structures.get(target.eid) is target:
                out.extend(structures.apply_damage(target.eid, pending.damage, minion.eid))
            else:
                actual = min(target.hp, pending.damage)
                out.append((OP_COMBAT_1054, roster.build_combat_delta(minion.eid, target.eid, -actual)))
                if isinstance(target, HeroMovement):
                    out.extend(target.apply_damage(actual, minion.eid, now))
                else:
                    target.hp -= actual
                    if target.hp <= 0 and target.alive:
                        out.extend(self.on_minion_death(target, minion.eid, now))
        if cancelled:
            self.pending_contacts = [pending for pending in self.pending_contacts
                                     if pending.serial not in cancelled]
            heapq.heapify(self.pending_contacts)
        return out

    def _combat(self, now, hero=None, *, structures=None, status_manager=None, damage_callback=None, all_heroes=None,
                on_projectile_release=None):
        """Resolve each living attacker once; dead actors cannot retaliate later.

        Range and attack-speed effects apply equally to minions and heroes.
        The session callback owns mitigation, rewards and event ordering.
        """
        if not self.combat:
            return []
        out = self._resolve_contacts(now, hero, structures=structures,
                                     damage_callback=damage_callback, all_heroes=all_heroes,
                                     on_projectile_release=on_projectile_release,
                                     status_manager=status_manager)
        fighters = [m for m in self.minions if m.alive and m.spawn_at <= now]
        for minion in fighters:
            if not minion.alive:
                continue
            target = self._select_target(minion, fighters, structures)
            if target is None or not self._in_attack_range(minion, target):
                continue
            if status_manager is not None and not status_manager.can_attack(minion.eid, now):
                continue
            if minion.next_attack_at is not None and now < minion.next_attack_at:
                continue
            attack_speed = status_manager.get_attack_speed_multiplier(minion.eid, now) if status_manager is not None else 1.0
            minion.next_attack_at = now + minion.attack_cooldown / max(0.05, attack_speed)
            archetype = self._archetype(minion)
            variants = {366: MELEE_MINION_BASIC_VARIANTS,
                        365: RANGED_MINION_BASIC_VARIANTS,
                        367: RANGED_MINION_BASIC_VARIANTS,
                        368: RANGED_MINION_BASIC_VARIANTS}.get(archetype)
            if variants is None:
                raise ValueError(f'no grounded lane ordinary action for archetype {archetype}')
            # Native lane actions use direct NPC ordinals. Their following
            # frame is a buff, not the heroes' immediate 1070 position pair.
            variant = variants[minion.attack_ordinal % len(variants)]
            out.append((1045, build_attack_start(minion.eid, target.eid, variant)))
            minion.attack_ordinal += 1
            delay = self.rules.melee_contact_delay if archetype == 366 else self.rules.ranged_contact_delay
            started_tick = self._contact_clock(now, round_up=True)
            due_tick = started_tick + round(delay * 20)
            release_tick = (started_tick + round(self.rules.ranged_release_delay * 20)
                            if archetype != 366 else None)
            self._contact_serial += 1
            heapq.heappush(self.pending_contacts, PendingMinionContact(
                due_tick, self._contact_serial, minion, target, minion.eid, target.eid,
                minion.attack_damage, release_tick, variant,
                interrupt_serial=(status_manager.get_attack_interrupt_serial(minion.eid)
                                  if status_manager is not None else 0)))
        return out

    def on_minion_damaged_by_hero(self, victim_eid: int, hero: "Any"):
        """Aggro phản đòn: minion attacked by hero (and nearby allies within 4u) switch target to hero."""
        victim = next((m for m in self.minions if m.eid == victim_eid and m.alive), None)
        if victim is None:
            return
        victim.target_hero = hero
        for m in self.minions:
            if m.alive and m.side == victim.side and self._dist(m, victim) <= 4.0:
                m.target_hero = hero

    def apply_hero_damage_to_minion(self, victim_eid: int, damage: float, hero: "Any", now=None) -> list[tuple[int, bytes]]:
        """Apply hero damage/aggro and native death; removal follows the corpse period."""
        out = []
        victim = next((m for m in self.minions if m.eid == victim_eid and m.alive), None)
        if victim is None:
            return out
        victim.hp -= damage
        self.on_minion_damaged_by_hero(victim_eid, hero)
        if victim.hp <= 0 and victim.alive:
            out.extend(self.on_minion_death(victim, hero.eid, self._last_now if now is None else now))
        return out

    @staticmethod
    def _in_attack_range(minion, target):
        # Integer directional integration rounds each component toward origin;
        # permit its two-microunit endpoint error at the nominal range boundary.
        radius = fixed(minion.attack_range) + 2
        dx, dy = fixed(minion.x) - fixed(target.x), fixed(minion.y) - fixed(target.y)
        return dx * dx + dy * dy <= radius * radius

    @staticmethod
    def _dist_pos(m: Minion, x: float, y: float) -> float:
        return ((m.x - x) ** 2 + (m.y - y) ** 2) ** 0.5

    @staticmethod
    def _dist(a: Minion, b: Minion) -> float:
        return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5
