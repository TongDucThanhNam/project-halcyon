"""Bounded real-client driver for Skye and minion-push acceptance scenarios.

MODE
----
This module drives ONE owned local session through the operator's already-running
local stack: the authoritative Halcyon server with ``HALCYON_QA_DIR`` enabled and
a live Android CE client (``com.superevilmegacorp.game``) driven over ADB.
The current phase is implementation plus headless/mock validation; a subsequent
bounded rendered-client validation performs live execution.

STAGES (machine-readable diagnosis)
-----------------------------------
  SETUP                  explicit owned session paths, supported resolution,
                         fresh matching trace connection, progressing WORLD
                         simulation proven through this driver's own acknowledged
                         read-only QA snapshot requests. A stale ``state.json``
                         after a disconnect is NOT a valid session even when
                         ``match_finished`` is false. Setup failure is reported,
                         never a gameplay regression.
  UI_COMMAND_SUBMITTED   the exact bounded UI gesture this driver issued (tap or
                         swipe coordinates, timestamps).
  CLIENT_INPUT_OBSERVED  the corresponding c2s frame actually observed in the
                         live wire trace (opcode, action byte, timing). Missing
                         input is distinct from received-but-unacknowledged.
  SERVER_ACKNOWLEDGED    matching s2c acknowledgment (or cooldown-timer 1162
                         evidence). An explicit server rejection is recorded as
                         such; an unknown rejection reason stays unknown.
  AUTHORITATIVE_EFFECT   attributed effect frames (1054 damage with victim/
                         attacker identity, ability actor publication, resource
                         delta). A bare post-cast HP decrease is insufficient:
                         incoming damage, other actors and unrelated basic
                         attacks are classified and excluded.
  TRIAL_CONTINUITY       end-of-trial diagnostics receipt read AFTER the whole
                         time-sensitive sequence (never between the basic hit
                         and the dependent cast) proving the SAME process,
                         startup and match were alive, in WORLD and unfinished,
                         with strictly advancing tick and simulation time from
                         the initial receipt. A missing, unacknowledged or
                         malformed endpoint receipt is an EVIDENCE failure: it
                         never rewrites the already-observed input/ack/outcome
                         stages and is never reported as a failed UI action.
  PRESENTATION           bounded video/screenshot capture with start/end/action
                         timestamps. An unreviewed recording is evidence of
                         capture only; its status stays UNVERIFIED until a
                         human reviews the rendered output.

LOCK-TO-CAST SEQUENCING (skye-b / skye-c)
-----------------------------------------
The B and C casts require a current basic-hit Target Lock. The driver taps the
enemy body, waits for the actual 1086 kind-602 lock in the trace, then issues
the ability gesture in the same bounded script — no model round trip and no QA
mailbox call between the observed lock and the dependent cast.

PREPARATION VS EVIDENCE
-----------------------
Legal QA operations (learn, resources, teleport of THIS hero to the verified
profile positions) are recorded as preparation. Forced casts, forced locks and
QA damage are never issued as evidence of client behavior.

WIRE ANCHORS (verified against current builders, see scenario doc)
------------------------------------------------------------------
  c2s 1042 ground cast: 14 B, [f32 x][f32 z][f32 y][u8 action][u8 flags];
        Skye native actions A=0, B=2, C=4 (UI upgrade slots 0/1/2 differ).
  s2c 1046 ack: 22 B, hero u32 @0, native action u8 @16.
  1086 buff add: target u32 @0, source u32 @4, f16 duration @8, instance @10,
        kind u16 @14; Target Lock kind is 602 (server/abilities.py).
  s2c 1162 cooldown tag bytes (FNV-1a of Ability__Skye__{A,B,C}):
        A 43a890d8, B 46a89591, C 45a893fe. B may also reset the A timer, so
        seeing the A timer move is NOT proof of the B cooldown.
  C volley actor publication: 1010 with volley class 0xF59CDB08 @4 and the
        casting hero's eid @112 (server/skye_wire.py build_volley).

Not every 1037 projectile, 1010 actor or 1054 damage inside a broad window
belongs to the skill under test: each is classified explicitly below.

All artifacts stay outside this repository under unique directories; old
records are never deleted. This driver stops only capture processes it
created itself.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import time
from typing import Any, Callable
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKYE_HERO_ID = 265
SKYE_NATIVE_ACTIONS = {"A": 0, "B": 2, "C": 4}
SKYE_COOLDOWN_TAGS = {"A": 0x43A890D8, "B": 0x46A89591, "C": 0x45A893FE}
TARGET_LOCK_KIND = 602
VOLLEY_CLASS = 0xF59CDB08
# Declared BYTE length of the Skye C volley publication entity record
# (server/skye_wire.py builds a 126-byte template: class @4, owner @112).
# Guards must count DECODED bytes, never hex characters: ``bytes.fromhex``
# ignores whitespace, so a padded payload can satisfy a character-count guard
# while decoding to far fewer bytes than the parser's offset reads require.
VOLLEY_PUBLICATION_BYTES = 126
SKYE_ENEMY_EID_DEFAULT = 1517

OP_GROUND_CAST = 1042
OP_POSITION_EVENT = 1046
OP_DAMAGE = 1054
OP_ENTITY_FULL_UPDATE = 1010
OP_MOVE_ORDER = 1016
OP_BUFF_ADD = 1086
# s2c [u32 victim][u32 killer][6 pad] — the only explicit minion-death
# evidence the trace carries: the lane census serves living minions only, so
# a disappearing row states an absence, never a death.
OP_ENTITY_DEATH = 1072
OP_TIMER_TICK = 1162
# Removal publications. 1073 retires the actor's presentation only: a hero's
# actor and compact slot survive it for resurrection, so it does NOT release
# the slot. 1035 is the release — server/actor_slots.py clears the slot on
# 1035 ("reused after 1035 removes its previous owner"), and every despawn
# path emits the two as a (1073, 1035) pair and releases at the 1035 step.
OP_ACTOR_RETIRE = 1073
OP_ACTOR_DESPAWN = 1035

STAGES = ("SETUP", "UI_COMMAND_SUBMITTED", "CLIENT_INPUT_OBSERVED",
          "SERVER_ACKNOWLEDGED", "AUTHORITATIVE_EFFECT", "TRIAL_CONTINUITY",
          "PRESENTATION",
          # observational minion-push stages (minion-push only)
          "LANE_APPROACH", "OPPOSING_COMBAT", "SURVIVOR_RESUMPTION",
          "STRUCTURE_INTERACTION")

CLIENT_SCENARIOS = ("skye-a", "skye-b", "skye-c", "minion-push")

ANDROID_PACKAGE = "com.superevilmegacorp.game"
PROFILE_RESOLUTION = (960, 540)

DEFAULT_PROFILE = {
    "package": ANDROID_PACKAGE,
    "width": PROFILE_RESOLUTION[0],
    "height": PROFILE_RESOLUTION[1],
    "skye_position": [0.0, 38.0],
    "enemy_position": [4.0, 38.0],
    "enemy_body_tap": [603, 235],
    "enemy_feet_aim": [603, 267],
    "controls": {"A": [406, 496], "B": [480, 496], "C": [550, 496]},
    "b_drag_to": [510, 285],
    "c_drag_to": [603, 260],
    # Ground tap issued after an accepted cast to stop the ordinary
    # auto-attack cycle through real UI (recorded as a gesture).
    "disengage_tap": [220, 320],
    # Native Skye energy costs (server/abilities.py create_skye_kit, rank 1).
    "ability_costs": {"A": 40.0, "B": 70.0, "C": 70.0},
    # Client "+" upgrade buttons (measured from the live HUD 2026-09-10);
    # tapping them spends leftover points through the real client UI so the
    # upgrade overlay cannot intercept a skill gesture.
    "upgrade_plus_taps": [[408, 440], [478, 440], [548, 440]],
    # The client-controlled local player always owns this eid (slot 0 Guest).
    "local_player_eid": 1500,
    # Declared per-trial fixture contract: BOTH resources are FULL-RESOURCE
    # requests (a deliberately oversized value the server clamps to the
    # actor cap, with the clamped actual recorded). Levels/ranks are left
    # undeclared (unknown) in the default profile: an unknown field blocks
    # the comparable-pair claim until a specific profile declares it.
    "declared_fixture": {
        "skye_energy_policy": "full",
        "skye_hp_policy": "full",
        "enemy_hp_policy": "full",
    },
    # The client camera pans smoothly after a QA teleport; gestures are only
    # valid once it has settled on the new framing (measured live 2026-09-10:
    # an immediate cast still acknowledged but missed the displaced target).
    "camera_settle_s": 4.0,
    # Observational window (seconds) for the client-side minion-push scan.
    "minion_push_window_s": 20.0,
    # Client minion-push observation point: near the lane but off its marching
    # path, inside the 40u snapshot radius of passing minions.
    "minion_push_hero_position": [0.0, 10.0],  # 8 u off the lane center:
}


class ClientStageFailure(Exception):
    """Classified client failure at a specific stage."""

    def __init__(self, stage: str, status: str, detail: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown client stage: {stage!r}")
        self.stage = stage
        self.status = status
        self.detail = detail
        super().__init__(f"[{stage}/{status}] {detail}")


def load_client_profile(path: str | None) -> dict:
    """Explicit profile JSON overrides the built-in 960x540 default."""
    if path is None:
        return json.loads(json.dumps(DEFAULT_PROFILE))
    try:
        override = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClientStageFailure("SETUP", "FAIL", f"client profile unreadable: {exc}")
    if not isinstance(override, dict):
        raise ClientStageFailure("SETUP", "FAIL", "client profile must be a JSON object")
    profile = json.loads(json.dumps(DEFAULT_PROFILE))
    profile.update(override)
    return profile


# ---------------------------------------------------------------------------
# Wire-trace tailing (incremental, incomplete-final-line tolerant)
# ---------------------------------------------------------------------------

class TraceTail:
    """Incremental JSONL wire-trace reader.

    Only complete newline-terminated lines are consumed; a partially written
    final record is left for the next poll. ``wait_for`` polls until a record
    matches all supplied predicates or the bounded deadline expires.
    """

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        # Start from the beginning: connection discovery and freshness checks
        # need the existing history. Stage waits filter by min_time, so older
        # records can never satisfy a later cast's wait.
        self._offset = 0
        self._inode = None
        if self.path.is_file():
            stat = self.path.stat()
            self._inode = (stat.st_dev, stat.st_ino)
        self.records: list[dict] = []
        self.skipped_partial_bytes = 0

    def poll(self) -> list[dict]:
        """Read every newly completed record since the last poll."""
        if not self.path.is_file():
            return []
        stat = self.path.stat()
        inode = (stat.st_dev, stat.st_ino)
        if inode != self._inode:              # rotated/replaced trace: restart
            self._offset = 0
            self._inode = inode
        if stat.st_size < self._offset:       # truncated in place: restart
            self._offset = 0
        if stat.st_size == self._offset:
            return []
        fresh: list[dict] = []
        with self.path.open("rb") as stream:
            stream.seek(self._offset)
            data = stream.read()
        cut = data.rfind(b"\n")
        if cut < 0:
            return []
        self._offset += cut + 1
        for line in data[:cut].splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                fresh.append(record)
        self.records.extend(fresh)
        return fresh

    def wait_for(self, predicate: Callable[[dict], bool], timeout: float,
                 *, min_time: float | None = None) -> dict | None:
        """Bounded poll for the first matching record after ``min_time``.

        The whole buffered history is scanned each iteration: a record already
        consumed by an earlier stage's wait must stay visible to later stages.
        ``min_time`` is what keeps earlier-cast records out.
        """
        deadline = time.monotonic() + timeout
        while True:
            self.poll()
            for record in self.records:
                if min_time is not None and record.get("time", 0) < min_time:
                    continue
                if predicate(record):
                    return record
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(0.05, max(0.005, deadline - time.monotonic())))


def _payload_u32(payload_hex: str, offset: int) -> int:
    return struct.unpack_from(">I", bytes.fromhex(payload_hex), offset)[0]


def _payload_u8(payload_hex: str, offset: int) -> int:
    return bytes.fromhex(payload_hex)[offset]


def _payload_f32(payload_hex: str, offset: int) -> float:
    return struct.unpack_from(">f", bytes.fromhex(payload_hex), offset)[0]


def ground_cast_action(record: dict) -> int | None:
    """Native action byte @12 of a c2s 1042, else None."""
    if record.get("opcode") != OP_GROUND_CAST:
        return None
    payload = record.get("payload", "")
    if len(payload) < 26:                      # 13 bytes minimum
        return None
    return _payload_u8(payload, 12)


def position_event_action(record: dict) -> int | None:
    """Native action byte @16 of an s2c 1046, else None."""
    if record.get("opcode") != OP_POSITION_EVENT:
        return None
    payload = record.get("payload", "")
    if len(payload) < 34:                      # 17 bytes minimum
        return None
    return _payload_u8(payload, 16)


def damage_identity(record: dict) -> tuple[int, int, float] | None:
    """(victim, attacker, signed delta) from a 1054, else None."""
    if record.get("opcode") != OP_DAMAGE:
        return None
    payload = record.get("payload", "")
    if len(payload) < 24:                      # 12 bytes minimum
        return None
    victim, attacker = struct.unpack_from(">II", bytes.fromhex(payload), 0)
    (delta,) = struct.unpack_from(">f", bytes.fromhex(payload), 8)
    return victim, attacker, delta


def payload_backs_hit(hit, hero_eid, enemy_eid) -> str | None:
    """Reason an attributed hit is NOT backed by its own recorded 1054
    payload, or None when victim/attacker/delta/tail all match it. Never
    raises: any malformed entry becomes a structured reason string."""
    if not isinstance(hit, dict):
        return f"entry is {type(hit).__name__}, not an object"
    payload = hit.get("payload")
    if not isinstance(payload, str):
        return f"payload missing ({payload!r})"
    try:
        raw = bytes.fromhex(payload)
    except ValueError:
        return "payload is not hexadecimal"
    if len(raw) < 12:
        return f"payload too short for victim/attacker/delta ({len(raw)} B)"
    victim, attacker = struct.unpack_from(">II", raw, 0)
    (delta,) = struct.unpack_from(">f", raw, 8)
    if victim != enemy_eid or attacker != hero_eid:
        return (f"payload identifies victim {victim}/attacker {attacker}, "
                f"not the declared enemy {enemy_eid}/skye {hero_eid}")

    def f32(value):
        try:
            return struct.unpack(">f", struct.pack(">f", value))[0]
        except (OverflowError, struct.error, ValueError):
            return None

    recorded = hit.get("delta")
    if not isinstance(recorded, (int, float)) or isinstance(recorded, bool) \
            or not math.isfinite(recorded) or f32(recorded) != delta:
        return f"recorded delta {recorded!r} != payload delta {delta!r}"
    if len(raw) < 16:
        return f"payload too short for the damage-kind tail ({len(raw)} B)"
    if raw[14] != 0x04:
        return (f"payload tail kind 0x{raw[14]:02x} is not the attributed "
                "COMBAT_DELTA_TAIL")
    return None


def lock_identity(record: dict) -> tuple[int, int, int] | None:
    """(target, source, kind) from a 1086 buff add, else None."""
    if record.get("opcode") != OP_BUFF_ADD:
        return None
    payload = record.get("payload", "")
    if len(payload) < 32:                      # 16 semantic bytes minimum
        return None
    target = _payload_u32(payload, 0)
    source = _payload_u32(payload, 4)
    kind = struct.unpack_from(">H", bytes.fromhex(payload), 14)[0]
    return target, source, kind


def volley_owner(record: dict) -> int | None:
    """Owner eid of a Skye C volley 1010 publication, else None."""
    if record.get("opcode") != OP_ENTITY_FULL_UPDATE:
        return None
    payload = record.get("payload", "")
    if len(payload) < 252:                     # 126 bytes
        return None
    if _payload_u32(payload, 4) != VOLLEY_CLASS:
        return None
    return _payload_u32(payload, 112)


SKYE_BASIC_SOCKETS = (0x77B4B72A, 0xB1AB2985)   # Skye LeftGun/RightGun, kind 108
SKYE_BASIC_KIND = 108
BASIC_CORRELATION_WINDOW_S = 0.5                # 1037 release -> basic impact


def projectile_identity(record: dict) -> tuple[int, int, int] | None:
    """(socket_hash, kind, source_slot) from a 1037 release, else None."""
    if record.get("opcode") != 1037:
        return None
    payload = record.get("payload", "")
    if len(payload) < 34:                      # 17 bytes minimum
        return None
    raw = bytes.fromhex(payload)
    socket_hash = struct.unpack_from(">I", raw, 4)[0]
    kind = struct.unpack_from(">H", raw, 12)[0]
    return socket_hash, kind, raw[14]


def build_fixture_contract(profile: dict, slot: str) -> dict:
    """The declared pre-cast state contract for one trial.

    Declared fields (profile ``declared_fixture``) are commitments the
    measured state must satisfy AFTER all legal preparation, BEFORE any
    input gesture. Resource policies: ``full`` = measured equals the
    actor's current maximum at validation time (a documented full-resource
    policy; differing maxima between pair runs then fail the pair gate);
    ``exact:<value>`` = measured equals the declared number.
    Anything left undeclared is ``None`` = "unknown", and an unknown field
    blocks the corresponding acceptance claim in the pair gate.

    The contract pins the SAME identity/state requirements for both
    actors: team, inventory, default_items, statuses, ranks, ability_points,
    hp, energy, coordinates. These fields are exposed by the QA snapshot
    for BOTH heroes (Skye and the enemy hero are both in
    ``world.hero_sims``); marking them "inapplicable" or omitting them
    would invent zero values that the snapshot does not provide. Only the
    energy_pool of an enemy hero that is NOT a hero (e.g. a minion) is
    inapplicable — for the current scenarios the enemy is always a hero.

    The contract is the single canonical declaration: the validator reads
    skye/enemy nested values directly, and the carried
    ``contract.declared_fixture`` MUST agree with those nested values
    (and with ``manifest.declared_fixture``).

    Complete audit of emitted contract fields (enforced vs observational):

    ENFORCED — the validator requires presence, type, and agreement with
    the measured manifest row (a missing or malformed required
    declaration is a structured FAIL, never a silent skip):
      contract.slot                     A/B/C; agrees with manifest.slot
                                        and the scenario's expected slot
      contract.skye.hero_id             == SKYE_HERO_ID; == measured
      contract.skye.eid                 == measured skye.eid
      contract.skye.team                == measured; opposing enemy.team
      contract.enemy.team               == measured; opposing skye.team
      contract.skye.level/ranks/        declared value must equal the
        ability_points                  measured row (undeclared None is
                                        itself a controlled-fixture FAIL
                                        for level/ranks/points)
      contract.enemy.level              declared must equal measured
                                        (None undeclared = FAIL)
      contract.enemy.ranks/             enforced when declared
        ability_points
      contract.{skye,enemy}.position    REQUIRED finite 2-sequence;
                                        measured placement within the
                                        declared tolerance
      contract.{skye,enemy}.            REQUIRED finite nonnegative;
        position_tolerance              equal across the two actors
      flattened skye_energy_policy/     the keys resource() actually
        skye_hp_policy/enemy_hp_policy  reads; full/exact only; exact
        (+ _exact)                      requires a finite numeric value;
                                        must agree with the nested AND
                                        declared_fixture copies

    OBSERVATIONAL — carried explicitly, never gates input, never
    compared as a declaration:
      contract.enemy.hero_id            None: the contract is built from
                                        the profile BEFORE the enemy row
                                        is measured, so the writer cannot
                                        declare it honestly. The MEASURED
                                        enemy hero_id is still required
                                        (typed int on the manifest +
                                        identified in the trial record).
                                        If a producer explicitly declares
                                        it (non-None), it is enforced
                                        against measured.
      contract.enemy.energy_policy/     None: the writer's preparation
        energy_exact                    restores enemy HP only, never
                                        enemy energy; the measured enemy
                                        energy/max_energy are still
                                        required on the manifest and
                                        pair-compared at the state gate.
      contract.placement_tolerance      reference copy of the per-actor
                                        nested tolerance (the validator
                                        reads the nested values).

    NOT contract fields — measured manifest state only, pair-compared at
    the state gate, never declared expectations: inventory,
    default_items, statuses, hp, max_hp, energy, max_energy, alive,
    x, y, cooldowns.
    """
    declared = profile.get("declared_fixture", {})
    placement_tol = profile.get(
        "placement_tolerance",
        DEFAULT_PROFILE.get("placement_tolerance", 1.5))
    # canonical contract values mirror declared_fixture exactly (None when
    # not declared) — never synthesized defaults — so the canonical
    # agreement check cannot trip on a defaulted nested value vs an
    # undeclared declared_fixture key.
    #
    # Every nested contract actor field below is an ENFORCED expectation
    # the validator compares against the measured manifest row. There are
    # NO observational defaults here: a field is either declared (its
    # value will be enforced) or absent (None = undeclared; the
    # validator does not enforce). Inventory / default_items / statuses
    # are NOT contract fields — they live only on the measured manifest
    # row and are compared at the pair level (state equality gate),
    # never as declared expectations.
    return {
        "slot": slot,
        "skye": {
            "hero_id": SKYE_HERO_ID,
            "eid": profile.get("local_player_eid", 1500),
            "team": 1,
            "level": declared.get("skye_level"),
            "ranks": declared.get("skye_ranks"),
            "ability_points": declared.get("skye_points"),
            "energy_policy": declared.get("skye_energy_policy"),
            "energy_exact": declared.get("skye_energy_exact"),
            "hp_policy": declared.get("skye_hp_policy"),
            "hp_exact": declared.get("skye_hp_exact"),
            "position_tolerance": placement_tol,
            "position": tuple(profile.get("skye_position") or ()),
        },
        "enemy": {
            # explicitly UNDECLARED (see audit in the docstring): the
            # measured enemy hero_id is required on the manifest instead
            "hero_id": None,
            "team": 2,
            "level": declared.get("enemy_level"),
            "ranks": declared.get("enemy_ranks"),
            "ability_points": declared.get("enemy_points"),
            # explicitly UNDECLARED: preparation restores enemy HP only
            "energy_policy": declared.get("enemy_energy_policy"),
            "energy_exact": declared.get("enemy_energy_exact"),
            "hp_policy": declared.get("enemy_hp_policy"),
            "hp_exact": declared.get("enemy_hp_exact"),
            "position_tolerance": placement_tol,
            "position": tuple(profile.get("enemy_position") or ()),
        },
        # flattened policy keys consumed by validate_fixture (mirror
        # declared_fixture exactly)
        "skye_energy_policy": declared.get("skye_energy_policy"),
        "skye_energy_exact": declared.get("skye_energy_exact"),
        "skye_hp_policy": declared.get("skye_hp_policy"),
        "skye_hp_exact": declared.get("skye_hp_exact"),
        "enemy_hp_policy": declared.get("enemy_hp_policy"),
        "enemy_hp_exact": declared.get("enemy_hp_exact"),
        "placement_tolerance": placement_tol,
        # the record carries the exact declaration it was validated against
        "declared_fixture": dict(declared),
    }


def validate_fixture(manifest: dict, contract: dict) -> list[str]:
    """Measured manifest vs the declared contract, applied to BOTH actors.

    Single canonical validation: the carried contract is the authoritative
    source for declared values; the manifest carries a copy of those
    declarations and the measured state. Every required identity/state
    field on both actors is checked before any comparison. A field that
    is undeclared (None), missing, of the wrong type, or non-finite is a
    structured failure — never a silently inferred zero, an assumed pass,
    or an exception.

    Type guards come first (no unsafe .get / iteration / math.dist / sum /
    float on malformed values). Then, for each actor:

      - type-guarded identity/state fields (team, hero_id, eid, level,
        ranks, ability_points, hp, max_hp, energy, max_energy, inventory,
        default_items, statuses, alive, x, y)
      - typed alive boolean (True/False, never truthy)
      - opposing teams + distinct eids (controlled-fixture invariants)
      - declared-vs-measured level, ranks, ability_points equality
      - resource policies (``full`` / ``exact``) checked against the
        ACTUAL measured value, never against an assumed default
      - declared positions REQUIRED, finite 2-sequences; measured
        placement checked within the declared tolerance

    Manifest/contract/declared_fixture copies must agree: a record
    whose ``manifest.declared_fixture.skye_level`` says 99 but whose
    ``contract.skye.level`` says 6 is structurally inconsistent and
    cannot be a controlled pair, even when the two declared_fixture
    dictionaries compare equal.
    """
    failures = []

    def finite_number(label, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            failures.append(f"{label} must be a finite number, got {value!r}")
            return False
        return True

    def finite_nonnegative(label, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value < 0:
            failures.append(f"{label} must be a finite nonnegative number, "
                            f"got {value!r}")
            return False
        return True

    # -- contract structure type guards (nested, before any .get/iter/dist) --
    if not isinstance(contract, dict):
        return [f"fixture_contract is {type(contract).__name__}, not an object"]
    contract_sk = contract.get("skye")
    contract_en = contract.get("enemy")
    if not isinstance(contract_sk, dict):
        return [f"contract.skye missing or malformed: {contract_sk!r}"]
    if not isinstance(contract_en, dict):
        return [f"contract.enemy missing or malformed: {contract_en!r}"]

    # -- contract actor field shape/type guards --
    # Every declared value the contract carries for an actor field must
    # match the producer-side shape BEFORE any equality comparison.
    # A wrong type disables the comparison (silent skip), so this guard
    # is the only place that can surface the malformed declaration.
    # Enforced: eid, hero_id, team, level, ranks, ability_points,
    # position, position_tolerance, hp_policy, hp_exact, energy_policy,
    # energy_exact, inventory. Observational metadata that does not
    # gate input: statuses, default_items (kept as lists, type-checked
    # but never compared for equality).
    def _check_contract_actor_shape(actor_label, actor_contract):
        if not isinstance(actor_contract, dict):
            return                    # already reported above
        # identity / eid / team / hero_id — must be finite int when present
        for int_field in ("eid", "hero_id", "team", "level",
                          "ability_points"):
            v = actor_contract.get(int_field)
            if v is None:
                continue              # undeclared is allowed
            if isinstance(v, bool) or not isinstance(v, int) \
                    or not math.isfinite(v):
                failures.append(f"contract {actor_label} {int_field} "
                                f"{v!r} must be a finite integer when "
                                "present")
        # ranks — dict of finite numeric values when present
        ranks = actor_contract.get("ranks")
        if ranks is not None:
            if not isinstance(ranks, dict) or any(
                    not isinstance(k, str)
                    or isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    for k, v in ranks.items()):
                failures.append(f"contract {actor_label} ranks {ranks!r} "
                                "must be a dict of string keys and finite "
                                "numeric values when present")
        # position — finite 2-sequence when present
        pos = actor_contract.get("position")
        if pos is not None:
            if not isinstance(pos, (tuple, list)) or len(pos) != 2 \
                    or not all(
                        isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) for v in pos):
                failures.append(f"contract {actor_label} position "
                                f"{pos!r} must be a finite 2-sequence when "
                                "present")
        # position_tolerance — finite nonnegative number when present
        tol = actor_contract.get("position_tolerance")
        if tol is not None:
            if isinstance(tol, bool) or not isinstance(tol, (int, float)) \
                    or not math.isfinite(tol) or tol < 0:
                failures.append(f"contract {actor_label} position_tolerance "
                                f"{tol!r} must be a finite nonnegative "
                                "number when present")
        # inventory / default_items / statuses — list when present
        for list_field in ("inventory", "default_items", "statuses"):
            v = actor_contract.get(list_field)
            if v is None:
                continue
            if not isinstance(v, list):
                failures.append(f"contract {actor_label} {list_field} "
                                f"{v!r} must be a list when present")
        # resource policy / exact — full/exact/None for policy, finite
        # number/None for exact
        for pol_field, ex_field in (("hp_policy", "hp_exact"),
                                    ("energy_policy", "energy_exact")):
            pol = actor_contract.get(pol_field)
            if pol is not None and pol not in ("full", "exact"):
                failures.append(f"contract {actor_label} {pol_field} "
                                f"{pol!r} must be full/exact/None")
            ex = actor_contract.get(ex_field)
            if ex is not None:
                if isinstance(ex, bool) or not isinstance(ex, (int, float)) \
                        or not math.isfinite(ex):
                    failures.append(f"contract {actor_label} {ex_field} "
                                    f"{ex!r} must be a finite number or None")

    _check_contract_actor_shape("skye", contract_sk)
    _check_contract_actor_shape("enemy", contract_en)

    # top-level flattened resource policy / exact must also be
    # finite-number / valid-policy — these are the keys the resource()
    # check actually reads.
    for pol_key in ("skye_energy_policy", "skye_hp_policy",
                    "enemy_hp_policy"):
        pol = contract.get(pol_key)
        if pol is not None and pol not in ("full", "exact"):
            failures.append(f"{pol_key} {pol!r} must be full/exact/None")
    for ex_key in ("skye_energy_exact", "skye_hp_exact",
                   "enemy_hp_exact"):
        ex = contract.get(ex_key)
        if ex is None:
            continue
        if isinstance(ex, bool) or not isinstance(ex, (int, float)) \
                or not math.isfinite(ex):
            failures.append(f"{ex_key} {ex!r} must be a finite number or "
                            "None")

    # -- manifest / contract / declared_fixture agreement (single canonical) --
    if not isinstance(manifest, dict):
        return [f"fixture_manifest is {type(manifest).__name__}, not an object"]
    mf_declared = manifest.get("declared_fixture")
    if not isinstance(mf_declared, dict):
        failures.append("manifest.declared_fixture missing/malformed — the "
                        "trial carries no controlled fixture declaration")
    contract_declared = contract.get("declared_fixture")
    if not isinstance(contract_declared, dict):
        failures.append("contract.declared_fixture missing/malformed — the "
                        "trial carries no controlled fixture declaration")
    if isinstance(mf_declared, dict) and isinstance(contract_declared, dict) \
            and mf_declared != contract_declared:
        failures.append("manifest.declared_fixture and contract.declared_"
                        "fixture disagree (the record and its carried "
                        "contract were not built from the same profile)")

    # -- canonical contract ↔ declared_fixture agreement --
    # The carried declared_fixture values must match the nested contract
    # values that the validator actually uses. Equal
    # manifest.declared_fixture / contract.declared_fixture dicts are
    # NOT sufficient if their nested contract values disagree. The same
    # check also covers the FLATTENED top-level keys that
    # resource() reads (skye_hp_policy / skye_hp_exact etc.) — a
    # flattened override must not disagree with the nested + declared
    # copies or with the measured state.
    if isinstance(contract_declared, dict):
        for declared_key, targets in (
                ("skye_level", [("nested", ("skye", "level"))]),
                ("enemy_level", [("nested", ("enemy", "level"))]),
                ("skye_ranks", [("nested", ("skye", "ranks"))]),
                ("enemy_ranks", [("nested", ("enemy", "ranks"))]),
                ("skye_points", [("nested", ("skye", "ability_points"))]),
                ("enemy_points", [("nested", ("enemy", "ability_points"))]),
                ("skye_energy_policy",
                 [("nested", ("skye", "energy_policy")),
                  ("flat", "skye_energy_policy")]),
                ("skye_hp_policy",
                 [("nested", ("skye", "hp_policy")),
                  ("flat", "skye_hp_policy")]),
                ("enemy_hp_policy",
                 [("nested", ("enemy", "hp_policy")),
                  ("flat", "enemy_hp_policy")]),
                ("skye_energy_exact",
                 [("nested", ("skye", "energy_exact")),
                  ("flat", "skye_energy_exact")]),
                ("skye_hp_exact",
                 [("nested", ("skye", "hp_exact")),
                  ("flat", "skye_hp_exact")]),
                ("enemy_hp_exact",
                 [("nested", ("enemy", "hp_exact")),
                  ("flat", "enemy_hp_exact")]),
        ):
            declared_value = contract_declared.get(declared_key)
            for kind, path in targets:
                if kind == "nested":
                    actor_label = path[0]
                    nested_value = contract.get(actor_label, {}).get(path[1])
                    if nested_value != declared_value:
                        failures.append(
                            f"declared_fixture.{declared_key}={declared_value!r} "
                            f"disagrees with contract.{actor_label}."
                            f"{path[1]}={nested_value!r} — declaration "
                            "copies must agree")
                elif kind == "flat":
                    flat_value = contract.get(path)
                    if flat_value != declared_value:
                        failures.append(
                            f"declared_fixture.{declared_key}={declared_value!r} "
                            f"disagrees with contract.{path}={flat_value!r} — "
                            "the flattened key the resource check actually "
                            "reads must agree")

    # -- resource policies: full / exact ONLY (no inapplicable) --
    for pol_key, ex_key in (("skye_energy_policy", "skye_energy_exact"),
                            ("skye_hp_policy", "skye_hp_exact"),
                            ("enemy_hp_policy", "enemy_hp_exact")):
        policy = contract.get(pol_key)
        if policy is None:
            failures.append(
                f"{pol_key} missing (None) — not a controlled fixture")
        elif policy not in ("full", "exact"):
            failures.append(
                f"{pol_key} {policy!r} is not full/exact (required resource "
                "policies cannot be inapplicable for an actor with that "
                "resource pool)")
        elif policy == "exact":
            exact = contract.get(ex_key)
            if exact is None or isinstance(exact, bool) \
                    or not isinstance(exact, (int, float)) \
                    or not math.isfinite(exact):
                failures.append(
                    f"{pol_key}=exact requires a finite numeric {ex_key}, "
                    f"got {exact!r}")

    # -- declared position_tolerance (finite, nonnegative, agree) --
    tol_sk = contract_sk.get("position_tolerance")
    if not finite_nonnegative("contract skye position_tolerance", tol_sk):
        tol_sk = None
    tol_en = contract_en.get("position_tolerance")
    if not finite_nonnegative("contract enemy position_tolerance", tol_en):
        tol_en = None
    if tol_sk is not None and tol_en is not None and tol_sk != tol_en:
        failures.append(f"contract skye/enemy position_tolerance differ: "
                        f"{tol_sk!r} vs {tol_en!r}")

    # -- declared positions are REQUIRED and must be finite 2-sequences --
    for actor_label, pos in (("skye", contract_sk.get("position")),
                             ("enemy", contract_en.get("position"))):
        if pos is None:
            failures.append(f"contract {actor_label} position missing — "
                            "declared placement is required")
            continue
        if not isinstance(pos, (tuple, list)) or len(pos) != 2 \
                or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in pos):
            failures.append(f"contract {actor_label} position {pos!r} must be "
                            "a finite 2-sequence")

    # -- declared ranks: must be dict[str, finite number] when declared --
    skye_decl_ranks = contract_sk.get("ranks")
    if skye_decl_ranks is None:
        pass  # the controlled-fixture check happens below
    elif not isinstance(skye_decl_ranks, dict) or any(
            not isinstance(k, str) or isinstance(v, bool)
            or not isinstance(v, (int, float)) or not math.isfinite(v)
            for k, v in skye_decl_ranks.items()):
        failures.append(f"contract skye ranks {skye_decl_ranks!r} must be a "
                        "dict of string keys and finite numeric values")
    declared_points = contract_sk.get("ability_points")
    if declared_points is not None and (
            isinstance(declared_points, bool)
            or not isinstance(declared_points, (int, float))
            or not math.isfinite(declared_points)):
        failures.append(f"contract skye ability_points {declared_points!r} "
                        "must be a finite integer/number")

    skye = manifest.get("skye")
    if not isinstance(skye, dict):
        return [f"manifest.skye missing or malformed: {skye!r}"]

    # -- contract.slot must equal scenario's expected slot --
    # validate_trial_record compares manifest.slot vs scenario; this
    # validator is reached both from the pre-input path (where scenario
    # is unknown) and from the serialized record path. The contract must
    # carry a valid slot string; if scenario is known (carried in the
    # manifest), the contract.slot must match.
    contract_slot = contract.get("slot")
    if not isinstance(contract_slot, str) or contract_slot not in (
            "A", "B", "C"):
        failures.append(f"contract.slot {contract_slot!r} is not A/B/C")
    manifest_slot = manifest.get("slot") if isinstance(manifest, dict) else None
    if manifest_slot is None:
        failures.append("manifest.slot missing — required to identify the "
                        "skill slot the contract gates")
    elif not isinstance(manifest_slot, str) or manifest_slot not in (
            "A", "B", "C"):
        failures.append(f"manifest.slot {manifest_slot!r} is not A/B/C")
    elif isinstance(contract_slot, str) and contract_slot in (
            "A", "B", "C") and manifest_slot != contract_slot:
        failures.append(f"contract.slot {contract_slot!r} != manifest.slot "
                        f"{manifest_slot!r} — the carried contract's slot "
                        "must match the manifest's slot")
    # scenario vs manifest.slot agreement: scenario is the public label
    # that pairs carry (skye-a -> A, skye-b -> B, skye-c -> C). If the
    # manifest carries a scenario string, it must agree with manifest.slot
    # and contract.slot.
    manifest_scenario = manifest.get("scenario") if isinstance(
        manifest, dict) else None
    if isinstance(manifest_scenario, str) and manifest_scenario in (
            "skye-a", "skye-b", "skye-c") \
            and isinstance(manifest_slot, str) \
            and manifest_slot in ("A", "B", "C"):
        expected_slot = SCENARIO_SLOT.get(manifest_scenario)
        if expected_slot and manifest_slot != expected_slot:
            failures.append(f"manifest.slot {manifest_slot!r} != the slot "
                            f"required by manifest.scenario "
                            f"{manifest_scenario!r} "
                            f"(expected {expected_slot!r})")
    if isinstance(manifest_scenario, str) and manifest_scenario in (
            "skye-a", "skye-b", "skye-c") \
            and isinstance(contract_slot, str) \
            and contract_slot in ("A", "B", "C"):
        expected_slot = SCENARIO_SLOT.get(manifest_scenario)
        if expected_slot and contract_slot != expected_slot:
            failures.append(f"contract.slot {contract_slot!r} != the slot "
                            f"required by manifest.scenario "
                            f"{manifest_scenario!r} "
                            f"(expected {expected_slot!r})")

    enemy = manifest.get("enemy")
    if not isinstance(enemy, dict):
        failures.append(f"manifest.enemy missing or malformed: {enemy!r}")
        enemy = {}

    # -- typed identity/state fields (no truthiness, no inferred defaults) --
    # Every typed identity/state field is REQUIRED on every controlled
    # fixture actor. A missing key is a structured FAIL: a missing
    # known-empty collection cannot equal a valid empty collection
    # (the contract must carry the prepared measured state).
    # The single exception is `ability_points`, which is legitimately
    # None in the pre-preparation snapshot — but only when the
    # contract does NOT declare a value for it. When a value is
    # declared (None = undeclared, not = declared None), the measured
    # state must carry it.
    def typed_field(actor_label, actor, field, expected_type,
                   declared_value=None, allow_none=False):
        v = actor.get(field)
        if v is None:
            if allow_none and declared_value is None:
                return None
            failures.append(
                f"manifest {actor_label} {field} is None — "
                "a missing known-empty collection cannot equal a valid "
                f"empty collection; required {expected_type.__name__}")
            return None
        if expected_type is bool:
            if not isinstance(v, bool):
                failures.append(f"manifest {actor_label} {field}={v!r} must "
                                "be a boolean")
                return None
            return v
        if expected_type is int:
            if isinstance(v, bool) or not isinstance(v, int) \
                    or not math.isfinite(v):
                failures.append(f"manifest {actor_label} {field}={v!r} must "
                                "be a finite integer")
                return None
            return v
        if expected_type is float:
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(v):
                failures.append(f"manifest {actor_label} {field}={v!r} must "
                                "be a finite number")
                return None
            return v
        if expected_type is list:
            if not isinstance(v, list):
                failures.append(f"manifest {actor_label} {field} missing or "
                                "not a list — a missing known-empty "
                                "collection cannot equal a valid empty "
                                "collection")
                return None
            return v
        if expected_type is dict:
            if not isinstance(v, dict):
                failures.append(f"manifest {actor_label} {field}={v!r} must "
                                "be a dict")
                return None
            return v
        return v

    # resolve declared values for typed_field declared-value guards
    decl_sk_points = contract_sk.get("ability_points")
    decl_en_points = contract_en.get("ability_points")

    for actor_label, actor, decl_points in (
            ("skye", skye, decl_sk_points),
            ("enemy", enemy, decl_en_points)):
        typed_field(actor_label, actor, "team", int)
        typed_field(actor_label, actor, "hero_id", int)
        typed_field(actor_label, actor, "eid", int)
        typed_field(actor_label, actor, "level", int)
        typed_field(actor_label, actor, "ranks", dict)
        # ability_points: None is the pre-preparation shape (production
        # snapshot exposes None when no economy exists). When the
        # contract declares a value (None = undeclared, not = declared
        # None), the measured state must carry that value — preparation
        # ran. Missing measured value when a declaration exists is a
        # structured FAIL, never an optional bypass.
        typed_field(actor_label, actor, "ability_points", int,
                   declared_value=decl_points, allow_none=True)
        typed_field(actor_label, actor, "hp", float)
        typed_field(actor_label, actor, "max_hp", float)
        typed_field(actor_label, actor, "energy", float)
        typed_field(actor_label, actor, "max_energy", float)
        typed_field(actor_label, actor, "inventory", list)
        typed_field(actor_label, actor, "default_items", list)
        typed_field(actor_label, actor, "statuses", list)
        typed_field(actor_label, actor, "alive", bool)
        typed_field(actor_label, actor, "x", float)
        typed_field(actor_label, actor, "y", float)

    # -- distinct eids + opposing teams + declared-vs-measured identity --
    # The controlled-fixture identity is the actor that actually exists
    # in the snapshot. Distinct eids + opposing teams remain required
    # controlled-fixture invariants.
    skye_eid = skye.get("eid") if isinstance(skye.get("eid"), int) else None
    enemy_eid = enemy.get("eid") if isinstance(enemy.get("eid"), int) else None
    skye_team = skye.get("team") if isinstance(skye.get("team"), int) else None
    enemy_team = enemy.get("team") if isinstance(enemy.get("team"), int) else None
    if skye_eid is not None and enemy_eid is not None and skye_eid == enemy_eid:
        failures.append(f"skye and enemy share eid {skye_eid} — they must be "
                        "distinct controlled-fixture actors")
    if skye_team is not None and enemy_team is not None \
            and skye_team == enemy_team:
        failures.append(f"skye and enemy share team {skye_team} — the "
                        "enemy must be on the opposing team")

    # REQUIRED declaration presence: build_fixture_contract always emits
    # these identity commitments, so a serialized record missing any of
    # them was mutated or tampered with — the declaration cannot
    # silently become optional.
    #   skye.hero_id (the client-controlled Skye), skye.eid, skye.team,
    #   enemy.team.
    # enemy.hero_id is the one explicitly UNDECLARED contract field: the
    # contract is built from the profile before the enemy row is
    # measured, so None means "not declared"; the measured enemy
    # hero_id is still required (typed_field + validate_trial_record).
    def required_identity(actor_label, field, value):
        if value is None:
            failures.append(f"contract {actor_label} {field} missing — "
                            "required identity declaration (the carried "
                            "contract always emits it)")
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            # shape already reported by _check_contract_actor_shape;
            # skip the measured comparison for a malformed declaration
            return None
        return value

    decl_sk_hero = required_identity("skye", "hero_id",
                                     contract_sk.get("hero_id"))
    decl_sk_eid = required_identity("skye", "eid", contract_sk.get("eid"))
    decl_sk_team = required_identity("skye", "team", contract_sk.get("team"))
    decl_en_team = required_identity("enemy", "team", contract_en.get("team"))
    # enemy.eid / enemy.hero_id are enforced only when declared
    decl_en_eid = contract_en.get("eid")
    if decl_en_eid is not None and (
            isinstance(decl_en_eid, bool) or not isinstance(decl_en_eid, int)):
        decl_en_eid = None      # malformed shape already reported
    decl_en_hero = contract_en.get("hero_id")
    if decl_en_hero is not None and (
            isinstance(decl_en_hero, bool)
            or not isinstance(decl_en_hero, int)):
        decl_en_hero = None     # malformed shape already reported

    # declared (contract) identity must match measured (manifest) identity
    if decl_sk_hero is not None and skye.get("hero_id") is not None \
            and decl_sk_hero != skye.get("hero_id"):
        failures.append(f"contract skye hero_id {decl_sk_hero} != measured "
                        f"skye hero_id {skye.get('hero_id')} — the "
                        "declared hero identity must match the measured "
                        "snapshot row")
    if decl_sk_eid is not None and skye_eid is not None \
            and decl_sk_eid != skye_eid:
        failures.append(f"contract skye eid {decl_sk_eid} != measured skye "
                        f"eid {skye_eid} — the controlled-fixture identity "
                        "must match the measured snapshot row")
    if decl_sk_team is not None and skye_team is not None \
            and decl_sk_team != skye_team:
        failures.append(f"contract skye team {decl_sk_team} != measured skye "
                        f"team {skye_team} — the controlled-fixture team "
                        "must match the measured snapshot row")
    if decl_en_hero is not None and enemy.get("hero_id") is not None \
            and decl_en_hero != enemy.get("hero_id"):
        failures.append(f"contract enemy hero_id {decl_en_hero} != measured "
                        f"enemy hero_id {enemy.get('hero_id')} — the "
                        "declared hero identity must match the measured "
                        "snapshot row")
    if decl_en_eid is not None and enemy_eid is not None \
            and decl_en_eid != enemy_eid:
        failures.append(f"contract enemy eid {decl_en_eid} != measured enemy "
                        f"eid {enemy_eid} — the controlled-fixture identity "
                        "must match the measured snapshot row")
    if decl_en_team is not None and enemy_team is not None \
            and decl_en_team != enemy_team:
        failures.append(f"contract enemy team {decl_en_team} != measured "
                        f"enemy team {enemy_team} — the controlled-fixture "
                        "team must match the measured snapshot row")

    # -- typed alive: must be True/False; each actor must independently be
    # alive. Both alive=False is a structured FAIL (a controlled fixture
    # requires both actors alive at validation time).
    if skye.get("alive") is False:
        failures.append("skye is not alive at validation time (alive=False)")
    if enemy.get("alive") is False:
        failures.append("enemy is not alive at validation time (alive=False)")

    # -- declared requirements: None defaults do NOT create a controlled fixture
    if contract_sk.get("level") is None:
        failures.append("skye level undeclared (None) — not a controlled "
                        "fixture")
    if contract_sk.get("ranks") is None:
        failures.append("skye ranks undeclared (None) — not a controlled "
                        "fixture")
    if contract_sk.get("ability_points") is None:
        failures.append("skye ability_points undeclared (None) — not a "
                        "controlled fixture")
    if contract_en.get("level") is None:
        failures.append("enemy level undeclared (None) — not a controlled "
                        "fixture")

    # -- declared-vs-measured equality (level, ranks, ability_points) --
    # When a value is declared, the measured state must equal it. If the
    # measured value is missing/None/non-numeric when a declaration
    # exists, that is a structured FAIL — typed_field has already
    # reported the shape problem; here we only compare when both are
    # typed integers.
    def compare_eq(actor_label, actor, field, declared_value):
        if declared_value is None:
            return
        measured = actor.get(field)
        if not isinstance(measured, int) or isinstance(measured, bool):
            return                  # typed_field already reported it
        if measured != declared_value:
            failures.append(f"{actor_label} {field} {measured} != declared "
                            f"{declared_value}")

    compare_eq("skye", skye, "level", contract_sk.get("level"))
    compare_eq("enemy", enemy, "level", contract_en.get("level"))
    compare_eq("skye", skye, "ability_points", decl_sk_points)
    compare_eq("enemy", enemy, "ability_points", decl_en_points)

    # -- declared-vs-measured ranks, BOTH actors --
    # An explicitly supplied rank expectation is enforced; undeclared
    # (None) ranks stay observational. Covers matching values, unequal
    # values, missing slots (declared key absent in measured) and extra
    # slots (measured key absent from the declaration). Malformed rank
    # values were already reported by the contract shape guard.
    def compare_ranks(actor_label, actor, declared_ranks):
        if not isinstance(declared_ranks, dict):
            return                  # None undeclared / shape reported
        measured_ranks = actor.get("ranks")
        if not isinstance(measured_ranks, dict):
            return                  # typed_field already reported it
        for key, value in declared_ranks.items():
            if measured_ranks.get(key) != value:
                failures.append(
                    f"{actor_label} rank {key} {measured_ranks.get(key)} "
                    f"!= declared {value}")
        extra = [k for k in measured_ranks if k not in declared_ranks]
        if extra:
            failures.append(
                f"{actor_label} ranks carry undeclared slots {extra}")

    compare_ranks("skye", skye, contract_sk.get("ranks"))
    compare_ranks("enemy", enemy, contract_en.get("ranks"))

    # -- resource policies against the ACTUAL measured value --
    def resource(actor_label, actor, policy_key, exact_key, measured_label):
        policy = contract.get(policy_key)
        measured = actor.get(measured_label)
        maximum = actor.get("max_" + measured_label)
        if policy is None:
            failures.append(
                f"{actor_label} {measured_label} policy undeclared (None) — "
                "not a controlled fixture")
            return
        if policy == "full":
            if not finite_number(f"{actor_label} {measured_label}",
                                 measured) or \
                    not finite_number(f"{actor_label} max_{measured_label}",
                                      maximum):
                return
            if abs(float(measured) - float(maximum)) > 1e-6:
                failures.append(
                    f"{actor_label} {measured_label} {measured} is not at its "
                    f"full {maximum} (declared full-resource policy)")
        elif policy == "exact":
            exact = contract.get(exact_key)
            if exact is None:
                failures.append(
                    f"{actor_label} {measured_label} exact policy without a "
                    "declared exact value")
            elif not finite_number(f"{actor_label} {measured_label}", measured):
                return
            elif not finite_number(f"{actor_label} {measured_label} exact",
                                   exact):
                # malformed exact (string/None/non-finite) — structured
                # FAIL, never a coerced float() that raises.
                failures.append(
                    f"{actor_label} {measured_label} exact value "
                    f"{exact!r} is not a finite number — exact policy "
                    "requires a declared finite numeric value")
            elif abs(float(measured) - float(exact)) > 1e-6:
                failures.append(
                    f"{actor_label} {measured_label} {measured} != declared "
                    f"exact {exact}")
        else:
            failures.append(
                f"{actor_label} {measured_label} unknown policy {policy!r}")

    resource("skye", skye, "skye_energy_policy", "skye_energy_exact",
             "energy")
    resource("skye", skye, "skye_hp_policy", "skye_hp_exact", "hp")
    resource("enemy", enemy, "enemy_hp_policy", "enemy_hp_exact", "hp")

    # -- statuses must be empty list (carried explicitly) --
    if isinstance(skye.get("statuses"), list) and skye.get("statuses"):
        failures.append(f"skye has active statuses/effects: "
                        f"{skye.get('statuses')}")
    if isinstance(enemy.get("statuses"), list) and enemy.get("statuses"):
        failures.append(f"enemy has active statuses/effects: "
                        f"{enemy.get('statuses')}")

    # -- declared positions vs measured placement (within tolerance) --
    def position_check(actor_label, actor, declared_pos, tolerance):
        if not declared_pos or not isinstance(declared_pos, (tuple, list)) \
                or len(declared_pos) != 2:
            return                  # position-missing already reported
        # declared_pos element type-check (defensive — the contract-level
        # check already runs, but a malformed declared position must
        # never reach math.dist below)
        for vi, vv in enumerate(declared_pos):
            if isinstance(vv, bool) or not isinstance(vv, (int, float)) \
                    or not math.isfinite(vv):
                return              # malformed already reported upstream
        # tolerance is finite_nonnegative at the top of the function; a
        # legitimate zero means the measured position must match the
        # declared position EXACTLY. Do not silently substitute 1.5.
        if tolerance is None:
            return
        x = actor.get("x"); y = actor.get("y")
        if isinstance(x, bool) or not isinstance(x, (int, float)) \
                or not math.isfinite(x) \
                or isinstance(y, bool) or not isinstance(y, (int, float)) \
                or not math.isfinite(y):
            return                  # typed_field already reported it
        distance = math.dist((x, y), declared_pos)
        if distance > tolerance:
            failures.append(
                f"{actor_label} actual position "
                f"{tuple(round(v, 3) for v in (x, y))} is "
                f"{distance:.2f}u from the declared position "
                f"{tuple(declared_pos)} (tolerance {tolerance}u)")

    position_check("skye", skye, contract_sk.get("position"), tol_sk)
    position_check("enemy", enemy, contract_en.get("position"), tol_en)

    slot = contract.get("slot")
    # contract.slot is required (and must be a string) — type-guard
    # before any dict lookup so a list/None/unknown value never reaches
    # the SKILL_SLOT_KEYS map. The earlier contract.slot/scenario
    # agreement check has already surfaced a string mismatch; here we
    # only need to defend the SKILL_SLOT_KEYS lookup.
    if not isinstance(slot, str):
        failures.append(f"contract.slot {slot!r} is not a string — the "
                        "skill-slot lookup requires a string")
    elif slot not in ("A", "B", "C"):
        failures.append(f"contract.slot {slot!r} is not A/B/C — the "
                        "skill-slot lookup requires a known slot")
    else:
        slot_key = {"A": "0", "B": "1", "C": "2"}[slot]
        cooldowns = manifest.get("cooldowns")
        if not isinstance(cooldowns, dict):
            failures.append(f"manifest.cooldowns malformed: {cooldowns!r}")
        else:
            # an absent entry means no running cooldown: 0
            remaining = cooldowns.get(slot_key, 0)
            if not isinstance(remaining, (int, float)) \
                    or not math.isfinite(remaining) or remaining != 0:
                failures.append(
                    f"slot {slot} cooldown at validation time must be exactly "
                    f"0, got {remaining!r}")
    return failures


PAIR_SCHEMA_VERSION = 4
OUTCOME_TOTAL_DECIMALS = 4
SCENARIO_SLOT = {"skye-a": "A", "skye-b": "B", "skye-c": "C"}
_HEX64 = set("0123456789abcdef")

# The census sampler's own declared schedule: the client samples the lane once
# per loop iteration, so a frame's real-time offset from the window origin is
# expected at ``index * nominal`` with ``nominal`` = the declared observation
# duration / the declared loop sample count. FIXTURE_SAMPLING_MARGIN_S is how
# far a frame's real-time offset may sit from that declared schedule (and,
# between two records, from the other record's offset) before the two
# observations stop being treated as the same sampling schedule.
#
# CALIBRATION SCOPE — FIXTURE ONLY. The number comes from the four independent
# productions ONE writer recorded on 2026-09-12 (worst deviation from the
# declared 1.0s cadence: 0.0086s). It is a decision threshold for
# fixture-shaped observations, NOT production measurement uncertainty: no
# device, emulator or real transport was measured, and the instants are not
# even simultaneous on the offline path — the server stamps the world clock
# when it SERVES a request and the client receives the reply afterwards (an
# offline in-process bracket is measured in this correction's evidence; no
# live bracket exists). Every pair report therefore carries
# ``live_sampling_equivalence: UNVERIFIED`` and says so. The elapsed
# SIMULATION clock is never compared with this margin: the carried simulation
# clock is compared EXACTLY, per census frame index.
FIXTURE_SAMPLING_MARGIN_S = 0.100
FIXTURE_CALIBRATION_PRODUCTIONS = 4
FIXTURE_CALIBRATION_WORST_DEVIATION_S = 0.0086
# Measured 2026-09-12 on the OFFLINE in-process real-QA path (the real
# SandboxQA service over the real mailbox; no device, no emulator, no network)
# by this correction's measure_qa_bracket.py. REPORTED FOR TRANSPARENCY ONLY —
# these numbers are never applied as margins in any decision here:
#  * 50 back-to-back requests: the client's receipt of a QA reply followed the
#    server's own service instant by 0.038s at the median and 0.0486s at the
#    worst (the 0.05s mailbox poll quantum dominates; the handler itself took
#    0.00009s at the median), so the instants are provably NOT simultaneous
#    even offline;
#  * a census-shaped 9-frame window at the declared 1.0s cadence deviated from
#    that cadence by 0.4515s at its worst frame — 52x the fixture calibration
#    above, i.e. the fixture margin does NOT transfer even to the offline real
#    path, which is why an out-of-margin deviation is refused as NOT
#    ESTABLISHED instead of being called a violation of a production bound.
OFFLINE_QA_BRACKET_MEDIAN_S = 0.038
OFFLINE_QA_BRACKET_MAX_S = 0.0486
OFFLINE_QA_BRACKET_REQUESTS = 50
OFFLINE_QA_CENSUS_WORST_DEVIATION_S = 0.4515
OFFLINE_QA_BRACKET_SOURCE = (
    "the offline in-process real SandboxQA service over the real mailbox, "
    "measured 2026-09-12 by measure_qa_bracket.py in the typed-clock-scope "
    "correction's evidence (no device, no emulator, no network)")
# The largest tick whose product with a tick rate is exactly representable as
# a float. Beyond 2**53 the record's own tick/time relation cannot be checked
# in float arithmetic at all — Python raises OverflowError converting such an
# int — so the entry is refused as a typed failure instead of being multiplied.
MAX_CLOCK_TICK = 2 ** 53
CLOCK_RATE_RELATIVE_EPSILON = 1e-12
CLOCK_RATE_ABSOLUTE_EPSILON = 1e-9


def _clock_epsilon(value) -> float:
    """Float-representation epsilon for a record's own tick/time relation.

    NOT a timing allowance: ``sim_time = tick * rate`` is exact arithmetic, and
    this only absorbs the round trip of both numbers through JSON float
    formatting. It is orders of magnitude below one tick.
    """
    return max(CLOCK_RATE_ABSOLUTE_EPSILON,
               abs(value) * CLOCK_RATE_RELATIVE_EPSILON)


def _is_hex64(value):
    return (isinstance(value, str) and len(value) == 64
            and all(ch in _HEX64 for ch in value))


def collect_linkage_field_failures(linkage):
    """Typed field checks for a diagnostics linkage object.

    SHARED by the live setup boundary (``ClientDriver._validate_diag_linkage``,
    which raises) and the serialized record validator (which collects). One
    definition means the receipt accepted at setup is exactly the receipt the
    pair gate re-reads; the two can never drift apart.

    Required: an integer pid, a finite startup_at, a non-empty match_id, an
    ACTIVE ``world`` phase, ``match_finished`` False, an integer tick and a
    finite time. Returns field-specific failure strings; never raises and
    never substitutes a default for a missing value.
    """
    if not isinstance(linkage, dict):
        return [f"linkage is {type(linkage).__name__}, not an object"]
    failures = []
    pid = linkage.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        failures.append(f"pid {pid!r} is not an integer")
    startup_at = linkage.get("startup_at")
    if isinstance(startup_at, bool) or not isinstance(startup_at, (int, float)) \
            or not math.isfinite(startup_at):
        failures.append(f"startup_at {startup_at!r} is not a finite number")
    match_id = linkage.get("match_id")
    if not isinstance(match_id, str) or not match_id:
        failures.append(f"match_id {match_id!r} is not a non-empty string")
    phase = linkage.get("phase")
    if phase != "world":
        failures.append(f"phase {phase!r} is not an active WORLD session")
    finished = linkage.get("match_finished")
    if finished is not False:
        failures.append(f"match_finished {finished!r} is not False — the "
                        "match has ended or the state is unknown")
    tick = linkage.get("tick")
    if not isinstance(tick, int) or isinstance(tick, bool):
        failures.append(f"tick {tick!r} is not an integer")
    sim_time = linkage.get("time")
    if isinstance(sim_time, bool) or not isinstance(sim_time, (int, float)) \
            or not math.isfinite(sim_time):
        failures.append(f"time {sim_time!r} is not a finite number")
    return failures


def validate_diagnostics_linkage(linkage, manifest):
    """Record-side validation of ``provenance.diagnostics``.

    The typed process/startup/session linkage must be coherent INSIDE its own
    trial: typed fields as above, plus agreement between the receipt's
    match_id and this record's own ``fixture_manifest.match_id`` (the fixture
    the trial measured). Fresh-session identity — pid, startup_at, match_id,
    tick and time — is deliberately NOT compared across a pair: two trials
    legitimately come from different processes/matches, so each record is
    judged on its own coherence only.
    """
    failures = collect_linkage_field_failures(linkage)
    manifest_match = manifest.get("match_id") if isinstance(manifest, dict) \
        else None
    if not isinstance(manifest_match, str) or not manifest_match:
        failures.append(
            f"fixture_manifest.match_id {manifest_match!r} is not a non-empty "
            "string — the diagnostics linkage cannot be tied to this trial")
    elif isinstance(linkage, dict) and linkage.get("match_id") != manifest_match:
        failures.append(
            f"diagnostics match_id {linkage.get('match_id')!r} != "
            f"fixture_manifest match_id {manifest_match!r} — the receipt and "
            "the measured fixture are not the same match")
    return failures


TRACE_ENV_KEY = "HALCYON_TRACE_WIRE"
# Comparison tokens for the trace ENABLE SWITCH. Deliberately not booleans:
# Python treats True == 1, which let a malformed numeric value collide with a
# valid enabled string in an earlier form of this normalizer.
_TRACE_ENABLED = "trace-switch:enabled"
_TRACE_DISABLED = "trace-switch:disabled"


def normalize_env_config(env_config):
    """Comparison form of a recorded diagnostics ``env`` object.

    ``HALCYON_TRACE_WIRE`` is an ENABLE SWITCH. Production
    (``server/match_server.py``: ``if os.environ.get("HALCYON_TRACE_WIRE")``)
    reads only its truthiness — any non-empty value enables the local wire
    trace — and the server then generates its own ``wire-<time_ns>.jsonl``
    destination, so the recorded string is the switch setting rather than
    necessarily the file actually written. Two enabled trials therefore
    compare equal whatever their recorded values.

    This reduces that one entry to an explicit enable/disable TOKEN, so a
    valid non-empty string can never collide with a malformed number (an
    earlier form used booleans, where ``True == 1`` produced a false PASS).
    Every other entry — including the simulation flags ``HALCYON_NO_BOTS`` /
    ``HALCYON_NO_TAPE`` / ``HALCYON_NO_WAVE`` — keeps its exact recorded
    value, so unrelated configuration differences still fail.

    Scope and honesty notes: a PRESENT value that is neither ``None`` nor a
    string is malformed receipt evidence — ``validate_trial_record`` rejects
    it per record, and here it is carried verbatim (never coerced, never
    defaulted) so it can never compare equal to an enable token. An ABSENT
    key stays ABSENT: absence is not a recorded disabled value, and the two
    are never equated. Raw records are never rewritten; the raw values remain
    in each serialized record and in the pair verdict.
    """
    if not isinstance(env_config, dict):
        return env_config
    normalized = {}
    for key, value in env_config.items():
        if key == TRACE_ENV_KEY and (value is None or isinstance(value, str)):
            normalized[key] = _TRACE_ENABLED if value else _TRACE_DISABLED
        else:
            normalized[key] = value
    return normalized


def _receipt_connection_check(label, receipt, trial_connection, failures):
    """A receipt must have been observed on THIS trial's connection."""
    if receipt.get("connection") != trial_connection:
        failures.append(
            f"{label}.connection {receipt.get('connection')!r} != the trial "
            f"connection {trial_connection!r} — a receipt observed on another "
            "session cannot establish this cast")


def _receipt_payload_check(label, receipt, failures):
    """The hex wire payload a receipt carries, or None when it is not carried.

    A receipt without its own bytes leaves only copied action/eid metadata,
    which is not independently bound to anything the wire showed.
    """
    payload = receipt.get("payload")
    if not isinstance(payload, str) or not payload:
        failures.append(
            f"{label}.payload {payload!r} is missing or not a hex string — the "
            "receipt's own wire bytes are not carried, so its action/eid "
            "metadata cannot bind itself to an observed packet")
        return None
    try:
        bytes.fromhex(payload)
    except ValueError:
        failures.append(f"{label}.payload is not hexadecimal: {payload!r}")
        return None
    return payload


def _receipt_window_check(label, when, window_ok, window_start, window_end,
                          failures):
    """The receipts that establish a cast must lie in the driver's OWN window.

    The window is the production observation window the driver recorded for
    this cast: it opens at the observed input and closes when the driver
    classified the effect. A receipt timestamped outside it cannot establish
    the cast, and nothing here invents a timing tolerance on top of the window
    the driver itself measured.
    """
    if not window_ok:
        return
    if not window_start <= when <= window_end:
        failures.append(
            f"{label}.time {when} is outside the observed action window "
            f"[{window_start}, {window_end}] — a receipt observed outside the "
            "window the driver measured cannot establish this cast")


def collect_skye_cast_causal_failures(result, manifest, slot):
    """Serialized CAUSAL coherence of one Skye cast trial's carried evidence.

    The input, the acknowledgment, the cooldown-timer receipt and the
    attributed damage must describe ONE action by ONE actor on ONE connection
    inside the observed action window — the same facts the live driver used
    to classify the stages, re-checked from the serialized record alone.
    Each receipt must additionally carry the wire bytes it was matched on, and
    those bytes must parse (with the same parsers the driver matched with) to
    the very action/actor/tag the metadata claims; a receipt outside the
    window the driver recorded for this cast establishes nothing.

    Nothing here re-derives the outcome: the counts and the four-decimal
    total are checked against the carried attribution EXACTLY, with no
    tolerance, no percentage, and no invented default for a missing field.

    ONE checker for the slots whose writer semantics are the same
    (``slot`` in A/B): ``ClientDriver.run_cast_scenario`` captures the input
    (``wait_client_input``), the acknowledgment (``wait_acknowledgment``), the
    timer receipt (``wait_cooldown_tag``) and the effect window
    (``classify_damage(window_start=cast_time)``) identically for every cast
    slot, so the only slot-specific values are the native action and timer tag
    passed in here. The one capture difference — B and C additionally require
    an observed Target Lock, A does not (``requires_lock=slot in ("B", "C")``)
    — is deliberately NOT checked here, so no B-only lock requirement is
    imported into A.

    Bounded slice: slots A, B and C are checked by the caller, which routes C's
    additional volley-publication evidence to ``collect_skye_c_volley_failures``
    (a publication count is not publication evidence). The minion window needs
    its own causal slice and is NOT claimed here.

    Returns a list of reason strings; [] only when every linkage is present
    and mutually coherent.
    """
    failures: list[str] = []
    if slot not in SKYE_NATIVE_ACTIONS:
        return [f"unknown cast slot {slot!r} — no native action/timer tag to "
                "bind this record against"]
    if not isinstance(result, dict):
        return ["record is not an object"]
    if not isinstance(manifest, dict):
        return ["fixture_manifest missing/malformed — the trial's actor and "
                "connection cannot be identified"]
    observations = result.get("observations")
    if not isinstance(observations, dict):
        return ["observations missing/malformed — the causal evidence is "
                "not carried"]
    skye = manifest.get("skye")
    enemy = manifest.get("enemy")
    hero_eid = skye.get("eid") if isinstance(skye, dict) else None
    enemy_eid = enemy.get("eid") if isinstance(enemy, dict) else None
    action = SKYE_NATIVE_ACTIONS[slot]
    tag = f"{SKYE_COOLDOWN_TAGS[slot]:08x}"

    # -- the trial's connection: the record's own and the manifest's --------
    trial_connection = result.get("connection")
    manifest_connection = manifest.get("connection")
    if isinstance(trial_connection, bool) or \
            not isinstance(trial_connection, int):
        failures.append(
            f"record.connection {trial_connection!r} is not an integer "
            "connection id")
    elif manifest_connection != trial_connection:
        failures.append(
            f"manifest.connection {manifest_connection!r} != record "
            f"connection {trial_connection!r} — the fixture and the "
            "observation are not the same session")

    # -- the observed action window ----------------------------------------
    # Read BEFORE the receipts: the acknowledgment and the timer receipt are
    # judged against the very window the driver recorded for this cast, so a
    # receipt moved past the window's end can never establish the cast.
    classification = observations.get("damage_classification")
    if not isinstance(classification, dict):
        failures.append("damage_classification missing or not an object")
        classification = {}
    window = classification.get("window")
    window_ok = False
    window_start = window_end = None
    if not isinstance(window, (list, tuple)) or len(window) != 2 \
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in window):
        failures.append(
            f"damage_classification.window {window!r} is not a pair of finite "
            "numbers — the outcome window is not carried")
    else:
        window_start, window_end = float(window[0]), float(window[1])
        if window_end <= window_start:
            failures.append(
                f"the observed action window [{window_start}, {window_end}] "
                "does not advance")
        else:
            window_ok = True

    # -- the client input ---------------------------------------------------
    client_input = observations.get("client_input")
    input_time = None
    if not isinstance(client_input, dict):
        failures.append(
            f"client_input {client_input!r} is missing or not an object — "
            f"no observed {slot} input to attribute the outcome to")
    else:
        input_action = client_input.get("action")
        if input_action != action:
            failures.append(
                f"client_input.action {input_action!r} != the {slot} native "
                f"action {action} — the recorded input is not this skill")
        if client_input.get("connection") != trial_connection:
            failures.append(
                f"client_input.connection {client_input.get('connection')!r} "
                f"!= the trial connection {trial_connection!r} — input and "
                "outcome evidence come from different sessions")
        payload = _receipt_payload_check("client_input", client_input, failures)
        if payload is not None:
            wire_action = ground_cast_action(
                {"opcode": OP_GROUND_CAST, "payload": payload})
            if wire_action != input_action:
                failures.append(
                    f"client_input.payload action {wire_action!r} != the "
                    f"recorded action {input_action!r} — the receipt's own "
                    "bytes do not carry this action")
        input_time = client_input.get("time")
        if isinstance(input_time, bool) or \
                not isinstance(input_time, (int, float)) or \
                not math.isfinite(input_time):
            failures.append(
                f"client_input.time {input_time!r} is not a finite number")
            input_time = None
        elif window_ok and window_start != input_time:
            # The driver's own relationship, taken from the shared cast path
            # (run_cast_scenario): the window it classifies the effect over is
            # opened exactly at the c2s input record it observed
            # (window_start = cast_time = client_input["time"]). An input
            # timestamp moved either way therefore re-dates the cast against
            # evidence that was measured at the real instant; no tolerance is
            # applied to that equality.
            failures.append(
                f"the observed action window opens at {window_start}, not at "
                f"the recorded input {input_time} — this driver's window opens "
                "exactly at the c2s input it observed, so an input shifted "
                "earlier or later than the window start is not this cast's "
                "input")

    # -- the acknowledgment (s2c 1046 for the same action) ------------------
    acknowledgment = observations.get("acknowledgment")
    ack_time = None
    if not isinstance(acknowledgment, dict):
        failures.append(
            f"acknowledgment {acknowledgment!r} is missing or not an object "
            f"— the {slot} cast was never acknowledged")
    else:
        ack_action = acknowledgment.get("action")
        if ack_action != action:
            failures.append(
                f"acknowledgment.action {ack_action!r} != the {slot} native "
                f"action {action} — acknowledgment and input are different "
                "actions")
        _receipt_connection_check("acknowledgment", acknowledgment,
                                  trial_connection, failures)
        payload = _receipt_payload_check("acknowledgment", acknowledgment,
                                         failures)
        if payload is not None:
            wire_action = position_event_action(
                {"opcode": OP_POSITION_EVENT, "payload": payload})
            if wire_action != ack_action:
                failures.append(
                    f"acknowledgment.payload action {wire_action!r} != the "
                    f"recorded action {ack_action!r} — the receipt's own bytes "
                    "do not carry this action")
            if len(bytes.fromhex(payload)) < 4:
                failures.append(
                    "acknowledgment.payload is too short to carry the "
                    "acknowledged eid (offset 0)")
            else:
                wire_eid = _payload_u32(payload, 0)
                if wire_eid != hero_eid:
                    failures.append(
                        f"acknowledgment.payload eid {wire_eid} != the trial "
                        f"hero {hero_eid!r} — the receipt's own bytes do not "
                        "name this actor")
        ack_time = acknowledgment.get("time")
        if isinstance(ack_time, bool) or \
                not isinstance(ack_time, (int, float)) or \
                not math.isfinite(ack_time):
            failures.append(
                f"acknowledgment.time {ack_time!r} is not a finite number")
            ack_time = None
        else:
            if input_time is not None and ack_time < input_time:
                failures.append(
                    f"acknowledgment.time {ack_time} precedes the observed "
                    f"input {input_time} — an acknowledgment cannot cause its "
                    "own input")
            _receipt_window_check("acknowledgment", ack_time, window_ok,
                                  window_start, window_end, failures)

    # -- the cooldown-timer receipt: this ACTOR's native tag ----------------
    cooldown_tag = observations.get("cooldown_tag")
    tag_time = None
    if not isinstance(cooldown_tag, dict):
        failures.append(
            f"cooldown_tag {cooldown_tag!r} is missing or not an object — a "
            "cast with no timer receipt has no acknowledgment evidence")
    else:
        if cooldown_tag.get("slot") != slot:
            failures.append(
                f"cooldown_tag.slot {cooldown_tag.get('slot')!r} != {slot!r}")
        if cooldown_tag.get("tag") != tag:
            failures.append(
                f"cooldown_tag.tag {cooldown_tag.get('tag')!r} != the native "
                f"{slot} timer tag {tag!r} — another ability's timer is not "
                "this cast's evidence")
        # A slot-only timer tag must never establish the cast: the receipt
        # has to be bound to the trial's own actor.
        tag_eid = cooldown_tag.get("eid")
        if tag_eid is None:
            failures.append(
                "cooldown_tag is slot-only (no eid): a timer tag not bound to "
                "the trial actor can never establish this hero's cast")
        elif tag_eid != hero_eid:
            failures.append(
                f"cooldown_tag.eid {tag_eid!r} != the trial hero "
                f"{hero_eid!r} — another actor's timer was carried as this "
                "cast's acknowledgment")
        _receipt_connection_check("cooldown_tag", cooldown_tag,
                                  trial_connection, failures)
        payload = _receipt_payload_check("cooldown_tag", cooldown_tag, failures)
        if payload is not None:
            identity = timer_tag_eid(
                {"opcode": OP_TIMER_TICK, "payload": payload})
            if identity is None:
                failures.append(
                    "cooldown_tag.payload does not parse as a 1162 timer "
                    "receipt (eid @0, tag @4) — the receipt's own bytes are "
                    "not the timer it claims to be")
            else:
                wire_eid, wire_tag = identity
                if wire_eid != hero_eid:
                    failures.append(
                        f"cooldown_tag.payload eid {wire_eid} != the trial "
                        f"hero {hero_eid!r} — the receipt's own bytes do not "
                        "name this actor")
                if f"{wire_tag:08x}" != tag:
                    failures.append(
                        f"cooldown_tag.payload tag {wire_tag:08x} != the "
                        f"native {slot} timer tag {tag!r} — the receipt's own "
                        "bytes carry a different timer")
        tag_time = cooldown_tag.get("time")
        if isinstance(tag_time, bool) or \
                not isinstance(tag_time, (int, float)) or \
                not math.isfinite(tag_time):
            failures.append(
                f"cooldown_tag.time {tag_time!r} is not a finite number")
            tag_time = None
        else:
            if ack_time is not None and tag_time < ack_time:
                failures.append(
                    f"cooldown_tag.time {tag_time} precedes the acknowledgment "
                    f"{ack_time} — a timer receipt cannot precede its own cast")
            _receipt_window_check("cooldown_tag", tag_time, window_ok,
                                  window_start, window_end, failures)

    # -- the attributed damage: same actor pair, same connection, in window --
    attributed = classification.get("attributed")
    if not isinstance(attributed, list) or not attributed:
        failures.append(
            "no attributed damaging events recorded — an empty or missing "
            "attribution cannot satisfy the effect")
        attributed = []
    totals = []
    for index, hit in enumerate(attributed):
        if not isinstance(hit, dict):
            failures.append(f"attributed[{index}] is not an object: {hit!r}")
            continue
        if hit.get("connection") != trial_connection:
            failures.append(
                f"attributed[{index}].connection {hit.get('connection')!r} != "
                f"the trial connection {trial_connection!r} — damage from "
                "another session was carried as this trial's outcome")
        when = hit.get("time")
        if isinstance(when, bool) or not isinstance(when, (int, float)) or \
                not math.isfinite(when):
            failures.append(
                f"attributed[{index}].time {when!r} is not a finite number")
        elif window_ok and not window_start <= when <= window_end:
            failures.append(
                f"attributed[{index}].time {when} is outside the observed "
                f"action window [{window_start}, {window_end}] — unrelated "
                "damage cannot establish this cast's outcome")
        # actor binding: the event's own payload must identify this trial's
        # attacker -> victim pair (the shared payload checker)
        wrong = payload_backs_hit(hit, hero_eid, enemy_eid)
        if wrong:
            failures.append(f"attributed[{index}] actor binding: {wrong}")
        delta = hit.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)) or \
                not math.isfinite(delta):
            continue
        totals.append(delta)

    # -- the carried outcome summary: exact counts and exact total ----------
    outcome = observations.get("outcome")
    if not isinstance(outcome, dict):
        failures.append(
            f"outcome {outcome!r} is missing or not an object — the record "
            "carries no summary of its own attribution")
    else:
        recorded_count = outcome.get("attributed_events")
        if recorded_count != len(attributed):
            failures.append(
                f"outcome.attributed_events {recorded_count!r} != the carried "
                f"attribution's {len(attributed)} event(s)")
        recorded_total = outcome.get("outcome_total")
        expected_total = round(sum(totals), OUTCOME_TOTAL_DECIMALS)
        if isinstance(recorded_total, bool) or \
                not isinstance(recorded_total, (int, float)) or \
                not math.isfinite(recorded_total):
            failures.append(
                f"outcome.outcome_total {recorded_total!r} is not a finite "
                "number")
        elif recorded_total != expected_total:
            failures.append(
                f"outcome.outcome_total {recorded_total!r} != the attributed "
                f"total {expected_total!r} at {OUTCOME_TOTAL_DECIMALS} "
                "decimals — an edited total is not a measured outcome")
    return failures


def collect_skye_c_volley_failures(result, manifest):
    """The skye-c volley PUBLICATIONS carried by one trial, re-derived.

    What this establishes: which actor published the volley, that the
    published entity is the C volley class, on which connection, and when —
    all read back out of the publication's own 1010 bytes with the same
    parser the driver matched with (``volley_owner``: class at offset 4, owner
    at offset 112), plus agreement between the carried count and the carried
    publications.

    What this does NOT establish, and must not be read as: that a publication
    CAUSED the attributed damage. No per-publication <-> per-pulse identity is
    carried anywhere in this record, so the damage evidence remains exactly
    what it was — the payload-backed 1054 attribution with its exact event
    count and four-decimal total. A publication binds the volley's publisher,
    class, session and instant; it is not a damage proof, and no linkage
    beyond the carried bytes is invented here.

    Timing uses the driver's own observation window for this cast (the window
    that opens at the observed c2s input and closes when the driver classified
    the effect) — the same rule the input/acknowledgment/timer receipts and
    the attributed damage are held to. The C capture step itself selects
    publications at or after the cast, with no upper bound, so a publication
    observed only after that window is a real finding rather than something
    this checker tolerates.

    The window is read defensively: a malformed window is reported by the
    shared cast checker, and this function does not pile a second, differently
    worded failure on top of it.

    Returns a list of reason strings; [] only when the publications are
    present, mutually consistent and bound to this trial.
    """
    failures: list[str] = []
    if not isinstance(result, dict):
        return ["record is not an object"]
    if not isinstance(manifest, dict):
        return ["fixture_manifest missing/malformed — the trial's actor and "
                "connection cannot be identified"]
    observations = result.get("observations")
    if not isinstance(observations, dict):
        return ["observations missing/malformed — the causal evidence is "
                "not carried"]
    skye = manifest.get("skye")
    hero_eid = skye.get("eid") if isinstance(skye, dict) else None

    trial_connection = result.get("connection")
    if isinstance(trial_connection, bool) or \
            not isinstance(trial_connection, int):
        failures.append(
            f"record.connection {trial_connection!r} is not an integer "
            "connection id")

    classification = observations.get("damage_classification")
    window = (classification.get("window")
              if isinstance(classification, dict) else None)
    window_ok, window_start, window_end = False, None, None
    if isinstance(window, (list, tuple)) and len(window) == 2 and not any(
            isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) for v in window):
        window_start, window_end = float(window[0]), float(window[1])
        window_ok = window_end > window_start

    count = observations.get("volley_actors")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        failures.append(
            f"volley_actors {count!r} is not a positive integer — a C trial "
            "with no counted volley actor publication has no volley evidence")
    publications = observations.get("volley_publications")
    if not isinstance(publications, list) or not publications:
        failures.append(
            f"volley_publications {publications!r} is missing, not a list or "
            "empty — a bare count cannot establish who published the volley, "
            "on what connection or when")
        return failures
    if isinstance(count, int) and not isinstance(count, bool) \
            and count != len(publications):
        failures.append(
            f"volley_actors {count} != the {len(publications)} carried "
            "publication(s) — the count and the carried publications disagree")

    for index, publication in enumerate(publications):
        label = f"volley_publications[{index}]"
        if not isinstance(publication, dict):
            failures.append(f"{label} is not an object: {publication!r}")
            continue
        payload = publication.get("payload")
        if not isinstance(payload, str) or not payload:
            failures.append(
                f"{label}.payload {payload!r} is missing or not a hex string "
                "— the publication's own wire bytes are not carried, so its "
                "owner/class metadata cannot bind itself to an observed packet")
            continue
        try:
            raw = bytes.fromhex(payload)
        except ValueError:
            failures.append(f"{label}.payload is not hexadecimal: {payload!r}")
            continue
        # The declared publication shape is a 126-BYTE entity record, and the
        # parser reads the class at offset 4 and the owner at offset 112. This
        # guard therefore counts DECODED bytes: ``bytes.fromhex`` ignores
        # whitespace, so a whitespace-padded payload ('00' + 252 spaces) passes
        # any character-count check while decoding to a single byte, and the
        # owner read would then raise out of the public CLI instead of failing
        # this record. Reject such a payload here, before any parser read.
        if len(raw) < VOLLEY_PUBLICATION_BYTES:
            padding = (" — whitespace-padded, so its character count is not "
                       "its byte count" if any(ch.isspace() for ch in payload)
                       else "")
            failures.append(
                f"{label}.payload decodes to {len(raw)} byte(s){padding}, "
                f"fewer than the {VOLLEY_PUBLICATION_BYTES}-byte C volley "
                "publication shape (class @4, owner @112) — the owner read "
                "would run past the carried bytes")
            continue
        wire_class = struct.unpack_from(">I", raw, 4)[0]
        if wire_class != VOLLEY_CLASS:
            failures.append(
                f"{label}.payload class {wire_class:08x} != the C volley "
                f"class {VOLLEY_CLASS:08x} — the receipt's own bytes are not "
                "this volley")
            continue
        owner = volley_owner({"opcode": OP_ENTITY_FULL_UPDATE,
                              "payload": payload})
        if owner is None:
            failures.append(
                f"{label}.payload does not parse as a 1010 volley publication "
                "(class @4, owner @112) — the receipt's own bytes are not the "
                "publication it claims to be")
            continue
        if owner != hero_eid:
            failures.append(
                f"{label}.payload owner {owner} != the trial hero {hero_eid!r} "
                "— the receipt's own bytes name another actor as the "
                "publisher")
        if publication.get("connection") != trial_connection:
            failures.append(
                f"{label}.connection {publication.get('connection')!r} != the "
                f"trial connection {trial_connection!r} — a publication from "
                "another session was carried as this trial's volley evidence")
        when = publication.get("time")
        if isinstance(when, bool) or not isinstance(when, (int, float)) \
                or not math.isfinite(when):
            failures.append(f"{label}.time {when!r} is not a finite number")
        elif window_ok and not window_start <= when <= window_end:
            failures.append(
                f"{label}.time {when} is outside the observed action window "
                f"[{window_start}, {window_end}] — a publication observed "
                "outside the window the driver measured cannot establish this "
                "cast's volley")
    return failures


def collect_trial_continuity_failures(initial, end):
    """One trial's initial and end-of-trial endpoint receipts, compared.

    Within a SINGLE trial the endpoint receipt must come from the same
    process, the same startup and the same match, both endpoints must be an
    ACTIVE, unfinished WORLD session, and the simulation must have strictly
    advanced (tick and time) between them. Fresh identities legitimately
    differ across SEPARATE trials and are never compared across a pair.

    Returns [] when either linkage is missing or malformed: those defects are
    reported per endpoint by ``validate_diagnostics_linkage``, and comparing
    untyped values would be a fabricated judgment.
    """
    if not isinstance(initial, dict) or not isinstance(end, dict):
        return []
    if collect_linkage_field_failures(initial) \
            or collect_linkage_field_failures(end):
        return []
    failures = []
    for field in ("pid", "startup_at", "match_id"):
        if initial[field] != end[field]:
            failures.append(
                f"{field} changed within the trial: {initial[field]!r} -> "
                f"{end[field]!r} — the process or match restarted mid-trial")
    if end["tick"] <= initial["tick"]:
        failures.append(
            f"tick did not strictly advance: {initial['tick']} -> "
            f"{end['tick']} (a stalled or regressing simulation is not a "
            "live trial)")
    if end["time"] <= initial["time"]:
        failures.append(
            f"simulation time did not strictly advance: {initial['time']} -> "
            f"{end['time']}")
    return failures


def validate_contract_structure(contract):
    """Structural validation of a carried fixture contract. Returns failures.

    Type guards come first. Then every nested field is checked for the
    correct shape (finite number, dict of finite numbers, 2-tuple of finite
    numbers, list, etc.) BEFORE any .get / iteration / math.dist / float()
    conversion. A missing or wrongly-typed field is a structured failure —
    never an exception, never a silently coerced default.

    Resource policies are full/exact ONLY — ``inapplicable`` is not a
    legal policy value for any actor with that resource pool (Skye HP,
    Skye energy, enemy hero HP all qualify).
    """
    failures = []
    if not isinstance(contract, dict):
        return [f"fixture_contract is {type(contract).__name__}, not an object"]
    skye = contract.get("skye")
    enemy = contract.get("enemy")
    if not isinstance(skye, dict):
        return [f"fixture_contract.skye missing or malformed: {skye!r}"]
    if not isinstance(enemy, dict):
        return [f"fixture_contract.enemy missing or malformed: {enemy!r}"]
    for key in ("slot", "skye_energy_policy", "skye_hp_policy",
                "enemy_hp_policy", "declared_fixture"):
        if key not in contract:
            failures.append(f"fixture_contract missing {key!r}")
    slot = contract.get("slot")
    if not isinstance(slot, str) or slot not in ("A", "B", "C"):
        failures.append(f"fixture_contract.slot {slot!r} is not A/B/C")
    for key in ("skye_energy_policy", "skye_hp_policy",
                "enemy_hp_policy"):
        policy = contract.get(key)
        if policy not in ("full", "exact"):
            failures.append(f"{key} {policy!r} is not full/exact")
        if policy == "exact":
            exact_key = key.replace("_policy", "_exact")
            exact = contract.get(exact_key)
            if isinstance(exact, bool) or not isinstance(exact, (int, float)) \
                    or not math.isfinite(exact):
                failures.append(
                    f"{key} is exact but {exact_key}={exact!r} is not a "
                    "finite number")

    # declared ranks must be dict[str, finite number]
    skye_decl_ranks = skye.get("ranks")
    if skye_decl_ranks is not None:
        if not isinstance(skye_decl_ranks, dict):
            failures.append(f"fixture_contract.skye.ranks {skye_decl_ranks!r} "
                            "must be a dict")
        else:
            for rk, rv in skye_decl_ranks.items():
                if not isinstance(rk, str):
                    failures.append(f"fixture_contract.skye.ranks key "
                                    f"{rk!r} must be a string")
                elif isinstance(rv, bool) or not isinstance(rv, (int, float)) \
                        or not math.isfinite(rv):
                    failures.append(f"fixture_contract.skye.ranks[{rk!r}] "
                                    f"{rv!r} must be a finite number")

    # declared level/ability_points must be finite numbers
    for actor_label, actor in (("skye", skye), ("enemy", enemy)):
        lvl = actor.get("level")
        if lvl is not None and (
                isinstance(lvl, bool) or not isinstance(lvl, (int, float))
                or not math.isfinite(lvl)):
            failures.append(f"fixture_contract.{actor_label}.level "
                            f"{lvl!r} must be a finite number or None")
    pts = skye.get("ability_points")
    if pts is not None and (
            isinstance(pts, bool) or not isinstance(pts, (int, float))
            or not math.isfinite(pts)):
        failures.append(f"fixture_contract.skye.ability_points {pts!r} "
                        "must be a finite number or None")

    # declared positions are REQUIRED, finite 2-sequences (tuple or list)
    for actor_label, pos in (("skye", skye.get("position")),
                             ("enemy", enemy.get("position"))):
        if pos is None:
            failures.append(f"fixture_contract.{actor_label}.position "
                            "missing — declared placement is required")
            continue
        if not isinstance(pos, (tuple, list)) or len(pos) != 2 \
                or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in pos):
            failures.append(f"fixture_contract.{actor_label}.position "
                            f"{pos!r} must be a finite 2-sequence")

    # declared position_tolerance must be finite/nonnegative (both actors);
    # they must agree if both are present.
    tol_sk = skye.get("position_tolerance")
    tol_en = enemy.get("position_tolerance")
    for actor_label, tol in (("skye", tol_sk), ("enemy", tol_en)):
        if tol is None:
            continue
        if isinstance(tol, bool) or not isinstance(tol, (int, float)) \
                or not math.isfinite(tol) or tol < 0:
            failures.append(f"fixture_contract.{actor_label}.position_"
                            f"tolerance {tol!r} must be finite and nonnegative")
    if tol_sk is not None and tol_en is not None and tol_sk != tol_en:
        failures.append(f"fixture_contract skye/enemy position_tolerance "
                        f"differ: {tol_sk!r} vs {tol_en!r}")

    # declared declared_fixture must be a dict (its internal agreement is
    # checked by validate_fixture, which has the field-level knowledge).
    declared = contract.get("declared_fixture")
    if not isinstance(declared, dict):
        failures.append("fixture_contract.declared_fixture must be an object")
    return failures


def validate_trial_record(result):
    """Single complete validation of one serialized client result record.

    Validates the ACTUAL carried fixture contract (result.fixture_contract)
    and manifest (result.fixture_manifest) — never a reconstruction from
    defaults. Structure/type checks come first; no unsafe nested access, no
    coercion, no fabricated defaults. Returns (failures, manifest, contract).

    Scenario must be a STRING before any dict lookup; presentation is
    optional metadata and may be missing (UNVERIFIED), but if present it
    must be a structurally valid object (otherwise a structured FAIL).
    Optional tape_file_identity metadata, if present, must be a dict
    (otherwise a structured FAIL).
    """
    failures: list[str] = []
    if not isinstance(result, dict):
        return [f"result record is {type(result).__name__}, not an object"], \
            {}, None

    if result.get("schema_version") != PAIR_SCHEMA_VERSION:
        failures.append(f"schema_version {result.get('schema_version')!r} "
                        f"!= {PAIR_SCHEMA_VERSION}")

    # scenario must be a STRING before any dict lookup; a list/None/etc.
    # becomes a structured FAIL, never an exception.
    raw_scenario = result.get("scenario")
    if not isinstance(raw_scenario, str):
        failures.append(f"result.scenario {raw_scenario!r} is not a string")
        scenario = None
    else:
        scenario = raw_scenario
        if scenario not in CLIENT_SCENARIOS:
            failures.append(f"unsupported scenario {scenario!r}")

    # presentation: optional metadata. Missing or None is fine (UNVERIFIED
    # is reported separately). If present (whether at result top-level or
    # nested under observations), it must be a structurally valid object
    # — a list here is a structured FAIL, never a crash.
    for label, container in (("result", result),
                             ("observations",
                              result.get("observations")
                              if isinstance(result.get("observations"), dict)
                              else None)):
        raw_presentation = container.get("presentation") if \
            isinstance(container, dict) else None
        if raw_presentation is not None and not isinstance(
                raw_presentation, dict):
            failures.append(f"{label}.presentation is "
                            f"{type(raw_presentation).__name__}, not an object")

    manifest = result.get("fixture_manifest")
    declared = manifest.get("declared_fixture") if \
        isinstance(manifest, dict) else None

    slot = manifest.get("slot") if isinstance(manifest, dict) else None
    expected_slot = SCENARIO_SLOT.get(scenario)
    if scenario in CLIENT_SCENARIOS and slot != expected_slot:
        failures.append(f"scenario/slot mismatch: {scenario!r} carries "
                        f"slot {slot!r}, expected {expected_slot!r}")
    if result.get("status") != "PASS":
        failures.append(f"overall status is {result.get('status')!r}, "
                        "not PASS")
    raw_stages = result.get("stages")
    if not isinstance(raw_stages, dict):
        failures.append(f"result.stages missing or not an object: "
                        f"{type(raw_stages).__name__}")
        raw_stages = {}
    for name in ("SETUP", "UI_COMMAND_SUBMITTED", "CLIENT_INPUT_OBSERVED",
                 "SERVER_ACKNOWLEDGED", "AUTHORITATIVE_EFFECT"):
        entry = raw_stages.get(name)
        if not isinstance(entry, dict):
            failures.append(f"required stage {name} is "
                            f"{type(entry).__name__ if entry is not None else 'MISSING'}")
        elif entry.get("status") != "PASS":
            failures.append(f"required stage {name} is "
                            f"{entry.get('status', 'MISSING')}")

    if not isinstance(manifest, dict):
        failures.append(f"fixture_manifest missing/malformed: "
                        f"{type(manifest).__name__}")
        return failures, manifest, None
    if not isinstance(declared, dict):
        failures.append("declared_fixture missing/malformed — the trial "
                        "carries no controlled fixture contract")
        return failures, manifest, None
    if slot not in SCENARIO_SLOT.values():
        failures.append(f"manifest slot {slot!r} is not a supported skill "
                        "slot (A/B/C)")
        return failures, manifest, None

    contract = result.get("fixture_contract")
    contract_errors = validate_contract_structure(contract)
    if contract_errors:
        failures.extend(contract_errors)
        return failures, manifest, declared

    failures.extend(validate_fixture(manifest, contract))

    # actor identities the record must carry explicitly
    skye = manifest.get("skye")
    if not isinstance(skye, dict):
        failures.append("manifest.skye is not an object")
        skye = {}
    enemy = manifest.get("enemy")
    if not isinstance(enemy, dict):
        failures.append("manifest.enemy is not an object")
        enemy = {}
    if skye.get("hero_id") != SKYE_HERO_ID:
        failures.append(f"manifest skye hero_id {skye.get('hero_id')!r} != "
                        f"the client-controlled Skye {SKYE_HERO_ID}")
    if not enemy.get("hero_id"):
        failures.append("manifest enemy hero_id missing")

    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        failures.append("provenance missing/malformed")
        provenance = {}
    startup = provenance.get("source_startup_digest")
    current = provenance.get("source_current_digest")
    if not _is_hex64(startup):
        failures.append(f"provenance.source_startup_digest invalid: {startup!r}")
    if not _is_hex64(current):
        failures.append(f"provenance.source_current_digest invalid: "
                        f"{current!r}")
    if _is_hex64(startup) and _is_hex64(current) and startup != current:
        failures.append("loaded source changed since server startup "
                        "(startup digest != current digest)")
    tape_loaded = provenance.get("tape_loaded")
    if not isinstance(tape_loaded, dict) or \
            not isinstance(tape_loaded.get("records"), int) or \
            not _is_hex64(tape_loaded.get("sha256") or ""):
        failures.append(
            f"provenance.tape_loaded lacks the loaded bootstrap identity "
            f"(records + sha256): {tape_loaded!r} — acceptance blocked")
    # optional tape_file_identity metadata: missing/None is fine, but if
    # present it MUST be a dict (not a list).
    tape_file_identity = provenance.get("tape_file_identity")
    if tape_file_identity is not None and not isinstance(
            tape_file_identity, dict):
        failures.append(f"provenance.tape_file_identity is "
                        f"{type(tape_file_identity).__name__}, not an object")
    env_config = provenance.get("env_config")
    if not isinstance(env_config, dict):
        failures.append("provenance.env_config missing/malformed")
    elif TRACE_ENV_KEY in env_config:
        # A PRESENT trace entry is an enable-switch receipt: the environment
        # carries strings, so the recorded value must be a string or null.
        # Anything else (integer, boolean, float, container) is malformed
        # evidence — rejected per record instead of being normalized, because
        # truthiness would otherwise let 1 / True collide with a valid
        # enabled destination and 0 / False with a disabled one. An ABSENT key
        # is not a disabled value and is never treated as one.
        trace_value = env_config[TRACE_ENV_KEY]
        if trace_value is not None and not isinstance(trace_value, str):
            failures.append(
                f"provenance.env_config.{TRACE_ENV_KEY} is "
                f"{type(trace_value).__name__} ({trace_value!r}), not a string "
                "or null — malformed environment receipt; acceptance blocked")
    client_version = provenance.get("client_version")
    if not isinstance(client_version, dict) or \
            not client_version.get("version_name") or \
            not isinstance(client_version.get("version_code"), int):
        failures.append("provenance.client_version must record both "
                        "versionName and versionCode")
    if not provenance.get("qa_dir"):
        failures.append("provenance.qa_dir missing")
    # REQUIRED typed process/startup/session linkage (schema 3). A record
    # whose diagnostics receipt is missing, malformed, ended/finished or
    # belongs to a different match than the fixture it measured carries no
    # coherent trial provenance and can never be half of a controlled pair.
    diagnostics = provenance.get("diagnostics")
    if not isinstance(diagnostics, dict):
        failures.append(
            "provenance.diagnostics "
            f"{'missing' if diagnostics is None else type(diagnostics).__name__}"
            " — no process/startup/session linkage evidence; acceptance blocked")
    else:
        failures.extend(f"provenance.diagnostics: {reason}" for reason in
                        validate_diagnostics_linkage(diagnostics, manifest))
    # REQUIRED end-of-trial endpoint receipt (schema 4), read after the whole
    # time-sensitive sequence, plus continuity between the two endpoints.
    # Missing, unacknowledged or malformed endpoint evidence can never be
    # half of a controlled pair.
    diagnostics_end = provenance.get("diagnostics_end")
    if not isinstance(diagnostics_end, dict):
        failures.append(
            "provenance.diagnostics_end "
            f"{'missing' if diagnostics_end is None else type(diagnostics_end).__name__}"
            " — no end-of-trial endpoint evidence; acceptance blocked")
    else:
        failures.extend(
            f"provenance.diagnostics_end: {reason}" for reason in
            validate_diagnostics_linkage(diagnostics_end, manifest))
    failures.extend(
        f"trial continuity: {reason}" for reason in
        collect_trial_continuity_failures(diagnostics, diagnostics_end))
    profile_digest = manifest.get("profile_digest")
    if not _is_hex64(profile_digest or ""):
        failures.append("manifest.profile_digest missing/invalid — the "
                        "prepared profile identity is unproven")

    raw_obs = result.get("observations")
    if not isinstance(raw_obs, dict):
        failures.append(f"observations missing or not an object: "
                        f"{type(raw_obs).__name__}")
        raw_obs = {}
    cooldown_tag = raw_obs.get("cooldown_tag")
    scenario_slot = SCENARIO_SLOT.get(scenario)
    if not isinstance(cooldown_tag, dict) or \
            cooldown_tag.get("slot") != scenario_slot:
        failures.append(
            f"skill cooldown-timer evidence missing or for the wrong slot: "
            f"{cooldown_tag!r} (expected slot {scenario_slot!r})")

    classification = raw_obs.get("damage_classification")
    if not isinstance(classification, dict):
        failures.append("observations.damage_classification missing or "
                        "not an object")
        classification = {}
    attributed = classification.get("attributed")
    if not isinstance(attributed, list) or not attributed:
        failures.append("no attributed damaging events recorded — an empty "
                        "or missing attribution cannot satisfy the effect")
        return failures, manifest, declared

    # positive (healing) deltas can never be ability damage; each hit
    # entry must be a dict with finite numeric delta.
    for i, hit in enumerate(attributed):
        if not isinstance(hit, dict):
            failures.append(f"attributed[{i}] is not an object: {hit!r}")
            continue
        delta = hit.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)) \
                or not math.isfinite(delta):
            failures.append(f"attributed[{i}].delta {delta!r} must be a "
                            "finite number")
            continue
        if delta >= 0:
            failures.append(
                f"attributed event delta is not damage: {delta!r} — a heal "
                "or zero delta can never be the skill's effect")

    hero_eid = skye.get("eid")
    enemy_eid = enemy.get("eid")
    bad = []
    for hit in attributed:
        if not isinstance(hit, dict):
            continue
        why = payload_backs_hit(hit, hero_eid, enemy_eid)
        if why:
            bad.append(why)
    if bad:
        failures.extend(f"attributed entry not payload-backed: {why}"
                        for why in bad[:4])
    # Causal coherence of the carried evidence. Bounded slice (checkpoints
    # 7-9): slots A, B and C — the input, acknowledgment/timer receipt and
    # attributed damage must describe one action by one actor on one
    # connection inside the observed window. The checks are SHARED by slot
    # because run_cast_scenario captures them identically for every cast slot
    # (only the native action and timer tag differ); the B/C-only Target Lock
    # requirement is deliberately outside the shared checker. C additionally
    # has to carry its volley publications, re-derived from their own bytes,
    # because a publication COUNT alone establishes no publisher, session or
    # instant. The minion window still needs its own causal slice; it is not
    # claimed here.
    if scenario_slot in ("A", "B", "C"):
        failures.extend(
            f"causal linkage: {why}"
            for why in collect_skye_cast_causal_failures(result, manifest,
                                                         scenario_slot))
    if scenario_slot == "C":
        failures.extend(
            f"volley evidence: {why}"
            for why in collect_skye_c_volley_failures(result, manifest))
    return failures, manifest, contract


# ---------------------------------------------------------------------------
# The minion observation contract
# ---------------------------------------------------------------------------

MINION_SCENARIO = "minion-push"
MINION_OBSERVED_STAGES = ("LANE_APPROACH", "OPPOSING_COMBAT",
                          "SURVIVOR_RESUMPTION", "STRUCTURE_INTERACTION")

# The wire grammar each carried evidence kind is decoded with: the publication
# name and the minimum payload BYTES that publication's fields occupy. These
# are exactly the lengths the writer decodes before it logs an entry, so a
# record can never be rejected for evidence it legitimately carries — and an
# entry whose payload is shorter than its own grammar is rejected outright
# rather than passing on its metadata.
EVIDENCE_GRAMMAR = {
    OP_DAMAGE: ("1054 combat-delta", 12),       # victim u32, attacker u32, delta f32
    OP_ENTITY_DEATH: ("1072 ENTITY_DEATH", 8),  # victim u32, killer u32
    OP_MOVE_ORDER: ("1016 move-order", 1),      # slot u8
}


def _is_number(value) -> bool:
    """A finite real number. A boolean is NOT a number: ``True == 1`` in
    Python, and a truth value is not a measurement."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _is_int(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _team_identity(value) -> bool:
    """Exactly the integers 1 and 2 name a side of the match."""
    return _is_int(value) and value in (1, 2)


def _entry_bytes(entry, label: str, failures: list) -> bytes | None:
    """The raw payload bytes of one carried evidence entry, or None with a
    structured reason. Nothing is decoded before the shape is known."""
    payload = entry.get("payload")
    if not isinstance(payload, str) or not payload:
        failures.append(f"{label}.payload is {payload!r}, not a non-empty "
                        "hex string")
        return None
    if len(payload) % 2 or any(ch not in _HEX64 for ch in payload.lower()):
        failures.append(f"{label}.payload is not an even-length hex string")
        return None
    try:
        return bytes.fromhex(payload)
    except ValueError:                      # pragma: no cover - guarded above
        failures.append(f"{label}.payload is not decodable hex")
        return None


def validate_minion_record(result) -> dict:
    """Validate ONE serialized minion observation record.

    The contract is the minimal one this observation can have: scenario,
    source/client/config/tape provenance, initial/end diagnostics continuity,
    the DECLARED observation duration against the observed frame, actor and
    team identities, timestamped census timelines, payload-backed
    combat/death/structure/slot evidence and the same-participant
    chronological sequence. The simulation clock each census frame was served
    at is OPTIONAL carried evidence: when it is there it must be coherent,
    when it is absent the check reports it as not-carried (``None``) rather
    than failing the record — what it cannot do is evidence elapsed gameplay
    time, and that is a claim of the PAIR contract, refused there.

    Everything derived is RECOMPUTED from the carried evidence through the
    production analysis (``minion_episodes``) and compared with what the
    record saved — a saved stage status, count or episode is an assertion to
    be checked, never evidence. Unknown fields are never treated as defaults:
    a missing team, identity or receipt is reported as such.

    Structure and type checks run FIRST, so a malformed record produces
    structured reasons rather than an exception. Returns::

        {"valid": bool,       # internally coherent and recomputable
         "accepted": bool,    # valid AND a complete, PASSING claim
         "reasons": [...],    # why it is NOT valid: tampering, malformed
                              # fields, claims its own evidence contradicts
         "incomplete": [...], # honest gaps that block acceptance without
                              # making the record incoherent
         "checks": {...}, "recomputed": {...}}

    ``valid`` is deliberately not the same as ``accepted``: a record that
    honestly reports an incomplete sequence (status FAIL, no endpoint receipt)
    is coherent and recomputable — it simply is not a complete acceptance
    claim, and ``incomplete`` says which part is missing. A record is only
    INVALID when it cannot be true on its own terms. This validator judges ONE
    record; the two-record pair equivalence contract is NOT implemented here
    and is NOT implied by ``accepted``.
    """
    failures: list[str] = []
    incomplete: list[str] = []
    checks: dict[str, bool] = {}
    recomputed: dict = {}
    if not isinstance(result, dict):
        return {"valid": False, "accepted": False, "reasons":
                [f"result record is {type(result).__name__}, not an object"],
                "incomplete": [], "checks": {}, "recomputed": {}}

    def close(name, mark):
        checks[name] = len(failures) == mark

    # -- 1. structural gate: types before anything else ---------------------
    mark = len(failures)
    if result.get("schema_version") != PAIR_SCHEMA_VERSION:
        failures.append(f"schema_version {result.get('schema_version')!r} != "
                        f"{PAIR_SCHEMA_VERSION}")
    scenario = result.get("scenario")
    if not isinstance(scenario, str):
        failures.append(f"result.scenario {scenario!r} is not a string")
    elif scenario != MINION_SCENARIO:
        failures.append(f"scenario {scenario!r} is not the minion observation "
                        f"scenario {MINION_SCENARIO!r}")
    status = result.get("status")
    if status not in ("PASS", "FAIL", "ERROR"):
        failures.append(f"result.status {status!r} is not PASS, FAIL or ERROR")
    elif status == "ERROR":
        # An infrastructure error is a real outcome, but it is not an
        # observation record: there is no window for anything below to
        # validate, so it is reported rather than treated as a partial trial.
        failures.append("the trial ended in an infrastructure error (status "
                        "ERROR) and carries no minion observation to "
                        "validate")
    connection = result.get("connection")
    if not _is_int(connection):
        failures.append(f"result.connection {connection!r} is not an integer "
                        "connection identity")
    observations = result.get("observations")
    if not isinstance(observations, dict):
        failures.append(f"observations is {type(observations).__name__}, "
                        "not an object")
        observations = None
    window = observations.get("minion_window") if \
        observations is not None else None
    if not isinstance(window, dict):
        failures.append(
            f"observations.minion_window "
            f"{'missing' if window is None else type(window).__name__} — the "
            "record carries no minion observation to validate")
    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        failures.append(f"provenance is {type(provenance).__name__}, not an "
                        "object — the trial's provenance is unproven")
        provenance = None
    contract = result.get("fixture_contract")
    if not isinstance(contract, dict):
        failures.append(f"fixture_contract is {type(contract).__name__}, not "
                        "an object — the declared observation is unproven")
        contract = None
    raw_stages = result.get("stages")
    if not isinstance(raw_stages, dict):
        failures.append(f"result.stages is {type(raw_stages).__name__}, not "
                        "an object")
        raw_stages = None
        close("structure", mark)
    if not isinstance(window, dict):
        # Nothing below is computed from a record with no observation object:
        # typed first, so a window that is a string or a list is a structured
        # reason instead of an exception.
        return {"valid": False, "accepted": False, "reasons": failures,
                "incomplete": incomplete, "checks": checks,
                "recomputed": recomputed}

    # -- 2. provenance: source, client, config, tape ------------------------
    mark = len(failures)
    if provenance is not None:
        startup = provenance.get("source_startup_digest")
        current = provenance.get("source_current_digest")
        if not _is_hex64(startup):
            failures.append(f"provenance.source_startup_digest invalid: "
                            f"{startup!r}")
        if not _is_hex64(current):
            failures.append(f"provenance.source_current_digest invalid: "
                            f"{current!r}")
        if _is_hex64(startup) and _is_hex64(current) and startup != current:
            failures.append("loaded source changed since server startup "
                            "(startup digest != current digest)")
        tape_loaded = provenance.get("tape_loaded")
        if not isinstance(tape_loaded, dict) or \
                not _is_int(tape_loaded.get("records")) or \
                not _is_hex64(tape_loaded.get("sha256") or ""):
            failures.append("provenance.tape_loaded lacks the loaded "
                            "bootstrap identity (records + sha256): "
                            f"{tape_loaded!r}")
        client_version = provenance.get("client_version")
        if not isinstance(client_version, dict) or \
                not client_version.get("version_name") or \
                not _is_int(client_version.get("version_code")):
            failures.append("provenance.client_version must record both "
                            "versionName and versionCode")
        if not provenance.get("qa_dir"):
            failures.append("provenance.qa_dir missing")
        env_config = provenance.get("env_config")
        if not isinstance(env_config, dict):
            failures.append("provenance.env_config missing/malformed")
        elif TRACE_ENV_KEY in env_config:
            # shared rule with the cast validator: a PRESENT trace entry is
            # an enable-switch receipt and must be a string or null
            trace_value = env_config[TRACE_ENV_KEY]
            if trace_value is not None and not isinstance(trace_value, str):
                failures.append(
                    f"provenance.env_config.{TRACE_ENV_KEY} is "
                    f"{type(trace_value).__name__} ({trace_value!r}), not a "
                    "string or null — malformed environment receipt")
    else:
        failures.append("provenance missing/malformed — source, client, "
                        "config and tape identity are unproven")
    profile_digest = window.get("profile_digest")
    if not _is_hex64(profile_digest):
        failures.append(f"minion_window.profile_digest {profile_digest!r} is "
                        "not a sha256 — the prepared configuration identity "
                        "is unproven")
    window_match = window.get("match_id")
    if not isinstance(window_match, str) or not window_match:
        failures.append(f"minion_window.match_id {window_match!r} is not a "
                        "non-empty string — the observed world is unnamed")
    window_connection = window.get("connection")
    if not _is_int(window_connection):
        failures.append(f"minion_window.connection {window_connection!r} is "
                        "not an integer connection identity")
    elif _is_int(connection) and window_connection != connection:
        failures.append(f"minion_window.connection {window_connection!r} != "
                        f"result.connection {connection!r} — the observation "
                        "frame and the record are different streams")
    # initial/end diagnostics continuity, through the SHARED typed linkage
    # checks the cast record validator uses
    initial = provenance.get("diagnostics") if provenance else None
    endpoint = provenance.get("diagnostics_end") if provenance else None
    for label, linkage, required in (
            ("provenance.diagnostics", initial, True),
            ("provenance.diagnostics_end", endpoint, status == "PASS")):
        if not isinstance(linkage, dict):
            message = (
                f"{label} "
                f"{'missing' if linkage is None else type(linkage).__name__}"
                " — no process/startup/session linkage evidence")
            if required:
                failures.append(message)
            else:
                incomplete.append(
                    f"{label} carries no typed receipt: the trial did not "
                    "reach its endpoint, so continuity is unproven")
            continue
        failures.extend(f"{label}: {reason}" for reason
                        in collect_linkage_field_failures(linkage))
        if isinstance(window_match, str) and window_match and \
                linkage.get("match_id") != window_match:
            failures.append(
                f"{label}: match_id {linkage.get('match_id')!r} != the "
                f"observed minion_window.match_id {window_match!r} — the "
                "receipt and the observation are not the same match")
    failures.extend(
        f"trial continuity: {reason}" for reason
        in collect_trial_continuity_failures(initial, endpoint))
    declared_window = contract.get("observational_window_s") if contract \
        else None
    if not _is_number(declared_window) or declared_window <= 0:
        failures.append(f"fixture_contract.observational_window_s "
                        f"{declared_window!r} is not a positive finite "
                        "declared duration")
        declared_window = None
    close("provenance", mark)

    # -- 3. the observed frame: duration and declared identities ------------
    mark = len(failures)
    window_start = window.get("window_start")
    window_end = window.get("window_end")
    if not _is_number(window_start):
        failures.append(f"minion_window.window_start {window_start!r} is not "
                        "a finite instant")
        window_start = None
    if not _is_number(window_end):
        failures.append(f"minion_window.window_end {window_end!r} is not a "
                        "finite instant")
        window_end = None
    if window_start is not None and window_end is not None:
        if window_end <= window_start:
            failures.append(f"minion_window.window_end {window_end!r} is not "
                            f"after window_start {window_start!r}")
        elif declared_window is not None and \
                (window_end - window_start) < declared_window:
            failures.append(
                f"the observed frame is {window_end - window_start:.3f}s "
                f"short of the declared observation duration "
                f"{declared_window}s — the declared window was not observed")
    if contract is not None and contract.get("slot") is not None:
        failures.append("fixture_contract.slot must be null for the "
                        "observational minion scenario (no cast slot is "
                        "claimed)")
    if contract is not None and \
            contract.get("declared_fixture") not in ({}, None):
        failures.append("fixture_contract.declared_fixture must be empty for "
                        "the observational minion scenario (no fixture is "
                        "declared)")
    if result.get("observed"):
        # the writer serializes the window twice (observed + observations);
        # a record whose two copies disagree was edited after the fact
        if result.get("observed") != window:
            failures.append("result.observed and observations.minion_window "
                            "disagree — one of them was changed after the "
                            "trial")
    if raw_stages is not None:
        # The four measured stages are written before any minion-path verdict
        # is raised, so every minion record carries them typed.
        for name in MINION_OBSERVED_STAGES:
            entry = raw_stages.get(name)
            if not isinstance(entry, dict) or \
                    not isinstance(entry.get("status"), str):
                failures.append(f"stage {name} is missing or carries no typed "
                                "status")
        # TRIAL_CONTINUITY is collected only at the END of the window, after a
        # trial that reached its endpoint. Its absence is a real, declared
        # outcome (a window that ended early), not automatically a malformed
        # record — but a record claiming PASS without it is incoherent.
        continuity_entry = raw_stages.get("TRIAL_CONTINUITY")
        if not isinstance(continuity_entry, dict) or \
                not isinstance(continuity_entry.get("status"), str):
            if status == "PASS":
                failures.append("a PASS record must carry a typed "
                                "TRIAL_CONTINUITY stage")
            else:
                incomplete.append("no TRIAL_CONTINUITY stage was collected: "
                                  "the window ended before an endpoint could "
                                  "be read")
    if status == "FAIL":
        first_failed = result.get("first_failed_stage")
        if not isinstance(first_failed, str):
            failures.append(f"a FAIL record must name first_failed_stage, got "
                            f"{first_failed!r}")
        elif raw_stages is not None:
            entry = raw_stages.get(first_failed)
            if not isinstance(entry, dict):
                failures.append(f"first_failed_stage {first_failed!r} is not "
                                "a carried stage")
            elif entry.get("status") == "PASS":
                failures.append(f"first_failed_stage {first_failed!r} is "
                                "recorded PASS")
    close("frame", mark)

    # -- 4. identities and timelines ---------------------------------------
    mark = len(failures)
    timelines = window.get("per_actor_timelines")
    if not isinstance(timelines, dict) or not timelines:
        failures.append(f"per_actor_timelines "
                        f"{'empty' if timelines == {} else type(timelines).__name__}"
                        " — the record carries no census timeline")
        timelines = None
    tracked_teams: dict[int, object] = {}
    timelines_ok = False
    if timelines is not None:
        timelines_ok = True
        for key, entry in timelines.items():
            if not isinstance(key, str) or not key.isdigit():
                failures.append(f"per_actor_timelines key {key!r} is not an "
                                "integer eid")
                timelines_ok = False
                continue
            eid = int(key)
            if not isinstance(entry, dict):
                failures.append(f"per_actor_timelines[{key}] is "
                                f"{type(entry).__name__}, not an object")
                timelines_ok = False
                continue
            team = entry.get("team")
            if not _team_identity(team):
                failures.append(f"per_actor_timelines[{key}].team {team!r} is "
                                "not a team identity (the integers 1 and 2)")
                timelines_ok = False
            tracked_teams[eid] = team
            if not isinstance(entry.get("episode"), dict):
                failures.append(f"per_actor_timelines[{key}].episode is not an "
                                "object")
                timelines_ok = False
            points = entry.get("points")
            if not isinstance(points, list) or not points:
                failures.append(f"per_actor_timelines[{key}].points "
                                f"{'empty' if points == [] else type(points).__name__}"
                                " — no timestamped census samples")
                timelines_ok = False
                continue
            previous = None
            for index, point in enumerate(points):
                label = f"per_actor_timelines[{key}].points[{index}]"
                if not isinstance(point, list) or len(point) != 5:
                    failures.append(f"{label} is not a 5-field "
                                    "[t, x, y, hp, present] sample")
                    timelines_ok = False
                    continue
                timestamp, x, y, hp, present = point
                if not _is_number(timestamp) or not _is_number(x) or \
                        not _is_number(y):
                    failures.append(f"{label} does not carry finite "
                                    "timestamps and coordinates")
                    timelines_ok = False
                    continue
                if hp is not None and not _is_number(hp):
                    failures.append(f"{label} hp is {hp!r}, neither a finite "
                                    "number nor null")
                    timelines_ok = False
                if not isinstance(present, bool):
                    failures.append(f"{label} present is "
                                    f"{type(present).__name__}, not a boolean")
                    timelines_ok = False
                if previous is not None and timestamp < previous:
                    failures.append(f"{label} timestamp {timestamp!r} precedes "
                                    f"the previous sample {previous!r}")
                    timelines_ok = False
                previous = timestamp
                if window_start is not None and window_end is not None and \
                        not window_start <= timestamp <= window_end:
                    failures.append(f"{label} timestamp {timestamp!r} is "
                                    "outside the observed window")
                    timelines_ok = False
    close("timelines", mark)
    if not timelines_ok:
        failures.append("the carried census timelines are not usable — the "
                        "derived claims cannot be recomputed from them")
    tracked_minions = window.get("tracked_minions")
    if not _is_int(tracked_minions) or tracked_minions < 1:
        failures.append(f"tracked_minions {tracked_minions!r} is not a "
                        "positive integer")
    elif timelines is not None and tracked_minions != len(timelines):
        failures.append(f"tracked_minions {tracked_minions} != the "
                        f"{len(timelines)} carried timelines")
    movement_samples = window.get("movement_samples")
    if not _is_int(movement_samples) or movement_samples < 0:
        failures.append(f"movement_samples {movement_samples!r} is not a "
                        "non-negative integer")
        movement_samples = None
    # The census FRAMES the window actually took. These are raw evidence: the
    # saved sample count is recomputed from them, every census sample in every
    # timeline must be one of them, and each timeline must be a tail of them
    # (a census stamps every tracked actor, so no timeline can skip a frame).
    raw_frames = window.get("census_instants")
    if not isinstance(raw_frames, list) or not raw_frames:
        failures.append(f"census_instants "
                        f"{'empty' if raw_frames == [] else type(raw_frames).__name__}"
                        " — the record does not carry the census frames it "
                        "observed, so no sample count is checkable")
        raw_frames = None
    frames = None
    if raw_frames is not None:
        frames = []
        for index, instant in enumerate(raw_frames):
            if not _is_number(instant):
                failures.append(f"census_instants[{index}] {instant!r} is not "
                                "a finite instant")
                frames = None
                break
            if window_start is not None and window_end is not None and \
                    not window_start <= instant <= window_end:
                failures.append(f"census_instants[{index}] {instant!r} is "
                                "outside the observed window")
                frames = None
                break
            if frames and instant <= frames[-1]:
                failures.append(f"census_instants[{index}] {instant!r} does "
                                f"not advance past the previous frame "
                                f"{frames[-1]!r}")
                frames = None
                break
            frames.append(instant)
    if frames is not None and movement_samples is not None:
        session_lost = window.get("session_lost_mid_window")
        if not isinstance(session_lost, bool):
            failures.append(f"session_lost_mid_window {session_lost!r} is not "
                            "a boolean")
        else:
            # `movement_samples` counts the loop iterations this window ran;
            # a lost session is counted but stamps no frame.
            expected = movement_samples if session_lost else movement_samples + 1
            if len(frames) != expected:
                failures.append(
                    f"the record says {movement_samples} loop samples with "
                    f"session_lost_mid_window={session_lost} but carries "
                    f"{len(frames)} census frames, which must be {expected} — "
                    "the saved sample count is not what the frames support")
    if frames is not None and timelines_ok:
        frame_set = set(frames)
        for key, entry in timelines.items():
            instants = [point[0] for point in entry["points"]]
            unbacked = [instant for instant in instants
                        if instant not in frame_set]
            if unbacked:
                failures.append(f"per_actor_timelines[{key}] carries "
                                f"{len(unbacked)} census sample(s) that are "
                                "not one of the observed frames")
                continue
            tail = frames[len(frames) - len(instants):]
            if instants != tail:
                failures.append(
                    f"per_actor_timelines[{key}] skips census frames: its "
                    f"{len(instants)} sample(s) are not the last "
                    f"{len(instants)} of the {len(frames)} observed frames, so "
                    "it cannot be the record of one actor watched frame by "
                    "frame")

    # -- 4b. the carried simulation clock of the census frames -------------
    # OPTIONAL evidence: a record may carry the world clock each census frame
    # was served at (tick/time, the same pair ``snapshot`` serves). Absence is
    # a named GAP — the elapsed GAMEPLAY time between frames cannot be shown
    # from such a record — but it is not incoherence, so it never makes a
    # record invalid. When it IS carried it must be coherent: parallel to the
    # frames, non-decreasing, on the record's own tick rate, and inside the
    # trial's own tick span.
    mark = len(failures)
    raw_ticks = window.get("census_sim_ticks")
    raw_sim_times = window.get("census_sim_times")
    sim_clock = {"carried": None, "carried_frames": 0, "frames": None,
                 "rate": None, "rate_source": None, "last_frame_sim_time": None,
                 "endpoint_sim_time": None}
    clock_absent = raw_ticks is None and raw_sim_times is None
    if clock_absent:
        # A record whose census replies carried no clock is still a coherent
        # observation of everything else it claims (shape, outcome, stages),
        # so it stays ACCEPTED here and the absence is reported as a named GAP:
        # what it cannot do is evidence elapsed gameplay time, which is a claim
        # of the PAIR contract and is refused there as UNVERIFIED. This check
        # is therefore None — not carried — never a pass and never a failure.
        sim_clock["carried"] = False
        sim_clock["missing_evidence"] = ("minion_window.census_sim_ticks / "
                                         "census_sim_times")
        sim_clock["consequence"] = (
            "the elapsed GAMEPLAY time between this record's census frames is "
            "not evidenced by it; a pair comparison over elapsed time can only "
            "report that as UNVERIFIED")
        checks["census_sim_clock"] = None
        recomputed.setdefault("sim_clock", sim_clock)
    elif not isinstance(raw_ticks, list) or not isinstance(raw_sim_times,
                                                          list):
        failures.append("minion_window.census_sim_ticks/census_sim_times must "
                        "be lists parallel to census_instants when carried")
    else:
        sim_clock["carried"] = True
        sim_clock["frames"] = len(raw_ticks)
        if frames is not None and len(raw_ticks) != len(frames):
            failures.append(
                f"census_sim_ticks carries {len(raw_ticks)} entrie(s) for "
                f"{len(frames)} census frame(s): the clock is not parallel to "
                "the frames it belongs to")
        if len(raw_ticks) != len(raw_sim_times):
            failures.append(
                f"census_sim_ticks and census_sim_times carry "
                f"{len(raw_ticks)} vs {len(raw_sim_times)} entrie(s): the two "
                "halves of one clock must be parallel")
        # TYPED FIRST: every entry is checked for type and range here, and only
        # entries that passed reach the arithmetic below (the rate relation and
        # the endpoint comparison). A malformed entry — a string, a container,
        # a boolean, a non-finite float, a tick too large to multiply — is a
        # structured failure naming the frame, never an exception raised from a
        # later loop.
        previous = None
        typed_clock = []
        for index, (tick, sim_time) in enumerate(zip(raw_ticks, raw_sim_times)):
            if tick is None or sim_time is None:
                if tick is None and sim_time is None:
                    continue
                failures.append(f"census frame {index} carries only one half "
                                "of the simulation clock (tick/time)")
                break
            if not _is_int(tick) or not _is_number(sim_time):
                failures.append(f"census frame {index} simulation clock "
                                f"({tick!r}, {sim_time!r}) is not an integer "
                                "tick with a finite time")
                break
            if abs(tick) > MAX_CLOCK_TICK:
                failures.append(f"census frame {index} tick {tick} is beyond "
                                f"{MAX_CLOCK_TICK}, where this record's own "
                                "tick/time relation cannot be checked in float "
                                "arithmetic")
                break
            if previous is not None and tick < previous[0]:
                failures.append(f"census frame {index} tick {tick} does not "
                                f"advance past the previous frame {previous[0]}")
                break
            previous = (tick, sim_time)
            typed_clock.append((index, tick, sim_time))
            sim_clock["carried_frames"] += 1
            sim_clock["last_frame_sim_time"] = sim_time
        # The record's own tick rate, from its own two receipts: sim_time =
        # tick * rate, the same relation ``snapshot`` and ``diagnostics``
        # serve. No timing tolerance is involved — this is a float
        # representation check, not an allowance. Only ``typed_clock`` entries
        # are multiplied: an entry the gate above refused is never arithmetic.
        initial = provenance.get("diagnostics") if provenance else None
        rate = None
        if isinstance(initial, dict) and _is_int(initial.get("tick")) and \
                _is_number(initial.get("time")) and initial["tick"] > 0:
            rate = initial["time"] / initial["tick"]
            sim_clock["rate"] = rate
            sim_clock["rate_source"] = "provenance.diagnostics tick/time"
        if rate is not None:
            for index, tick, sim_time in typed_clock:
                if abs(sim_time - tick * rate) > _clock_epsilon(tick * rate):
                    failures.append(
                        f"census frame {index} simulation clock {sim_time!r} "
                        f"is not tick {tick} on this record's own rate "
                        f"{rate!r} (expected {tick * rate!r})")
                    break
        if endpoint is not None:
            if not isinstance(endpoint, dict):
                failures.append(
                    f"the trial endpoint {endpoint!r} is not a receipt object, "
                    "so the census clock cannot be placed inside the trial "
                    "that read it")
            elif not _is_number(endpoint.get("time")):
                failures.append(
                    f"the trial endpoint time {endpoint.get('time')!r} is not "
                    "a finite number, so the census clock cannot be placed "
                    "inside the trial that read it")
            else:
                sim_clock["endpoint_sim_time"] = endpoint["time"]
                last = sim_clock["last_frame_sim_time"]
                if last is not None and last > endpoint["time"] + \
                        _clock_epsilon(endpoint["time"]):
                    failures.append(
                        f"the last census frame simulation time {last!r} is "
                        f"after the trial endpoint {endpoint['time']!r} that "
                        "was read AFTER the window closed")
    if not clock_absent:
        # a clock that is not carried leaves the None the absence branch
        # recorded: there is nothing to check, so no pass and no failure
        checks["census_sim_clock"] = len(failures) == mark
    if sim_clock["frames"] is not None:
        recomputed.setdefault("sim_clock", sim_clock)

    # -- 5. payload-backed evidence ----------------------------------------
    mark = len(failures)
    teams_by_structure: dict[int, object] = {}
    raw_structures = window.get("structure_teams")
    if not isinstance(raw_structures, dict):
        failures.append(f"structure_teams {type(raw_structures).__name__} is "
                        "not an object")
        raw_structures = {}
    for key, team in raw_structures.items():
        if not isinstance(key, str) or not key.isdigit():
            failures.append(f"structure_teams key {key!r} is not an integer "
                            "structure eid")
            continue
        if team is not None and not _team_identity(team):
            failures.append(f"structure_teams[{key}] {team!r} is neither null "
                            "nor a team identity (1 or 2)")
        teams_by_structure[int(key)] = team

    def check_common(entry, label):
        """Wire identity shared by every carried evidence entry."""
        ok = True
        if not _is_number(entry.get("time")):
            failures.append(f"{label}.time {entry.get('time')!r} is not a "
                            "finite instant")
            ok = False
        elif window_start is not None and window_end is not None and \
                not window_start <= entry["time"] <= window_end:
            failures.append(f"{label}.time {entry['time']!r} is outside the "
                            "observed window")
            ok = False
        if window_connection is not None and \
                entry.get("connection") != window_connection:
            failures.append(f"{label}.connection {entry.get('connection')!r} "
                            f"!= the observed connection "
                            f"{window_connection!r} — evidence from another "
                            "stream")
            ok = False
        return ok

    def check_identity(entry, label, derived, fields):
        """The carried identity must BE the identity its payload encodes."""
        for field, value in zip(fields, derived):
            if entry.get(field) != value:
                failures.append(f"{label}.{field} {entry.get(field)!r} != "
                                f"{value!r} re-derived from its own payload")

    def entity_identity(entry, field, label):
        """``entry[field]`` as an integer entity identity, or None with a
        structured reason. Checked BEFORE the value is used as a key or in a
        computation: a list/dict cannot be a dict key at all, and a string,
        float or bool is not an identity, so neither is looked up, and a
        missing identity is never defaulted to something checkable."""
        value = entry.get(field)
        if not _is_int(value):
            failures.append(f"{label}.{field} {value!r} "
                            f"({type(value).__name__}) is not an integer "
                            "entity identity")
            return None
        return value

    def check_evidence_payload(entry, label, opcode, *, declared=True):
        """The entry's own DECODED payload, or None with a structured reason.

        The entry must publish the opcode it claims, and its payload must
        decode to at least the bytes that publication's grammar reads (see
        EVIDENCE_GRAMMAR). A shorter payload is a failure, never a skipped
        check: no identity can be re-derived from it, so the entry would be
        accepted on its metadata alone.

        ``declared`` marks the kinds whose entries carry the opcode they were
        published under (combat, structure, death). A slot attribution is
        named by the ``move_log`` key itself and carries no opcode claim, so
        its own grammar is what is enforced — but an opcode it does carry must
        still be the 1016 it was read as."""
        grammar, minimum = EVIDENCE_GRAMMAR[opcode]
        recorded = entry.get("opcode")
        if recorded != opcode and (declared or recorded is not None):
            failures.append(f"{label}.opcode {recorded!r} is not "
                            f"the {grammar} publication the entry claims")
            return None
        payload = _entry_bytes(entry, label, failures)
        if payload is None:
            return None
        if len(payload) < minimum:
            failures.append(
                f"{label}.payload decodes to {len(payload)} byte(s), below "
                f"the {minimum} byte(s) the {grammar} grammar reads — its "
                "identities cannot be re-derived from it, so the entry is not "
                "evidence of what it claims")
            return None
        return payload

    combat_log = window.get("combat_log")
    structure_log = window.get("structure_log")
    death_log = window.get("death_log")
    move_log = window.get("move_log")
    for name, log in (("combat_log", combat_log), ("structure_log",
                                                   structure_log),
                      ("death_log", death_log), ("move_log", move_log)):
        if not isinstance(log, list):
            failures.append(f"{name} is {type(log).__name__}, not a list")
    evidence_ok = all(isinstance(log, list) for log in
                      (combat_log, structure_log, death_log, move_log))
    if evidence_ok:
        # Every identity below is type-checked by entity_identity() before it
        # is used as a key: tracked_teams/teams_by_structure are keyed by
        # integer eids, so a container identity is reported, never looked up.
        for index, entry in enumerate(combat_log):
            label = f"combat_log[{index}]"
            if not isinstance(entry, dict):
                failures.append(f"{label} is {type(entry).__name__}, not an "
                                "object")
                evidence_ok = False
                continue
            payload = check_evidence_payload(entry, label, OP_DAMAGE)
            if not check_common(entry, label) or payload is None:
                evidence_ok = False
            victim = entity_identity(entry, "victim", label)
            attacker = entity_identity(entry, "attacker", label)
            for field, actor in (("victim_team", victim),
                                 ("attacker_team", attacker)):
                team = entry.get(field)
                if not _team_identity(team):
                    failures.append(f"{label}.{field} {team!r} is not a team "
                                    "identity")
                    evidence_ok = False
                elif actor in tracked_teams and tracked_teams[actor] != team:
                    failures.append(f"{label}.{field} {team!r} contradicts "
                                    f"the census team of {actor!r} "
                                    f"({tracked_teams[actor]!r})")
                    evidence_ok = False
            if victim is None or attacker is None:
                evidence_ok = False
            elif victim not in tracked_teams or attacker not in tracked_teams:
                failures.append(f"{label} names victim {victim!r} / attacker "
                                f"{attacker!r} that this record does not "
                                "track")
                evidence_ok = False
            else:
                census_teams = (tracked_teams[victim], tracked_teams[attacker])
                if not all(_team_identity(team) for team in census_teams):
                    failures.append(f"{label} cannot be checked against "
                                    "unidentified actor teams")
                    evidence_ok = False
                elif census_teams[0] == census_teams[1]:
                    failures.append(f"{label} is not opposing-team combat: "
                                    f"victim and attacker are both team "
                                    f"{census_teams[0]!r}")
                    evidence_ok = False
            if payload is not None:
                check_identity(
                    entry, label,
                    (struct.unpack_from(">II", payload, 0)[0],
                     struct.unpack_from(">II", payload, 0)[1],
                     struct.unpack_from(">f", payload, 8)[0]),
                    ("victim", "attacker", "delta"))

        for index, entry in enumerate(structure_log):
            label = f"structure_log[{index}]"
            if not isinstance(entry, dict):
                failures.append(f"{label} is {type(entry).__name__}, not an "
                                "object")
                evidence_ok = False
                continue
            payload = check_evidence_payload(entry, label, OP_DAMAGE)
            if not check_common(entry, label) or payload is None:
                evidence_ok = False
            structure = entity_identity(entry, "structure", label)
            attacker = entity_identity(entry, "attacker", label)
            if structure is None:
                evidence_ok = False
            elif structure not in teams_by_structure:
                failures.append(f"{label}.structure {structure!r} has no "
                                "carried team — its side is unknown")
                evidence_ok = False
            elif teams_by_structure[structure] != entry.get("structure_team"):
                failures.append(f"{label}.structure_team "
                                f"{entry.get('structure_team')!r} contradicts "
                                f"the served team of structure {structure!r} "
                                f"({teams_by_structure[structure]!r})")
                evidence_ok = False
            if attacker is None:
                evidence_ok = False
            elif attacker not in tracked_teams:
                failures.append(f"{label}.attacker {attacker!r} is not a "
                                "tracked actor")
                evidence_ok = False
            elif tracked_teams[attacker] != entry.get("attacker_team"):
                failures.append(f"{label}.attacker_team "
                                f"{entry.get('attacker_team')!r} contradicts "
                                f"the census team of {attacker!r} "
                                f"({tracked_teams[attacker]!r})")
                evidence_ok = False
            if payload is not None:
                check_identity(
                    entry, label,
                    struct.unpack_from(">IIf", payload, 0),
                    ("structure", "attacker", "delta"))

        for index, entry in enumerate(death_log):
            label = f"death_log[{index}]"
            if not isinstance(entry, dict):
                failures.append(f"{label} is {type(entry).__name__}, not an "
                                "object")
                evidence_ok = False
                continue
            payload = check_evidence_payload(entry, label, OP_ENTITY_DEATH)
            if not check_common(entry, label) or payload is None:
                evidence_ok = False
            victim = entity_identity(entry, "victim", label)
            killer = entity_identity(entry, "killer", label)
            if victim is None or killer is None:
                evidence_ok = False
            elif victim not in tracked_teams:
                failures.append(f"{label}.victim {victim!r} is not a tracked "
                                "actor")
                evidence_ok = False
            if payload is not None:
                check_identity(
                    entry, label,
                    struct.unpack_from(">II", payload, 0),
                    ("victim", "killer"))

        for index, entry in enumerate(move_log):
            label = f"move_log[{index}]"
            if not isinstance(entry, dict):
                failures.append(f"{label} is {type(entry).__name__}, not an "
                                "object")
                evidence_ok = False
                continue
            payload = check_evidence_payload(entry, label, OP_MOVE_ORDER,
                                              declared=False)
            if not check_common(entry, label) or payload is None:
                evidence_ok = False
            slot = entity_identity(entry, "slot", label)
            owner = entity_identity(entry, "owner", label)
            if slot is None or owner is None:
                evidence_ok = False
            elif owner not in tracked_teams:
                failures.append(f"{label}.owner {owner!r} is not a tracked "
                                "actor")
                evidence_ok = False
            if payload is not None:
                # the 1016 slot is the first payload byte the order assigns
                check_identity(entry, label, (payload[0],), ("slot",))
        tracked_move_orders = window.get("tracked_move_orders")
        if not _is_int(tracked_move_orders) or tracked_move_orders < 0:
            failures.append(f"tracked_move_orders {tracked_move_orders!r} is "
                            "not a non-negative integer")
        else:
            if tracked_move_orders != len(move_log):
                failures.append(f"tracked_move_orders {tracked_move_orders} "
                                f"!= the {len(move_log)} carried slot "
                                "attributions")
            elif tracked_move_orders > 0 and not any(
                    isinstance(entry, dict) and entry.get("slot") is not None
                    for entry in move_log):
                failures.append("carried slot attributions name no slot")
    close("evidence", mark)

    # -- 6. recompute every derived claim from the carried evidence --------
    mark = len(failures)
    if timelines_ok and evidence_ok and all(
            _team_identity(team) for team in tracked_teams.values()):
        tracked = {eid: {"team": tracked_teams[eid],
                         "timeline": [tuple(point) for point in
                                      timelines[str(eid)]["points"]]}
                   for eid in tracked_teams}
        episodes = minion_episodes(tracked, combat_log, structure_log,
                                   death_log, teams_by_structure)
        approached = [eid for eid, ep in episodes.items()
                      if (ep["approach"] or 0) >= 1.0]
        participants = [eid for eid, ep in episodes.items()
                        if ep["combat_participant"]]
        resumed = [eid for eid, ep in episodes.items()
                   if ep["resumed_after_combat"] is not None
                   and ep["resumed_after_combat"] >= 1.0]
        unproven_resumptions = [eid for eid, ep in episodes.items()
                                if ep["resumption_unverified"] is not None]
        structure_cohort = [eid for eid, ep in episodes.items()
                            if ep["structure_sequence"] is not None]
        structure_unproven = [eid for eid, ep in episodes.items()
                              if ep["structure_unverified"] is not None]
        recomputed_summary = {
            "tracked_minions": len(tracked),
            "minions_advanced_toward_enemy_base": len(approached),
            "combat_participants": len(participants),
            "minion_vs_minion_events": len(combat_log),
            "survivors_resumed": len(resumed),
            "survivor_claims_unverified": len(unproven_resumptions),
            "resumed_cohort_structure_hits": len(structure_cohort),
            "structure_claims_unverified": len(structure_unproven),
            "tracked_move_orders": len(move_log),
        }
        for name, value in recomputed_summary.items():
            if window.get(name) != value:
                failures.append(
                    f"summary.{name} is recorded {window.get(name)!r} but "
                    f"recomputing it from the carried evidence gives "
                    f"{value!r} — a saved count is checked, not trusted")
        recomputed["summary"] = recomputed_summary
        stage_status = {
            "LANE_APPROACH": "PASS" if approached else "NOT_OBSERVED",
            "OPPOSING_COMBAT": "PASS" if combat_log else "NOT_OBSERVED",
            "SURVIVOR_RESUMPTION": "PASS" if resumed else "NOT_OBSERVED",
            "STRUCTURE_INTERACTION": "PASS" if structure_cohort
            else "NOT_OBSERVED",
        }
        recomputed["stage_status"] = stage_status
        recomputed["episodes"] = {str(eid): episode
                                  for eid, episode in episodes.items()}
        if raw_stages is not None:
            for name, expected_status in stage_status.items():
                entry = raw_stages.get(name)
                recorded = entry.get("status") if isinstance(entry, dict) \
                    else None
                if recorded != expected_status:
                    failures.append(
                        f"stage {name} is recorded {recorded!r} but the "
                        f"carried evidence recomputes it as "
                        f"{expected_status!r} — the saved claim is not what "
                        "the evidence supports")
        for key, entry in timelines.items():
            saved_episode = entry["episode"]
            recomputed_episode = episodes[int(key)]
            if saved_episode != recomputed_episode:
                differences = [field for field in
                               sorted(set(saved_episode) | set(recomputed_episode))
                               if saved_episode.get(field)
                               != recomputed_episode.get(field)][:3]
                failures.append(
                    f"per_actor_timelines[{key}].episode differs from the "
                    "episode recomputed from its own timeline: "
                    + ", ".join(
                        f"{field}: recorded {saved_episode.get(field)!r} != "
                        f"recomputed {recomputed_episode.get(field)!r}"
                        for field in differences))
        if status == "PASS":
            if any(value != "PASS" for value in stage_status.values()):
                failures.append("the record claims PASS while its carried "
                                "evidence recomputes an incomplete sequence")
            if window.get("session_lost_mid_window") is not False:
                failures.append(
                    f"a PASS record must carry a boolean false "
                    f"session_lost_mid_window, got "
                    f"{window.get('session_lost_mid_window')!r}")
    else:
        failures.append("the derived claims were not recomputed: the carried "
                        "timelines or evidence are structurally unusable")
    close("recomputed", mark)

    continuity = (raw_stages or {}).get("TRIAL_CONTINUITY")
    continuity_status = continuity.get("status") if isinstance(continuity,
                                                               dict) else None
    checks["complete_claim"] = (
        status == "PASS"
        and all((raw_stages or {}).get(name, {}).get("status") == "PASS"
                for name in MINION_OBSERVED_STAGES)
        and continuity_status == "PASS")
    checks["trial_continuity"] = continuity_status == "PASS"
    # An honest record of an INCOMPLETE trial is coherent: its verdict is
    # reported, not treated as a malformed record. It simply is not an
    # acceptance claim, so it blocks `accepted` and says why.
    if status != "PASS":
        incomplete.append(f"the record's own verdict is {status!r}, not PASS"
                          + (f" ({result.get('failure_detail')})"
                             if isinstance(result.get("failure_detail"), str)
                             else ""))
    if status == "PASS" and continuity_status != "PASS":
        # The writer reads the endpoint receipt and sets TRIAL_CONTINUITY
        # before it can reach PASS, so a PASS record whose continuity is not
        # PASS is a claim its own carried evidence cannot support.
        failures.append(f"the record claims PASS but TRIAL_CONTINUITY is "
                        f"recorded {continuity_status!r}")
    elif continuity_status is not None and continuity_status != "PASS":
        incomplete.append(f"TRIAL_CONTINUITY is recorded "
                          f"{continuity_status!r}")
    return {"valid": not failures,
            "accepted": not failures and not incomplete
                        and checks["complete_claim"],
            "reasons": failures, "incomplete": incomplete, "checks": checks,
            "recomputed": recomputed}


# The time-erasing comparison form of an analysis reason string. A reason TEXT
# quotes instants ("the hit at t=1789153977.15"), and the minion window clock is
# wall clock, so two fresh sessions legitimately quote different ones. The
# CLAIM is what is compared; the instants themselves are reported separately,
# per record, with their offset from that record's own recorded origin.
# Erased: an absolute-instant-shaped number (>= 7 integer digits) with an
# optional fraction, and any float with 3+ fractional digits (a sub-millisecond
# wall-clock measurement). Small stable values (-30.0 damage, 4.0 u march,
# 2 of 5 samples, a 4610 eid) are left exactly as they are.
_INSTANT_LIKE = re.compile(r"\d{7,}(?:\.\d+)?|\d+\.\d{3,}")


def erase_instants(text: str) -> str:
    """``text`` with wall-clock-shaped numbers replaced by ``<t>``."""
    return _INSTANT_LIKE.sub("<t>", text)


def _minion_episode_projection(episode):
    """One actor's episode reduced to what two fresh sessions must agree on.

    Every absolute instant becomes a PRESENCE FLAG (its value is reported with
    the record's own origin), ``opponent_closure`` keeps the closure KIND but
    not the instant it quotes, and every analysis reason string is
    time-erased. Nothing is dropped silently: the caller reports the measured
    instants and their offsets separately.
    """
    if not isinstance(episode, dict):
        return episode

    def cleaned(value):
        if not isinstance(value, dict):
            return value
        out = {}
        for key, item in value.items():
            if key == "time":
                continue                 # absolute instant: presence only
            if key == "reasons":
                out["reasons"] = [erase_instants(reason)
                                  if isinstance(reason, str) else reason
                                  for reason in item or []]
            elif key == "opponent_closure":
                out[key] = {str(eid): str(claim).split("@", 1)[0]
                            for eid, claim in (item or {}).items()}
            else:
                out[key] = item
        return out

    return {
        "approach": episode.get("approach"),
        "combat_participant": episode.get("combat_participant"),
        "opponents": sorted(episode.get("opponents") or []),
        "unaccounted_opponents": sorted(episode.get("unaccounted_opponents")
                                        or []),
        "engagement_end_carried": episode.get("engagement_end") is not None,
        "end_evidence": episode.get("end_evidence"),
        "opponent_closure": cleaned({"opponent_closure":
                                     episode.get("opponent_closure")})
        ["opponent_closure"],
        "resumed_after_combat": episode.get("resumed_after_combat"),
        "resumption_unverified": cleaned(episode.get("resumption_unverified")),
        "alive_samples_after_end": episode.get("alive_samples_after_end"),
        "death_evidence": episode.get("death_evidence"),
        "death_carried": episode.get("death_time") is not None,
        "absent_since_carried": episode.get("absent_since") is not None,
        "last_combat_carried": episode.get("last_combat_time") is not None,
        "structure_hit": episode.get("structure_hit"),
        "structure_hits": [cleaned(hit)
                           for hit in episode.get("structure_hits") or []],
        "structure_sequence": cleaned(episode.get("structure_sequence")),
        "structure_unverified": cleaned(episode.get("structure_unverified")),
    }


def minion_pair_score(window: dict, recomputed: dict) -> tuple[dict | None, list]:
    """The comparable outcome of ONE validated minion observation window.

    Everything here is recomputed from the carried raw evidence (census
    timelines, payload-backed event logs, the census frames) or read from the
    single-record validator's own recomputation — never from a saved status or
    count. Only quantities that are independent of the wall clock are
    returned: the census shape, the ordered event sequences, exact counts and
    damage totals, and each actor's episode projection. Returns
    ``(score, reasons)``; the caller never trusts that this record was
    accepted, so unusable carried shapes yield reasons instead of a score.
    """
    reasons: list[str] = []
    timelines = window.get("per_actor_timelines")
    logs = {}
    for name in ("combat_log", "structure_log", "death_log", "move_log"):
        log = window.get(name)
        if not isinstance(log, list) or not all(isinstance(entry, dict)
                                                for entry in log):
            reasons.append(f"{name} is not a list of carried entries")
        logs[name] = log if isinstance(log, list) else []
    frames = window.get("census_instants")
    if not isinstance(frames, list) or not frames or \
            not all(_is_number(instant) for instant in frames):
        reasons.append("the carried census frames are unusable")
    if not isinstance(timelines, dict) or not timelines:
        reasons.append("the carried per-actor timelines are unusable")
    if not isinstance(recomputed, dict) or \
            not isinstance(recomputed.get("episodes"), dict):
        reasons.append("the record carries no recomputed episodes")
    if reasons:
        return None, reasons
    combat, structure = logs["combat_log"], logs["structure_log"]
    deaths, moves = logs["death_log"], logs["move_log"]

    def identities(entry, fields):
        return tuple(entry.get(field) for field in fields)

    def merged(log, kind, fields):
        return [(entry["time"], kind) + identities(entry, fields)
                for entry in log]

    chronology = (merged(combat, "combat", ("victim", "attacker"))
                  + merged(deaths, "death", ("victim", "killer"))
                  + merged(structure, "structure", ("structure", "attacker")))
    # sorted by the record's OWN instants, so the comparison is the ORDER the
    # events happened in, never the instants themselves
    chronology.sort(key=lambda row: (row[0], row[1], row[2:]))

    def damage_total(log):
        total = 0.0
        for entry in log:
            delta = entry.get("delta")
            if _is_number(delta):
                total += delta
        return round(total, OUTCOME_TOTAL_DECIMALS)

    per_actor_damage: dict[str, dict] = {}
    for entry in combat:
        delta = entry.get("delta")
        if not _is_number(delta):
            continue
        for role, eid in (("dealt", entry.get("attacker")),
                          ("taken", entry.get("victim"))):
            slot = per_actor_damage.setdefault(str(eid), {"dealt": 0.0,
                                                          "taken": 0.0})
            slot[role] = round(slot[role] + delta, OUTCOME_TOTAL_DECIMALS)

    points = {}
    for key, entry in timelines.items():
        rows = entry.get("points")
        if not isinstance(rows, list) or \
                not all(isinstance(row, list) and len(row) == 5
                        for row in rows):
            reasons.append(f"per_actor_timelines[{key}] has no usable points")
            continue
        # every carried OBSERVATION is compared (x, y, hp, alive); the instant
        # that observation was stamped with is the wall clock and is reported
        # by minion_measured_time instead of being compared
        points[str(key)] = [tuple(row[1:]) for row in rows]
    if reasons:
        return None, reasons

    score = {
        "census_frames": len(frames),
        "movement_samples": window.get("movement_samples"),
        "tracked_minions": len(timelines),
        "timeline_samples": {key: len(rows) for key, rows in points.items()},
        "census_points": points,
        "presence": {key: [row[3] for row in rows]
                     for key, rows in points.items()},
        "combat_sequence": [identities(entry, ("victim", "attacker"))
                            for entry in combat],
        "death_sequence": [identities(entry, ("victim", "killer"))
                           for entry in deaths],
        "structure_sequence": [identities(entry, ("structure", "attacker"))
                               for entry in structure],
        "event_chronology": [row[1:] for row in chronology],
        "slot_frames": [tuple(entry.get(field) for field in ("slot",
                                                             "payload"))
                        for entry in moves],
        "combat_damage_total": damage_total(combat),
        "structure_damage_total": damage_total(structure),
        "combat_damage_by_actor": per_actor_damage,
        "summary": dict(recomputed.get("summary") or {}),
        "stage_status": dict(recomputed.get("stage_status") or {}),
        "episodes": {str(eid): _minion_episode_projection(episode)
                     for eid, episode in (recomputed.get("episodes")
                                          or {}).items()},
    }
    return score, []


def minion_measured_time(window: dict, recomputed: dict) -> dict:
    """The wall-clock values of ONE record, made explicit.

    The minion window is stamped with real time, so these values are NOT
    compared between two records; they are reported together with the offset
    from that record's own recorded origin (``window_start``), which is the
    origin every normalisation in this contract uses.
    """
    origin = window.get("window_start")
    frames = [instant for instant in window.get("census_instants") or []
              if _is_number(instant)]

    def offset(value):
        if not _is_number(value) or not _is_number(origin):
            return None
        return round(value - origin, 3)

    episodes = (recomputed or {}).get("episodes") or {}
    timelines = window.get("per_actor_timelines")
    point_offsets = {}
    if isinstance(timelines, dict):
        for key, entry in timelines.items():
            rows = (entry or {}).get("points") if isinstance(entry, dict) else None
            if isinstance(rows, list) and rows:
                stamps = [row[0] for row in rows
                          if isinstance(row, list) and row and _is_number(row[0])]
                if stamps:
                    point_offsets[str(key)] = {"first": offset(stamps[0]),
                                               "last": offset(stamps[-1]),
                                               "samples": len(rows)}
    return {
        "origin": origin,
        "window_end": window.get("window_end"),
        "window_end_offset": offset(window.get("window_end")),
        "census_frame_offsets": [offset(instant) for instant in frames],
        "census_point_offset_spans": point_offsets,
        "episode_instant_offsets": {
            str(eid): {
                "engagement_end": offset(episode.get("engagement_end")),
                "last_combat_time": offset(episode.get("last_combat_time")),
                "death_time": offset(episode.get("death_time")),
                "structure_hit_times": [offset(hit.get("time"))
                                        for hit in episode.get("structure_hits")
                                        or []],
                "structure_sequence_time": offset(
                    (episode.get("structure_sequence") or {}).get("time")),
            } for eid, episode in episodes.items()
            if isinstance(episode, dict)},
    }


def compare_minion_pair(result_a: dict, result_b: dict) -> dict:
    """Controlled-pair gate between TWO minion observation records.

    Each record is judged FIRST by the single-record contract
    (``validate_minion_record``): both must be individually ACCEPTED — a mixed
    scenario, a FAIL trial, an infrastructure error and an honest but
    incomplete observation all fail here, each with that record's own reasons.

    The bounded equivalence contract between two accepted records is:

    * EQUAL: the semantic identity (source startup/current digests, loaded tape
      identity, client build, semantic config, the prepared profile digest) and
      the declared observation duration;
    * EQUAL: the carried actor mapping and each mapped actor's team — the
      mapping IS the carried eid. Two records that track different eids carry
      no correspondence between their actors, so the pair is REFUSED as
      unverified (an early evidence gap) instead of sorting actors into an
      invented equivalence;
    * EQUAL: the census shape (frame count, loop samples, every carried census
      point and its presence) and the recomputed summary counts, stage
      statuses and per-actor episode verdicts;
    * EQUAL: the ordered event sequences of every carried evidence log and
      their cross-kind chronological merge, and the exact damage totals at
      float32-derived precision;
    * EQUAL (the elapsed-time contract, ``elapsed_time``): the ELAPSED
      SIMULATION TIME per census frame, from the world clock each census frame
      was served at, normalised to each record's own first frame — this is the
      gameplay timing claim and it does not depend on the client's wall clock
      at all. It is compared EXACTLY, per frame index, with no tolerance: equal
      elapsed simulation time is what this implementation's determinism
      produces (the round's four independent fixture productions carry
      identical normalised series), and no measurement justifies any non-zero
      allowance between two independent LIVE samplers, so none is applied. A
      difference is reported as a demonstrated divergence in elapsed gameplay
      time, with its exact size.
      Every census frame's and every event's real-time offset from that
      record's own origin must also agree per index within
      ``FIXTURE_SAMPLING_MARGIN_S``, and each record's own cadence must sit
      inside its own declared schedule (the declared duration and loop-sample
      count it carries). That margin is CALIBRATED ON THE FIXTURE PATH ONLY
      (0.0086s measured on this round's productions) and its scope is reported
      beside every verdict: the offline real path already deviates by 0.4515s
      at the same declared cadence, so an out-of-margin deviation is refused
      as NOT ESTABLISHED — UNVERIFIED, never called a violation of a
      production bound, and never accepted either;
    * REFUSED as UNVERIFIED: a pair whose records carry no simulation clock.
      The elapsed gameplay time cannot be shown from them, so the
      ``elapsed_time`` gate names the missing carried field and
      ``controlled_pair`` stays false — timing is never dropped to make a pair
      pass;
    * NOT REQUIRED: the absolute clock origin. Each record's raw instants are
      reported with their offset from that record's own origin
      (``measured_time``) and only those offsets are compared, so a uniform
      shift of the whole clock is the same observation while a nonuniform
      shift of the sampling schedule is not;
    * NORMALIZED away: fresh-session identity (match id, connection, process
      and startup receipts, wall times, trace path) — each record's own
      continuity checks already proved it coherent;
    * NOT CLAIMED: ``live_sampling_equivalence`` — whether two independent LIVE
      clients, whose census replies are stamped by the server at SERVICE time
      and received afterwards (measured 0.038s median apart even offline),
      produce the timing this contract compares. It is reported UNVERIFIED in
      every verdict, with the missing evidence named, and a VERIFIED verdict
      does not claim it; slot->owner ownership (a 1016 move frame alone does
      not prove which actor owned the slot and no assignment/release lifecycle
      publication is carried, so slot evidence is compared only as ordered raw
      frames, never as proven ownership); and the simulation instant of an
      individual EVENT, which is not carried at all — only the census frames
      carry the sim clock.

    ``controlled_pair`` is true only when both records are accepted and every
    equality above holds.
    """
    report: dict = {
        "contract": "minion-push bounded observational equivalence",
        "schema_version_required": PAIR_SCHEMA_VERSION,
        "scenario": MINION_SCENARIO,
        "gates": {},
        "failures": [],
        "controlled_pair": False,
        "normalized_fresh_session_identity": [
            "match_id", "connection",
            "provenance.diagnostics process/startup/tick receipts",
            "window_start", "window_end", "census frame instants (compared as "
            "offsets from each record's own origin, never as absolute values)",
            "trace path", "wall times"],
        "not_required_measured_time": {},
        "not_claimed": [
            "absolute clock origin: the two members are independent sessions, "
            "so only each record's own origin-relative timing is compared (the "
            "carried simulation clock per census frame, EXACTLY, and the "
            "real-time offsets per frame and per event within the "
            "FIXTURE-calibrated margin); the simulation INSTANT of an "
            "individual event is not carried at all — only the census frames "
            "carry the sim clock",
            "live sampling equivalence: that two independent LIVE clients "
            "produce the timing this contract compares. The census clock is "
            "stamped by the server at SERVICE time and received afterwards, "
            "and no live bracket or live cadence measurement exists, so every "
            "verdict reports it UNVERIFIED with the missing evidence named "
            "(see elapsed_time.live_sampling_equivalence)",
            "slot->owner ownership: a 1016 move frame alone does not prove "
            "which actor owned the slot, and no assignment/release lifecycle "
            "publication is carried",
            "presentation/video",
            "publication-to-pulse identity"],
        "actor_mapping": {},
        "chronology": {},
        "outcome": {},
        "slot_ownership": {},
        "measured_time": {},
    }
    failures = report["failures"]

    def gate(name, ok, detail=""):
        report["gates"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(f"{name}: {detail}")
        return ok

    for label, result in (("A", result_a), ("B", result_b)):
        if not isinstance(result, dict):
            failures.append(f"record_{label} is {type(result).__name__}, not "
                            "an object")
    if failures:
        return report

    scenario_failures = []
    for label, result in (("A", result_a), ("B", result_b)):
        declared = result.get("scenario")
        if declared != MINION_SCENARIO:
            scenario_failures.append(
                f"record {label} declares scenario {declared!r}, not the "
                f"minion observation scenario {MINION_SCENARIO!r}")
    if not gate("identity", not scenario_failures,
                "both records are minion observation records"
                if not scenario_failures else "; ".join(scenario_failures)):
        return report

    # -- both records must be accepted on their OWN, one at a time ----------
    verdicts = {}
    for label, result in (("A", result_a), ("B", result_b)):
        verdict = validate_minion_record(result)
        verdicts[label] = verdict
        if verdict["accepted"]:
            detail = ("accepted: coherent, complete and passing on its own "
                      "evidence")
        else:
            detail = "; ".join((verdict["reasons"] + verdict["incomplete"])[:4]) \
                or "not an accepted minion observation"
        gate(f"record_{label}", verdict["accepted"], detail)
    if failures:
        return report

    window_a = result_a["observations"]["minion_window"]
    window_b = result_b["observations"]["minion_window"]
    provenance_a = result_a.get("provenance") or {}
    provenance_b = result_b.get("provenance") or {}

    # -- semantic provenance identity (fresh-session fields normalized away) --
    provenance_failures = []
    for field in ("source_startup_digest", "source_current_digest",
                  "tape_loaded", "client_version"):
        value_a, value_b = provenance_a.get(field), provenance_b.get(field)
        if value_a != value_b:
            provenance_failures.append(f"provenance.{field} differs: "
                                       f"{value_a!r} vs {value_b!r}")
    env_a, env_b = provenance_a.get("env_config"), provenance_b.get("env_config")
    trace_note = ""
    if env_a != env_b:
        if normalize_env_config(env_a) != normalize_env_config(env_b):
            provenance_failures.append(f"provenance.env_config differs: "
                                       f"{env_a!r} vs {env_b!r}")
        else:
            trace_note = (" (trace enable switch normalized: "
                          f"{env_a.get(TRACE_ENV_KEY) if isinstance(env_a, dict) else None!r} "
                          "vs "
                          f"{env_b.get(TRACE_ENV_KEY) if isinstance(env_b, dict) else None!r})")
    file_a = provenance_a.get("tape_file_identity")
    file_b = provenance_b.get("tape_file_identity")
    if file_a is not None or file_b is not None:
        if isinstance(file_a, dict) and isinstance(file_b, dict):
            if file_a.get("file_sha256") and file_b.get("file_sha256") and \
                    file_a["file_sha256"] != file_b["file_sha256"]:
                provenance_failures.append("tape file identity differs")
        else:
            provenance_failures.append(
                "tape_file_identity shape differs: "
                f"{type(file_a).__name__} vs {type(file_b).__name__}")
    gate("provenance", not provenance_failures,
         ("loaded source/tape/config/client identity identical" + trace_note)
         if not provenance_failures else "; ".join(provenance_failures))

    # -- prepared configuration + declared observation duration --------------
    digest_a = window_a.get("profile_digest")
    digest_b = window_b.get("profile_digest")
    gate("profile", digest_a == digest_b,
         f"profile digest {str(digest_a)[:12]}… equal" if digest_a == digest_b
         else f"profile digests differ: {digest_a!r} vs {digest_b!r}")
    declared_a = (result_a.get("fixture_contract") or {}).get(
        "observational_window_s")
    declared_b = (result_b.get("fixture_contract") or {}).get(
        "observational_window_s")
    gate("declared_observation", declared_a == declared_b,
         f"both records declare a {declared_a}s observation window"
         if declared_a == declared_b
         else f"declared durations differ: {declared_a!r} vs {declared_b!r}")

    # -- the carried actor mapping: the eid itself, or an explicit refusal ----
    timelines_a = window_a.get("per_actor_timelines") or {}
    timelines_b = window_b.get("per_actor_timelines") or {}
    eids_a = sorted(int(key) for key in timelines_a)
    eids_b = sorted(int(key) for key in timelines_b)
    mapping = {
        "source": "the carried eid each record's own census observed",
        "mapping": {str(eid): str(eid) for eid in eids_a} if eids_a == eids_b
        else {},
        "tracked_a": eids_a, "tracked_b": eids_b,
    }
    report["actor_mapping"] = mapping
    if eids_a != eids_b:
        report["boundary"] = (
            "no carried actor mapping: the records track different actors "
            "(A: {a}, B: {b}) and carry nothing that relates them, so this "
            "contract refuses the pair as unverified rather than sorting "
            "actors into an invented equivalence. A stable mapping would need "
            "a carried correspondence key (for example the spawn slot or the "
            "hero/unit identity the server assigned) in BOTH records."
            .format(a=eids_a, b=eids_b))
        gate("actor_mapping", False, report["boundary"])
        return report
    team_failures = []
    for key in sorted(timelines_a):
        team_a = timelines_a[key].get("team")
        team_b = timelines_b[key].get("team")
        if team_a != team_b:
            team_failures.append(f"actor {key} is team {team_a!r} in A and "
                                 f"team {team_b!r} in B")
    report["actor_mapping"]["teams"] = {
        key: [timelines_a[key].get("team"), timelines_b[key].get("team")]
        for key in sorted(timelines_a)}
    gate("actor_mapping", not team_failures,
         f"identical carried actor set {eids_a}, same team for each actor"
         if not team_failures else "; ".join(team_failures))

    # -- recompute both outcomes from the carried evidence ------------------
    score_a, reasons_a = minion_pair_score(window_a,
                                           verdicts["A"]["recomputed"])
    score_b, reasons_b = minion_pair_score(window_b,
                                           verdicts["B"]["recomputed"])
    if reasons_a or reasons_b:
        gate("evidence", False,
             "record A: " + "; ".join(reasons_a) + " | record B: "
             + "; ".join(reasons_b))
        return report
    gate("evidence", True, "both records carry recomputable raw evidence")

    report["measured_time"] = {
        "A": minion_measured_time(window_a, verdicts["A"]["recomputed"]),
        "B": minion_measured_time(window_b, verdicts["B"]["recomputed"]),
        "origin": "each record's own window_start; offsets are relative to it",
        "required_equal": False,
        "note": "the raw instants themselves are reported, per record, in that "
                "record's own units; what the pair contract compares is the "
                "elapsed timing, in elapsed_time: the carried simulation clock "
                "EXACTLY (no tolerance) and the origin-relative offsets within "
                "the fixture-calibrated sampling margin, whose scope is "
                "reported beside it and never claimed for a live path",
    }

    # -- the ELAPSED-TIME contract ------------------------------------------
    # The absolute clock origin may differ; the elapsed timing may not. Two
    # clocks are compared, each normalised to the record's OWN origin:
    #
    #  * the SIMULATION clock the census frames were served at (carried
    #    tick/time): the elapsed GAMEPLAY time per frame index, in the
    #    simulation's own units and independent of any client wall clock. It is
    #    compared EXACTLY, per frame index, with no tolerance at all: the world
    #    advances deterministically, so equal elapsed simulation time is what
    #    the same inputs produce, and the four independent fixture productions
    #    of this round carry identical normalised series. No live measurement
    #    establishes how far two independent LIVE samplers can drift, so no
    #    margin is applied here — a difference is reported as a demonstrated
    #    divergence in elapsed gameplay time, not as a bounded tolerance;
    #  * the SAMPLING schedule (each frame's and each event's real-time offset
    #    from that record's own origin): the two records must agree per frame
    #    index and per event within FIXTURE_SAMPLING_MARGIN_S — a margin
    #    calibrated on FIXTURE productions only (see the constant's comment and
    #    ``sampling.calibration`` below) — and each record's own cadence must
    #    sit inside its own declared schedule. An out-of-margin deviation is
    #    refused, and because the margin's scope is the fixture path, it is
    #    reported as UNVERIFIED (not established) with the exact deviation
    #    named, and ``live_sampling_equivalence`` says what is missing.
    #
    # A record that carries no simulation clock cannot evidence the elapsed
    # gameplay time at all, so the pair is refused as UNVERIFIED with the
    # missing field named — never accepted by dropping timing.
    elapsed_failures = []
    elapsed_unverified = []
    contract_a = result_a.get("fixture_contract") or {}
    contract_b = result_b.get("fixture_contract") or {}

    def nominal_interval(window, declared):
        duration = declared.get("observational_window_s")
        samples = window.get("movement_samples")
        if not _is_number(duration) or not _is_int(samples) or samples <= 0:
            return None
        return duration / samples

    def frame_offsets(window):
        origin = window.get("window_start")
        if not _is_number(origin):
            return None
        return [round(instant - origin, OUTCOME_TOTAL_DECIMALS)
                for instant in window.get("census_instants") or []]

    def elapsed_sim_times(window):
        """Elapsed simulation time per frame, normalised to the first frame."""
        times = window.get("census_sim_times")
        if not isinstance(times, list) or not times or \
                not all(_is_number(value) for value in times):
            return None
        return [round(value - times[0], OUTCOME_TOTAL_DECIMALS + 2)
                for value in times]

    def event_offsets(window):
        """Real-time offset of every carried event, in carried order."""
        origin = window.get("window_start")
        if not _is_number(origin):
            return None
        rows = []
        for log, fields in (("combat_log", ("victim", "attacker")),
                            ("death_log", ("victim", "killer")),
                            ("structure_log", ("structure", "attacker"))):
            for entry in window.get(log) or []:
                when = entry.get("time")
                if not _is_number(when):
                    return None
                rows.append((round(when - origin, OUTCOME_TOTAL_DECIMALS),
                             log, entry.get(fields[0]), entry.get(fields[1])))
        rows.sort(key=lambda row: (row[0], row[1], row[2:]))
        return rows

    sim_a = elapsed_sim_times(window_a)
    sim_b = elapsed_sim_times(window_b)
    carried_a = sim_a is not None and all(
        value is not None for value in window_a.get("census_sim_times") or [])
    carried_b = sim_b is not None and all(
        value is not None for value in window_b.get("census_sim_times") or [])
    missing_clock = [f"record {side}" for side, carried in (("A", carried_a),
                                                            ("B", carried_b))
                     if not carried]
    bound = FIXTURE_SAMPLING_MARGIN_S
    if not missing_clock:
        # The elapsed GAMEPLAY time per frame index, from the carried
        # simulation clock: the primary timing claim, in the record's own units
        # and normalised to its own first frame. It is compared EXACTLY, with
        # no tolerance: the world advances deterministically, so the same
        # schedule of observations produces the same elapsed simulation time
        # (the four independent fixture productions of this correction carry
        # identical normalised series), and no live measurement exists that
        # would justify any non-zero allowance for two independent LIVE
        # samplers. A difference is therefore a demonstrated divergence in
        # elapsed gameplay time — reported with its exact size, never absorbed.
        if len(sim_a) != len(sim_b):
            elapsed_failures.append(
                f"different elapsed-simulation-time series lengths: "
                f"{len(sim_a)} vs {len(sim_b)}")
        else:
            differing = [(index, a, b) for index, (a, b) in
                         enumerate(zip(sim_a, sim_b)) if a != b]
            if differing:
                index, sim_time_a, sim_time_b = differing[0]
                elapsed_failures.append(
                    f"elapsed SIMULATION time at census frame {index} differs "
                    f"by {abs(sim_time_a - sim_time_b):.6f}s "
                    f"({sim_time_a:.6f}s vs {sim_time_b:.6f}s) and is compared "
                    "with no tolerance at all: the two records' own carried "
                    "world clocks show they did not observe the same elapsed "
                    "GAMEPLAY time")
    offsets_a = frame_offsets(window_a)
    offsets_b = frame_offsets(window_b)
    if offsets_a is None or offsets_b is None:
        elapsed_failures.append(
            "the census frame offsets cannot be measured: "
            f"{'A' if offsets_a is None else 'B'} carries no usable "
            "window_start to normalise against")
        offsets_a = offsets_a or []
        offsets_b = offsets_b or []
    if len(offsets_a) != len(offsets_b):
        elapsed_unverified.append(
            f"different census frame counts: {len(offsets_a)} vs "
            f"{len(offsets_b)}")
    else:
        for index, (offset_a, offset_b) in enumerate(zip(offsets_a,
                                                         offsets_b)):
            if abs(offset_a - offset_b) > bound:
                elapsed_unverified.append(
                    f"census frame {index} real-time offset differs by "
                    f"{abs(offset_a - offset_b):.3f}s ({offset_a:.3f}s vs "
                    f"{offset_b:.3f}s), beyond the {bound:.3f}s margin "
                    "calibrated on the fixture path")
    # Each record's OWN sampling cadence, against its OWN declaration. The
    # declared schedule is the average cadence its own two declarations imply
    # (declared duration / declared loop samples) and the check is that no
    # gap between two consecutive frames exceeds that average by more than the
    # fixture-calibrated margin — a record whose frames crowd into one part of
    # its declared window has not observed the schedule it claims, whatever the
    # other record did. The deviation from the uniform model is reported as
    # well, for the reader: it characterises the sampler and is not itself a
    # gate, because the declaration only fixes the AVERAGE cadence.
    nominal_a = nominal_interval(window_a, contract_a)
    nominal_b = nominal_interval(window_b, contract_b)
    schedule_deviations = {}
    for side, offsets, nominal in (("A", offsets_a, nominal_a),
                                   ("B", offsets_b, nominal_b)):
        if nominal is None:
            elapsed_unverified.append(
                f"record {side} carries no usable declared observation "
                "duration and loop-sample count, so its sampling schedule "
                "cannot be bounded")
            continue
        if not offsets:
            continue
        gaps = [later - earlier for earlier, later
                in zip(offsets, offsets[1:])]
        worst_gap = max(gaps) if gaps else 0.0
        deviations = [abs(offset - index * nominal)
                      for index, offset in enumerate(offsets)]
        schedule_deviations[side] = {
            "nominal_interval_s": round(nominal, OUTCOME_TOTAL_DECIMALS),
            "worst_gap_s": round(worst_gap, OUTCOME_TOTAL_DECIMALS),
            "max_deviation_s": round(max(deviations), OUTCOME_TOTAL_DECIMALS),
            "frames": len(offsets),
        }
        if worst_gap > nominal + bound:
            index = gaps.index(worst_gap) + 1
            elapsed_unverified.append(
                f"record {side} census frame {index} follows its predecessor "
                f"by {worst_gap:.3f}s, beyond the {nominal:.3f}s+{bound:.3f}s "
                "cadence margin calibrated on the fixture path")
    events_a = event_offsets(window_a)
    events_b = event_offsets(window_b)
    if events_a is None or events_b is None:
        elapsed_unverified.append(
            "the carried event instants cannot be measured: "
            f"{'A' if events_a is None else 'B'} carries no usable "
            "window_start to normalise against")
        events_a = events_a or []
        events_b = events_b or []
    elif len(events_a) != len(events_b):
        elapsed_unverified.append(
            f"different carried event counts: {len(events_a)} vs "
            f"{len(events_b)}")
    else:
        for index, (row_a, row_b) in enumerate(zip(events_a, events_b)):
            if abs(row_a[0] - row_b[0]) > bound:
                elapsed_unverified.append(
                    f"event {index} ({row_a[1]} {row_a[2]}->{row_a[3]}) "
                    f"real-time offset differs by "
                    f"{abs(row_a[0] - row_b[0]):.3f}s ({row_a[0]:.3f}s vs "
                    f"{row_b[0]:.3f}s), beyond the {bound:.3f}s margin "
                    "calibrated on the fixture path")
    # Three-way, and the three ways mean different things:
    #  * FAILED     — a DEMONSTRATED divergence in elapsed gameplay time: the
    #                 carried simulation clocks differ. The comparison is
    #                 exact, so no margin is involved in saying so;
    #  * UNVERIFIED — the elapsed-time equivalence cannot be ESTABLISHED: a
    #                 clock is missing, or a sampling-schedule deviation
    #                 exceeds the fixture-calibrated margin whose scope does
    #                 not reach a live path, or the record's own declared
    #                 schedule is unusable;
    #  * VERIFIED   — the exact simulation-clock comparison passed AND the
    #                 sampling schedule is inside the fixture-calibrated
    #                 margin. ``live_sampling_equivalence`` is reported
    #                 UNVERIFIED beside it and is never claimed by it.
    elapsed_status = "FAILED" if elapsed_failures else (
        "UNVERIFIED" if (elapsed_unverified or missing_clock) else "VERIFIED")
    report["elapsed_time"] = {
        "status": elapsed_status,
        "sim_clock": {
            "A": sim_a, "B": sim_b,
            "source": "minion_window.census_sim_ticks/census_sim_times, the "
                      "world clock each census frame was served at",
            "origin": "each record's own FIRST census frame; the absolute "
                      "clock origin is not compared",
            "comparison": "EXACT, per census frame index: any difference is "
                          "reported as a demonstrated divergence in elapsed "
                          "gameplay time and no tolerance is applied",
            "required_equal": "exactly, per census frame index, after "
                              "normalisation to each record's own first frame. "
                              "Equal elapsed simulation time is what "
                              "same-implementation determinism produces — the "
                              "four independent fixture productions of this "
                              "correction carry identical normalised series — "
                              "and no live measurement establishes any "
                              "non-zero allowance for two independent LIVE "
                              "samplers, so none is applied",
        },
        "fixture_calibration": {
            "label": "fixture",
            "productions": FIXTURE_CALIBRATION_PRODUCTIONS,
            "measured_worst_deviation_s":
                FIXTURE_CALIBRATION_WORST_DEVIATION_S,
            "declared_cadence_s": 1.0,
            "source": "the independent productions ONE writer recorded on "
                      "2026-09-12 for the elapsed-time correction; the "
                      "deviation is that sampler's own, from its own declared "
                      "1.0s cadence, and is reported per record in "
                      "sampling.declared_schedule",
            "scope": "a decision threshold for fixture-shaped observations. "
                     "NOT production measurement uncertainty: no device, no "
                     "emulator and no real transport was measured, and the two "
                     "instants are not simultaneous even offline — the server "
                     "stamps the world clock when it SERVES a request and the "
                     "client receives the reply afterwards. Measured on the "
                     "offline real path, a census-shaped window at this same "
                     "declared cadence deviated by 0.4515s, 52x this "
                     "calibration, so the margin does not transfer to any real "
                     "sampler and an out-of-margin deviation is never called a "
                     "violation of a production bound (see "
                     "live_sampling_equivalence)",
        },
        "live_sampling_equivalence": {
            "status": "UNVERIFIED",
            "claim": "that two independent LIVE clients observing the same "
                     "schedule produce the elapsed timing this contract "
                     "compares, within the margin it applies",
            "why": "the server stamps the world clock at SERVICE time and the "
                   "client receives that reply afterwards, so the two instants "
                   "are not the same event; no live measurement of that "
                   "bracket, and no live measurement of a sampler's cadence "
                   "spread, exists",
            "measured_offline": {
                "receipt_minus_service_median_s": OFFLINE_QA_BRACKET_MEDIAN_S,
                "receipt_minus_service_max_s": OFFLINE_QA_BRACKET_MAX_S,
                "requests": OFFLINE_QA_BRACKET_REQUESTS,
                "census_worst_deviation_from_declared_s":
                    OFFLINE_QA_CENSUS_WORST_DEVIATION_S,
                "source": OFFLINE_QA_BRACKET_SOURCE,
                "scope": "in-process real SandboxQA service over the real "
                         "mailbox: no device, no emulator, no real transport. "
                         "Reported for transparency and NEVER used as a margin "
                         "in any decision of this contract",
            },
            "missing_evidence": [
                "a live production record carrying minion_window."
                "census_sim_ticks / census_sim_times",
                "a bracket measurement on the device path (emulator or "
                "device), which this correction does not run",
            ],
        },
        "sampling": {
            "margin_s": bound,
            "margin_label": "fixture-calibrated; applied only to the sampling "
                            "schedule, never to the simulation clock",
            "declared_schedule": schedule_deviations,
            "frame_offsets": {"A": offsets_a, "B": offsets_b},
            "event_offsets": {"A": events_a, "B": events_b},
        },
        "note": "elapsed timing is compared, not dropped: the carried "
                "SIMULATION clock exactly (no tolerance), and every frame and "
                "event at the same relative real time within a margin whose "
                "scope is the fixture path — absolute instants never are",
    }
    if elapsed_unverified:
        # A deviation beyond a FIXTURE-calibrated margin is refused as not
        # established, not called a violation of a production bound: the
        # margin's scope stops at the fixture path, and
        # ``live_sampling_equivalence`` names what would be needed to extend it.
        report["elapsed_time"]["sampling_unverified"] = list(elapsed_unverified)
        report["elapsed_time"]["sampling_unverified_boundary"] = (
            "the deviation(s) above exceed the margin calibrated on the FIXTURE "
            "path, whose scope does not reach a live sampler: the pair is "
            "refused as NOT ESTABLISHED, and whether a live path could produce "
            "them is left UNVERIFIED (see live_sampling_equivalence)")
    if missing_clock:
        # An absent clock is a GAP, not a pass: whatever the measurable
        # comparisons above showed, the elapsed gameplay time cannot be
        # ESTABLISHED from these records, so the gate stays not-ok and says
        # which field is missing. When the exact simulation-clock comparison
        # also failed, the status is FAILED and the gap is reported alongside.
        report["elapsed_time"]["sim_clock"]["carried"] = {
            "A": bool(carried_a), "B": bool(carried_b)}
        report["elapsed_time"]["missing_evidence"] = (
            "minion_window.census_sim_ticks / census_sim_times (the "
            "simulation clock each census frame was served at)")
        report["elapsed_time"]["unverified_detail"] = (
            "the elapsed GAMEPLAY time cannot be established from "
            + " and ".join(missing_clock)
            + ": the record(s) carry no "
              "minion_window.census_sim_ticks / census_sim_times for their "
              "census frames")
    if elapsed_status == "VERIFIED":
        elapsed_detail = (
            "the carried simulation clock agrees EXACTLY per census frame "
            "index with no tolerance, every frame and event offset agrees "
            "within the fixture-calibrated margin, and each record's own "
            "cadence is inside its own declared schedule; live sampling "
            "equivalence is UNVERIFIED beside this and is not claimed by it "
            "(see elapsed_time.live_sampling_equivalence)")
    else:
        parts = list(elapsed_failures) + list(elapsed_unverified)
        if missing_clock:
            parts.append("UNVERIFIED: "
                         + report["elapsed_time"]["unverified_detail"])
        if elapsed_unverified:
            parts.append("UNVERIFIED: live sampling equivalence — "
                         + report["elapsed_time"]
                         ["sampling_unverified_boundary"])
        elapsed_detail = "; ".join(parts)
    gate("elapsed_time", elapsed_status == "VERIFIED", elapsed_detail)

    # -- observation shape, census points included --------------------------
    shape_failures = []
    for field in ("census_frames", "movement_samples", "tracked_minions"):
        if score_a[field] != score_b[field]:
            shape_failures.append(f"{field}: {score_a[field]!r} vs "
                                  f"{score_b[field]!r}")
    for key in sorted(set(score_a["census_points"]) | set(score_b["census_points"])):
        if score_a["census_points"].get(key) != score_b["census_points"].get(key):
            shape_failures.append(
                f"the carried census points of actor {key} differ "
                f"({len(score_a['census_points'].get(key) or [])} vs "
                f"{len(score_b['census_points'].get(key) or [])} samples)")
    report["observation"] = {
        "census_frames": [score_a["census_frames"], score_b["census_frames"]],
        "movement_samples": [score_a["movement_samples"],
                             score_b["movement_samples"]],
        "presence": {"A": score_a["presence"], "B": score_b["presence"]},
        "note": "the census frames and every carried OBSERVATION point (x, y, "
                "hp, alive) are compared exactly: a different number of "
                "observed frames, a different trajectory or a differently "
                "recorded absence is an observation divergence, not a "
                "normalisation. The instant each observation was stamped with "
                "is the wall clock, so it is reported per record in "
                "measured_time and never compared.",
    }
    gate("observation", not shape_failures,
         "same census frames, samples and carried points"
         if not shape_failures else "; ".join(shape_failures))

    # -- recomputed outcome: counts, stages, damage totals, episodes --------
    count_failures = []
    for name in sorted(set(score_a["summary"]) | set(score_b["summary"])):
        if score_a["summary"].get(name) != score_b["summary"].get(name):
            count_failures.append(
                f"{name}: {score_a['summary'].get(name)!r} vs "
                f"{score_b['summary'].get(name)!r}")
    gate("outcome_counts", not count_failures,
         f"{len(score_a['summary'])} recomputed summary counts equal"
         if not count_failures else "; ".join(count_failures))
    stage_failures = []
    for name in sorted(set(score_a["stage_status"])
                       | set(score_b["stage_status"])):
        if score_a["stage_status"].get(name) != \
                score_b["stage_status"].get(name):
            stage_failures.append(
                f"{name}: {score_a['stage_status'].get(name)!r} vs "
                f"{score_b['stage_status'].get(name)!r}")
    gate("stages", not stage_failures,
         "every recomputed stage status equal" if not stage_failures
         else "; ".join(stage_failures))
    damage_failures = []
    for total in ("combat_damage_total", "structure_damage_total"):
        if score_a[total] != score_b[total]:
            damage_failures.append(f"{total}: {score_a[total]!r} vs "
                                   f"{score_b[total]!r}")
    for actor in sorted(set(score_a["combat_damage_by_actor"])
                        | set(score_b["combat_damage_by_actor"])):
        value_a = score_a["combat_damage_by_actor"].get(actor)
        value_b = score_b["combat_damage_by_actor"].get(actor)
        if value_a != value_b:
            damage_failures.append(f"actor {actor} combat damage: {value_a!r} "
                                   f"vs {value_b!r}")
    report["outcome"] = {
        "summary": {"A": score_a["summary"], "B": score_b["summary"]},
        "stage_status": {"A": score_a["stage_status"],
                         "B": score_b["stage_status"]},
        "combat_damage_total": [score_a["combat_damage_total"],
                                score_b["combat_damage_total"]],
        "structure_damage_total": [score_a["structure_damage_total"],
                                   score_b["structure_damage_total"]],
        "combat_damage_by_actor": {"A": score_a["combat_damage_by_actor"],
                                   "B": score_b["combat_damage_by_actor"]},
        "precision_decimals": OUTCOME_TOTAL_DECIMALS,
        "note": "totals are exact at float32-derived 4-decimal precision; no "
                "relative tolerance is applied",
    }
    gate("damage_totals", not damage_failures,
         f"combat {score_a['combat_damage_total']} and structure "
         f"{score_a['structure_damage_total']} damage equal per actor"
         if not damage_failures else "; ".join(damage_failures))
    episode_failures = []
    for eid in sorted(set(score_a["episodes"]) | set(score_b["episodes"])):
        projection_a = score_a["episodes"].get(eid)
        projection_b = score_b["episodes"].get(eid)
        if projection_a != projection_b:
            differing = [field for field in
                         sorted(set(projection_a or {}) | set(projection_b or {}))
                         if isinstance(projection_a, dict)
                         and isinstance(projection_b, dict)
                         and projection_a.get(field) != projection_b.get(field)]
            episode_failures.append(
                f"actor {eid}: " + (", ".join(differing[:4]) or "projection "
                                    "differs"))
    gate("episodes", not episode_failures,
         f"{len(score_a['episodes'])} per-actor episode projections equal"
         if not episode_failures else "; ".join(episode_failures))

    # -- chronology: the carried order of every log and the merged order ----
    chronology_failures = []
    for field in ("combat_sequence", "death_sequence", "structure_sequence",
                  "event_chronology"):
        if score_a[field] != score_b[field]:
            chronology_failures.append(
                f"{field} differs: {score_a[field]!r} vs {score_b[field]!r}")
    report["chronology"] = {
        "combat_sequence": {"A": score_a["combat_sequence"],
                            "B": score_b["combat_sequence"]},
        "death_sequence": {"A": score_a["death_sequence"],
                           "B": score_b["death_sequence"]},
        "structure_sequence": {"A": score_a["structure_sequence"],
                               "B": score_b["structure_sequence"]},
        "merged_order": {"A": score_a["event_chronology"],
                         "B": score_b["event_chronology"]},
        "note": "each log is compared in its CARRIED order and the three logs "
                "are merged by each record's own instants, so the comparison "
                "is the order the events happened in, never their instants",
    }
    gate("chronology", not chronology_failures,
         "every carried sequence and the merged chronology are identical"
         if not chronology_failures else "; ".join(chronology_failures))

    # -- slot evidence: raw frames compared, ownership explicitly unverified --
    slot_failures = []
    if len(score_a["slot_frames"]) != len(score_b["slot_frames"]):
        slot_failures.append(f"carried slot frames: {len(score_a['slot_frames'])}"
                             f" vs {len(score_b['slot_frames'])}")
    elif score_a["slot_frames"] != score_b["slot_frames"]:
        slot_failures.append("the ordered carried slot frames differ")
    report["slot_ownership"] = {
        "status": "UNVERIFIED",
        "carried_frames": [len(score_a["slot_frames"]),
                           len(score_b["slot_frames"])],
        "note": "a 1016 move frame carries a slot and the owner this record "
                "attributed to it; the record carries no 1010 assignment or "
                "1035/1073 release lifecycle publication, so the slot->owner "
                "binding cannot be shown from these two records and is NOT "
                "part of the equivalence claim. Only the ordered raw frames "
                "are compared.",
    }
    gate("slot_frames", not slot_failures,
         f"{len(score_a['slot_frames'])} carried slot frames in both records "
         f"(ownership NOT claimed)" if not slot_failures
         else "; ".join(slot_failures))

    report["controlled_pair"] = not failures
    return report


def compare_pair(result_a: dict, result_b: dict) -> dict:
    """The PUBLIC compare-pair contract: ONE entry point, dispatched by the
    scenario each record declares.

    Two minion observation records go through ``compare_minion_pair``. A pair
    that mixes the minion scenario with anything else is dispatched there too
    and refused as unverified, because only two records of the SAME scenario
    can be a controlled pair. Every other pair keeps the cast contract
    (``compare_cast_pair``) exactly as it was.

    There is deliberately no second CLI command and no new executable path:
    ``--mode compare-pair`` calls this function and reports whichever contract
    applied, so ``controlled_pair`` keeps its single meaning.
    """
    declared = [result.get("scenario") if isinstance(result, dict) else None
                for result in (result_a, result_b)]
    if MINION_SCENARIO in declared:
        report = compare_minion_pair(result_a, result_b)
        report.setdefault("dispatched_contract", "minion observation pair")
        return report
    report = compare_cast_pair(result_a, result_b)
    report.setdefault("dispatched_contract", "cast trial pair")
    return report


def compare_cast_pair(result_a: dict, result_b: dict) -> dict:
    """Controlled-pair gate between two serialized CAST client results.

    This is the cast contract exactly as it was; ``compare_pair`` dispatches to
    it for every pair that is not a minion observation pair.

    Validates EACH record completely (see validate_trial_record), then
    requires: same named scenario and skill slot, identical declared
    fixture, identical provenance identity (startup/current loaded source,
    tape loaded frames+sha256, tape file sha256, config, client name+build,
    qa dir, profile digest), identical measured gameplay state, and outcome
    agreement (equal attributed event counts and totals exact at the
    recorded decimal precision). Fresh-session identity (match id, ticks,
    connection ids, process ids, startup times, wall times, trace path)
    legitimately differs and is normalized — INCLUDING
    provenance.diagnostics, which is validated for internal coherence
    inside each record (typed fields, active world phase, match agreement
    with that record's own fixture_manifest) and never required to be
    equal across the pair. Presentation is reported separately and never
    contributes to controlled_pair.

    Tolerance and exact resource values are read from the NESTED contract
    (skye/enemy.position_tolerance, skye.position, skye.ranks, etc.),
    never from a flattened (and frequently absent) tolerance key.
    """
    report: dict = {
        "schema_version_required": PAIR_SCHEMA_VERSION,
        "gates": {},
        "failures": [],
        "controlled_pair": False,
        "normalized_fresh_session_identity": ["match_id", "tick", "time",
                                              "connection", "pid",
                                              "startup_at", "trace path",
                                              "wall times"],
        "presentation": {"status": "UNVERIFIED",
                         "note": "presentation is a separate gate; an "
                                 "unreviewed video never becomes visual PASS"},
        "run_a_video": None,
        "run_b_video": None,
    }
    failures = report["failures"]

    def gate(name, ok, detail=""):
        report["gates"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(f"{name}: {detail}")
        return ok

    # -- type guards on the records themselves (no nested .get on null/list) --
    if not isinstance(result_a, dict):
        failures.append(f"record_A is {type(result_a).__name__}, not an "
                        "object")
    if not isinstance(result_b, dict):
        failures.append(f"record_B is {type(result_b).__name__}, not an "
                        "object")
    if failures:
        report["failures"] = failures
        return report

    record_failures = {}
    manifests = {}
    contracts = {}
    for label, result in (("A", result_a), ("B", result_b)):
        record_failures[label], manifests[label], contracts[label] = \
            validate_trial_record(result)
        gate(f"record_{label}", not record_failures[label],
             "; ".join(record_failures[label][:6]) or "valid")
    if failures:
        report["failures"] = failures
        return report

    if result_a.get("scenario") != result_b.get("scenario"):
        gate("identity", False,
             f"different scenarios: {result_a.get('scenario')!r} vs "
             f"{result_b.get('scenario')!r}")
        report["failures"] = failures
        return report
    ma = result_a.get("fixture_manifest")
    mb = result_b.get("fixture_manifest")
    if ma.get("slot") != mb.get("slot"):
        gate("identity", False,
             f"different skill slots: {ma.get('slot')!r} vs {mb.get('slot')!r}")
        report["failures"] = failures
        return report
    gate("identity", "same named scenario and skill slot")

    # semantic provenance equality (fresh-session fields normalized away)
    pa = result_a.get("provenance")
    pb = result_b.get("provenance")
    if not isinstance(pa, dict):
        pa = {}
    if not isinstance(pb, dict):
        pb = {}
    prov_failures = []
    for field in ("source_startup_digest", "source_current_digest",
                  "tape_loaded", "client_version"):
        va, vb = pa.get(field), pb.get(field)
        if va != vb:
            prov_failures.append(f"provenance.{field} differs: {va!r} vs {vb!r}")
    # env_config: HALCYON_TRACE_WIRE is the trace ENABLE SWITCH — production
    # match_server reads only its truthiness and generates its own
    # wire-<ns>.jsonl path — so two ENABLED trials compare equal whatever
    # strings they recorded. Enabled vs disabled, a key that is present
    # rather than absent, and every other flag's exact value do not.
    env_a, env_b = pa.get("env_config"), pb.get("env_config")
    trace_note = ""
    if env_a != env_b:
        if normalize_env_config(env_a) != normalize_env_config(env_b):
            prov_failures.append(
                f"provenance.env_config differs: {env_a!r} vs {env_b!r}")
        else:
            raw_trace_a = env_a.get(TRACE_ENV_KEY) if isinstance(env_a, dict) \
                else None
            raw_trace_b = env_b.get(TRACE_ENV_KEY) if isinstance(env_b, dict) \
                else None
            trace_note = (" (trace enable switch normalized: "
                          f"{raw_trace_a!r} vs {raw_trace_b!r})")
    report["env_trace_normalization"] = {
        "key": TRACE_ENV_KEY,
        "present_a": isinstance(env_a, dict) and TRACE_ENV_KEY in env_a,
        "present_b": isinstance(env_b, dict) and TRACE_ENV_KEY in env_b,
        "raw_a": (env_a.get(TRACE_ENV_KEY) if isinstance(env_a, dict)
                  else None),
        "raw_b": (env_b.get(TRACE_ENV_KEY) if isinstance(env_b, dict)
                  else None),
        "enabled_a": bool(env_a.get(TRACE_ENV_KEY)) if isinstance(env_a, dict)
        else False,
        "enabled_b": bool(env_b.get(TRACE_ENV_KEY)) if isinstance(env_b, dict)
        else False,
        "normalized_equal": normalize_env_config(env_a)
        == normalize_env_config(env_b),
        "note": "HALCYON_TRACE_WIRE is the trace ENABLE SWITCH (the server "
                "reads only its truthiness and generates its own path); the "
                "recorded value is not necessarily the file written. Only the "
                "switch is normalized: enabled vs disabled, a present key vs "
                "an absent one, and every other flag's exact value are "
                "compared, and a present non-string value is rejected per "
                "record as malformed",
    }
    # Optional tape_file_identity metadata; if either side carries it,
    # both must carry a structurally-valid dict. A list here is a
    # structured FAIL (already surfaced by validate_trial_record).
    fa_raw = pa.get("tape_file_identity")
    fb_raw = pb.get("tape_file_identity")
    if fa_raw is not None or fb_raw is not None:
        if isinstance(fa_raw, dict) and isinstance(fb_raw, dict):
            if fa_raw.get("file_sha256") and fb_raw.get("file_sha256") \
                    and fa_raw["file_sha256"] != fb_raw["file_sha256"]:
                prov_failures.append("tape file identity differs: "
                                     f"{fa_raw['file_sha256'][:16]}… vs "
                                     f"{fb_raw['file_sha256'][:16]}…")
        elif fa_raw is None and fb_raw is None:
            pass
        else:
            prov_failures.append("tape_file_identity shape differs: "
                                 f"{type(fa_raw).__name__} vs "
                                 f"{type(fb_raw).__name__}")
    gate("provenance", not prov_failures,
         ("loaded-source/tape/config/client identity identical" + trace_note)
         if not prov_failures else "; ".join(prov_failures))

    # declared fixture + profile digest equality
    declared_equal = ma.get("declared_fixture") == mb.get("declared_fixture")
    gate("declared_fixture", declared_equal,
         "declared fixture contracts identical" if declared_equal
         else "declared fixture contracts differ")
    if ma.get("profile_digest") != mb.get("profile_digest"):
        gate("profile", False,
             f"profile digests differ: {ma.get('profile_digest')!r} vs "
             f"{mb.get('profile_digest')!r}")
        report["failures"] = failures
    else:
        gate("profile", True,
             f"profile digest {str(ma.get('profile_digest'))[:12]}… equal")

    # measured gameplay state equality. Required identity/state fields are
    # checked BEFORE position math; missing or wrongly-typed actor fields
    # are structured failures, never silent defaults.
    sa, sb = ma.get("skye"), mb.get("skye")
    ea, eb = ma.get("enemy"), mb.get("enemy")
    actor_pair = (("skye", sa, sb), ("enemy", ea, eb))
    for actor_label, actor_a, actor_b in actor_pair:
        if not isinstance(actor_a, dict):
            failures.append(f"manifest {actor_label} (A) is "
                            f"{type(actor_a).__name__}, not an object")
            actor_a = {}
        if not isinstance(actor_b, dict):
            failures.append(f"manifest {actor_label} (B) is "
                            f"{type(actor_b).__name__}, not an object")
            actor_b = {}
    state_failures = []
    for actor_label, actor_a, actor_b in actor_pair:
        if not isinstance(actor_a, dict) or not isinstance(actor_b, dict):
            continue
        for field in ("hero_id", "team", "level", "ranks", "ability_points",
                      "max_hp", "max_energy", "hp", "energy", "alive",
                      "inventory", "default_items", "statuses"):
            va, vb = actor_a.get(field), actor_b.get(field)
            if va != vb:
                state_failures.append(
                    f"{actor_label}.{field}: {va!r} != {vb!r}")
    # coordinates are reported separately (with tolerance), but missing or
    # non-finite values are still structured failures.
    coord_failures = []
    for actor_label, actor_a, actor_b in actor_pair:
        if not isinstance(actor_a, dict) or not isinstance(actor_b, dict):
            continue
        for coord in ("x", "y"):
            va, vb = actor_a.get(coord), actor_b.get(coord)
            if (isinstance(va, bool) or not isinstance(va, (int, float))
                    or not math.isfinite(va)) and \
               (isinstance(vb, bool) or not isinstance(vb, (int, float))
                    or not math.isfinite(vb)):
                coord_failures.append(
                    f"{actor_label}.{coord} non-finite in both: {va!r}/{vb!r}")
    gate("state", not state_failures,
         "measured gameplay state identical" if not state_failures
         else "; ".join(state_failures))
    if coord_failures:
        failures.extend(f"positions: {c}" for c in coord_failures)
        report["gates"]["positions"] = {
            "ok": False,
            "detail": "; ".join(coord_failures)}

    # measured positions within the DECLARED tolerance from each record's
    # NESTED contract (skye/enemy.position_tolerance). Flat manifest keys
    # are NOT read; their absence is not a silent default.
    tol_sk_a = (contracts.get("A") or {}).get("skye", {}).get(
        "position_tolerance") if isinstance(
            contracts.get("A"), dict) else None
    tol_sk_b = (contracts.get("B") or {}).get("skye", {}).get(
        "position_tolerance") if isinstance(
            contracts.get("B"), dict) else None
    tol_en_a = (contracts.get("A") or {}).get("enemy", {}).get(
        "position_tolerance") if isinstance(
            contracts.get("A"), dict) else None
    tol_en_b = (contracts.get("B") or {}).get("enemy", {}).get(
        "position_tolerance") if isinstance(
            contracts.get("B"), dict) else None
    if tol_sk_a is None or tol_en_a is None or tol_sk_b is None \
            or tol_en_b is None:
        if "positions" not in report["gates"]:
            gate("positions", False,
                 "nested contract position_tolerance missing for one or "
                 "both records")
    else:
        if tol_sk_a != tol_sk_b or tol_en_a != tol_en_b:
            gate("positions", False,
                 f"nested contract position_tolerance differs: "
                 f"skye {tol_sk_a!r}/{tol_sk_b!r}, "
                 f"enemy {tol_en_a!r}/{tol_en_b!r}")
        elif isinstance(sa, dict) and isinstance(sb, dict) \
                and isinstance(ea, dict) and isinstance(eb, dict):
            sx_a = sa.get("x"); sy_a = sa.get("y")
            sx_b = sb.get("x"); sy_b = sb.get("y")
            ex_a = ea.get("x"); ey_a = ea.get("y")
            ex_b = eb.get("x"); ey_b = eb.get("y")
            skye_dist = math.dist((sx_a, sy_a), (sx_b, sy_b))
            enemy_dist = math.dist((ex_a, ey_a), (ex_b, ey_b))
            if "positions" not in report["gates"]:
                gate("positions",
                     max(skye_dist, enemy_dist) <= max(tol_sk_a, tol_en_a),
                     f"skye Δ{skye_dist:.2f}u, enemy Δ{enemy_dist:.2f}u ≤ "
                     f"tolerance skye {tol_sk_a}u / enemy {tol_en_a}u")

    # outcome: exact counts and exact totals at recorded precision
    raw_obs_a = result_a.get("observations")
    raw_obs_b = result_b.get("observations")
    if not isinstance(raw_obs_a, dict):
        raw_obs_a = {}
    if not isinstance(raw_obs_b, dict):
        raw_obs_b = {}
    class_a = raw_obs_a.get("damage_classification")
    class_b = raw_obs_b.get("damage_classification")
    if not isinstance(class_a, dict):
        class_a = {}
    if not isinstance(class_b, dict):
        class_b = {}
    att_a = class_a.get("attributed") if isinstance(class_a, dict) else None
    att_b = class_b.get("attributed") if isinstance(class_b, dict) else None
    count_a = len(att_a) if isinstance(att_a, list) else 0
    count_b = len(att_b) if isinstance(att_b, list) else 0
    def _safe_total(att):
        total = 0.0
        for h in att or []:
            if not isinstance(h, dict):
                continue
            d = h.get("delta")
            if isinstance(d, bool) or not isinstance(d, (int, float)) \
                    or not math.isfinite(d):
                continue
            total += d
        return round(total, OUTCOME_TOTAL_DECIMALS)
    total_a = _safe_total(att_a)
    total_b = _safe_total(att_b)
    outcome_failures = []
    if count_a != count_b:
        outcome_failures.append(
            f"attributed event counts differ: {count_a} vs {count_b}")
    if total_a != total_b:
        outcome_failures.append(
            f"attributed totals differ at the recorded precision: "
            f"{total_a} vs {total_b}")
    gate("outcome", not outcome_failures,
         f"{count_a} attributed events, totals {total_a}/{total_b}"
         if not outcome_failures else "; ".join(outcome_failures))
    report["outcome"] = {
        "attributed_events": [count_a, count_b],
        "attributed_totals": [total_a, total_b],
        "precision_decimals": OUTCOME_TOTAL_DECIMALS,
        "note": "totals are exact at float32-derived 4-decimal precision; "
                "no relative tolerance is applied",
    }
    for label, obs in (("A", raw_obs_a), ("B", raw_obs_b)):
        if isinstance(obs, dict):
            pres = obs.get("presentation")
            report[f"run_{label}_video"] = (pres.get("video")
                                            if isinstance(pres, dict)
                                            else None)
    report["controlled_pair"] = not failures
    return report


def build_slot_timeline(records, connection=None):
    """Chronological compact-slot ownership events from the live trace.

    1010 publications bind (eid -> slot). The slot is released by the actor's
    1035 DESPAWN and by nothing earlier (server/actor_slots.py contract: the
    allocator clears the slot on 1035, and every despawn path emits the pair
    (1073, 1035) and releases at the 1035 step). 1073 alone retires the
    presentation — for a hero the actor and its compact slot deliberately
    survive it so resurrection can reuse them — so ownership persists across
    a lone 1073 and a slot is never freed early. Returns a sorted list of
    (time, "assign"|"release", slot, eid).
    """
    events = []
    for record in records:
        if connection is not None and record.get("connection") != connection:
            continue
        op = record.get("opcode")
        payload = record.get("payload", "")
        when = record.get("time", 0)
        if op == OP_ENTITY_FULL_UPDATE and len(payload) >= 234:
            events.append((when, "assign", _payload_u8(payload, 116),
                           _payload_u32(payload, 8)))
        elif op == OP_ACTOR_DESPAWN and len(payload) >= 8:
            events.append((when, "release", None, _payload_u32(payload, 0)))
        elif op == OP_ACTOR_RETIRE and len(payload) >= 8:
            # Considered and deliberately NOT a release: retirement keeps the
            # owner bound so a lone 1073 (hero corpse hide) cannot free the
            # slot early. Do not fold this back into the branch above.
            continue
    events.sort(key=lambda item: item[0])
    return events


def slot_owner_at(slot_events, slot, when):
    """Owner eid of ``slot`` at time ``when`` (latest assign wins; the owner's
    1035 release clears it). None = unknown/unowned."""
    owner = None
    for event_time, kind, event_slot, eid in slot_events:
        if event_time > when:
            break
        if kind == "assign" and event_slot == slot:
            owner = eid
        elif kind == "release" and eid == owner:
            owner = None
    return owner


def minion_episodes(tracked, minion_combat, structure_hits, deaths=None,
                    structure_teams=None):
    """Per-minion causal episodes from timestamped timelines and events.

    tracked: eid -> {team, timeline: [(t, x, y, hp, present)]}. ``present``
    is False for censuses where the actor was missing: the absence is carried
    with its instant and the actor's last known position and HP, and the
    CAUSE of an absence is never invented. The lane census serves living
    minions only, so a missing row is neither a death nor an engagement end.

    deaths: [{"time", "victim", "killer"}] — explicit 1072 ENTITY_DEATH
    publications.

    structure_teams: {structure_eid: team_or_None} — the team each observed
    structure belongs to, read from the same snapshot that lists it. A hit on
    a structure whose team this record does not carry cannot be shown to be an
    OPPOSING-structure hit, so it is reported as unverified, never assumed.

    An engagement END is a CARRIED EVENT WITH AN INSTANT, never an absence of
    evidence. The only end event this record can carry is a death: every
    opponent the actor engaged must be evidenced dead (1072 publication, or a
    census sample recording hp <= 0), and ``engagement_end`` is then the
    LATEST such death instant, never earlier than the actor's own last
    recorded involvement. An opponent observed alive, holding position, or
    simply missing from the census carries no end at all, so the claim stays
    unknown — silence and life are not disengagement.

    ``resumed_after_combat`` is a CLAIM, and it carries it only when: the
    actor itself fought a tracked opposing minion; the end above exists; and a
    CONTIGUOUS run of samples strictly after that instant shows the actor
    explicitly alive — ``present`` with a KNOWN hp > 0 (an unknown HP is not
    alive evidence) — with at least two such samples to measure the
    push-direction net march. The run must start at the first sample after the
    end and must not bridge an absence, an unknown sample or the actor's own
    death, so a gap can never be stitched into one surviving interval.

    Movement before the end is pursuit, not resumption; a bystander that only
    moved after someone else's combat has no engagement to resume; and a death
    recorded LATER does not erase an interval that was validly observed alive
    before it (``death_time`` is reported separately). A participant whose end
    is unknown, or that was not observed alive in an unbroken interval after
    it, keeps ``resumed_after_combat`` None and states why in
    ``resumption_unverified`` instead of guessing.

    STRUCTURE_INTERACTION is bound to the SAME participant whose sequence was
    accepted. ``structure_hits`` keeps every hit the actor made (raw time,
    structure, delta and the structure team the record carries), and
    ``structure_sequence`` carries a hit only when it is that participant's
    own, strictly after its carried engagement end, strictly before its own
    death, against a structure whose recorded team is EXPLICITLY the opposing
    one — team 1 versus team 2, the only two teams of the match: a missing
    team, an unknown or invalid value, a boolean or any non-integer is not an
    opposing side and never qualifies — and already preceded by at least two
    contiguous observed-alive samples whose push-direction march is >= 1.0 u
    whose run REACHES the hit: every census sample between the engagement end
    and the hit must observe the actor alive, so a prefix followed by a
    carried absence, an unknown hp or a dead sample does not certify a hit
    across the gap. Every hit that cannot be shown that way is reported in
    ``structure_unverified`` with its reason rather than dropped or invented;
    one minion's combat and another's hit never satisfy the sequence.
    """
    deaths = deaths or []
    episodes = {}
    combat_by_eid: dict[int, list] = {}
    for event in minion_combat:
        for role_eid in (event["victim"], event["attacker"]):
            combat_by_eid.setdefault(role_eid, []).append(event)
    structure_by_eid: dict[int, list] = {}
    for event in structure_hits:
        structure_by_eid.setdefault(event["attacker"], []).append(event)
    death_time_by_eid: dict[int, float] = {}
    for event in deaths:
        victim, when = event.get("victim"), event.get("time")
        if victim is None or when is None:
            continue
        if victim not in death_time_by_eid or when < death_time_by_eid[victim]:
            death_time_by_eid[victim] = when
    # A census row recording hp <= 0 is lethal evidence too: that is a
    # recorded measurement, not an inference from a missing row.
    lethal_sample_by_eid: dict[int, float] = {}
    for other_eid, other in tracked.items():
        for row in other.get("timeline") or []:
            if row[3] is not None and row[3] <= 0:
                if (other_eid not in lethal_sample_by_eid
                        or row[0] < lethal_sample_by_eid[other_eid]):
                    lethal_sample_by_eid[other_eid] = row[0]

    def death_evidence(other_eid):
        """(instant, kind) that ``other_eid`` is evidenced dead, or None.

        Kinds: "death-publication" (1072) and "death-sample" (a census row
        with hp <= 0). When both are carried the EARLIER instant is the
        death, and an absence is NEVER death evidence: the census serves
        living minions only, so a missing row states only that the actor was
        not observed.
        """
        candidates = []
        if other_eid in death_time_by_eid:
            candidates.append((death_time_by_eid[other_eid],
                               "death-publication"))
        if other_eid in lethal_sample_by_eid:
            candidates.append((lethal_sample_by_eid[other_eid],
                               "death-sample"))
        return min(candidates) if candidates else None

    def observed_alive(row) -> bool:
        """Explicit live evidence: present AND a known hp above zero."""
        return bool(row[4]) and row[3] is not None and row[3] > 0

    def observed_alive_after(other_eid, when) -> bool:
        other = tracked.get(other_eid) or {}
        return any(observed_alive(row) and row[0] > when
                   for row in other.get("timeline") or [])

    for eid, entry in tracked.items():
        team = entry.get("team")
        timeline = entry.get("timeline") or []
        episode = {"approach": None, "combat_participant": False,
                   "opponents": [], "engagement_end": None,
                   "end_evidence": None, "opponent_closure": {},
                   "unaccounted_opponents": [],
                   "resumed_after_combat": None, "resumption_unverified": None,
                   "alive_samples_after_end": None, "structure_hit": False,
                   "structure_hits": [], "structure_sequence": None,
                   "structure_unverified": None,
                   "last_combat_time": None, "absent_since": None,
                   "death_time": None, "death_evidence": None}
        episodes[eid] = episode
        # Absence, death evidence and combat participation are observations in
        # their own right: they are recorded even when this actor was too
        # briefly visible to measure an approach or a march.
        episode["absent_since"] = next(
            (row[0] for row in timeline if not row[4]), None)
        own_death = death_evidence(eid)
        episode["death_time"] = own_death[0] if own_death else None
        episode["death_evidence"] = own_death[1] if own_death else None
        episode["structure_hit"] = bool(structure_by_eid.get(eid))
        participations = combat_by_eid.get(eid) or []
        episode["combat_participant"] = bool(participations)
        if participations:
            episode["last_combat_time"] = max(
                event["time"] for event in participations)
            episode["opponents"] = sorted({
                other for event in participations
                for other in (event["victim"], event["attacker"])
                if other != eid})
        observed = [row for row in timeline if observed_alive(row)]
        if team not in (1, 2):
            continue
        if len(observed) >= 2:
            first, last = observed[0], observed[-1]
            march = (last[1] - first[1]) if team == 1 else (first[1] - last[1])
            episode["approach"] = round(march, 3)
        # Raw structure observations, kept whatever the verdict is: every hit
        # this actor made inside the window, with the team the record carries
        # for the structure (None when the record does not carry one).
        hits = sorted(structure_by_eid.get(eid) or [],
                      key=lambda hit: hit["time"])
        episode["structure_hits"] = [
            {"time": round(hit["time"], 3), "structure": hit["structure"],
             "delta": hit.get("delta"),
             "structure_team": (structure_teams or {}).get(hit["structure"])}
            for hit in hits]
        episode["structure_hit"] = bool(hits)

        def push_march(run):
            """Push-direction net march of a run (None below two samples)."""
            if len(run) < 2:
                return None
            net = (run[-1][1] - run[0][1]) if team == 1 \
                else (run[0][1] - run[-1][1])
            return round(net, 3)

        def alive_run_before(when):
            """The contiguous observed-alive run that starts at the first
            sample after the closure and stops at ``when`` (None = the whole
            observed window). An absence, an unknown-HP sample or the actor's
            own death ends the run, so nothing is stitched across a gap.
            """
            run = []
            for row in timeline:
                if end is None or row[0] <= end:
                    continue
                if when is not None and row[0] >= when:
                    break
                if episode["death_time"] is not None and \
                        row[0] >= episode["death_time"]:
                    break
                if not observed_alive(row):
                    break
                run.append(row)
            return run

        def structure_verdict(hit):
            """Why this hit does or does not extend THIS actor's accepted
            sequence. An empty ``reasons`` list means it is proven: the hit is
            this participant's own, strictly after its carried engagement end,
            strictly before its own death, against a structure whose recorded
            team is EXPLICITLY the opposing one (teams 1 and 2 are the only
            real teams: any other value, a missing value, a boolean or a
            non-integer is not opposing), and the resumption was already
            measured before it by at least two contiguous observed-alive
            samples whose run reaches the hit without a break.
            """
            reasons = []
            when = hit["time"]
            structure_team = (structure_teams or {}).get(hit["structure"])
            if structure_team is None:
                reasons.append(
                    f"the record does not carry a team for structure "
                    f"{hit['structure']}, so a hit on the OPPOSING structure "
                    "cannot be established")
            elif isinstance(structure_team, bool) or \
                    not isinstance(structure_team, int):
                reasons.append(
                    f"the record carries {structure_team!r} as the team of "
                    f"structure {hit['structure']}, which is not a team "
                    "identity: only the integers 1 and 2 name a side, so the "
                    "hit cannot be established as opposing")
            elif structure_team not in (1, 2):
                reasons.append(
                    f"the record carries {structure_team!r} as the team of "
                    f"structure {hit['structure']}, which is not one of the two "
                    "teams of the match: an unknown or invalid team is not the "
                    "opposing side, so the hit cannot be established as "
                    "opposing")
            elif structure_team == team:
                reasons.append(
                    f"structure {hit['structure']} is on the actor's own team "
                    f"{team}: a friendly structure is not the opposing push "
                    "the stage measures")
            if not participations:
                reasons.append(
                    "the actor is not an opposing-combat participant, so it "
                    "has no proven engagement end and no measured resumption "
                    "of its own to bind this hit to")
            elif end is None:
                reasons.append(
                    "the actor's engagement has no carried end instant, so the "
                    "hit cannot be placed after a proven end")
            elif when <= end:
                reasons.append(
                    f"the hit at t={when:.2f} is not later than the "
                    f"engagement-end instant t={end:.2f}")
            if episode["death_time"] is not None and \
                    when >= episode["death_time"]:
                reasons.append(
                    f"the hit at t={when:.2f} is at or after the actor's own "
                    f"death t={episode['death_time']:.2f}: a post-death hit "
                    "cannot qualify")
            run = alive_run_before(when)
            march = push_march(run)
            # The measured resumption must REACH the hit: every census sample
            # between the closure and the hit has to observe the actor alive.
            # Two alive samples followed by an absence, an unknown hp or a dead
            # sample do not certify a same-actor sequence across that gap —
            # nothing in this record re-establishes the actor's identity or
            # life inside it, so the hit stays unverified with that reason.
            between = [row for row in timeline
                       if end is not None and end < row[0] < when]
            uninterrupted = len(between) == len(run)
            if not uninterrupted:
                reasons.append(
                    f"the observed-alive interval does not reach the hit: "
                    f"{len(between) - len(run)} of {len(between)} census "
                    "sample(s) between the engagement-end instant and the hit "
                    "are an absence, an unknown hp or a dead sample, so the "
                    "actor is not continuously observed alive up to the hit "
                    "and no uninterrupted same-actor sequence is established")
            if len(run) < 2:
                reasons.append(
                    f"only {len(run)} contiguous observed-alive census "
                    "sample(s) lie between the engagement end and the hit (two "
                    "are needed for the resumption to be measured before it)")
            elif march < 1.0:
                reasons.append(
                    f"the push measured before the hit is {march:.2f} u, below "
                    "the 1.0 u resumption threshold")
            return {"time": when, "structure": hit["structure"],
                    "structure_team": structure_team,
                    "delta": hit.get("delta"), "samples": len(run),
                    "samples_between": len(between),
                    "uninterrupted": uninterrupted,
                    "march": march, "reasons": reasons}

        def analyse_structure_hits():
            proven, unproven = [], []
            for hit in hits:
                verdict = structure_verdict(hit)
                (unproven if verdict["reasons"] else proven).append(verdict)
            if proven:
                first = proven[0]
                episode["structure_sequence"] = {
                    "time": first["time"], "structure": first["structure"],
                    "structure_team": first["structure_team"],
                    "delta": first["delta"],
                    "samples_before_hit": first["samples"],
                    "march_before_hit": first["march"]}
            if unproven:
                episode["structure_unverified"] = {
                    "hits": len(hits), "unproven": len(unproven),
                    "reasons": unproven[0]["reasons"]}

        end = None
        if not participations:
            # A bystander damaged a structure: the hit is preserved raw and
            # stays UNVERIFIED, because the sequence belongs to the combat
            # participant, never to whoever happened to hit the structure.
            if hits:
                analyse_structure_hits()
            continue
        opponents = episode["opponents"]
        # Closure: each opponent must be evidenced dead, and the engagement
        # cannot have ended before this actor's own last recorded involvement.
        closures = {}
        unaccounted = []
        for opponent in opponents:
            death = death_evidence(opponent)
            if death is None:
                unaccounted.append(opponent)
                closures[str(opponent)] = "no-death-evidence"
            else:
                closures[str(opponent)] = f"{death[1]}@{death[0]:.2f}"
        episode["opponent_closure"] = closures
        episode["unaccounted_opponents"] = unaccounted
        end = None
        if not unaccounted:
            end = max([death_evidence(opponent)[0] for opponent in opponents]
                      + [episode["last_combat_time"]])
        episode["engagement_end"] = end
        if unaccounted:
            episode["end_evidence"] = "unknown"
        elif all(kind.startswith("death-publication")
                 for kind in closures.values()):
            episode["end_evidence"] = "opponent-death-publication"
        else:
            episode["end_evidence"] = "opponent-death-sample"
        # The resumption interval: strictly after the closure instant, and
        # CONTIGUOUS — an absence, an unknown sample or the actor's own death
        # ends it, so nothing is stitched across a gap.
        after = [row for row in timeline if end is not None and row[0] > end]
        interval = alive_run_before(None)
        episode["alive_samples_after_end"] = len(interval)
        march_after = push_march(interval)
        reasons = []
        if unaccounted:
            living = [opponent for opponent in unaccounted
                      if observed_alive_after(opponent, episode["last_combat_time"])]
            named = ", ".join(str(opponent) for opponent in unaccounted)
            if living:
                reasons.append(
                    f"no disengagement evidence is carried for opposing "
                    f"participant(s) {named}: they were still observed alive "
                    "after the last contact, and an opponent observed alive "
                    "(or holding position, or leaving the census) is not "
                    "evidence that the engagement ended — the record carries "
                    "no death for them, so the end is unknown")
            else:
                reasons.append(
                    f"opposing participant(s) {named} were not observed alive "
                    "after the last contact and no death is carried for them: "
                    "the end of the engagement is unknown (an absence is not "
                    "a death)")
        elif not after:
            reasons.append(
                "no lane census sample after the engagement-end instant fell "
                "inside the observed window")
        elif not interval:
            reasons.append(
                "the first census sample after the engagement-end instant "
                "does not observe the actor explicitly alive (present with a "
                "known hp > 0), so no contiguous observed-alive interval "
                "starts there")
        elif len(interval) < 2:
            reasons.append(
                f"only {len(interval)} contiguous observed-alive census "
                "sample(s) after the engagement-end instant (two are needed "
                "to measure a march)")
        if reasons:
            episode["resumption_unverified"] = {"reasons": reasons,
                                                "march_after": march_after}
        else:
            episode["resumed_after_combat"] = march_after
        if hits:
            analyse_structure_hits()
    return episodes


def locate_enemy_aim(png_path: str | os.PathLike, *, fallback: tuple[int, int],
                     bar_to_ground_px: int = 100, bar_to_body_px: int = 68,
                     ground: bool = True) -> tuple[tuple[int, int], str]:
    """Locate the enemy hero's red-orange health bar in a fresh screenshot
    (a drained or distant hero's bar shrinks below 40 px, so the
    minimum run is 10)
    and aim at the enemy's GROUND point below it (measured live 2026-09-10 by
    three calibration casts: the bar floats ~100 px above the enemy's ground
    contact at the 4 u duel separation; 58 px landed 2.1 u short, 12 px
    4.6 u short). Falls back
    to the verified profile coordinates (recorded as such) when nothing
    matches -- a missed localization must stay visible in the evidence.
    """
    try:
        from PIL import Image
        image = Image.open(png_path).convert("RGB")
    except Exception:
        return fallback, "fallback:screencap-unavailable"
    width, height = image.size
    pixels = image.load()
    best = None                    # (run_length, cx, y, run_start_x)
    y0, y1 = int(height * 0.08), int(height * 0.60)
    x0, x1 = int(width * 0.20), int(width * 0.95)
    for y in range(y0, y1):
        run = 0
        for x in range(x0, x1):
            r, g, b = pixels[x, y]
            # measured live: the enemy bar is a red->orange gradient
            # (r 165..247, g 40..150, b < 120); ally bars are blue.
            if r > 150 and r - g >= 60 and b < 120:
                run += 1
                continue
            # drained/distant bars shrink: accept >= 10 px
            if 10 <= run <= 140 and (best is None or run > best[0]):
                best = (run, x - run // 2, y, x - run)
            run = 0
        if 10 <= run <= 140 and (best is None or run > best[0]):
            best = (run, x1 - run // 2, y, x1 - run)
    if best is None:
        return fallback, "fallback:enemy-bar-not-found"
    length, cx, cy, run_start = best
    # The bar is right-offset from the model: a body tap aims at the bar's
    # left quarter (measured live: bar-center taps landed on ground beside
    # the model), a ground aim at the bar center.
    if ground:
        return (int(cx), int(min(height - 60, cy + bar_to_ground_px))),             "located:enemy-health-bar"
    return (int(run_start + length // 5),
            int(min(height - 60, cy + bar_to_body_px))),         "located:enemy-health-bar"


def timer_tag_eid(record: dict) -> tuple[int, int] | None:
    """(eid, tag) from a 1162 cooldown timer, else None."""
    if record.get("opcode") != OP_TIMER_TICK:
        return None
    payload = record.get("payload", "")
    if len(payload) < 16:                      # 8 semantic bytes
        return None
    eid = _payload_u32(payload, 0)
    tag = _payload_u32(payload, 4)
    return eid, tag


# ---------------------------------------------------------------------------
# Bounded adapters (the only places that touch adb / the QA mailbox)
# ---------------------------------------------------------------------------

class Adb:
    """Subprocess adb adapter; every call is bounded and serial-scoped."""

    def __init__(self, serial: str) -> None:
        self.serial = serial

    def _run(self, *arguments: str, timeout: float = 15.0) -> subprocess.CompletedProcess:
        return subprocess.run(["adb", "-s", self.serial, *arguments],
                              capture_output=True, timeout=timeout)

    def shell(self, command: str, *, timeout: float = 15.0) -> str:
        completed = self._run("shell", command, timeout=timeout)
        if completed.returncode != 0:
            raise RuntimeError(
                f"adb shell {command!r} failed ({completed.returncode}): "
                f"{completed.stderr.decode('utf-8', 'replace').strip()}")
        return completed.stdout.decode("utf-8", "replace").strip()

    def back(self) -> None:
        self.shell("input keyevent 4")

    def client_version(self, package: str = ANDROID_PACKAGE) -> dict:
        """Both build identities of the owned client, from dumpsys."""
        output = self.shell(f"dumpsys package {package}")
        name = re.search(r"versionName=(\S+)", output)
        code = re.search(r"versionCode=(\d+)", output)
        return {"version_name": name.group(1) if name else None,
                "version_code": int(code.group(1)) if code else None}

    def wm_size(self) -> tuple[int, int]:
        output = self.shell("wm size")
        match = re.search(r"(\d+)x(\d+)", output)
        if not match:
            raise RuntimeError(f"unparseable wm size: {output!r}")
        return int(match.group(1)), int(match.group(2))

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, *, duration_ms: int = 250) -> None:
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")

    def screencap(self, destination: Path) -> dict:
        started = time.time()
        completed = self._run("exec-out", "screencap", "-p", timeout=30.0)
        if completed.returncode != 0 or not completed.stdout:
            raise RuntimeError(f"screencap failed ({completed.returncode})")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(completed.stdout)
        return {"path": str(destination), "captured_at": started,
                "bytes": len(completed.stdout)}

    def start_screenrecord(self, device_path: str, *, time_limit: float) -> subprocess.Popen:
        """Start a bounded recording and retain its remote PID receipt.

        The shell replaces itself with screenrecord, preserving the reported
        PID. Exclusive receipt creation refuses an existing recording path.
        """
        seconds = max(1, int(math.ceil(time_limit)))
        pid_path = device_path + ".pid"
        command = (f"set -C; printf '%s\\n' \"$$\" > {shlex.quote(pid_path)} "
                   f"&& exec screenrecord --time-limit {seconds} "
                   f"{shlex.quote(device_path)}")
        recorder = subprocess.Popen(
            ["adb", "-s", self.serial, "shell", command],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and recorder.poll() is None:
                try:
                    receipt = self.shell(f"cat {shlex.quote(pid_path)}", timeout=2.0)
                except RuntimeError:
                    time.sleep(0.05)
                    continue
                if not receipt:
                    # The exclusive redirection creates the file before
                    # printf fills it; an early read can legitimately be empty.
                    time.sleep(0.05)
                    continue
                if not re.fullmatch(r"[1-9][0-9]*", receipt) or int(receipt) < 2:
                    raise RuntimeError("invalid screenrecord PID receipt")
                recorder.halcyon_recording = {
                    "remote_pid": int(receipt), "serial": self.serial,
                    "device_path": device_path, "pid_path": pid_path,
                    "time_limit": seconds}
                return recorder
            raise RuntimeError("screenrecord did not produce a live PID receipt")
        except Exception:
            if recorder.poll() is None:
                recorder.terminate()
                try:
                    recorder.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    recorder.kill()
                    recorder.wait(timeout=2.0)
            # With no trusted remote identity, leave the bounded recorder
            # and its partial output intact instead of signaling by name.
            raise

    def stop_screenrecord(self, recorder: subprocess.Popen) -> None:
        """Signal only the recorded PID while it still owns this output."""
        identity = getattr(recorder, "halcyon_recording", None)
        if (not isinstance(identity, dict) or identity.get("serial") != self.serial
                or type(identity.get("remote_pid")) is not int
                or identity["remote_pid"] < 2):
            raise RuntimeError("screenrecord has no trusted remote identity")
        pid = identity["remote_pid"]
        expected = "\n".join(("screenrecord", "--time-limit",
                              str(identity["time_limit"]), identity["device_path"]))
        # The command-line check and signal share one remote shell request.
        # A reused PID belonging to another recording must not be stopped.
        command = (
            f"if [ ! -e /proc/{pid}/cmdline ]; then exit 0; fi; "
            f"halcyon_cmd=$(tr '\\000' '\\n' < /proc/{pid}/cmdline) || exit 1; "
            f"case \"$halcyon_cmd\" in {shlex.quote(expected)}|"
            f"{shlex.quote('/system/bin/' + expected)}) kill -2 {pid} ;; "
            "*) echo 'screenrecord identity mismatch; refused to signal' >&2; "
            "exit 1 ;; esac")
        self.shell(command, timeout=5.0)

    def pull(self, device_path: str, destination: Path) -> dict:
        completed = self._run("pull", device_path, str(destination), timeout=60.0)
        if completed.returncode != 0:
            raise RuntimeError(f"adb pull failed: {completed.stderr.decode(errors='replace')}")
        return {"path": str(destination), "bytes": destination.stat().st_size}


class QaSession:
    """Existing QA submit semantics with explicit directory and unique IDs."""

    def __init__(self, qa_dir: str, *, submit: Callable | None = None) -> None:
        self.qa_dir = str(Path(qa_dir).resolve())
        self._submit = submit
        self.receipts: list[dict] = []
        self._sequence = 0

    def _next_id(self, label: str) -> str:
        self._sequence += 1
        return f"scenario-client-{label}-{int(time.time())}-{self._sequence}"

    def submit(self, command: dict, *, label: str, timeout: float = 5.0) -> dict:
        # The QA mailbox bounds a single wait to 0..10 s; the driver's larger
        # --timeout is a stage bound, not a mailbox bound (live-run finding
        # 2026-09-10: --timeout 25 crashed the first submit).
        timeout = min(max(0.0, float(timeout)), 10.0)
        if self._submit is None:
            previous = os.environ.get("HALCYON_QA_DIR")
            os.environ["HALCYON_QA_DIR"] = self.qa_dir
            try:
                from Tools.sandbox_qa import submit as qa_submit
                result = qa_submit(command, timeout=timeout,
                                   request_id=self._next_id(label))
            finally:
                if previous is None:
                    os.environ.pop("HALCYON_QA_DIR", None)
                else:
                    os.environ["HALCYON_QA_DIR"] = previous
        else:
            result = self._submit(command, timeout=timeout,
                                  request_id=self._next_id(label))
        self.receipts.append({"label": label, "command": command, "result": result,
                              "at": time.time()})
        return result

    def snapshot(self, *, timeout: float = 5.0) -> dict:
        result = self.submit({"command": "snapshot"}, label="snapshot", timeout=timeout)
        if result.get("pending"):
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"snapshot request not acknowledged within {timeout}s; receipt "
                f"preserved (id {result.get('id')}, result path {result.get('result_path')})")
        if not result.get("ok"):
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"snapshot rejected: {result.get('error', 'unknown reason')}")
        return result.get("result") or {}


# ---------------------------------------------------------------------------
# Session preconditions
# ---------------------------------------------------------------------------

def _state_path(qa_dir: str) -> Path:
    return Path(qa_dir) / "state.json"


def read_state(qa_dir: str) -> dict:
    path = _state_path(qa_dir)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ClientStageFailure("SETUP", "FAIL",
                                 f"session state.json unreadable at {path}: {exc}")
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClientStageFailure("SETUP", "FAIL", f"state.json is not valid JSON: {exc}")
    if not isinstance(state, dict):
        raise ClientStageFailure("SETUP", "FAIL", "state.json must be a JSON object")
    return state


def verify_session(qa: QaSession, *, timeout: float) -> dict:
    """Owned paths, WORLD phase, progressing simulation via read-only snapshots."""
    qa_dir = qa.qa_dir
    resolved = Path(qa_dir).resolve()
    repository = ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ClientStageFailure("SETUP", "FAIL",
                                 f"QA directory must stay outside the repository: {resolved}")
    if not Path(qa_dir).is_dir():
        raise ClientStageFailure("SETUP", "FAIL", f"QA directory does not exist: {qa_dir}")
    first = read_state(qa_dir)
    first_snapshot = qa.snapshot(timeout=timeout)
    tick = first_snapshot.get("tick")
    if not isinstance(tick, int):
        raise ClientStageFailure("SETUP", "FAIL",
                                 f"snapshot has no integer tick: {first_snapshot.get('tick')!r}")
    if first_snapshot.get("phase") != "world":
        raise ClientStageFailure(
            "SETUP", "FAIL",
            f"session phase is {first_snapshot.get('phase')!r}, not an active WORLD match")
    time.sleep(max(0.25, timeout / 4))
    second_snapshot = qa.snapshot(timeout=timeout)
    if second_snapshot.get("tick", tick) <= tick:
        finished = second_snapshot.get("match_finished")
        raise ClientStageFailure(
            "SETUP", "FAIL",
            f"simulation is not progressing (tick {tick} -> {second_snapshot.get('tick')}); "
            f"a stale session after disconnect is not valid even when match_finished={finished}")
    heroes = second_snapshot.get("heroes") or []
    skye = next((row for row in heroes if row.get("hero_id") == SKYE_HERO_ID), None)
    if skye is None:
        raise ClientStageFailure(
            "SETUP", "FAIL",
            f"no hero_id {SKYE_HERO_ID} (Skye) in session snapshot heroes: "
            f"{[row.get('hero_id') for row in heroes]}")
    if not skye.get("alive"):
        raise ClientStageFailure("SETUP", "FAIL", "Skye is dead in the current session")
    return {"snapshot": second_snapshot, "tick": second_snapshot["tick"],
            "state_file_tick": first.get("tick"), "heroes": heroes}


def verify_resolution(adb: Adb, profile: dict) -> dict:
    width, height = adb.wm_size()
    expected = (profile["width"], profile["height"])
    if (width, height) != expected and (height, width) != expected:
        raise ClientStageFailure(
            "SETUP", "FAIL",
            f"device resolution {width}x{height} does not match the profile "
            f"{expected[0]}x{expected[1]}; profile coordinates must not be applied "
            "to an unverified layout")
    return {"width": width, "height": height}


def verify_trace(trace_path: str | None, *, timeout: float) -> TraceTail:
    if not trace_path:
        raise ClientStageFailure("SETUP", "FAIL", "--wire-trace is required")
    tail = TraceTail(trace_path)
    if not tail.path.is_file():
        raise ClientStageFailure("SETUP", "FAIL", f"wire trace not found: {trace_path}")
    tail.wait_for(lambda _record: True, min(timeout, 2.0))
    if not tail.records:
        raise ClientStageFailure(
            "SETUP", "FAIL",
            "wire trace exists but produced no complete records; it may be stale "
            "or belong to a finished connection")
    return tail


def select_connection(tail: TraceTail, explicit: int | None, *,
                      max_age: float) -> int | None:
    """Fresh matching connection: explicit id, else the most recently active.

    An explicitly requested connection must still be LIVE — its most recent
    record inside the freshness window — otherwise the trace is stale.
    """
    now = time.time()

    def fresh(record: dict) -> bool:
        return (isinstance(record.get("time"), (int, float))
                and now - record["time"] <= max_age)

    if explicit is not None:
        known = {record.get("connection") for record in tail.records}
        if explicit not in known:
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"connection {explicit} has no records in the trace; known: {sorted(known, key=repr)}")
        if not any(record.get("connection") == explicit and fresh(record)
                   for record in tail.records):
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"connection {explicit} has no records within {max_age:.0f}s — "
                "a stale (disconnected) trace connection must not receive UI input")
        return explicit
    recent = [record.get("connection") for record in tail.records if fresh(record)]
    if not recent:
        raise ClientStageFailure(
            "SETUP", "FAIL",
            f"no trace records within {max_age:.0f}s; the trace connection may be "
            "stale (disconnected) — refusing to send UI input against it")
    counts: dict[Any, int] = {}
    for connection in recent:
        counts[connection] = counts.get(connection, 0) + 1
    return max(counts, key=counts.get)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class ClientDriver:
    """One bounded scenario against one owned live session."""

    def __init__(self, scenario: str, *, adb: Adb, qa: QaSession, tail: TraceTail,
                 connection: int | None, profile: dict, out_dir: Path,
                 timeout: float, profile_digest: str | None = None) -> None:
        self.scenario = scenario
        self.adb = adb
        self.qa = qa
        self.tail = tail
        self.connection = connection
        self.profile = profile
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.stages: dict[str, dict] = {name: {"status": "PENDING", "detail": ""}
                                        for name in STAGES}
        self.observations: dict[str, Any] = {}
        self.preparation: list[dict] = []
        self.gestures: list[dict] = []
        self.artifacts: list[str] = []
        self.capture_processes: list[subprocess.Popen] = []
        self.device_recordings: list[str] = []
        self.capture: dict | None = None
        self._framing_clear = False
        self.profile_digest: str | None = profile_digest
        self._source_digest = None
        self._source_current = None
        self._tape_loaded = None
        self._tape_file = None
        self._env_config = None
        self._diag_linkage: dict | None = None
        self._diag_linkage_end: dict | None = None
        self._client_version = None
        self._skye: dict | None = None
        self._enemy: dict | None = None
        # None until this trial declares one: a failure before (or during)
        # contract validation must still serialize, so the failure path
        # never reads an attribute that was never set.
        self.fixture_contract: dict | None = None

    # -- bookkeeping --------------------------------------------------------

    def stage(self, name: str, status: str, detail: str = "") -> None:
        self.stages[name] = {"status": status, "detail": detail}

    def provenance_frame(self) -> dict:
        """The trial provenance both record kinds carry verbatim.

        A PASS record and a FAIL record must be able to evidence the same
        things — the source, the loaded tape, the prepared configuration, the
        client build and the typed process/startup/session linkage at both
        endpoints — so both go through this one frame rather than each
        assembling its own. Every field is None when it was never observed;
        none is a default.
        """
        return {
            "source_startup_digest": self._source_digest,
            "source_current_digest": self._source_current,
            "tape_loaded": self._tape_loaded,
            "tape_file_identity": self._tape_file,
            "env_config": self._env_config,
            "client_version": self._client_version,
            "qa_dir": self.qa.qa_dir,
            # The typed linkage validated at the setup boundary, carried
            # verbatim: pid, startup_at, match_id, phase, match_finished,
            # tick and time. When no receipt arrived this stays None and
            # the pair gate refuses the record — never a default.
            "diagnostics": self._diag_linkage,
            # The end-of-trial receipt (same typed schema), read after the
            # whole action sequence. Together with the initial receipt it
            # proves one uninterrupted live world trial: same process,
            # startup and match, with strictly advancing tick/time.
            "diagnostics_end": self._diag_linkage_end,
        }

    def artifact(self, path: Path | str) -> str:
        self.artifacts.append(str(path))
        return str(path)

    def prepare(self, operation: str, **detail) -> None:
        self.preparation.append({"at": time.time(), "operation": operation, **detail})

    def gesture(self, kind: str, **detail) -> dict:
        record = {"at": time.time(), "kind": kind, **detail}
        self.gestures.append(record)
        return record

    def skye(self) -> dict:
        if self._skye is None:
            raise ClientStageFailure("SETUP", "FAIL", "Skye row not established")
        return self._skye

    def enemy(self) -> dict:
        if self._enemy is None:
            raise ClientStageFailure("SETUP", "FAIL", "enemy hero row not established")
        return self._enemy

    # -- setup --------------------------------------------------------------

    def setup(self) -> dict:
        session = verify_session(self.qa, timeout=self.timeout)
        # Fresh matching connection: explicit id must still be live in the
        # trace; otherwise select the most recently active connection. A trace
        # whose records all predate the freshness window is refused before any
        # UI input is sent against it.
        self.tail.poll()
        self.connection = select_connection(
            self.tail, self.connection,
            max_age=max(30.0, self.timeout * 2))
        resolution = verify_resolution(self.adb, self.profile)
        snapshot = session["snapshot"]
        heroes = snapshot.get("heroes") or []
        # The measured hero must be the CLIENT-controlled Skye: the owning
        # slot-0 local player (eid 1500 in this architecture), not any Skye
        # the roster happens to contain.
        local_eid = int(self.profile.get("local_player_eid", 1500))
        self._skye = next((row for row in heroes
                           if row.get("eid") == local_eid
                           and row.get("hero_id") == SKYE_HERO_ID), None)
        if self._skye is None:
            found = [(row.get("eid"), row.get("hero_id")) for row in heroes]
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"the client-controlled hero (eid {local_eid}) is not Skye "
                f"(265); roster as seen: {found} — lock in Skye on the client "
                "before running this scenario")
        enemies = [row for row in heroes
                   if row.get("team") != self._skye.get("team") and row.get("alive")
                   and row.get("eid") != self._skye.get("eid")]
        self._enemy = enemies[0] if enemies else None
        self.stage("SETUP", "PASS",
                   f"owned session at {self.qa.qa_dir}, phase=world, tick={session['tick']}, "
                   f"resolution={resolution['width']}x{resolution['height']}, "
                   f"skye eid={self._skye.get('eid')}")
        try:
            # REAL loaded-process provenance: the server's own read-only
            # diagnostics receipt (startup digest computed inside that
            # process), never a hash of today's disk files labeled as loaded
            # state.
            diag = self.qa.submit({"command": "diagnostics"},
                                  label="provenance-diagnostics",
                                  timeout=self.timeout)
            if diag.get("ok"):
                receipt = diag.get("result") or {}
                self._source_digest = receipt.get("source_startup_digest")
                self._source_current = receipt.get("source_current_digest")
                self._tape_loaded = receipt.get("tape_loaded")
                self._tape_file = receipt.get("tape_file_identity")
                self._env_config = receipt.get("env")
                # Typed process/startup/session linkage, validated HERE at
                # the setup boundary (outside the cast loop) so a
                # restarted/different process or match, a finished or
                # non-world session, or a malformed receipt fails BEFORE
                # any input gesture. The full typed linkage is carried
                # into the serialized provenance for pair validation.
                self._diag_linkage = self._validate_diag_linkage(
                    receipt, session)
            else:
                self._source_digest = None
                self._source_current = None
                self._tape_loaded = None
                self._tape_file = None
                self._env_config = None
                self._diag_linkage = None
        except ClientStageFailure:
            # A receipt we DID receive and could not vouch for is not a
            # best-effort gap: the trial's own provenance is incoherent, so
            # the setup boundary fails BEFORE any gameplay gesture instead of
            # continuing with null linkage. Transport errors (no receipt at
            # all) stay best-effort below.
            raise
        except Exception as exc:            # noqa: BLE001 -- provenance is
            self._source_digest = None      # best-effort, never gameplay
            self._source_current = None
            self._tape_loaded = None
            self._tape_file = None
            self._env_config = None
            self._diag_linkage = None
            self.observations["provenance_error"] = repr(exc)
        try:
            self._client_version = self.adb.client_version()
        except Exception as exc:            # noqa: BLE001
            self._client_version = None
            self.observations["provenance_error"] = repr(exc)
        self.observations["setup"] = {"resolution": resolution,
                                      "tick": session["tick"],
                                      "skye_eid": self._skye.get("eid"),
                                      "enemy_eid": (self._enemy or {}).get("eid"),
                                      "source_digest": self._source_digest,
                                      "client_version": self._client_version}
        return session

    def _validate_diag_linkage(self, receipt: dict, session: dict) -> dict:
        """Typed process/startup/session linkage from the diagnostics
        receipt, checked against the session snapshot this trial will
        prepare against. Runs at the setup boundary (outside the cast
        loop). Raises ClientStageFailure on:
          - missing/malformed required fields (pid, startup_at, match_id,
            phase, match_finished, tick, time) — the same shared field
            checks the serialized record validator re-applies
          - a non-world or finished session
          - a receipt from a DIFFERENT match than the session snapshot
            (restarted/different match)
        Returns the typed linkage dict carried into serialized provenance.
        """
        reasons = collect_linkage_field_failures(receipt)
        snapshot = session.get("snapshot") or {}
        snapshot_match = snapshot.get("match_id")
        if not reasons and receipt.get("match_id") != snapshot_match:
            reasons.append(
                f"diagnostics match_id {receipt.get('match_id')!r} != session "
                f"snapshot match_id {snapshot_match!r} — the session restarted "
                "or changed matches between preconditions and provenance")
        if reasons:
            raise ClientStageFailure(
                "SETUP", "FAIL",
                "diagnostics receipt lacks coherent trial linkage: "
                + "; ".join(reasons))
        linkage = {"pid": receipt["pid"],
                   "startup_at": float(receipt["startup_at"]),
                   "match_id": receipt["match_id"],
                   "phase": receipt["phase"],
                   "match_finished": receipt["match_finished"],
                   "tick": receipt["tick"],
                   "time": float(receipt["time"])}
        self.observations["diagnostics_linkage"] = linkage
        return linkage

    def collect_endpoint_linkage(self, session: dict) -> dict:
        """End-of-trial diagnostics receipt, read AFTER the whole
        time-sensitive action sequence (never between the basic hit and the
        dependent cast) and validated for the SAME process/startup/match with
        strictly advancing tick and simulation time.

        A missing, unacknowledged or malformed receipt is an EVIDENCE
        failure on TRIAL_CONTINUITY: the already-observed input/ack/outcome
        stages keep their own statuses and this is never reported as a failed
        UI action. Returns the typed linkage carried into the record.
        """
        def evidence_failure(status: str, detail: str) -> ClientStageFailure:
            self.stage("TRIAL_CONTINUITY", status, detail)
            return ClientStageFailure("TRIAL_CONTINUITY", status, detail)

        diag = self.qa.submit({"command": "diagnostics"},
                              label="endpoint-diagnostics",
                              timeout=self.timeout)
        if diag.get("pending"):
            raise evidence_failure(
                "UNVERIFIED",
                "endpoint diagnostics receipt was not acknowledged within the "
                f"mailbox bound (id {diag.get('id')!r}, result path "
                f"{diag.get('result_path')!r}) — the trial's end state is "
                "unknown, so it cannot enter a controlled pair; the observed "
                "input/ack/effect stages keep their own statuses")
        if not diag.get("ok"):
            raise evidence_failure(
                "UNVERIFIED",
                f"endpoint diagnostics was rejected: "
                f"{diag.get('error', 'unknown reason')}")
        receipt = diag.get("result")
        if not isinstance(receipt, dict):
            raise evidence_failure(
                "FAIL",
                "endpoint diagnostics result is "
                f"{type(receipt).__name__}, not an object")
        reasons = collect_linkage_field_failures(receipt)
        snapshot = session.get("snapshot") or {}
        snapshot_match = snapshot.get("match_id")
        if not reasons and receipt.get("match_id") != snapshot_match:
            reasons.append(
                f"endpoint match_id {receipt.get('match_id')!r} != session "
                f"snapshot match_id {snapshot_match!r}")
        if reasons:
            raise evidence_failure(
                "FAIL", "endpoint diagnostics receipt is not a coherent world "
                "session: " + "; ".join(reasons))
        linkage = {"pid": receipt["pid"],
                   "startup_at": float(receipt["startup_at"]),
                   "match_id": receipt["match_id"],
                   "phase": receipt["phase"],
                   "match_finished": receipt["match_finished"],
                   "tick": receipt["tick"],
                   "time": float(receipt["time"])}
        continuity = collect_trial_continuity_failures(self._diag_linkage,
                                                       linkage)
        if self._diag_linkage is None:
            continuity.append(
                "no initial diagnostics linkage was collected this trial")
        if continuity:
            raise evidence_failure(
                "FAIL", "trial endpoint continuity violated: "
                + "; ".join(continuity))
        self._diag_linkage_end = linkage
        self.observations["diagnostics_linkage_end"] = linkage
        return linkage

    def check_skye_readiness(self, slot: str) -> None:
        """Strict pre-cast readiness from a REFRESHED authoritative row.

        Rank present, no leftover upgrade points (an on-screen upgrade
        overlay intercepts skill input), the measured slot OFF cooldown,
        energy sufficient for the ability's native cost, and a living target.
        A running cooldown is a setup failure, never a logged-and-cast-anyway.
        """
        skye = self.skye()
        ranks = skye.get("ranks") or {}
        slot_index = {"A": "0", "B": "1", "C": "2"}[slot]
        if ranks.get(slot_index, 0) < 1:
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"Skye slot {slot} has rank 0 after legal preparation "
                f"(ranks={ranks}) — refusing the cast gesture")
        leftover_points = skye.get("ability_points") or 0
        plus_taps = list(self.profile.get("upgrade_plus_taps", []))
        # The measured slot must keep its rank across the comparable pair:
        # never tap ITS "+" button (the other slots absorb the leftovers).
        plus_taps = [pt for i, pt in enumerate(plus_taps)
                     if i != int(slot_index)]
        index = 0
        # Spend leftovers through the CLIENT's own "+" buttons (the legal UI
        # path the operator used), ONE tap at a time with an authoritative
        # re-read after each: a tap past the last remaining point would hit
        # ground and WALK the hero out of the verified framing (measured live
        # 2026-09-10: Skye drifted 11u, the cast then missed its line).
        # Positions cycle: spending one point re-reveals the same slot's
        # "+" for its next rank, and mid-match XP can grant extras.
        while leftover_points and index < 3 * len(plus_taps):
            plus = plus_taps[index % len(plus_taps)]
            index += 1
            self.adb.tap(*plus)
            self.gesture("tap", label="spend-upgrade-plus", xy=list(plus))
            time.sleep(0.8)
            self.refresh_rows()
            leftover_points = self.skye().get("ability_points") or 0
        if leftover_points and not self._framing_clear:
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"{leftover_points} ability point(s) remain after legal "
                "client-side spending; the upgrade overlay would intercept "
                "skill input (framing_clear="
                f"{self._framing_clear})")
        if leftover_points:
            # At the level cap nothing is upgradeable, no "+" button renders,
            # and the verified framing is overlay-free (enemy located) --
            # recorded instead of failing the trial.
            self.prepare("unspendable-points-at-level-cap",
                         points=leftover_points)
        # The hero must still stand in the verified framing for the profile
        # tap geometry; re-check and re-place once if anything walked.
        placement = self.profile["skye_position"]
        actual = (self.skye().get("x", 0.0), self.skye().get("y", 0.0))
        if math.dist(actual, tuple(placement)) > float(
                self.profile.get("placement_tolerance", 1.5)):
            self.prepare("re-teleport-after-preparation",
                         from_pos=[round(actual[0], 3), round(actual[1], 3)])
            result = self.qa.submit({"command": "teleport",
                                     "eid": self.skye().get("eid"),
                                     "x": placement[0], "y": placement[1]},
                                    label="teleport-reset", timeout=self.timeout)
            if result.get("pending") or not result.get("ok"):
                raise ClientStageFailure("SETUP", "FAIL",
                                         "placement reset teleport rejected")
            time.sleep(float(self.profile.get("camera_settle_s", 4.0)))
            self.refresh_rows()
        cooldowns = skye.get("ability_cooldowns") or {}
        remaining = float(cooldowns.get(slot_index, 0))
        if remaining > 0:
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"slot {slot} still on cooldown for another {remaining:.1f}s — "
                "wait out the natural cooldown or start a fresh match instead "
                "of casting into a running timer")
        costs = self.profile.get("ability_costs", {"A": 40.0, "B": 70.0, "C": 70.0})
        cost = float(costs[slot])
        energy = float(skye.get("energy", 0))
        if not math.isfinite(energy) or energy < cost:
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"Skye energy {energy:.1f} is below the native slot-{slot} cost "
                f"({cost:.0f}); regenerate or legally restore energy first")
        if self._enemy is None or not self._enemy.get("alive"):
            raise ClientStageFailure(
                "SETUP", "FAIL", "no living enemy target after preparation")

    def refresh_rows(self) -> dict:
        """Fresh authoritative snapshot; replace the cached hero rows.

        Legal preparation (learn/teleport) mutates ranks, points and
        positions; the cached setup rows go stale the moment it is applied.
        Also re-validates that the match is still a live WORLD -- a finished
        or disconnected session fails here, not later as a mystery.
        """
        snapshot = self.qa.snapshot(timeout=self.timeout)
        if snapshot.get("phase") != "world" or snapshot.get("match_finished"):
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"session no longer a live WORLD match (phase "
                f"{snapshot.get('phase')!r}, match_finished "
                f"{snapshot.get('match_finished')})")
        heroes = snapshot.get("heroes") or []
        local_eid = int(self.profile.get("local_player_eid", 1500))
        skye = next((row for row in heroes
                     if row.get("eid") == local_eid
                     and row.get("hero_id") == SKYE_HERO_ID), None)
        if skye is None:
            raise ClientStageFailure("SETUP", "FAIL",
                                     "client-controlled Skye row vanished on refresh")
        if not skye.get("alive"):
            raise ClientStageFailure("SETUP", "FAIL", "Skye is dead after preparation")
        self._skye = skye
        enemy = next((row for row in heroes
                      if row.get("team") != skye.get("team")
                      and row.get("eid") != skye.get("eid")), None)
        if enemy is not None and not enemy.get("alive"):
            enemy = None
        self._enemy = enemy
        return snapshot

    def prepare_positions(self) -> None:
        """Explicit QA teleport of Skye AND the enemy into the profile frame.

        Positions are always placed (a stale row that happens to sit near the
        target is not reused), then verified from a fresh snapshot against
        the strict tolerance -- the tap coordinates are only valid for this
        framing.
        """
        self.refresh_rows()
        skye, enemy = self.skye(), self.enemy()
        target = self.profile["skye_position"]
        enemy_target = self.profile["enemy_position"]
        placements = [("skye", skye, target)]
        if enemy is not None:
            placements.append(("enemy", enemy, enemy_target))
        for label, row, wanted in placements:
            self.prepare(f"qa-teleport-{label}", eid=row.get("eid"), to=wanted)
            result = self.qa.submit({"command": "teleport", "eid": row.get("eid"),
                                     "x": wanted[0], "y": wanted[1]},
                                    label=f"teleport-{label}", timeout=self.timeout)
            if result.get("pending") or not result.get("ok"):
                raise ClientStageFailure(
                    "SETUP", "FAIL",
                    f"{label} teleport preparation not applied: "
                    f"{result.get('error', result.get('message', 'pending'))}")
        # Let the client camera finish panning, then re-verify: a cast while
        # the framing is still moving misses the placed target (measured).
        time.sleep(float(self.profile.get("camera_settle_s", 4.0)))
        self.refresh_rows()
        placed_skye = self.skye()
        tolerance = float(self.profile.get("placement_tolerance", 1.5))
        actual = (placed_skye.get("x", 0.0), placed_skye.get("y", 0.0))
        if math.dist(actual, tuple(target)) > tolerance:
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"Skye placement {tuple(round(v, 3) for v in actual)} is more than "
                f"{tolerance}u from the verified profile position {tuple(target)}; "
                "the tap coordinates must not be applied to an unverified framing")
        enemy_actual = None
        if self._enemy is not None:
            enemy_actual = (self._enemy.get("x", 0.0), self._enemy.get("y", 0.0))
            if math.dist(enemy_actual, tuple(enemy_target)) > tolerance:
                raise ClientStageFailure(
                    "SETUP", "FAIL",
                    f"enemy placement {tuple(round(v, 3) for v in enemy_actual)} is "
                    f"more than {tolerance}u from the verified profile position "
                    f"{tuple(enemy_target)}")
        self.prepare("placement-verified",
                     skye=[round(actual[0], 3), round(actual[1], 3)],
                     enemy=[round(enemy_actual[0], 3), round(enemy_actual[1], 3)]
                     if enemy_actual else None,
                     tolerance=tolerance)

    def ensure_learned(self, slot: str) -> None:
        """Legal QA learn (real XP/point path) when the slot is unlearned,
        then re-read the authoritative rows the learn just changed."""
        self.refresh_rows()
        skye = self.skye()
        ranks = skye.get("ranks") or {}
        slot_index = {"A": 0, "B": 1, "C": 2}[slot]
        if ranks.get(str(slot_index), 0) >= 1:
            return
        result = self.qa.submit({"command": "learn", "eid": skye.get("eid"),
                                 "slot": slot_index},
                                label=f"learn-{slot}", timeout=self.timeout)
        if result.get("pending") or not result.get("ok"):
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"legal learn of slot {slot} failed: "
                f"{result.get('error', result.get('message', 'pending'))}")
        self.prepare("qa-learn", slot=slot, rank=result.get("rank"),
                     level=result.get("level"), xp_granted=result.get("xp_granted"))
        self.refresh_rows()

    # -- capture lifecycle ----------------------------------------------------

    def start_capture(self, *, window_hint: float) -> dict:
        """Start the bounded device recording BEFORE any authored UI gesture.

        Only this driver's own recorder process is ever stopped. The
        recording stays UNVERIFIED until a human reviews it.
        """
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        unique = f"{self.scenario}-{stamp}-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        device_video = f"/sdcard/halcyon-{unique}.mp4"
        local_video = self.out_dir / f"video-{unique}.mp4"
        evidence: dict[str, Any] = {"device_path": device_video,
                                    "local_path": str(local_video),
                                    "video": None, "screenshots": [],
                                    "capture_errors": [],
                                    "started_at": time.time(),
                                    "status": "UNVERIFIED",
                                    "note": "capture provenance only; a human must "
                                            "review the rendered presentation before "
                                            "any visual PASS claim",
                                    "finalized": False}
        try:
            recorder = self.adb.start_screenrecord(device_video,
                                                   time_limit=window_hint)
            self.capture_processes.append(recorder)
            self.device_recordings.append(device_video)
            self._recorder = recorder       # process object stays out of the
            evidence["recorder_identity"] = getattr(recorder, "halcyon_recording", None)
        except Exception as exc:            # JSON-serialized evidence
            self._recorder = None
            evidence["capture_errors"].append({"stage": "start", "error": repr(exc)})
        self.capture = evidence
        self.observations["presentation"] = evidence
        return evidence

    def capture_frame(self, label: str) -> None:
        """One named screenshot inside the running capture, best-effort."""
        if self.capture is None:
            return
        try:
            path = self.out_dir / f"frame-{label}-{int(time.time())}.png"
            captured = self.adb.screencap(path)
            self.capture["screenshots"].append({
                "path": self.artifact(path), "at": time.time(), "label": label,
                "bytes": captured.get("bytes")})
        except Exception as exc:            # noqa: BLE001
            self.capture["capture_errors"].append({"label": label, "error": repr(exc)})

    def finalize_capture(self) -> None:
        """Stop only this driver's recorder, pull the video, retain partials.

        Runs on success, exception, timeout and disconnect alike.
        """
        if self.capture is None or self.capture.get("finalized"):
            return
        self.capture["ended_at"] = time.time()
        recorder = getattr(self, "_recorder", None)
        if recorder is not None and recorder.poll() is None:
            try:
                self.adb.stop_screenrecord(recorder)
                recorder.wait(timeout=8)
            except Exception as exc:        # noqa: BLE001
                self.capture["capture_errors"].append({"stage": "stop",
                                                       "error": repr(exc)})
            finally:
                try:
                    if recorder.poll() is None:
                        recorder.terminate()  # only this driver's adb transport
                        try:
                            recorder.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            recorder.kill()
                            recorder.wait(timeout=2)
                except Exception as exc:    # noqa: BLE001
                    self.capture["capture_errors"].append({"stage": "transport-stop",
                                                           "error": repr(exc)})
        try:
            time.sleep(1.0)                 # device finalizes the mp4 on stop
            pulled = self.adb.pull(self.capture["device_path"],
                                   Path(self.capture["local_path"]))
            self.capture["video"] = self.artifact(self.capture["local_path"])
            self.capture["video_bytes"] = pulled.get("bytes")
        except Exception as exc:            # noqa: BLE001
            self.capture["capture_errors"].append({"stage": "finalize",
                                                   "error": repr(exc)})
        finally:
            self.capture["finalized"] = True
        self.stage("PRESENTATION", "UNVERIFIED",
                   f"{len(self.capture.get('screenshots') or [])} named frames, "
                   + ("video pulled" if self.capture.get("video")
                      else "video NOT pulled") + "; unreviewed")

    def capture_presentation(self, *, actions: list[dict],
                             duration: float) -> dict:
        """Legacy one-shot capture (kept for direct callers/tests): start,
        screenshot the named actions, finalize."""
        self.start_capture(window_hint=duration)
        try:
            for action in actions:
                self.capture_frame(action.get("label", "action"))
                time.sleep(0.4)
        finally:
            self.finalize_capture()
        return self.capture

    def aim_for_enemy(self, label: str, fallback: tuple[int, int],
                      *, required: bool = True,
                      target: str = "ground") -> tuple[int, int]:
        """Fresh screenshot + enemy-bar localization for one gesture aim.

        ``target="ground"`` aims at the enemy's ground contact (ground-targeted
        abilities); ``target="body"`` aims at the visible model (the
        basic-attack target tap). ``required=True``: if the enemy is not
        clearly visible the trial fails SETUP with the screenshot retained --
        a blind cast proves nothing about targeting.
        """
        path = self.out_dir / f"aim-{label}-{int(time.time())}.png"
        try:
            self.adb.screencap(path)
        except Exception as exc:        # noqa: BLE001
            self.gesture("aim", label=label, mode="screencap-failed",
                         error=repr(exc), fallback=list(fallback))
            if required:
                raise ClientStageFailure(
                    "SETUP", "FAIL",
                    f"pre-gesture screenshot for {label} failed: {exc!r}")
            return fallback
        aim, mode = locate_enemy_aim(path, fallback=fallback,
                                     ground=(target == "ground"))
        self._framing_clear = not mode.startswith("fallback")

        def frame_is_dark(png_path) -> bool:
            """Mean-luma overlay probe: Choose-a-Build/Settings cover the
            screen with a dark layer (measured ~40-60 luma vs ~90-120 in
            game). Only a DARK frame justifies a BACK press -- pressing BACK
            during normal play opens the settings menu instead."""
            try:
                from PIL import Image, ImageStat
                small = Image.open(png_path).convert("L").resize((64, 36))
                return ImageStat.Stat(small).mean[0] < 75.0
            except Exception:
                return False

        # A covering HUD overlay (Choose-a-Build, shop, ...) hides the enemy;
        # dismiss with bounded BACK presses ONLY while the frame is dark,
        # re-shooting the frame each time.
        attempts = 0
        while mode.startswith("fallback") and attempts < 4                 and frame_is_dark(path):
            attempts += 1
            if attempts % 2 == 1:
                self.adb.back()
                self.gesture("back", label=f"dismiss-overlay-{label}",
                             attempt=attempts)
            else:
                # the open panels (Settings, Choose-a-Build) share an X at
                # the panel's top-right; a plain BACK can cycle panels
                self.adb.tap(928, 37)
                self.gesture("tap", label=f"close-panel-{label}",
                             attempt=attempts)
            time.sleep(2.0)
            path = self.out_dir / f"aim-{label}-retry{attempts}-{int(time.time())}.png"
            self.adb.screencap(path)
            aim, mode = locate_enemy_aim(path, fallback=fallback)
        self.artifact(path)
        self.gesture("aim", label=label, mode=mode, aim=list(aim),
                     fallback=list(fallback), capture=str(path),
                     overlay_back_presses=attempts)
        if required and mode.startswith("fallback"):
            raise ClientStageFailure(
                "SETUP", "FAIL",
                f"enemy hero not visible in the {label} framing ({mode}) after "
                f"{attempts} overlay dismissals; the retained screenshots show "
                "what the driver saw -- no blind cast is issued")
        return aim

    # -- trace attribution --------------------------------------------------

    def _on_connection(self, record: dict) -> bool:
        """True when a record belongs to the selected live connection.

        A record on any other stream (a newer or older session in the same
        trace) can never satisfy an intended action.
        """
        if self.connection is None:
            return True
        return record.get("connection") == self.connection

    def wait_client_input(self, *, action: int, since: float) -> dict:
        """c2s 1042 with the expected native action from our connection."""
        def match(record: dict) -> bool:
            if record.get("direction") != "c2s":
                return False
            if not self._on_connection(record):
                return False
            return ground_cast_action(record) == action

        record = self.tail.wait_for(match, self.timeout, min_time=since)
        if record is None:
            raise ClientStageFailure(
                "CLIENT_INPUT_OBSERVED", "NOT_OBSERVED",
                f"no c2s 1042 action {action} observed in the selected trace "
                f"connection within {self.timeout}s of the UI gesture; whether "
                "the input left the client at all is unknown from this evidence")
        self.stage("CLIENT_INPUT_OBSERVED", "PASS",
                   f"c2s 1042 action={action} at {record.get('time')}")
        self.observations["client_input"] = {
            "time": record.get("time"), "action": action,
            "connection": record.get("connection"),
            # the c2s 1042 payload travels with the receipt: the action
            # metadata above is re-derivable from these bytes, so a copied
            # action cannot present itself as an observed cast
            "payload": record.get("payload", "")}
        return record

    def wait_acknowledgment(self, *, action: int, hero_eid: int, since: float) -> dict:
        """Matching s2c 1046, else classified unacknowledged."""
        def match(record: dict) -> bool:
            if record.get("direction") != "s2c":
                return False
            if not self._on_connection(record):
                return False
            if position_event_action(record) != action:
                return False
            return _payload_u32(record.get("payload", ""), 0) == hero_eid

        record = self.tail.wait_for(match, self.timeout, min_time=since)
        if record is None:
            raise ClientStageFailure(
                "SERVER_ACKNOWLEDGED", "UNACKNOWLEDGED",
                f"no matching s2c 1046 (eid {hero_eid}, action {action}) within "
                f"{self.timeout}s — input observed but unacknowledged; reason unknown")
        self.stage("SERVER_ACKNOWLEDGED", "PASS",
                   f"s2c 1046 eid={hero_eid} action={action} at {record.get('time')}")
        self.observations["acknowledgment"] = {"time": record.get("time"),
                                               "action": action,
                                               "connection": record.get("connection"),
                                               "payload": record.get("payload", "")}
        return record

    def wait_cooldown_tag(self, *, slot: str, hero_eid: int, since: float) -> dict | None:
        """1162 carrying this ability's native tag for the hero.

        B may also reset the A timer, so the caller must match the B/C tag
        explicitly; an A-tag movement alone is never accepted as B evidence.
        """
        expected_tag = SKYE_COOLDOWN_TAGS[slot]

        def match(record: dict) -> bool:
            if not self._on_connection(record):
                return False
            identity = timer_tag_eid(record)
            return (identity is not None and identity[0] == hero_eid
                    and identity[1] == expected_tag)

        record = self.tail.wait_for(match, self.timeout, min_time=since)
        if record is not None:
            self.observations["cooldown_tag"] = {
                "slot": slot, "tag": f"{expected_tag:08x}",
                # the tag was matched against THIS actor's identity; the
                # serialized receipt must carry it, otherwise the record
                # leaves a slot-only timer tag, which can never establish a
                # specific hero's cast
                "eid": hero_eid,
                "time": record.get("time"),
                # the 1162 payload travels with the receipt: (eid, tag) are
                # re-derivable from these bytes
                "connection": record.get("connection"),
                "payload": record.get("payload", "")}
        return record

    def classify_damage(self, *, hero_eid: int, enemy_eid: int,
                        window_start: float, window_end: float | None = None) -> dict:
        """Attribute 1054s in the window using PRODUCTION metadata.

        The authoritative emitter tags every 1054 tail with the damage kind
        (server/match_server.py ``_deal_damage``: COMBAT_DELTA_HERO_TAIL for
        basic attacks, COMBAT_DELTA_TAIL for every other source). Tail byte
        @16 therefore separates basics (0x00) from ability pulses (0x04)
        causally -- no time-proximity heuristic can do that for interleaved
        fire. Classification on the selected connection only:

        - hero->enemy, tail basic  -> ``basic_hits`` (never ability evidence)
        - hero->enemy, tail other  -> ``attributed`` (ability pulses)
        - hero->enemy, other tail  -> ``ambiguous`` (unverified; e.g. corpus
          variants this local build does not emit -- never auto-ability)
        - hero->enemy, delta >= 0  -> ``non_damage`` (heal/zero: excluded)
        - victim/attacker mismatches -> ``excluded.other_*``

        Raw payloads and reasons are preserved for re-review.
        """
        window_end = window_end if window_end is not None else time.time()
        # The damage pulses land DURING the post-cast sleeps; no wait_for ran
        # in that time, so the buffer must be refreshed before scanning.
        self.tail.poll()
        result = {
            "attributed": [], "basic_hits": [], "ambiguous": [],
            "non_damage": [], "excluded": {"other_victim": [], "other_attacker": []},
        }
        for record in self.tail.records:
            if not self._on_connection(record):
                continue
            when = record.get("time", 0)
            if not window_start <= when <= window_end:
                continue
            identity = damage_identity(record)
            if identity is None:
                continue
            victim, attacker, delta = identity
            payload = record.get("payload", "")
            if victim == enemy_eid and attacker == hero_eid:
                # the observed connection travels with the event: the
                # serialized outcome evidence must be bindable to the trial's
                # own connection, not only to an actor pair
                row = {"time": when, "delta": delta, "payload": payload,
                       "connection": record.get("connection")}
                if delta >= 0:
                    row["reason"] = "non-negative delta (heal/zero)"
                    result["non_damage"].append(row)
                elif len(payload) < 40:
                    row["reason"] = "payload too short for the 8-byte tail"
                    result["ambiguous"].append(row)
                else:
                    # the 1054 tail's third byte carries the kind: 0x00 =
                    # COMBAT_DELTA_HERO_TAIL (basic), 0x04 = COMBAT_DELTA_TAIL
                    tail_kind = _payload_u8(payload, 14)
                    if tail_kind == 0x00:
                        row["reason"] = "COMBAT_DELTA_HERO_TAIL (basic attack)"
                        result["basic_hits"].append(row)
                    elif tail_kind == 0x04:
                        row["reason"] = "COMBAT_DELTA_TAIL (non-basic source)"
                        result["attributed"].append(row)
                    else:
                        row["reason"] = f"unknown tail kind 0x{tail_kind:02x}"
                        result["ambiguous"].append(row)
            elif victim == enemy_eid:
                result["excluded"]["other_attacker"].append(
                    {"time": when, "attacker": attacker, "payload": payload})
            elif attacker == hero_eid:
                result["excluded"]["other_victim"].append(
                    {"time": when, "victim": victim, "payload": payload})
        self.observations["damage_classification"] = {
            **result, "window": [window_start, window_end],
            "note": "tail-kind attribution per production emitter "
                    "(COMBAT_DELTA_HERO_TAIL=basic, COMBAT_DELTA_TAIL=other)"}
        return result

    # -- scenario flows -----------------------------------------------------

    def run_cast_scenario(self, slot: str, *, requires_lock: bool) -> dict:
        """Shared A/B/C flow: capture first, preparation, gesture, wire
        stages, presentation. The lock-to-cast script stays timing-critical:
        no QA, model or capture-setup call runs between the observed lock and
        the cast gesture."""
        session = self.setup()
        try:
            # Recording starts before ANY authored gesture (including overlay
            # dismissal) and covers the whole trial.
            self.start_capture(window_hint=max(60.0, self.timeout * 3))
            self.ensure_learned(slot)
            self.prepare_positions()
            # Sweep covering HUD overlays (Choose-a-Build, shop) out of the
            # way BEFORE point spending: the readiness "+" taps are only
            # meaningful on a clear ability bar.
            self.aim_for_enemy("preparation-frame",
                               tuple(self.profile["enemy_body_tap"]),
                               required=False)
            self.check_skye_readiness(slot)
            self.refresh_rows()
            hero_eid = self.skye().get("eid")
            enemy = self.enemy()
            if enemy is None:
                raise ClientStageFailure("SETUP", "FAIL",
                                         "no living enemy hero for the duel")
            enemy_eid = enemy.get("eid")

            # Declared fixture: restore the comparable HP/EP values through
            # legal QA resources (receipts retained), then freeze the manifest
            # that both executions of a comparable pair must share.
            declared = self.profile.get("declared_fixture", {})
            skye_row = self.skye()
            enemy_row = self.enemy()

            def declare_resource(label, eid, field, policy, exact,
                                 current_value, maximum):
                """One declared resource request with its receipt.

                full   -> deliberately oversized request; the server clamps
                          to the actor cap and the clamped actual is recorded
                exact  -> the declared value itself; requests outside the
                          actor's legal maximum are rejected BEFORE sending
                """
                if policy == "full":
                    requested = 100000.0          # documented full request
                elif policy == "exact":
                    if exact is None:
                        raise ClientStageFailure(
                            "SETUP", "FAIL",
                            f"{label} exact policy without a declared value")
                    if not math.isfinite(exact) or exact < 0 or \
                            (maximum is not None and exact > maximum):
                        raise ClientStageFailure(
                            "SETUP", "FAIL",
                            f"{label} exact request {exact} is outside the "
                            f"actor's legal maximum {maximum}")
                    requested = exact
                else:
                    raise ClientStageFailure(
                        "SETUP", "FAIL",
                        f"{label} resource policy {policy!r} is not "
                        "full/exact")
                result = self.qa.submit(
                    {"command": "resources", "eid": eid, field: requested},
                    label=f"declare-{label}", timeout=self.timeout)
                if result.get("pending") or not result.get("ok"):
                    raise ClientStageFailure(
                        "SETUP", "FAIL",
                        f"{label} resource restore rejected: "
                        f"{result.get('error', result.get('message', 'pending'))}")
                actual = (result.get("result") or {}).get(field)
                self.prepare("declared-resource", resource=label, field=field,
                             requested=requested, actual=actual,
                             policy=policy)
                return actual

            energy_policy = declared.get("skye_energy_policy", "full")
            declare_resource("skye-energy", skye_row.get("eid"), "energy",
                             energy_policy,
                             declared.get("skye_energy_exact"),
                             skye_row.get("energy"), skye_row.get("max_energy"))
            skye_hp_policy = declared.get("skye_hp_policy", "full")
            declare_resource("skye-hp", skye_row.get("eid"), "hp",
                             skye_hp_policy, declared.get("skye_hp_exact"),
                             skye_row.get("hp"), skye_row.get("max_hp"))
            if enemy_row is not None:
                enemy_hp_policy = declared.get("enemy_hp_policy", "full")
                declare_resource("enemy-hp", enemy_row.get("eid"), "hp",
                                 enemy_hp_policy,
                                 declared.get("enemy_hp_exact"),
                                 enemy_row.get("hp"), enemy_row.get("max_hp"))

            snapshot = self.refresh_rows()
            # REQUIRED identity/state fields for every controlled fixture
            # actor. The QA snapshot exposes team/inventory/default_items/
            # statuses for heroes (both Skye and the enemy hero); emitting
            # the same shape for both actors means the validator can check
            # the same fields on both, and a missing field is always a
            # structured failure rather than a silent default. The QA
            # snapshot exposes BOTH heroes (Skye and the enemy hero) with
            # the same field set (see server/sandbox_qa.py:snapshot),
            # so the writer publishes the same identity/state fields for
            # both actors. Only the energy pool of a NON-hero enemy would
            # be inapplicable; in the current scenarios the enemy is
            # always a hero with the same QA-exposed shape as Skye.
            skye_row = self.skye() or {}
            enemy_row = self._enemy if self._enemy is not None else {}
            skye_fields = ("team", "hero_id", "eid", "level", "ranks",
                           "ability_points", "hp", "max_hp", "energy",
                           "max_energy", "inventory", "default_items",
                           "statuses", "alive", "x", "y")
            enemy_fields = ("team", "hero_id", "eid", "level", "ranks",
                            "ability_points", "hp", "max_hp", "energy",
                            "max_energy", "inventory", "default_items",
                            "statuses", "alive", "x", "y")
            manifest = {
                "match_id": snapshot.get("match_id"),
                "tick": snapshot.get("tick"),
                "slot": slot,
                "skye": {k: skye_row.get(k) for k in skye_fields},
                "enemy": ({k: enemy_row.get(k) for k in enemy_fields}
                          if enemy_row else None),
                "positions": {"skye": self.profile["skye_position"],
                              "enemy": self.profile["enemy_position"]},
                "placement_tolerance": self.profile.get(
                    "placement_tolerance",
                    DEFAULT_PROFILE.get("placement_tolerance", 1.5)),
                "connection": self.connection,
                "declared_fixture": declared,
                "cooldowns": skye_row.get("ability_cooldowns") or {},
                "profile_digest": self.profile_digest,
                "provenance": {
                    "source_startup_digest": self._source_digest,
                    "source_current_digest": self._source_current,
                    "tape_loaded": self._tape_loaded,
                    "tape_file_identity": self._tape_file,
                    "env_config": self._env_config,
                    "client_version": self._client_version,
                    "qa_dir": self.qa.qa_dir,
                },
            }
            self.observations["fixture_manifest"] = manifest
            # The declared contract gates every input gesture: measured state
            # must satisfy it AFTER all legal preparation, BEFORE input.
            contract = build_fixture_contract(self.profile, slot)
            # Carried BEFORE validation so a refused trial still serializes
            # the contract it was refused against (the failure record and
            # both record kinds read this attribute).
            self.fixture_contract = contract
            failures = validate_fixture(manifest, contract)
            if failures:
                raise ClientStageFailure(
                    "SETUP", "FAIL",
                    "declared fixture contract violated before input: "
                    + "; ".join(failures))

            # Pre-cast resource baseline (read-only), after all preparation.
            before = self.qa.snapshot(timeout=self.timeout)
            skye_before = next(row for row in before["heroes"]
                               if row.get("eid") == hero_eid)
            energy_before = float(skye_before.get("energy", 0))

            # ALL screenshots, overlay dismissal and aim computation happen
            # here, BEFORE the basic-hit sequence. The timing-critical script
            # below (target tap -> observed lock -> cast swipe) performs no
            # screenshot, QA or model call: measured live, an aim shot between
            # lock and cast stretched the lock->1042 gap to ~5 s.
            body = self.aim_for_enemy("basic-attack-target",
                                      tuple(self.profile["enemy_body_tap"]),
                                      target="body")
            control = self.profile["controls"][slot]
            fallback_aim = {"A": self.profile["enemy_feet_aim"],
                            "B": self.profile["b_drag_to"],
                            "C": self.profile["c_drag_to"]}[slot]
            aim = self.aim_for_enemy(f"cast-{slot}", tuple(fallback_aim))
            self.capture_frame(f"pre-cast-{slot}")

            gesture_time = time.time()
            lock_record = None
            if requires_lock:
                self.adb.tap(*body)
                self.gesture("tap", label="basic-attack-target", xy=list(body))
                lock_deadline = 6.0        # stale-aim guard, not the stage cap
                lock_record = self.tail.wait_for(
                    lambda record: (
                        self._on_connection(record)
                        and record.get("direction") == "s2c"
                        and (identity := lock_identity(record)) is not None
                        and identity[2] == TARGET_LOCK_KIND
                        and identity[0] == enemy_eid and identity[1] == hero_eid),
                    lock_deadline, min_time=gesture_time)
                if lock_record is None:
                    raise ClientStageFailure(
                        "SETUP", "FAIL",
                        f"basic-attack Target Lock (1086 kind {TARGET_LOCK_KIND} "
                        f"target {enemy_eid}) not observed in the selected trace "
                        f"connection within {lock_deadline}s of the pre-aimed tap "
                        "-- the aim is stale; prepare a fresh attempt instead of "
                        "casting blind")
                self.observations["lock"] = {"time": lock_record.get("time"),
                                             "target": enemy_eid,
                                             "kind": TARGET_LOCK_KIND}

            # cast immediately at the pre-computed aim: no intervening call
            swipe_started = time.time()
            self.adb.swipe(*control, *aim)
            self.gesture("swipe", label=f"cast-{slot}", frm=list(control),
                         to=list(aim), started_at=swipe_started)
            cast_issued = time.time()
            self.stage("UI_COMMAND_SUBMITTED", "PASS",
                       f"{self.gestures[-1]['kind']} for slot {slot}; "
                       f"lock-to-swipe "
                       f"{(cast_issued - (lock_record or {}).get('time', cast_issued)) * 1000:.0f} ms")
            self.observations["ui_command"] = self.gestures[-1]

            action = SKYE_NATIVE_ACTIONS[slot]
            cast_record = self.wait_client_input(action=action, since=gesture_time)
            cast_time = cast_record["time"]
            self.observations["timing"] = {
                "gesture_time": gesture_time,
                "lock_time": (lock_record or {}).get("time"),
                "swipe_started": swipe_started,
                "cast_issued": cast_issued,
                "c2s_time": cast_time,
                "lock_to_c2s_ms": round((cast_time - (lock_record or {}).get(
                    "time", cast_time)) * 1000, 1) if lock_record else None}
            self.wait_acknowledgment(action=action, hero_eid=hero_eid,
                                     since=cast_time)
            self.wait_cooldown_tag(slot=slot, hero_eid=hero_eid, since=cast_time)

            # Effect window first: A's barrage channels ~2.6 s, B missiles
            # land within ~1 s, the C volley runs past its 1.3 s delay. Only
            # afterwards does the disengage ground tap stop the ordinary
            # auto-attack cycle, so it cannot truncate the measured ability.
            time.sleep({"A": 3.2, "B": 1.5, "C": 3.2}[slot])
            if slot in ("B", "C"):
                disengage = self.profile.get("disengage_tap")
                if disengage:
                    self.adb.tap(*disengage)
                    self.gesture("tap", label="disengage-move", xy=list(disengage))
            time.sleep(0.5)
            self.capture_frame(f"post-effect-{slot}")

            # Post-cast resources and match liveness from one fresh snapshot.
            after = self.qa.snapshot(timeout=self.timeout)
            if after.get("phase") != "world" or after.get("match_finished"):
                raise ClientStageFailure(
                    "AUTHORITATIVE_EFFECT", "UNVERIFIED",
                    "the match ended during the effect window; resource and "
                    "damage evidence cannot be attributed to a live session")
            skye_after = next(row for row in after["heroes"]
                              if row.get("eid") == hero_eid)
            energy_after = float(skye_after.get("energy", 0))
            cooldowns_after = skye_after.get("ability_cooldowns") or {}
            slot_index = {"A": "0", "B": "1", "C": "2"}[slot]
            energy_paid = energy_after < energy_before
            cooldown_running = float(cooldowns_after.get(slot_index, 0)) > 0
            if not energy_paid and not cooldown_running:
                raise ClientStageFailure(
                    "SERVER_ACKNOWLEDGED", "FAIL",
                    f"cast acknowledged but no resource state changed (energy "
                    f"{energy_before:.1f} -> {energy_after:.1f}, slot {slot} "
                    "cooldown not running) -- acknowledgment without acceptance")
            self.stage("SERVER_ACKNOWLEDGED", "PASS",
                       f"energy {energy_before:.1f} -> {energy_after:.1f}, "
                       f"slot {slot} cooldown running: {cooldown_running}")
            self.observations["resources"] = {
                "energy_before": energy_before, "energy_after": energy_after,
                "energy_paid": energy_paid, "cooldown_running": cooldown_running}

            classification = self.classify_damage(
                hero_eid=hero_eid, enemy_eid=enemy_eid,
                window_start=cast_time, window_end=time.time())
            attributed = classification["attributed"]
            if not attributed:
                raise ClientStageFailure(
                    "AUTHORITATIVE_EFFECT", "FAIL",
                    f"no COMBAT_DELTA_TAIL (ability) 1054 from {hero_eid} onto "
                    f"enemy {enemy_eid} in the post-cast window "
                    f"({len(classification['basic_hits'])} basic-tail hits, "
                    f"{len(classification['ambiguous'])} ambiguous, "
                    f"{len(classification['excluded']['other_victim'])} excluded "
                    f"other-victim, "
                    f"{len(classification['excluded']['other_attacker'])} incoming "
                    "-- a basic-only trace never satisfies an ability effect)")
            # record the exact normalized outcome total for pair comparison
            outcome_total = round(sum(h["delta"] for h in attributed),
                                  OUTCOME_TOTAL_DECIMALS)
            observed_outcome = {
                "attributed_events": len(attributed),
                "outcome_total": outcome_total,
            }
            self.observations["outcome"] = observed_outcome
            detail = f"{len(attributed)} attributed damage events, total "                      f"{outcome_total}"
            if slot == "C":
                volleys = [record for record in self.tail.records
                           if self._on_connection(record)
                           and volley_owner(record) is not None
                           and volley_owner(record) == hero_eid
                           and record.get("time", 0) >= cast_time]
                if not volleys:
                    raise ClientStageFailure(
                        "AUTHORITATIVE_EFFECT", "FAIL",
                        "no Skye C volley actor 1010 (class F59CDB08, owner "
                        f"{hero_eid}) published on the selected connection")
                detail += f", {len(volleys)} C volley actor publications"
                self.observations["volley_actors"] = len(volleys)
                # The matched publications travel with the count: the owner,
                # the volley class and the observation instant are re-derivable
                # from these bytes with the same parser that matched them, so a
                # bare count cannot present itself as publication evidence.
                self.observations["volley_publications"] = [
                    {"time": record.get("time"),
                     "connection": record.get("connection"),
                     "payload": record.get("payload", "")}
                    for record in volleys]
            self.stage("AUTHORITATIVE_EFFECT", "PASS", detail)

            # Endpoint evidence comes AFTER the whole time-sensitive
            # sequence above: it must never sit between the basic hit and
            # the dependent cast. A collection problem here is an evidence
            # failure on TRIAL_CONTINUITY, never a reinterpretation of the
            # input/ack/effect stages already measured.
            endpoint = self.collect_endpoint_linkage(session)
            self.stage("TRIAL_CONTINUITY", "PASS",
                       f"pid {endpoint['pid']} startup {endpoint['startup_at']} "
                       f"match {endpoint['match_id']} unchanged; tick "
                       f"{self._diag_linkage['tick']} -> {endpoint['tick']}, "
                       f"time {self._diag_linkage['time']} -> "
                       f"{endpoint['time']}")

            self.capture_frame(f"post-cast-{slot}")
            self.finalize_capture()
            return self.finish("PASS", observed={
                "fixture_manifest": self.observations.get("fixture_manifest"),
                "attributed_damage_events": len(attributed),
                "total_attributed_delta": round(
                    sum(h["delta"] for h in attributed), 4),
                "energy_paid": energy_paid,
                "cooldown_running": cooldown_running,
                "cooldown_tag_observed": self.observations.get("cooldown_tag"),
            }, expected={
                "client_input_observed": True,
                "matching_acknowledgment": True,
                "slot_cooldown_or_energy": True,
                "attributed_effect_on_enemy": True,
            })
        except Exception:
            self.finalize_capture()
            raise

    def run_minion_push(self) -> dict:
        """Client observation of the assigned four-stage sequence: lane
        approach, opposing-minion combat, survivors resuming toward the
        opposing structure, and structure interaction. Every stage is named
        and independently PASS/NOT_OBSERVED; the overall result is PASS only
        when all four hold. Minions are never teleported or killed; tracking
        uses the read-only ``lane_minions`` QA census (both teams, uncapped),
        and 1016 orders are attributed to tracked actors via the slot map
        built from 1010 publications. Per-actor timelines (t, x, y, hp,
        alive) are retained in full, including the samples in which an actor
        was missing (recorded as absences, never as deaths).

        SURVIVOR_RESUMPTION is a causal claim and is measured as one: the
        survivor must itself have fought a tracked opposing minion, the
        engagement must end in a CARRIED EVENT WITH AN INSTANT — every
        opponent it engaged evidenced dead (an explicit 1072 ENTITY_DEATH
        publication for it, or a census sample recording hp <= 0), so that
        the closure is the LATEST such death and never earlier than the
        actor's own last recorded involvement — and the resumed march must be
        measured over a contiguous run of samples, strictly after that
        instant, in which the actor is present with a KNOWN hp > 0. An
        opponent observed alive, holding position or leaving the census
        carries no end at all, so the claim stays UNVERIFIED and unknown
        rather than inferred from silence; and a measured interval is not
        erased by the survivor's own later death.

        STRUCTURE_INTERACTION is bound to that SAME participant, not to any
        hit: the qualifying hit is the actor's own, strictly after its carried
        engagement end and strictly before its own death, on a structure whose
        recorded team (read from the same snapshot that lists it) is
        EXPLICITLY the opposing one — the snapshot's team must be the integer
        1 or 2 and the other side; a missing, unknown, invalid, boolean or
        non-integer value is not an opposing side — and it is only accepted
        once the actor's resumption has already been measured by at least two
        contiguous observed-alive samples with a push-direction march >= 1.0 u
        whose run reaches the hit, i.e. every census sample between the
        engagement end and the hit observes the actor alive, so no absence, no
        unknown hp and no death inside that span is bridged. A hit from a
        bystander, a friendly or invalidly-attributed structure, a hit that
        precedes the sequence, a hit separated from the resumption by a gap or
        a post-death hit is reported in ``structure_unverified`` with its
        reason, and raw hits are kept in ``structure_hits`` /
        ``structure_log`` either way.
        """
        try:
            session = self.setup()
            window = float(self.profile.get("minion_push_window_s", 20.0))
            # Observational contract: minion-push validates no Skye resource
            # fixture, so nothing is declared here; the record still carries
            # the schema-v2 contract key naming the census window it observed.
            self.fixture_contract = {
                "slot": SCENARIO_SLOT.get(self.scenario),
                "observational_window_s": window,
                "declared_fixture": {},
            }
            self.start_capture(window_hint=window + 20.0)
            lane_prep = self.profile.get("minion_push_hero_position")
            if lane_prep:
                self.prepare("qa-teleport-skye-lane", eid=self.skye().get("eid"),
                             to=lane_prep)
                result = self.qa.submit({"command": "teleport",
                                         "eid": self.skye().get("eid"),
                                         "x": lane_prep[0], "y": lane_prep[1]},
                                        label="teleport-lane",
                                        timeout=self.timeout)
                if result.get("pending") or not result.get("ok"):
                    raise ClientStageFailure(
                        "SETUP", "FAIL",
                        "lane observation teleport not applied: "
                        f"{result.get('error', result.get('message', 'pending'))}")

            def lane_census():
                result = self.qa.submit({"command": "lane_minions"},
                                        label="lane-census",
                                        timeout=self.timeout)
                if result.get("pending") or not result.get("ok"):
                    raise ClientStageFailure(
                        "SETUP", "FAIL",
                        "lane_minions census rejected: "
                        f"{result.get('error', result.get('message', 'pending'))}")
                return result.get("result") or {}

            window_start = time.time()
            census = lane_census()
            hero_snapshot = self.qa.snapshot(timeout=self.timeout)
            hero_eids = {row.get("eid") for row in
                         (hero_snapshot.get("heroes") or [])}
            # The world this window observed: the same session identity the
            # setup boundary validated, kept so a record validator can tie the
            # carried census and evidence to one match instead of assuming it.
            window_match_id = hero_snapshot.get("match_id")
            # Structures are read ONCE from the existing snapshot and both of
            # its facts are kept: where each one stands, and the team it
            # belongs to (the snapshot's structure rows carry it). Without the
            # team a hit can never be shown to be an OPPOSING-structure hit.
            structure_rows = (self.qa.snapshot(timeout=self.timeout)
                              .get("structures") or [])
            structures = {row.get("eid"): (row.get("x"), row.get("y"))
                          for row in structure_rows}
            structure_teams = {row.get("eid"): row.get("team")
                               for row in structure_rows}
            tracked: dict[int, dict] = {}
            opening_sample_t = time.time()
            # Every census FRAME this window actually took, the opening one
            # included, raw and in order. The timelines below are the rows
            # stamped into these frames, so the frame count and every derived
            # sample count are recomputable from the record instead of being
            # believed.
            census_instants = [opening_sample_t]
            # The WORLD CLOCK each census was served at, carried parallel to
            # the frames: the census reply reports the simulation tick/time it
            # observed (the snapshot serves the same pair), so the elapsed
            # GAMEPLAY time between two frames is evidence rather than the
            # client's wall clock. A reply that does not carry it is recorded
            # as an explicit absence (None), never invented.
            census_sim_ticks = [census.get("tick")]
            census_sim_times = [census.get("time")]
            for row in census.get("minions") or []:
                tracked[row["eid"]] = {
                    "team": row.get("team"), "hp": row.get("hp"),
                    "alive": True,
                    "timeline": [(opening_sample_t, row["x"], row["y"],
                                  row.get("hp"), True)]}
            movement_samples = 0
            session_lost = False
            deadline = time.monotonic() + window
            while time.monotonic() < deadline:
                time.sleep(1.0)
                movement_samples += 1
                try:
                    census = lane_census()
                except ClientStageFailure:
                    session_lost = True        # keep what was observed
                    break
                # One census is ONE instant: every row it serves (and every
                # absence it proves) is stamped with that same sample time.
                sample_t = time.time()
                census_instants.append(sample_t)
                census_sim_ticks.append(census.get("tick"))
                census_sim_times.append(census.get("time"))
                present_eids = set()
                for row in census.get("minions") or []:
                    eid = row.get("eid")
                    present_eids.add(eid)
                    entry = tracked.setdefault(eid, {
                        "team": row.get("team"), "hp": row.get("hp"),
                        "alive": True, "timeline": []})
                    entry["timeline"].append((sample_t, row["x"], row["y"],
                                              row["hp"], True))
                    entry["alive"] = True
                # A tracked actor missing from this census is recorded as an
                # ABSENCE at this instant, with its last known position and
                # HP. The observation ends there: the cause is never inferred
                # here, because the read-only census serves living minions
                # only, so a missing row is not a death and not an engagement
                # end (1072 ENTITY_DEATH is what evidences a death).
                for eid, entry in tracked.items():
                    if eid in present_eids:
                        continue
                    seen = [point for point in entry["timeline"] if point[4]]
                    last_seen = seen[-1] if seen else (None, None, None, None)
                    entry["timeline"].append((sample_t, last_seen[1],
                                              last_seen[2], last_seen[3],
                                              False))
                    entry["alive"] = False
                self.tail.poll()
            window_end = time.time()
            self.finalize_capture()

            # Death evidence: an explicit 1072 ENTITY_DEATH publication for a
            # tracked actor. Nothing else in this record is read as a death —
            # a missing census row stays an absence with an unknown cause.
            minion_deaths: list[dict] = []
            for record in self.tail.records:
                if not self._on_connection(record):
                    continue
                when = record.get("time", 0)
                if not window_start <= when <= window_end:
                    continue
                if record.get("opcode") != OP_ENTITY_DEATH:
                    continue
                payload = record.get("payload", "")
                if len(payload) < 16:              # 8 bytes: victim + killer
                    continue
                victim = _payload_u32(payload, 0)
                if victim not in tracked:
                    continue
                minion_deaths.append({
                    "time": when, "victim": victim,
                    "killer": _payload_u32(payload, 4),
                    # The raw wire identity the claim rests on: the stream it
                    # arrived on, the opcode and the payload bytes themselves,
                    # so the identity can be RE-DERIVED rather than trusted.
                    "connection": record.get("connection"),
                    "opcode": OP_ENTITY_DEATH, "payload": payload})

            # 1016 attribution: compact slot ownership over time. Each 1016
            # is attributed to the eid that OWNED the slot AT THAT TIME
            # (1010 assigns / 1035 releases processed chronologically; a 1073
            # retires the presentation without freeing the slot; slots are
            # reused by the production allocator).
            slot_events = build_slot_timeline(
                self.tail.records, connection=self.connection)
            tracked_move_orders = 0
            tracked_move_log = []
            for record in self.tail.records:
                if not self._on_connection(record):
                    continue
                when = record.get("time", 0)
                if not window_start <= when <= window_end:
                    continue
                if record.get("opcode") != OP_MOVE_ORDER:
                    continue
                payload = record.get("payload", "")
                if len(payload) < 2:
                    continue
                slot = _payload_u8(payload, 0)
                owner = slot_owner_at(slot_events, slot, when)
                if owner in tracked:
                    tracked_move_orders += 1
                    tracked_move_log.append({"time": when, "slot": slot,
                                             "owner": owner,
                                             "connection": record.get(
                                                 "connection"),
                                             "payload": payload})

            minion_combat: list[dict] = []
            structure_hits: list[dict] = []
            for record in self.tail.records:
                if not self._on_connection(record):
                    continue
                when = record.get("time", 0)
                if not window_start <= when <= window_end:
                    continue
                identity = damage_identity(record)
                if identity is None:
                    continue
                victim, attacker, delta = identity
                if victim in tracked and attacker in tracked:
                    if tracked[victim]["team"] != tracked[attacker]["team"]:
                        minion_combat.append({
                            "time": when, "victim": victim,
                            "attacker": attacker, "delta": delta,
                            "victim_team": tracked[victim]["team"],
                            "attacker_team": tracked[attacker]["team"],
                            "connection": record.get("connection"),
                            "opcode": record.get("opcode"),
                            "payload": record.get("payload", "")})
                elif victim in structures and attacker in tracked:
                    structure_hits.append({
                        "time": when, "structure": victim,
                        "attacker": attacker, "delta": delta,
                        "attacker_team": tracked[attacker]["team"],
                        "structure_team": structure_teams.get(victim),
                        "connection": record.get("connection"),
                        "opcode": record.get("opcode"),
                        "payload": record.get("payload", "")})

            episodes = minion_episodes(tracked, minion_combat,
                                       structure_hits, minion_deaths,
                                       structure_teams)
            approached = [eid for eid, ep in episodes.items()
                          if (ep["approach"] or 0) >= 1.0]
            combat_participants = [eid for eid, ep in episodes.items()
                                   if ep["combat_participant"]]
            resumed = [eid for eid, ep in episodes.items()
                       if ep["resumed_after_combat"] is not None
                       and ep["resumed_after_combat"] >= 1.0]
            unproven_resumptions = [eid for eid, ep in episodes.items()
                                    if ep["resumption_unverified"] is not None]
            # STRUCTURE_INTERACTION is the SAME participant's sequence: the
            # cohort is the actors whose own accepted resumption was already
            # measured before their own hit on a recorded opposing structure.
            structure_cohort = [eid for eid, ep in episodes.items()
                                if ep["structure_sequence"] is not None]
            structure_unproven = [eid for eid, ep in episodes.items()
                                  if ep["structure_unverified"] is not None]

            resumption_detail = (
                f"{len(resumed)}/{len(combat_participants)} combat "
                "participants proved an evidence-backed engagement end and "
                "resumed the push toward the opposing structure while "
                "observed alive")
            if unproven_resumptions:
                first = episodes[unproven_resumptions[0]]["resumption_unverified"]
                resumption_detail += (
                    f"; {len(unproven_resumptions)} further participant(s) "
                    "make an UNVERIFIED resumption claim: "
                    + first["reasons"][0])

            structure_detail = (
                f"{len(structure_cohort)} combat participant(s) damaged an "
                "OPPOSING structure after their own carried engagement end and "
                "their own observed-alive resumption were measured")
            if structure_unproven:
                first_hit = episodes[structure_unproven[0]]["structure_unverified"]
                structure_detail += (
                    f"; {len(structure_unproven)} further structure hit(s) "
                    "make an UNVERIFIED sequence: "
                    + first_hit["reasons"][0])

            stage_specs = {
                "LANE_APPROACH": (
                    len(approached) > 0,
                    f"{len(approached)}/{len(tracked)} minions advanced "
                    "toward the opposing base"),
                "OPPOSING_COMBAT": (
                    len(minion_combat) > 0,
                    f"{len(minion_combat)} opposing-team minion-vs-minion "
                    "events"),
                "SURVIVOR_RESUMPTION": (
                    len(resumed) > 0, resumption_detail),
                "STRUCTURE_INTERACTION": (
                    len(structure_cohort) > 0, structure_detail),
            }
            for name, (ok, detail) in stage_specs.items():
                self.stage(name, "PASS" if ok else "NOT_OBSERVED", detail)
            self.stage("UI_COMMAND_SUBMITTED", "N/A",
                       "observational scenario: no authored cast gesture")
            self.stage("CLIENT_INPUT_OBSERVED", "N/A", "no authored cast expected")
            self.stage("SERVER_ACKNOWLEDGED", "N/A",
                       f"{tracked_move_orders} 1016 orders attributed to "
                       "tracked actors via their at-the-time slot owners")
            self.stage("SETUP", "PASS",
                       f"{len(tracked)} lane minions tracked over "
                       f"{movement_samples} samples")

            timelines = {}
            for eid, entry in tracked.items():
                timelines[eid] = {
                    "team": entry["team"],
                    "episode": episodes.get(eid, {}),
                    # The RAW census observations, unrounded: this timeline is
                    # the evidence the episode was computed from, so a record
                    # validator can recompute the very same numbers from the
                    # record instead of trusting the saved conclusions.
                    "points": [list(point) for point in entry["timeline"]]}
            observed = {
                # The raw frame of the observation: the instants the window
                # opened and closed, the stream it watched, the world it
                # watched and the prepared configuration digest. A record
                # without them cannot be tied to one match, one connection and
                # one declared duration.
                "window_start": window_start,
                "window_end": window_end,
                "connection": self.connection,
                "match_id": window_match_id,
                "profile_digest": self.profile_digest,
                "tracked_minions": len(tracked),
                "movement_samples": movement_samples,
                "census_instants": census_instants,
                # The simulation clock each frame was served at, parallel to
                # the frames (None = the census reply did not carry it, which
                # is a named evidence gap, not an assumed instant).
                "census_sim_ticks": census_sim_ticks,
                "census_sim_times": census_sim_times,
                "minions_advanced_toward_enemy_base": len(approached),
                "combat_participants": len(combat_participants),
                "minion_vs_minion_events": len(minion_combat),
                "survivors_resumed": len(resumed),
                "survivor_claims_unverified": len(unproven_resumptions),
                "resumed_cohort_structure_hits": len(structure_cohort),
                "structure_claims_unverified": len(structure_unproven),
                "tracked_move_orders": tracked_move_orders,
                "session_lost_mid_window": session_lost,
                "per_actor_timelines": timelines,
                "combat_log": minion_combat,
                "structure_log": structure_hits,
                # The slot attribution the 1016 orders were credited through:
                # every entry names the slot, its at-the-time owner, the stream
                # and the raw payload, so the attribution is re-derivable.
                "move_log": tracked_move_log,
                # The team each observed structure belongs to, as the snapshot
                # served it (None = the record does not carry one).
                "structure_teams": {str(eid): team
                                    for eid, team in structure_teams.items()},
                # The deaths the trace actually evidenced (1072 publications
                # for tracked actors). An empty log means "no death
                # publication was observed" — never "nobody died".
                "death_log": minion_deaths,
            }
            self.observations["minion_window"] = observed
            if not tracked:
                self.stage("LANE_APPROACH", "NOT_OBSERVED",
                           "no living lane minions existed in the lane census "
                           "inside the window")
                raise ClientStageFailure(
                    "LANE_APPROACH", "NOT_OBSERVED",
                    "no living lane minions existed in the lane census inside "
                    "the window -- a specific absence, reported not assumed")
            if session_lost:
                self.stage("AUTHORITATIVE_EFFECT", "UNVERIFIED",
                           "the QA session stopped answering inside the "
                           "observation window")
                raise ClientStageFailure(
                    "AUTHORITATIVE_EFFECT", "UNVERIFIED",
                    "the QA session stopped answering inside the observation "
                    "window; earlier samples alone must not become a PASS")
            # Endpoint evidence, read after the bounded observation window and
            # before the result is constructed: the SAME typed receipt, the
            # same continuity comparison and the same serialized provenance
            # slot the cast trial uses (collect_endpoint_linkage / finish). A
            # missing, unacknowledged, malformed, restarted or stalled endpoint
            # is an EVIDENCE failure on TRIAL_CONTINUITY: the gameplay stages
            # measured above keep their own statuses, and continuity can never
            # upgrade an incomplete sequence into a PASS.
            endpoint = self.collect_endpoint_linkage(session)
            self.stage("TRIAL_CONTINUITY", "PASS",
                       f"pid {endpoint['pid']} startup "
                       f"{endpoint['startup_at']} match {endpoint['match_id']} "
                       f"unchanged; tick {self._diag_linkage['tick']} -> "
                       f"{endpoint['tick']}, time {self._diag_linkage['time']} "
                       f"-> {endpoint['time']}")
            failed_stages = [name for name, (ok, _d) in stage_specs.items()
                             if not ok]
            if failed_stages:
                # incomplete results must finalize coherently: name the failed
                # stages on AUTHORITATIVE_EFFECT with a matching
                # first_failed_stage, never leave PENDING with no failure
                detail = "; ".join(stage_specs[name][1] for name in failed_stages)
                self.stage("AUTHORITATIVE_EFFECT", "NOT_OBSERVED",
                           "incomplete sequence: " + detail)
                raise ClientStageFailure(
                    "AUTHORITATIVE_EFFECT", "NOT_OBSERVED",
                    "incomplete minion sequence: " + detail)
            status = "PASS"

            return self.finish(status, observed=observed, expected={
                "lane_approach": True,
                "opposing_minion_combat": True,
                "survivor_resumption": True,
                "structure_interaction": True})
        except Exception:
            self.finalize_capture()
            raise

    def finish(self, status: str, *, observed: dict, expected: dict) -> dict:
        result = {
            "schema_version": PAIR_SCHEMA_VERSION,
            "scenario": self.scenario,
            "mode": "client",
            "status": status,
            "stages": self.stages,
            "first_failed_stage": None,
            "failure_detail": None,
            "observed": observed,
            "expected": expected,
            "preparation": self.preparation,
            "gestures": self.gestures,
            "observations": self.observations,
            "qa_receipts": self.qa.receipts,
            "artifact_paths": self.artifacts,
            "connection": self.connection,
            # versioned top-level consumers depend on these keys:
            "fixture_contract": self.fixture_contract,
            "provenance": self.provenance_frame(),
            "fixture_manifest": self.observations.get("fixture_manifest"),
            "wall_completed_at": time.time(),
        }
        path = self.out_dir / f"client-result-{int(time.time())}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True),
                        encoding="utf-8")
        result["result_path"] = self.artifact(path)
        return result


def _resolve_client_output(explicit: str | None, scenario: str) -> Path:
    """Validated external output directory, before any input or capture.

    Rejects repository destinations and symlink/junction traversal, never
    overwrites a non-empty directory, and otherwise allocates a unique
    directory under TEMP.
    """
    from Tools.run_scenarios import OutputPathError, resolve_output_dir

    try:
        if explicit:
            return resolve_output_dir(explicit)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = Path(os.environ.get("TEMP", ".")) / f"halcyon-client-{scenario}-{stamp}"
        if base.exists():
            base = Path(os.environ.get("TEMP", ".")) /                 f"halcyon-client-{scenario}-{stamp}-{int(time.time())}"
        return resolve_output_dir(str(base))
    except OutputPathError as exc:
        raise ClientStageFailure("SETUP", "FAIL", f"invalid output directory: {exc}")


def run_client(scenario: str, args) -> dict:
    """Runner entry: execute one bounded client scenario, return its result.

    Any required-stage failure produces a classified result that retains all
    completed stages, gestures, observations and receipts; the caller
    (Tools.run_scenarios --mode client) maps non-PASS to a nonzero exit.
    """
    started = time.time()
    driver = None
    qa = None
    try:
        out_dir = _resolve_client_output(getattr(args, "output", None), scenario)
        if scenario not in CLIENT_SCENARIOS:
            raise ClientStageFailure("SETUP", "FAIL",
                                     f"unsupported client scenario: {scenario!r}")
        profile = load_client_profile(getattr(args, "client_profile", None))
        import hashlib as _hashlib
        profile_source_path = getattr(args, "client_profile", None)
        if profile_source_path:
            profile_digest = _hashlib.sha256(
                Path(profile_source_path).read_bytes()).hexdigest()
        else:
            profile_digest = _hashlib.sha256(json.dumps(
                DEFAULT_PROFILE, sort_keys=True).encode()).hexdigest()
        serial = getattr(args, "adb_serial", None)
        if not serial:
            raise ClientStageFailure("SETUP", "FAIL",
                                     "--adb-serial is required for client mode")
        qa_dir = getattr(args, "qa_dir", None)
        if not qa_dir:
            raise ClientStageFailure("SETUP", "FAIL",
                                     "--qa-dir (the running server's "
                                     "HALCYON_QA_DIR) is required for client mode")
        adb = Adb(serial)
        qa = QaSession(qa_dir)
        tail = verify_trace(getattr(args, "wire_trace", None),
                            timeout=float(getattr(args, "timeout", 30.0) or 30.0))
        driver = ClientDriver(scenario, adb=adb, qa=qa, tail=tail,
                              connection=getattr(args, "connection", None),
                              profile=profile, out_dir=out_dir,
                              timeout=float(getattr(args, "timeout", 30.0) or 30.0),
                              profile_digest=profile_digest)
        driver.stage("SETUP", "PENDING")
        if scenario == "minion-push":
            return driver.run_minion_push()
        slot = {"skye-a": "A", "skye-b": "B", "skye-c": "C"}[scenario]
        return driver.run_cast_scenario(slot, requires_lock=slot in ("B", "C"))
    except ClientStageFailure as exc:
        # Retain everything the trial completed: stages, gestures,
        # observations, receipts, artifacts -- only the failing stage is
        # marked; transport/capture cleanup still runs.
        if driver is not None:
            driver.finalize_capture()
            stages = driver.stages
            gestures = driver.gestures
            observations = driver.observations
            preparation = driver.preparation
            artifacts = driver.artifacts
            receipts = driver.qa.receipts
        else:
            stages = {name: {"status": "PENDING", "detail": ""}
                      for name in STAGES}
            gestures, observations, preparation, artifacts, receipts =                 [], {}, [], [], (qa.receipts if qa is not None else [])
        stages[exc.stage] = {"status": exc.status, "detail": exc.detail}
        result = {"scenario": scenario, "mode": "client", "status": "FAIL",
                  "stages": stages, "first_failed_stage": exc.stage,
                  "failure_detail": exc.detail, "observed": {}, "expected": {},
                  "preparation": preparation, "gestures": gestures,
                  "observations": observations, "qa_receipts": receipts,
                  "artifact_paths": artifacts,
                  "wall_completed_at": time.time(),
                  "elapsed_s": round(time.time() - started, 3)}
        if driver is not None:
            # An incomplete sequence is still a record of a REAL trial: it
            # carries the same provenance frame and the same observation
            # frame as a PASS record, so a validator can tell "this trial
            # failed its claim" from "this trial cannot evidence itself".
            result.update({
                "schema_version": PAIR_SCHEMA_VERSION,
                "connection": driver.connection,
                "fixture_contract": driver.fixture_contract,
                "provenance": driver.provenance_frame()})
        return _write_client_failure(result, out_dir if "out_dir" in locals()
                                     else None, scenario)
    except Exception as exc:                 # noqa: BLE001 -- transport/subprocess/
        # parser/capture infrastructure errors keep the partial state too,
        # with a structured error instead of losing all work.
        if driver is not None:
            driver.finalize_capture()
            stages = driver.stages
            extra = {"gestures": driver.gestures,
                     "observations": driver.observations,
                     "preparation": driver.preparation,
                     "artifact_paths": driver.artifacts,
                     "qa_receipts": driver.qa.receipts,
                     # same provenance frame as a PASS record: an
                     # infrastructure failure must not lose the ability to
                     # evidence which source/tape/config/match it ran against
                     "schema_version": PAIR_SCHEMA_VERSION,
                     "connection": driver.connection,
                     "fixture_contract": driver.fixture_contract,
                     "provenance": driver.provenance_frame()}
        else:
            stages = {name: {"status": "PENDING", "detail": ""}
                      for name in STAGES}
            extra = {"gestures": [], "observations": {},
                     "preparation": [], "artifact_paths": [],
                     "qa_receipts": qa.receipts if qa is not None else []}
        stages["SETUP"] = {"status": "ERROR", "detail": repr(exc)}
        result = {"scenario": scenario, "mode": "client", "status": "ERROR",
                  "stages": stages, "first_failed_stage": "SETUP",
                  "failure_kind": "infrastructure",
                  "failure_detail": repr(exc), "observed": {}, "expected": {},
                  "wall_completed_at": time.time(),
                  "elapsed_s": round(time.time() - started, 3), **extra}
        return _write_client_failure(result, out_dir if "out_dir" in locals()
                                     else None, scenario)


def _write_client_failure(result: dict, out_dir, scenario: str) -> dict:
    """Persist a failure result with partial evidence; never silent."""
    try:
        if out_dir is None:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            out_dir = Path(os.environ.get("TEMP", ".")) / \
                f"halcyon-client-{scenario}-failed-{stamp}"
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"client-result-{int(time.time())}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True),
                        encoding="utf-8")
        result["result_path"] = str(path)
    except Exception as exc:                 # noqa: BLE001
        result["result_write_error"] = repr(exc)
    return result
