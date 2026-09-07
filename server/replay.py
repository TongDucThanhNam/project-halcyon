"""Deterministic Replay and Stream Verification for Project Halcyon (T3 Milestone 3).

Seed design from Docs/Research/spikes/determinism/ (input-stream model).

Features:
1. MatchRecorder: records timestamped input intents (c2s 1012, 1060, 1078, 1081)
   and authoritative server emissions (s2c 1070, 1054, 1053, 1082, 1046, etc.).
2. MatchReplayer: replays input intent traces through the authoritative sim,
   producing a second event stream.
3. DeterminismVerifier: compares two event streams byte-for-byte, asserts SHA-256
   identity, and pinpoints the first divergent frame if any divergence occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from . import hero_movement, roster, wire


@dataclass
class RecordedIntent:
    tick: int
    eid: int
    opcode: int
    payload: bytes


@dataclass
class RecordedFrame:
    tick: int
    opcode: int
    payload: bytes

    def serialize(self) -> bytes:
        return self.tick.to_bytes(4, "big") + self.opcode.to_bytes(2, "big") + self.payload


class MatchRecorder:
    """Records input intents and resulting broadcast frames."""

    def __init__(self):
        self.intents: List[RecordedIntent] = []
        self.frames: List[RecordedFrame] = []

    def record_intent(self, tick: int, eid: int, opcode: int, payload: bytes):
        self.intents.append(RecordedIntent(tick, eid, opcode, payload))

    def record_frame(self, tick: int, opcode: int, payload: bytes):
        self.frames.append(RecordedFrame(tick, opcode, payload))

    def get_event_stream_hash(self) -> str:
        hasher = hashlib.sha256()
        for f in self.frames:
            hasher.update(f.serialize())
        return hasher.hexdigest()


class DeterminismVerifier:
    """Verifies that two simulation runs produced byte-identical event streams."""

    @staticmethod
    def verify(run_a_frames: List[RecordedFrame], run_b_frames: List[RecordedFrame]) -> Tuple[bool, str]:
        if len(run_a_frames) != len(run_b_frames):
            return False, f"Frame count mismatch: run_a={len(run_a_frames)} vs run_b={len(run_b_frames)}"

        hasher_a = hashlib.sha256()
        hasher_b = hashlib.sha256()

        for idx, (fa, fb) in enumerate(zip(run_a_frames, run_b_frames)):
            bytes_a = fa.serialize()
            bytes_b = fb.serialize()
            hasher_a.update(bytes_a)
            hasher_b.update(bytes_b)

            if bytes_a != bytes_b:
                return False, (
                    f"Divergence at frame #{idx} (tick {fa.tick} vs {fb.tick}): "
                    f"run_a=(op={fa.opcode}, payload={fa.payload.hex()}) vs "
                    f"run_b=(op={fb.opcode}, payload={fb.payload.hex()})"
                )

        hash_a = hasher_a.hexdigest()
        hash_b = hasher_b.hexdigest()
        if hash_a != hash_b:
            return False, f"Hash mismatch: {hash_a} != {hash_b}"

        return True, f"PASS: identical {len(run_a_frames)} frames (sha256={hash_a})"


class ReplaySimulation:
    """A self-contained deterministic simulation runner for replay testing."""

    def __init__(self, dt: float = 0.05):
        self.dt = dt
        self.tick = 0
        self.hero = hero_movement.HeroMovement(eid=1500, x=-76.18, y=0.88)
        self.recorder = MatchRecorder()

    def feed_intent(self, opcode: int, payload: bytes):
        self.recorder.record_intent(self.tick, self.hero.eid, opcode, payload)
        if opcode == wire.OP.MOVE_CAST:
            tx, ty = roster.parse_move(payload)
            start_frames = self.hero.set_target(tx, ty)
            for op, p in start_frames:
                self.recorder.record_frame(self.tick, op, p)

    def step(self):
        self.tick += 1
        now = self.tick * self.dt
        frames = self.hero.step(self.dt, now=now)
        for op, p in frames:
            self.recorder.record_frame(self.tick, op, p)
