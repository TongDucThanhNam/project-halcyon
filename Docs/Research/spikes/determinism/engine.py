"""
DeterministicRuleEngine contract spike for Veilbound multiplayer research.

Maps directly to the proposed contract in
Docs/Research/veilbound-multiplayer-design.md §3 / §10 step 2.

    (new_state, events) = ApplyRules(current_state, action)

This implementation deliberately exercises the three floating-point paths
listed in design doc §4a as non-deterministic sources on .NET:

  - Trig (Quaternion.Euler equivalent: yaw -> forward vector)
  - Division  (Vector3.Distance equivalent: unit vector normalisation)
  - Lerp     (Vector3.Lerp equivalent: chase/move interpolation)

Goal: verify whether two isolated Python processes (representing host +
peer) produce bit-identical state after running the same intent log
through the same engine. Python floats are IEEE 754 doubles, just like
.NET floats on Linux/IL2CPP; whatever Python produces here, .NET
would produce too. The spike therefore characterises C# behaviour
indirectly without needing .NET SDK installed.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field, asdict
from typing import List, Tuple


# --- Types ---------------------------------------------------------

@dataclass
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, o: "Vec3") -> "Vec3":
        return Vec3(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o: "Vec3") -> "Vec3":
        return Vec3(self.x - o.x, self.y - o.y, self.z - o.z)

    def scaled(self, k: float) -> "Vec3":
        return Vec3(self.x * k, self.y * k, self.z * k)

    def length(self) -> float:
        # mirrors Vector3.Distance(v, Vec3.zero) / math.sqrt(dot)
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalised(self) -> "Vec3":
        # mirrors Vector3.normalized — division by length is the
        # canonical non-deterministic path on some IL2CPP builds
        L = self.length()
        if L < 1e-9:
            return Vec3(0.0, 0.0, 0.0)
        return Vec3(self.x / L, self.y / L, self.z / L)


@dataclass
class Unit:
    id: int
    team: int               # 0 or 1
    pos: Vec3
    yaw_deg: float          # Quaternion.Euler(x,y,z).eulerAngles equivalent
    hp: int
    attack_range: float


@dataclass
class State:
    tick: int = 0
    units: List[Unit] = field(default_factory=list)
    rng_state: int = 0xC0FFEE   # mirrors Unity Random.InitState


@dataclass
class ActionMove:
    """Player intent: move unit toward target world position."""
    unit_id: int
    target: Vec3


@dataclass
class ActionAttack:
    """Player intent: attack a target unit id."""
    unit_id: int
    target_id: int


Action = ActionMove | ActionAttack


# --- Deterministic helpers ----------------------------------------

def yaw_to_forward(yaw_deg: float) -> Vec3:
    """Equivalent of Quaternion.Euler(0, yaw, 0) * Vector3.forward.

    C#:  Vector3 fwd = Quaternion.Euler(0, yaw, 0) * Vector3.forward;
    Both languages reduce to (sin, 0, cos) but the order of evaluation
    is implementation-defined when yaw is multiple of special angles
    (NaN-free here, but still worth exercising).
    """
    rad = math.radians(yaw_deg)
    return Vec3(math.sin(rad), 0.0, math.cos(rad))


def step_rng(state: int) -> Tuple[int, float]:
    """Linear congruential generator — deterministic on every platform
    that follows the IEEE-754 spec for `int` overflow."""
    state = (state * 1103515245 + 12345) & 0x7FFFFFFF
    return state, (state & 0xFFFF) / 65536.0


# --- The rule engine -----------------------------------------------

def apply_rules(state: State, action: Action) -> Tuple[State, List[str]]:
    """Pure function. Returns a *new* State and a list of event strings.

    Two side effects are forbidden:
      1. mutation of `state` in place
      2. any clock / time / OS call

    This is the contract that must hold on both client and server.
    """
    new_units = [Unit(u.id, u.team, Vec3(u.pos.x, u.pos.y, u.pos.z),
                       u.yaw_deg, u.hp, u.attack_range)
                 for u in state.units]
    events: List[str] = []

    if isinstance(action, ActionMove):
        u = next(x for x in new_units if x.id == action.unit_id)
        # chase speed simulates Vector3.MoveTowards / Lerp
        CHASE_SPEED = 0.08
        to_target = action.target - u.pos
        dist = to_target.length()
        if dist > 1e-6:
            # mirror Vector3.MoveTowards: take min(step_size, dist)
            step_mag = min(CHASE_SPEED, dist)
            step_vec = to_target.normalised().scaled(step_mag)
            u.pos = u.pos + step_vec
            # face the direction of travel (Quaternion.Euler equivalent)
            fwd = yaw_to_forward(math.degrees(math.atan2(step_vec.x,
                                                         step_vec.z)))
            # Composite yaw: x-only projection kept, so trig fires twice
            u.yaw_deg = math.degrees(math.atan2(fwd.x, fwd.z))
        events.append(f"tick={state.tick} move unit={u.id} -> "
                      f"({u.pos.x:.9f},{u.pos.z:.9f})")

    elif isinstance(action, ActionAttack):
        attacker = next(x for x in new_units if x.id == action.unit_id)
        target = next(x for x in new_units if x.id == action.target_id)
        sep = attacker.pos - target.pos
        if sep.length() <= attacker.attack_range:
            target.hp -= 10
            events.append(f"tick={state.tick} attack "
                          f"{attacker.id}->{target.id} hp={target.hp}")
        else:
            events.append(f"tick={state.tick} attack out_of_range "
                          f"{attacker.id}->{target.id}")

    new_state = State(tick=state.tick + 1,
                      units=new_units,
                      rng_state=state.rng_state)
    return new_state, events


# --- Determinism self-check ---------------------------------------

if __name__ == "__main__":
    # Run engine twice on the exact same starting state + intent sequence.
    # If the rule engine is deterministic, the final state bytes must match.
    initial = State(
        tick=0,
        units=[
            Unit(1, 0, Vec3(0.0, 0.0, 0.0),  90.0, 100, 1.5),
            Unit(2, 1, Vec3(5.0, 0.0, 5.0), 270.0, 100, 1.5),
        ],
        rng_state=0xC0FFEE,
    )
    intents = [
        ActionMove(1, Vec3(3.0, 0.0, 3.0)),
        ActionMove(2, Vec3(2.0, 0.0, 2.0)),
        ActionAttack(1, 2),
        ActionMove(2, Vec3(0.0, 0.0, 0.0)),
        ActionAttack(1, 2),
    ]
    s1 = initial
    for a in intents:
        s1, _ = apply_rules(s1, a)
    s2 = initial
    for a in intents:
        s2, _ = apply_rules(s2, a)
    assert s1.tick == s2.tick, "tick diverged"
    for a, b in zip(s1.units, s2.units):
        assert a.id == b.id and a.hp == b.hp
        # bit-exact on floats: compare struct pack
        for ax, bx in [(a.pos.x, b.pos.x), (a.pos.y, b.pos.y),
                       (a.pos.z, b.pos.z), (a.yaw_deg, b.yaw_deg)]:
            assert struct.pack(">d", ax) == struct.pack(">d", bx), \
                f"float diverged: {ax!r} vs {bx!r}"
    print("self-check: deterministic across two runs ({} ticks)".format(s1.tick))
    print("final state:")
    for u in s1.units:
        print(f"  unit {u.id}: pos=({u.pos.x},{u.pos.z}) yaw={u.yaw_deg:.9f} hp={u.hp}")
