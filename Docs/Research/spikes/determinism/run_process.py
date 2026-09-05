"""
Two-process determinism spike.

This script runs as either the "host" or the "peer" process.

  host   : generates an intent log, runs its own engine, snapshots state
           at every Nth tick.
  peer   : reads the same intent log (from disk), runs its own engine,
           snapshots state at the same ticks.

A third script (verify.py) then byte-compares the snapshot files.

This mirrors the multiplayer design document §3 design at the smallest
possible scope:

  intent log  <=>  IntentLogEntry on the server (§3c)
  snapshot    <=>  GameState broadcast (§3a)
  engine      <=>  DeterministicRuleEngine shared library (§9, §10 step 2)

Usage:
    python run_process.py host   30
    python run_process.py peer   30
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path
from typing import Dict, List

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from engine import (  # noqa: E402  (path injection must come first)
    Action, ActionAttack, ActionMove, State, Unit, Vec3,
    apply_rules,
)


# --- Intent log generator -----------------------------------------

def build_intent_log(max_ticks: int) -> List[Action]:
    """Deterministic script of two units dueling. Same script on both
    processes by construction — the log is serialised to disk and
    reloaded by the peer, eliminating any shared-memory ambiguity."""
    actions: List[Action] = []
    for t in range(max_ticks):
        if t % 7 == 0 and t > 0:
            actions.append(ActionMove(2, Vec3(float(t % 5), 0.0,
                                              float((t * 3) % 5))))
        if t % 5 == 0 and t > 0:
            actions.append(ActionMove(1, Vec3(float(t % 4), 0.0,
                                              float((t * 2) % 4))))
        if t % 11 == 0 and t > 0:
            actions.append(ActionAttack(1, 2))
    return actions


def serialise_action(a: Action) -> Dict:
    if isinstance(a, ActionMove):
        return {"k": "move", "uid": a.unit_id,
                "tx": a.target.x, "ty": a.target.y, "tz": a.target.z}
    return {"k": "attack", "uid": a.unit_id, "tid": a.target_id}


def deserialise_action(d: Dict) -> Action:
    if d["k"] == "move":
        return ActionMove(d["uid"], Vec3(d["tx"], d["ty"], d["tz"]))
    return ActionAttack(d["uid"], d["tid"])


# --- Snapshot serialisation ---------------------------------------

def serialise_state(s: State) -> bytes:
    """Compact deterministic binary form. One record per unit:
       id(int32) team(int32) hp(int32) pos.x pos.y pos.z yaw_deg (all f64)
    Trailing tick(int64). Pack big-endian so two hosts give the same
    bytes on different machines/architectures."""
    out = bytearray()
    for u in s.units:
        out += struct.pack(">iiidddddi",
                           u.id, u.team, u.hp,
                           u.pos.x, u.pos.y, u.pos.z,
                           u.yaw_deg,
                           u.attack_range,
                           0)  # reserved
    out += struct.pack(">q", s.tick)
    return bytes(out)


# --- Main ---------------------------------------------------------

def run(role: str, max_ticks: int) -> None:
    intent_path = THIS_DIR / "intent_log.json"
    snap_path = THIS_DIR / f"snapshots_{role}.bin"

    if role == "host":
        actions = build_intent_log(max_ticks)
        intent_path.write_text(
            json.dumps([serialise_action(a) for a in actions],
                       indent=2),
            encoding="utf-8",
        )
        print(f"[host] wrote intent log: {len(actions)} actions")

    initial = State(
        tick=0,
        units=[
            Unit(1, 0, Vec3(0.0, 0.0, 0.0),  90.0, 100, 1.5),
            Unit(2, 1, Vec3(5.0, 0.0, 5.0), 270.0, 100, 1.5),
        ],
        rng_state=0xC0FFEE,
    )

    # Reload intent log from disk on every role so no in-process shortcut
    loaded = json.loads(intent_path.read_text(encoding="utf-8"))
    actions = [deserialise_action(d) for d in loaded]
    print(f"[{role}] loaded intent log: {len(actions)} actions")

    state = initial
    snaps: List[bytes] = []
    SNAPSHOT_EVERY = 4
    for t, a in enumerate(actions):
        state, events = apply_rules(state, a)
        if (t + 1) % SNAPSHOT_EVERY == 0:
            snaps.append(serialise_state(state))
    # Always snapshot tick=0 for control
    snaps.insert(0, serialise_state(initial))

    snap_path.write_bytes(b"".join(snaps))
    print(f"[{role}] wrote {len(snaps)} snapshots, "
          f"final tick={state.tick}")


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "host"
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    run(role, ticks)
