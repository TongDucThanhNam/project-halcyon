"""Native Recall buff presentation and measured successful-return actions.

The session owns recall decisions, movement, HP and energy. This class only
tracks native instances: 25=Buff_Withdraw, 26=Buff_Withdraw_Ping. Early cancel
uses 1093 for both; successful completion invokes 1094 on instance25. Optional
1049/1033 return presentation requires caller-supplied measured 3D heights.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

RECALL_SECONDS = 4.0
RECALL_RESOURCE_FRACTION = 0.25
WITHDRAW_KIND = 25
PING_KIND = 26
RETURN_EFFECT_TAG = 0x48D95353
WITHDRAW_KEY = 'recall_withdraw'
PING_KEY = 'recall_ping'

# Exact f32 values from the observed A001 return effects/relocations. Right
# slots1517/1518/1519 agree. Left relocation height varies by spawn slot, so a
# single team1 pair would be false; stable measured left slots are separate.
RETURN_HEIGHTS = {2: (1.5, 1.7470695972442627)}
RETURN_HEIGHTS_BY_EID = {
    1500: (1.2999999523162842, 1.2670695781707764),
    1515: (1.2999999523162842, 1.2670695781707764),
}


def build_recall_trigger(eid: int, withdraw_instance: int) -> bytes:
    """1094 target/buff-instance trigger, observed on successful Withdraw."""
    return struct.pack('>II6x', eid, withdraw_instance)


def build_return_effect(eid: int, x: float, y: float, height: float) -> bytes:
    """1049 Recall-specific effect; do not generalize its ten zero bytes."""
    if not all(math.isfinite(value) for value in (x, y, height)):
        raise ValueError('return-effect coordinates must be finite')
    return struct.pack('>IIfff10x', RETURN_EFFECT_TAG, eid, x, height, y)


def build_return_relocation(eid: int, x: float, y: float, height: float) -> bytes:
    """1033 return relocation has flag0, unlike native resurrection's flag1."""
    if not all(math.isfinite(value) for value in (x, y, height)):
        raise ValueError('return-relocation coordinates must be finite')
    return struct.pack('>Ifff6x', eid, x, height, y)


@dataclass(frozen=True)
class RecallState:
    eid: int
    started_at: float
    completes_at: float
    withdraw_instance: int
    ping_instance: int


class RecallPresentation:
    """Call start/cancel/complete at the authoritative session transitions.

    Start and cancellation enqueue native buff frames on the shared manager;
    the session drains it normally. Complete returns its ordered action burst.
    This avoids guessing whether a cleared timer meant movement, death or a
    successful return. Reconnect uses StatusManager.snapshot_frames(now).
    """

    def __init__(self, status_manager):
        self.status = status_manager
        self.active: dict[int, RecallState] = {}

    def start(self, eid: int, now: float, duration: float = RECALL_SECONDS) -> RecallState:
        if not math.isfinite(now) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('recall start and positive duration must be finite')
        previous = self.active.get(eid)
        if previous is not None and (previous.started_at, previous.completes_at) == (now, now + duration):
            return previous
        self.cancel(eid, now)
        withdraw = self.status.apply_presentation(WITHDRAW_KEY, eid, eid, WITHDRAW_KIND, now, duration)
        ping = self.status.apply_presentation(PING_KEY, eid, eid, PING_KIND, now, duration)
        state = RecallState(eid, now, now + duration, withdraw, ping)
        self.active[eid] = state
        return state

    def cancel(self, eid: int, now: float) -> bool:
        if not math.isfinite(now):
            raise ValueError('recall cancellation time must be finite')
        state = self.active.pop(eid, None)
        if state is None:
            return False
        self.status.remove_presentation(eid, WITHDRAW_KEY, now=now)
        self.status.remove_presentation(eid, PING_KEY, now=now)
        return True

    def complete(self, eid: int, now: float, *, x: float | None = None,
                 y: float | None = None, effect_height: float | None = None,
                 relocation_height: float | None = None) -> list[tuple[int, bytes]]:
        if not math.isfinite(now):
            raise ValueError('recall completion time must be finite')
        state = self.active.get(eid)
        if state is None:
            return []
        if now + 1e-9 < state.completes_at:
            raise ValueError('recall cannot complete before its deadline')
        coordinates = (x, y, effect_height, relocation_height)
        if any(value is not None for value in coordinates) and any(value is None for value in coordinates):
            raise ValueError('return presentation requires both coordinates and both measured heights')
        frames = [(1094, build_recall_trigger(eid, state.withdraw_instance))]
        if x is not None:
            frames.extend(((1049, build_return_effect(eid, x, y, effect_height)),
                           (1033, build_return_relocation(eid, x, y, relocation_height))))
        # Natural end does not emit a cancellation, including at a rounded tick.
        self.status.remove_presentation(eid, WITHDRAW_KEY, now=max(now, state.completes_at))
        self.status.remove_presentation(eid, PING_KEY, now=max(now, state.completes_at))
        del self.active[eid]
        return frames
