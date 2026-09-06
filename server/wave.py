"""Lane-minion wave director — the first deterministic T3 sim slice.

Every value here is corpus-measured (vg5_final.pcap match 5, 2026-09-06;
see roster.py "Lane-minion wave spawn" block for the byte layout and the
falsified 1087/1010-HP assumption). The director is pure: it emits
(opcode, payload) frames as a function of (wave schedule, elapsed time) —
no randomness, no wall-clock state, no c2s input. The caller owns sending,
framing and the shared 1010 seq counter (passed in as a one-int list).

Per minion pair the emission order is the corpus raw-burst order:
  1010(right) 1016(right) 1070(right,B) · 1010(left) 1016(left) 1070(left,B)
  · 1070(left,A) 1070(right,A) · 1067(left,0) 1067(right,0)
  · +WAVE_STATE_DELAY: 1067(left,0x0f) 1067(right,0x0f)
After spawning, each minion walks its side's lane polyline at MINION_SPEED,
publishing 1070 on waypoint arrival and every MINION_POSITION_PERIOD s,
holding at the line's end (corpus idle heartbeats keep flowing).
"""
from __future__ import annotations

from . import roster

OP_SPAWN_1010 = 1010
OP_INTENT_1016 = 1016
OP_STATE_1067 = 1067
OP_POSITION_1070 = 1070


class Minion:
    """One lane minion: spawn schedule, walk state, publish cadence."""

    __slots__ = ("eid", "side", "spawn_at", "x", "y", "path", "seg",
                 "next_position_at", "_last_step")

    def __init__(self, eid: int, side: int, spawn_at: float):
        self.eid = eid
        self.side = side                        # 1067 side byte (01|02)
        self.spawn_at = spawn_at
        right = side == roster.ENTITY_STATE_SIDE_RIGHT
        self.x, self.y = (roster.LANE_SPAWN_RIGHT if right
                          else roster.LANE_SPAWN_LEFT)
        self.path = roster.LANE_PATH_RIGHT if right else roster.LANE_PATH_LEFT
        self.seg = 0                            # walking toward path[seg]
        self.next_position_at = spawn_at + roster.MINION_POSITION_PERIOD
        self._last_step = spawn_at

    def step_to(self, now: float):
        """Advance the walk to `now`; the walk starts at spawn_at, so the
        first step covers exactly the elapsed slice (never the pre-spawn
        gap). Position is pure (path, dt, speed)."""
        if now <= self._last_step or self.arrived:
            return
        self.step(now - self._last_step)
        self._last_step = now

    def step(self, dt: float):
        budget = roster.MINION_SPEED * dt
        while budget > 0.0 and self.seg < len(self.path):
            tx, ty = self.path[self.seg]
            dx, dy = tx - self.x, ty - self.y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= budget:
                self.x, self.y = tx, ty
                budget -= dist
                self.seg += 1
            else:
                self.x += dx / dist * budget
                self.y += dy / dist * budget
                budget = 0.0

    @property
    def arrived(self) -> bool:
        return self.seg >= len(self.path)


class Director:
    """Schedules waves and produces the s2c payloads, deterministically.

    `now` is the caller's monotonic clock; `t0` anchors the world (the
    corpus 1137-ack instant — the tape's t=0). `seq_1010` is a one-int list
    shared with the rest of the entity stream so hero-1010s (if ever
    re-enabled) and minion-1010s draw one counter.
    """

    def __init__(self, t0: float, first_eid: int = roster.LANE_MINION_FIRST_EID,
                 seq_1010: list[int] | None = None):
        self.t0 = t0
        self.first_eid = first_eid
        self.seq_1010 = seq_1010 if seq_1010 is not None else [0]
        self.next_minion = first_eid
        self.wave_index = 0
        self.pending_pairs: list[tuple[float, int]] = []   # (due, pair)
        self.minions: list[Minion] = []
        self.pending_states: list[tuple[float, Minion]] = []
        self.spawned = 0
        self._last_now = t0

    # -- pair emission (corpus raw-burst order) ------------------------------

    def _spawn_pair(self, due: float, pair: int):
        frames: list[tuple[int, bytes]] = []
        pair_minions = []
        for side in (roster.ENTITY_STATE_SIDE_RIGHT,
                     roster.ENTITY_STATE_SIDE_LEFT):
            m = Minion(self.next_minion, side, due)
            self.next_minion += 1
            self.minions.append(m)
            pair_minions.append(m)
        right, left = pair_minions
        for m in (right, left):
            self.seq_1010[0] = (self.seq_1010[0] + 1) & 0xFF
            seq = self.seq_1010[0]
            spawner = roster.LANE_SPAWNER_EIDS[pair % len(roster.LANE_SPAWNER_EIDS)]
            frames.append((OP_SPAWN_1010, roster.build_minion_spawn_1010(
                spawner, m.eid, m.x, m.y, seq, m.side)))
            frames.append((OP_INTENT_1016, roster.build_move_intent(
                seq, *m.path[0])))
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

    # -- pump ----------------------------------------------------------------

    def pump(self, now: float):
        """Return every frame due at `now`, in corpus emission order."""
        out: list[tuple[int, bytes]] = []
        self._last_now = now

        first_at = self.t0 + roster.WAVE_FIRST_SPAWN_AT
        while first_at + roster.WAVE_INTERVAL * self.wave_index <= now:
            wave_start = first_at + roster.WAVE_INTERVAL * self.wave_index
            for pair, off in enumerate(roster.WAVE_PAIR_OFFSETS):
                self.pending_pairs.append((wave_start + off, pair))
            self.wave_index += 1

        while self.pending_pairs and self.pending_pairs[0][0] <= now:
            due, pair = self.pending_pairs.pop(0)
            out += self._spawn_pair(due, pair)
            self.spawned += 1

        due_states = [i for i in self.pending_states if i[0] <= now]
        if due_states:
            self.pending_states = [i for i in self.pending_states if i[0] > now]
            for _, m in due_states:
                out.append((OP_STATE_1067, roster.build_entity_state(
                    m.eid, m.side, roster.ENTITY_STATE_MOVING)))

        for m in self.minions:
            if now < m.spawn_at:
                continue
            if not m.arrived:
                prev_seg = m.seg
                m.step_to(now)
                if m.seg != prev_seg or now >= m.next_position_at:
                    out.append((OP_POSITION_1070,
                                roster.build_position(m.eid, m.x, m.y)))
                    m.next_position_at = now + roster.MINION_POSITION_PERIOD
            elif now >= m.next_position_at:
                # corpus idle: rest-position heartbeats keep flowing (measured
                # 1.32–1.35 s at the meeting point)
                out.append((OP_POSITION_1070,
                            roster.build_position(m.eid, m.x, m.y)))
                m.next_position_at = now + roster.MINION_POSITION_PERIOD
        return out
