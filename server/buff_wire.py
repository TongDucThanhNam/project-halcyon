"""Measured native buffs: 1086 add, 1087 state and 1093 explicit cancellation.

1086 uses an IEEE-754 half-float duration. The u32 instance after it is a buff
identity, not an item inventory instance or packet sequence. Natural expiry
uses the duration; 1093 addresses the same target/instance for an early cancel.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import struct
from typing import Callable

BUFF_ADD = 1086
BUFF_STATE = 1087
BUFF_CANCEL = 1093
_ADD = struct.Struct(">IIeIH6s")

# Exact zero-based indices from the native KindredBuffs pointer registry.
# 259/268/270/279/287 also occur in the bounded vg5 packet corpus.
ITEM_BUFF_KINDS = {
    "healing_flask": 259,
    "reflex_block": 268,
    "fountain_of_renewal": 270,
    "sprint_boots_sprint": 278,
    "travel_boots_sprint": 279,
    "halcyon_chargers_sprint": 281,
    "vision_totem_aura": 287,
    "atlas_pauldron_slow": 295,
}


@dataclass(frozen=True)
class PresentedBuff:
    key: str
    target_eid: int
    source_eid: int
    kind: int
    instance_id: int
    applied_at: float
    expires_at: float
    wire_expires_at: float | None = None

    def payload(self, now: float) -> bytes:
        duration = -1.0 if math.isinf(self.expires_at) else max(0.0, self.expires_at - now)
        return build_buff_add(self.target_eid, self.source_eid, duration, self.instance_id, self.kind)


class BuffLifecycle:
    """Native identities shared by item and ability presentation in one match.

    The optional local allocator is for standalone simulations. A live match
    supplies its allocator so buffs cannot overlap another actor's identity.
    A refresh cancels the previous native instance and allocates a new one;
    identical compound-status applications do not duplicate their one buff.
    """

    def __init__(self, instance_allocator: Callable[[], int] | None = None):
        if instance_allocator is not None and not callable(instance_allocator):
            raise TypeError("buff instance allocator must be callable")
        self._next_instance = 2_000_000
        self._allocate = instance_allocator or self._allocate_local
        self._allocated: set[int] = set()
        self.active: dict[tuple[int, str], PresentedBuff] = {}
        self._frames: list[tuple[int, bytes]] = []

    def _allocate_local(self) -> int:
        instance = self._next_instance
        self._next_instance += 1
        return instance

    def apply(self, key: str, source_eid: int, target_eid: int, kind: int,
              now: float, duration: float) -> int:
        if not isinstance(key, str) or not key:
            raise ValueError("buff presentation key must be a nonempty string")
        if not math.isfinite(now):
            raise ValueError("buff application time must be finite")
        # Validate the wire fields before changing any active presentation.
        build_buff_add(target_eid, source_eid, duration, 1, kind)
        expires = math.inf if duration == -1 else now + duration
        previous = self.active.get((target_eid, key))
        if previous is not None and (previous.source_eid, previous.kind, previous.applied_at,
                                     previous.expires_at) == (source_eid, kind, now, expires):
            return previous.instance_id
        instance = self._allocate()
        _u32(instance, "buff instance")
        if instance == 0 or instance in self._allocated:
            raise ValueError("buff allocator returned a zero or previously allocated identity")
        value = PresentedBuff(key, target_eid, source_eid, kind, instance, now, expires)
        payload = value.payload(now)
        if previous is not None:
            self.remove(target_eid, key, now=now)
        self._allocated.add(instance)
        self.active[(target_eid, key)] = value
        self._frames.append((BUFF_ADD, payload))
        return instance

    def remove(self, target_eid: int, key: str, *, now: float | None = None) -> None:
        value = self.active.pop((target_eid, key), None)
        if value is not None and (now is None or now < (value.wire_expires_at
                                                       if value.wire_expires_at is not None else value.expires_at)):
            self._frames.append((BUFF_CANCEL, build_buff_cancel(target_eid, value.instance_id)))

    def shorten(self, target_eid: int, key: str, expires_at: float, now: float) -> bool:
        """Shorten an effect without replaying its add on every deflection/hit."""
        if not math.isfinite(expires_at) or not math.isfinite(now):
            raise ValueError("shortened buff times must be finite")
        value = self.active.get((target_eid, key))
        if value is None or expires_at >= value.expires_at:
            return False
        wire_expiry = value.wire_expires_at if value.wire_expires_at is not None else value.expires_at
        self.active[(target_eid, key)] = replace(value, expires_at=expires_at, wire_expires_at=wire_expiry)
        if expires_at <= now:
            self.remove(target_eid, key, now=now)
        return True

    def clear_target(self, target_eid: int, *, now: float | None = None) -> None:
        selected = sorted((value for value in self.active.values() if value.target_eid == target_eid),
                          key=lambda value: value.instance_id)
        for value in selected:
            self.remove(target_eid, value.key, now=now)

    def expire(self, now: float) -> None:
        # 1086 supplies the lifetime; natural expiry emits no redundant cancel.
        for identity, value in sorted(list(self.active.items()), key=lambda item: item[1].instance_id):
            if value.expires_at <= now:
                self.remove(value.target_eid, value.key, now=now)

    def drain_frames(self) -> list[tuple[int, bytes]]:
        frames, self._frames = self._frames, []
        return frames

    def snapshot_frames(self, now: float) -> list[tuple[int, bytes]]:
        return [(BUFF_ADD, value.payload(now))
                for value in sorted(self.active.values(), key=lambda value: value.instance_id)
                if value.applied_at <= now < value.expires_at]


def _u32(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must fit u32")


@dataclass(frozen=True)
class BuffAdd:
    target_eid: int
    source_eid: int
    duration: float
    instance_id: int
    kind: int

    def encode(self) -> bytes:
        for name, value in (("target", self.target_eid), ("source", self.source_eid), ("instance", self.instance_id)):
            _u32(value, name)
        if isinstance(self.kind, bool) or not isinstance(self.kind, int) or not 0 <= self.kind <= 0xFFFF:
            raise ValueError("buff kind must fit u16")
        if (not math.isfinite(self.duration) or self.duration > 65504
                or (self.duration < 0 and self.duration != -1)):
            raise ValueError("buff duration must fit f16, be nonnegative or -1 for indefinite")
        return _ADD.pack(self.target_eid, self.source_eid, self.duration, self.instance_id, self.kind, bytes(6))


def build_buff_add(target_eid: int, source_eid: int, duration: float, instance_id: int, kind: int) -> bytes:
    """1086 payload; callers allocate a unique live buff instance identity."""
    return BuffAdd(target_eid, source_eid, duration, instance_id, kind).encode()


def parse_buff_add(payload: bytes) -> BuffAdd:
    if len(payload) != 22 or payload[16:] != bytes(6):
        raise ValueError("1086 requires its 16 semantic bytes and six zero bytes")
    value = BuffAdd(*struct.unpack_from(">IIeIH", payload))
    value.encode()
    return value


@dataclass(frozen=True)
class BuffState:
    """1087 extends the buff header with a u16 and four opaque u32 words.

    The u16 behaves as a stack/state count in the measured cases. Words may
    contain float bits, integer state, or an entity reference, depending on
    native kind; this codec deliberately does not assign universal meanings.
    """
    buff: BuffAdd
    state_count: int
    words: tuple[int, int, int, int]

    def encode(self, *, padded: bool = True) -> bytes:
        header = self.buff.encode()[:16]
        if isinstance(self.state_count, bool) or not isinstance(self.state_count, int) or not 0 <= self.state_count <= 0xFFFF:
            raise ValueError("buff state count must fit u16")
        if len(self.words) != 4:
            raise ValueError("1087 requires four opaque state words")
        for value in self.words:
            _u32(value, "buff state word")
        return header + struct.pack(">H4I", self.state_count, *self.words) + (bytes(4) if padded else b"")


def build_buff_state(target_eid: int, source_eid: int, duration: float, instance_id: int,
                     kind: int, state_count: int, words: tuple[int, int, int, int]) -> bytes:
    return BuffState(BuffAdd(target_eid, source_eid, duration, instance_id, kind), state_count, words).encode()


def parse_buff_state(payload: bytes) -> BuffState:
    if len(payload) not in (34, 38) or (len(payload) == 38 and payload[34:] != bytes(4)):
        raise ValueError("1087 requires 34 semantic bytes and optional four-byte zero padding")
    value = BuffState(BuffAdd(*struct.unpack_from(">IIeIH", payload)),
                      struct.unpack_from(">H", payload, 16)[0], struct.unpack_from(">4I", payload, 18))
    value.encode()
    return value


def build_buff_cancel(target_eid: int, instance_id: int) -> bytes:
    """1093 payload addresses the target and the instance assigned by 1086."""
    _u32(target_eid, "target")
    _u32(instance_id, "instance")
    return struct.pack(">II", target_eid, instance_id) + bytes(6)


def parse_buff_cancel(payload: bytes) -> tuple[int, int]:
    if len(payload) != 14 or payload[8:] != bytes(6):
        raise ValueError("1093 requires target, buff instance and six zero bytes")
    return struct.unpack_from(">II", payload)
