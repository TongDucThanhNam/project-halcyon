"""Repeatable Skye and minion/turret verification pilot through the production sandbox.

MODES
-----
  headless   Deterministic pilot scenarios through the production
             SnapshotStream.advance_simulation() using the operator's external
             A001 navmesh with normal wave, structure, turret, jungle and hero
             lifecycle integration. No fake meshes, no disabled structures, no
             postponed ecology, no standalone wave pump. Repeatability means
             TWO independent Python processes (PYTHONHASHSEED 11 and 7919)
             running one pinned immutable source snapshot and compared by
             exact event/state bytes — never by PASS labels alone.

  client     Bounded real-client operation of one owned local session through
             Tools/scenario_client.py (QA snapshot verification, subprocess
             ADB input, wire-trace correlation, video evidence). This runner
             only forwards CLI arguments to it; live execution is a separate
             parent-delegated phase.

SCENARIOS (--mode headless)
----------------------------
  skye-a                  Forward Barrage: 1078 learn, 1042 ground cast,
                          energy paid, 1046 acknowledgment, attributed 1054
                          damage through the live world.
  skye-b                  Suri Strike: no-lock negative control, real 1060
                          basic-attack lock, then lock -> dash -> 4 missile
                          hits, with basic-attack damage excluded by window.
  skye-c                  Death from Above (Skye C is the ultimate, not
                          Calligraphy Strike): lock, immediate energy payment,
                          damage delayed exactly 26 ticks, stun applied.
  skye-lock-neg           Negative controls: B and C without a lock and B with
                          an expired lock must produce no cast acknowledgment,
                          no energy change and no attributed damage.
  minion-push             Full-world lane: wave 1 walks the A001 navmesh and
                          the two sides naturally meet at lane center (the
                          measured production outcome is mutual annihilation
                          there — the same lane-center stalemate the live
                          acceptance leaf documents). One recorded fixture
                          operation then eliminates the opposing wave (the
                          accepted test_wave_sandbox pattern inside the full
                          production world), and the survivor cohort must
                          resume toward the vulnerable outer turret through
                          normal navigation, stepped turret fire and minion
                          structure damage.
  minion-wave-regression  Same full-world run with wave 2 spawning distant at
                          base during the push; a post-combat survivor with no
                          current target must keep working toward the
                          vulnerable structure instead of chasing the distant
                          wave. Protects the ``structures is None``
                          precondition in ``wave.Director._select_target``:
                          removing it was the rejected experiment, now
                          reverted, and its return would fail this scenario
                          with a measured survivor retreat.

EVIDENCE (per scenario, per worker process)
--------------------------------------------
  events.bin               Every wire frame (bootstrap, intent-attributed and
                           simulation) as [u32 tick][u8 phase][u16 opcode]
                           [u16 length][payload]. Byte-compared across runs.
  initial-state.json       Canonical freeze (Tools.verify_sandbox.freeze_state)
                           after setup, before authored intents.
  final-state.json         Canonical freeze at the final tick.
  state-checkpoints.jsonl  Periodic canonical state hashes.
  evidence.json            Observed metrics, stage details, fixture operations.
  result.json              Worker result (wall times and paths; never compared).

Deterministic comparisons cover events.bin, initial-state.json,
final-state.json and state-checkpoints.jsonl only. Wall times, output paths
and the seed label never enter those artifacts. A changed effect or event
fails the pilot even when both runs otherwise satisfy their assertions.

Reference comparison (optional --reference) evaluates one externally authored
semantic fixture against observed metrics with per-metric tolerances. It never
generates expected values from the current run and never claims official
fidelity; without a fixture the reference status is UNAVAILABLE.

This pilot is distinct from Tools/verify_sandbox.py: the 960-second
coverage/deadline gate there is unchanged and remains the production fixture.

Run:
  python Tools/run_scenarios.py --mode headless --scenario all
  python Tools/run_scenarios.py --mode headless --scenario skye-b
  python Tools/run_scenarios.py --mode headless --scenario skye-a --reference ref.json
  python Tools/run_scenarios.py --mode client --scenario skye-b --adb-serial ... \
      --qa-dir ... --wire-trace ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TICK_SECONDS = 0.05
SEEDS = (11, 7919)
CHECKPOINT_CADENCE_TICKS = 20
ISOLATED_ENVIRONMENT = (
    "HALCYON_QA_DIR", "HALCYON_BOTS", "HALCYON_NO_WAVE", "HALCYON_HERO_1010",
    "HALCYON_SPARSE_1070", "HALCYON_HERO_KEEPALIVE", "HALCYON_HERO_SPAWN_X",
    "HALCYON_HERO_SPAWN_Y", "HALCYON_TEAM_ALLOCATION", "HALCYON_EXPERIMENTAL_CAPTURE",
    "HALCYON_SUPPRESS_PERIODIC_1070_SEC", "HALCYON_SUPPRESS_PERIODIC_1070_MOVE",
)
REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

# Authored modules pinned for the two-process repeatability runs. The pinned
# runtime imports only snapshot files (script path and sys.path both resolve
# inside the snapshot) and the worker asserts that before simulating.
PINNED_TOOLS = ("Tools/run_scenarios.py", "Tools/scenario_client.py",
                "Tools/verify_sandbox.py")

STAGES = (
    "SETUP",
    "INPUT_NOT_OBSERVED",
    "INPUT_UNACKNOWLEDGED",
    "ACCEPTED",
    "AUTHORITATIVE_EFFECT",
    "PRESENTATION",
)

PHASE_BOOTSTRAP, PHASE_INTENT, PHASE_SIM = 0, 1, 2

COMPARED_ARTIFACTS = ("events.bin", "initial-state.json", "final-state.json",
                      "state-checkpoints.jsonl")

SKYE_HERO_ID = 265
ENEMY_HERO_ID = 243


class StageFailure(Exception):
    """Classified failure at a specific evidence stage."""

    def __init__(self, stage: str, detail: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage: {stage!r}")
        self.stage = stage
        self.detail = detail
        super().__init__(f"[{stage}] {detail}")


class OutputPathError(ValueError):
    """Refused output destination (inside repo, link traversal, overwrite)."""


class ReferenceFixtureError(ValueError):
    """Invalid or incompatible external reference fixture.

    ``kind`` is MALFORMED (unreadable or schema-invalid) or INCOMPATIBLE
    (declared setup conditions do not match the scenario configuration).
    """

    def __init__(self, kind: str, detail: str) -> None:
        if kind not in ("MALFORMED", "INCOMPATIBLE"):
            raise ValueError(f"unknown reference error kind: {kind!r}")
        self.kind = kind
        super().__init__(f"[{kind}] {detail}")


# ---------------------------------------------------------------------------
# Source manifest and pinning (server/*.py plus every pinned Tools module)
# ---------------------------------------------------------------------------

def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, str]:
    paths = sorted((ROOT / "server").glob("*.py"))
    paths.extend(ROOT / name for name in PINNED_TOOLS if (ROOT / name).is_file())
    return {str(path.relative_to(ROOT)).replace("\\", "/"): digest_file(path)
            for path in paths}


def manifest_digest(manifest: dict[str, str]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def pin_sources(directory: Path) -> tuple[Path, dict[str, str]]:
    """Copy authored Python source into an immutable snapshot, race-safely."""
    while True:
        before = source_manifest()
        try:
            contents = {name: (ROOT / name).read_bytes() for name in before}
        except FileNotFoundError:
            continue
        if (source_manifest() == before
                and all(hashlib.sha256(contents[name]).hexdigest() == digest
                        for name, digest in before.items())):
            break
    pin_root = directory / "source-pin"
    pin_root.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="scenario-source-", dir=pin_root))
    for name, data in contents.items():
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return snapshot, before


# ---------------------------------------------------------------------------
# Output destination validation (before any simulation or live input)
# ---------------------------------------------------------------------------

def _reject_link_traversal(path: Path) -> None:
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            attributes = parent.lstat()
            if parent.is_symlink() or getattr(attributes, "st_file_attributes", 0) & REPARSE_ATTRIBUTE:
                raise OutputPathError(
                    f"output path must not traverse a symlink or junction: {parent}")


def resolve_output_dir(explicit: str | None, *, allow_existing_empty: bool = True) -> Path:
    """Validate and create the run directory before any simulation starts.

    The directory must stay outside this repository, must not traverse a
    symlink/junction, and an explicitly requested non-empty directory is never
    overwritten. Existing files anywhere on the path are preserved.
    """
    repository = ROOT.resolve()
    if explicit:
        base = Path(os.path.abspath(explicit))
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        parent = Path(tempfile.gettempdir())
        base = parent / f"halcyon-scenario-pilot-{stamp}"
        if base.exists():
            base = Path(tempfile.mkdtemp(prefix=f"halcyon-scenario-pilot-{stamp}-"))
    _reject_link_traversal(base)
    resolved = base.resolve()
    if resolved == repository or repository in resolved.parents:
        raise OutputPathError(f"output directory must stay outside the repository: {resolved}")
    if resolved.exists():
        if any(resolved.iterdir()):
            raise OutputPathError(f"refusing to write into non-empty directory: {resolved}")
        if not allow_existing_empty:
            raise OutputPathError(f"output directory already exists: {resolved}")
    else:
        resolved.mkdir(parents=True)
    return resolved


# ---------------------------------------------------------------------------
# Production world construction (verify_sandbox.run_worker pattern)
# ---------------------------------------------------------------------------

def default_navmesh_path() -> Path:
    from server import navigation
    return Path(os.environ.get("HALCYON_NAVMESH", "") or navigation.DEFAULT_A001_PATH)


def build_world(navmesh_path: Path, match_id: str = "scenario-pilot-match"):
    """Full production world: real A001 mesh, waves, structures, jungle, QA off.

    Returns (world, owner, pending, mesh). The owner object is the registered
    local connection so authored intents route to players[0] (eid 1500),
    matching the test_skye_session pattern.
    """
    from server import match_server, navigation, roster

    mesh = navigation.load_halcyon_navmesh(navmesh_path)
    players = roster.default_solo_bots("scenario-pilot", match_id)
    players = [players[0], players[3]]           # slot-0 eid=1500, slot-3 eid=1517
    players[0].hero_id = SKYE_HERO_ID
    players[1].hero_id = ENEMY_HERO_ID
    for player in players:
        player.is_bot = False
        player.selection_hash = 0
        player.pick_flags = roster.PICK_FLAG_LOCKED
    owner = object()
    pending: list[tuple[int, bytes]] = []
    world = match_server.SnapshotStream(
        owner, players, match_id,
        lambda opcode, payload: pending.append((opcode, payload)),
        log=lambda _: None, navigation_mesh=mesh)
    world._finalize()
    world._dump_world()
    world._enter_world()
    if world.qa is not None or world.tape_frames:
        raise AssertionError("scenario worker must not consume live QA commands or replay a world tape")
    # _run_world publishes initial jungle actors before its first fixed tick;
    # reproduce that setup with the same production publisher.
    sequence = [world.seq_1010]
    world._emit_frames(world.jungle.get_spawn_frames(
        seq_1010=sequence, actor_slots=world.actor_slots))
    world.seq_1010 = sequence[0]
    world._jungle_published = True
    return world, owner, pending, mesh


class ScenarioController:
    """Authored tick-indexed intents plus recorded fixture placement.

    Intents are real production opcodes applied through world._apply_event at
    fixed tick indices. Fixture operations (placement teleports, resource and
    XP preparation, stops) are recorded separately and never presented as
    production intents or effects.
    """

    def __init__(self, world, owner, pending):
        self.world = world
        self.owner = owner
        self.pending = pending
        self.schedule: dict[int, list[tuple[int, bytes]]] = {}
        self.state: dict[str, Any] = {"intents": [], "fixture_operations": [], "notes": []}

    def intent(self, tick: int, opcode: int, payload: bytes, note: str) -> None:
        self.schedule.setdefault(tick, []).append((opcode, payload))
        self.state["intents"].append({"tick": tick, "opcode": opcode,
                                      "payload": payload.hex(), "note": note})

    def fixture(self, op: str, **detail) -> None:
        self.state["fixture_operations"].append(
            {"tick": self.world.sim_tick, "op": op, **detail})

    def note(self, message: str) -> None:
        self.state["notes"].append({"tick": self.world.sim_tick, "note": message})

    def step(self, tick: int) -> None:
        for opcode, payload in self.schedule.get(tick, ()):
            self.world._apply_event(opcode, payload, conn=self.owner)

    def drain(self) -> list[tuple[int, bytes]]:
        frames, self.pending[:] = list(self.pending), []
        return frames


# ---------------------------------------------------------------------------
# Evidence writers
# ---------------------------------------------------------------------------

def json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


class EventLog:
    """Tick-indexed wire record; the canonical byte-compared event stream."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._binary = path.open("wb")
        self._text = path.with_suffix(".jsonl").open("w", encoding="ascii")
        self.frames = 0

    def extend(self, tick: int, phase: int, frames: list[tuple[int, bytes]]) -> None:
        for opcode, payload in frames:
            self._binary.write(struct.pack(">IBHH", tick, phase, opcode, len(payload)))
            self._binary.write(payload)
            self._text.write(json.dumps({"tick": tick, "phase": phase,
                                         "opcode": opcode, "payload": payload.hex()},
                                        separators=(",", ":")) + "\n")
            self.frames += 1

    def close(self) -> None:
        self._binary.close()
        self._text.close()


class CheckpointWriter:
    """Periodic canonical state hashes, byte-compared across runs."""

    def __init__(self, path: Path, world, controller, mesh_digest: str) -> None:
        self.path = path
        self.world = world
        self.controller = controller
        self.mesh_digest = mesh_digest
        self.rolling = hashlib.sha256()
        self.count = 0
        self._handle = path.open("wb")

    def _write(self) -> None:
        from Tools.verify_sandbox import freeze_state
        snapshot = freeze_state(self.world, self.controller, self.mesh_digest)
        record = json_bytes({"tick": self.world.sim_tick,
                             "sha256": hashlib.sha256(snapshot).hexdigest()}) + b"\n"
        self._handle.write(record)
        self.rolling.update(record)
        self.count += 1

    def maybe(self, world) -> None:
        if world.sim_tick % CHECKPOINT_CADENCE_TICKS == 0:
            self._write()

    def finalize(self) -> None:
        if self.world.sim_tick % CHECKPOINT_CADENCE_TICKS != 0:
            self._write()
        self._handle.close()


def freeze_world(world, controller, mesh_digest: str) -> bytes:
    """Reuse the production canonical freeze; controller.state carries only
    tick-indexed authored intents and fixture records, never wall time."""
    from Tools.verify_sandbox import freeze_state
    return freeze_state(world, controller, mesh_digest)


# ---------------------------------------------------------------------------
# Frame analysis helpers
# ---------------------------------------------------------------------------

def damage_records(frames) -> list[tuple[int, int, float]]:
    """(victim, attacker, damage) from (opcode, payload) pairs; 1054 signed f32 at +8."""
    out = []
    for opcode, payload in frames:
        if opcode == 1054 and len(payload) >= 12:
            victim, attacker = struct.unpack_from(">II", payload, 0)
            (damage,) = struct.unpack_from(">f", payload, 8)
            out.append((victim, attacker, damage))
    return out


def cast_ack_payloads(frames, native_action: int) -> list[bytes]:
    """1046 ground-cast acknowledgments carrying the native action byte at +16."""
    return [payload for opcode, payload in frames
            if opcode == 1046 and len(payload) > 16 and payload[16] == native_action]


def lock_buff_payloads(frames, target_eid: int) -> list[bytes]:
    """1086 lock-kind (602) buffs targeting ``target_eid`` via the production parser."""
    from server.buff_wire import parse_buff_add
    found = []
    for opcode, payload in frames:
        if opcode == 1086 and len(payload) == 22:
            try:
                buff = parse_buff_add(payload)
            except ValueError:
                continue
            if buff.kind == 602 and buff.target_eid == target_eid:
                found.append(payload)
    return found


# ---------------------------------------------------------------------------
# Scenario harness
# ---------------------------------------------------------------------------

def _stage(result: dict, name: str, status: str, detail: str = "") -> None:
    result["stages"][name] = {"status": status, "detail": detail}


def _pass(result: dict, observed: dict, expected: dict) -> None:
    result["status"] = "PASS"
    result["observed"] = observed
    result["expected"] = expected


def _fail(result: dict, exc: StageFailure) -> None:
    result["status"] = "FAIL"
    result["first_failed_stage"] = exc.stage
    result["failure_detail"] = exc.detail
    _stage(result, exc.stage, "FAIL", exc.detail)


def _base_result(scenario_id: str, seed: int, out_dir: Path, navmesh_path: Path,
                 mesh) -> dict:
    return {
        "scenario_id": scenario_id,
        "mode": "headless",
        "seed": seed,          # label only; compared artifacts never embed it
        "configuration": {
            "match_id": "scenario-pilot-match",
            "hero_id": SKYE_HERO_ID,
            "enemy_hero_id": ENEMY_HERO_ID,
            "navmesh": {"path": str(navmesh_path), "sha256": digest_file(navmesh_path),
                        "vertices": len(mesh.vertices), "triangles": len(mesh.triangles)},
            "tick_seconds": TICK_SECONDS,
        },
        "source_manifest_sha256": manifest_digest(source_manifest()),
        "intents": [],
        "fixture_operations": [],
        "stages": {name: {"status": "PENDING", "detail": ""} for name in STAGES},
        "status": "UNKNOWN",
        "first_failed_stage": None,
        "failure_detail": None,
        "observed": {},
        "expected": {},
        "observed_metrics": {},
        "reference": {"status": "UNAVAILABLE",
                      "detail": "no external reference fixture provided"},
        "events": {"path": str(out_dir / "events.bin")},
        "initial_state": {"path": str(out_dir / "initial-state.json")},
        "final_state": {"path": str(out_dir / "final-state.json")},
        "checkpoints": {"path": str(out_dir / "state-checkpoints.jsonl")},
        "artifact_paths": [],
        "wall_elapsed_s": 0.0,
    }


class WorldEvidence:
    """Bounded in-memory interpretation of the live world during a run."""

    def __init__(self, world) -> None:
        self.world = world
        self.guard_window: tuple[int, int] | None = None
        self.damage: list[tuple[int, int, int, float]] = []       # (tick, victim, attacker, dmg)
        self.wave_index_changes: list[tuple[int, int]] = []
        self.structure_hp_changes: list[tuple[int, int, float]] = []
        self.minion_first_damage_pos: dict[int, tuple[float, float]] = {}
        self.minion_pos_at_fixture: dict[int, tuple[float, float]] = {}
        self.minion_peak: dict[int, tuple[float, float]] = {}    # best toward-enemy pos
        self.minion_last_pos: dict[int, tuple[float, float]] = {}
        self.guard_samples: list[tuple[int, int, float, float, bool, bool]] = []
        self._structure_hp: dict[int, float] = {}
        self._last_wave_index = None

    def observe(self, tick: int, frames: list[tuple[int, bytes]]) -> None:
        if self.world.wave_director:
            for m in self.world.wave_director.minions:
                if m.alive:
                    prev = self.minion_peak.get(m.eid)
                    if (prev is None
                            or (m.side == 1 and m.x > prev[0])
                            or (m.side == 2 and m.x < prev[0])):
                        self.minion_peak[m.eid] = (m.x, m.y)
        for victim, attacker, amount in damage_records(frames):
            self.damage.append((tick, victim, attacker, amount))
            minions = {m.eid: m for m in self.world.wave_director.minions} \
                if self.world.wave_director else {}
            for eid in (victim, attacker):
                if eid in minions and eid not in self.minion_first_damage_pos:
                    m = minions[eid]
                    self.minion_first_damage_pos[eid] = (m.x, m.y)
        if self.world.wave_director and self.world.wave_director.wave_index != self._last_wave_index:
            self._last_wave_index = self.world.wave_director.wave_index
            self.wave_index_changes.append((tick, self._last_wave_index))
        for eid, structure in self.world.structures.structures.items():
            known = self._structure_hp.get(eid)
            if known is None or structure.hp != known:
                self._structure_hp[eid] = structure.hp
                self.structure_hp_changes.append((tick, eid, structure.hp))
        if self.guard_window and self.guard_window[0] <= tick <= self.guard_window[1] \
                and self.world.wave_director:
            if tick % 5 == 0:
                for m in self.world.wave_director.minions:
                    if m.alive:
                        self.minion_last_pos[m.eid] = (m.x, m.y)
                        if m.has_engaged and m.target is None:
                            self.guard_samples.append(
                                (tick, m.eid, m.x, m.y, m.target is None, m.has_engaged))

    def sample_final(self) -> None:
        if self.world.wave_director:
            for m in self.world.wave_director.minions:
                if m.alive:
                    self.minion_last_pos[m.eid] = (m.x, m.y)


class ScenarioRun:
    """One scenario execution: world, event log, checkpoints, evidence."""

    def __init__(self, scenario_id: str, seed: int, out_dir: Path, navmesh_path: Path,
                 *, keep_frames: bool = False) -> None:
        self.scenario_id = scenario_id
        self.seed = seed
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.navmesh_path = navmesh_path
        self.mesh_digest = digest_file(navmesh_path)
        self.started = time.perf_counter()
        self.world, self.owner, self.pending, self.mesh = build_world(
            navmesh_path, f"scenario-pilot-{scenario_id}")
        self.controller = ScenarioController(self.world, self.owner, self.pending)
        self.log = EventLog(out_dir / "events.bin")
        self.checkpoints = CheckpointWriter(out_dir / "state-checkpoints.jsonl",
                                            self.world, self.controller, self.mesh_digest)
        self.evidence = WorldEvidence(self.world)
        self.keep_frames = keep_frames
        self.frames: list[tuple[int, int, int, bytes]] = []   # (tick, phase, opcode, payload)
        self.initial_freeze: bytes | None = None
        self.result = _base_result(scenario_id, seed, out_dir, navmesh_path, self.mesh)
        self.log.extend(0, PHASE_BOOTSTRAP, self.controller.drain())

    # -- lifecycle ----------------------------------------------------------

    def freeze_initial(self) -> None:
        self.initial_freeze = freeze_world(self.world, self.controller, self.mesh_digest)
        (self.out_dir / "initial-state.json").write_bytes(self.initial_freeze)

    def ticks(self, count: int, *, monitor: Callable[[], None] | None = None,
              after_intents: Callable[[], None] | None = None) -> None:
        """Advance ``count`` fixed ticks with per-phase frame attribution.

        ``after_intents`` runs after intent application but before the
        simulation advance of each tick — the only point where immediate cast
        state (e.g. energy payment) is observable without regen drift.
        """
        for _ in range(count):
            tick = self.world.sim_tick
            self.controller.step(tick)
            intent_frames = self.controller.drain()
            self.log.extend(tick, PHASE_INTENT, intent_frames)
            if after_intents is not None:
                after_intents()
            self.world.advance_simulation()
            sim_frames = self.controller.drain()
            self.log.extend(tick, PHASE_SIM, sim_frames)
            if self.keep_frames:
                self.frames.extend((tick, PHASE_INTENT, op, p) for op, p in intent_frames)
                self.frames.extend((tick, PHASE_SIM, op, p) for op, p in sim_frames)
            self.evidence.observe(tick, sim_frames)
            self.checkpoints.maybe(self.world)
            if monitor is not None:
                monitor()

    def finish(self) -> None:
        if getattr(self, "_finished", False):
            return
        self._finished = True
        self.evidence.sample_final()
        (self.out_dir / "final-state.json").write_bytes(
            freeze_world(self.world, self.controller, self.mesh_digest))
        self.checkpoints.finalize()
        self.log.close()
        self.result["intents"] = self.controller.state["intents"]
        self.result["fixture_operations"] = self.controller.state["fixture_operations"]
        self.result["notes"] = self.controller.state["notes"]
        self.result["events"].update(sha256=digest_file(self.out_dir / "events.bin"),
                                     frames=self.log.frames)
        self.result["initial_state"].update(
            sha256=hashlib.sha256(self.initial_freeze or b"").hexdigest())
        final_path = self.out_dir / "final-state.json"
        self.result["final_state"].update(sha256=digest_file(final_path))
        self.result["checkpoints"].update(
            sha256=self.checkpoints.rolling.hexdigest(), count=self.checkpoints.count)
        self.result["configuration"]["window_ticks"] = self.world.sim_tick
        self.result["configuration"]["sim_time"] = self.world.sim_time
        self.result["wall_elapsed_s"] = round(time.perf_counter() - self.started, 4)
        self.result["artifact_paths"] = [
            str(self.out_dir / name) for name in COMPARED_ARTIFACTS]
        evidence_path = self.out_dir / "evidence.json"
        evidence_path.write_bytes(json_bytes({
            "scenario_id": self.scenario_id,
            "stages": self.result["stages"],
            "observed": self.result["observed"],
            "observed_metrics": self.result["observed_metrics"],
            "intents": self.result["intents"],
            "fixture_operations": self.result["fixture_operations"],
            "notes": self.result["notes"],
            "events_sha256": self.result["events"]["sha256"],
            "initial_state_sha256": self.result["initial_state"]["sha256"],
            "final_state_sha256": self.result["final_state"]["sha256"],
            "checkpoints_sha256": self.result["checkpoints"]["sha256"],
        }))
        self.result["artifact_paths"].append(str(evidence_path))

    def frames_since(self, tick: int) -> list[tuple[int, bytes]]:
        return [(op, p) for t, _phase, op, p in self.frames if t >= tick]

    # -- Skye helpers ---------------------------------------------------------

    def skye_actors(self) -> tuple[Any, Any, Any]:
        world = self.world
        hero = world.hero_sims[world.players[0].eid]
        enemy = world.hero_sims[world.players[1].eid]
        return hero, enemy, world.hero_kits[hero.eid]

    def prepare_skye_duel(self) -> dict:
        """Fixture placement through the production QA teleport/stop path.

        Positions (0,35)/(4,35) are the live-verified placement; nearest_point
        is identity there on the real A001 mesh (verified during design).
        """
        world = self.world
        hero, enemy, _kit = self.skye_actors()
        for actor, pos in ((hero, (0.0, 35.0)), (enemy, (4.0, 35.0))):
            nx, ny = world.navigation.nearest_point(pos)
            actor.set_target_eid(None)
            world.attacks.cancel(actor.eid)
            frames = actor.stop() + actor.teleport(nx, ny)
            world._emit_frames(frames)
            self.controller.fixture("teleport", eid=actor.eid, requested=list(pos),
                                    placed=[round(nx, 4), round(ny, 4)])
        econ = world.economy.get_or_create(hero.eid)
        econ.add_xp(500.0)
        econ.apply_to_hero(hero)
        self.controller.fixture("grant-xp", eid=hero.eid, amount=500.0,
                                level=econ.level, ability_points=econ.ability_points)
        # Level recalculation resets energy to the level baseline; grant the
        # full cell afterwards so the cast cost is measured from a known cell.
        hero.energy = hero.max_energy = 1000.0
        enemy.hp = enemy.max_hp = 10000.0
        self.controller.fixture("resources", eid=hero.eid, energy=1000.0)
        self.controller.fixture("resources", eid=enemy.eid, hp=10000.0)
        placement = self.safety_check()
        self.controller.note(f"placement {json.dumps(placement, sort_keys=True)}")
        return {"hero": hero, "enemy": enemy, "placement": placement}

    def safety_check(self) -> dict:
        """Setup honesty: on-mesh positions, viable separation, no turret threat."""
        world = self.world
        hero, enemy, _kit = self.skye_actors()
        hero_pos, enemy_pos = (hero.x, hero.y), (enemy.x, enemy.y)
        if not world.navigation.contains(hero_pos) or not world.navigation.contains(enemy_pos):
            raise StageFailure("SETUP",
                               f"scenario positions off the A001 mesh: {hero_pos} {enemy_pos}")
        distance = math.dist(hero_pos, enemy_pos)
        if not 0.5 <= distance <= 5.5:
            raise StageFailure("SETUP",
                               f"hero separation {distance:.3f} outside lock viability (0.5..5.5)")
        threats = []
        for structure in world.structures.structures.values():
            if structure.is_alive and not structure.is_crystal:
                for label, pos in (("hero", hero_pos), ("enemy", enemy_pos)):
                    if math.dist(pos, (structure.x, structure.y)) <= structure.attack_range + 1.0:
                        threats.append([structure.eid, label])
        if threats:
            raise StageFailure("SETUP", f"scenario positions inside turret threat: {threats}")
        if not hero.is_alive or not enemy.is_alive:
            raise StageFailure("SETUP", "duel actors must be alive at setup")
        return {"hero_pos": [round(hero.x, 4), round(hero.y, 4)],
                "enemy_pos": [round(enemy.x, 4), round(enemy.y, 4)],
                "distance": round(distance, 4)}

    def wait_for_lock(self, hero, enemy, kit, *, max_wait: int = 30) -> int:
        """Real 1060 basic-attack intent, then fixed ticks until the lock binds.

        Returns the post-advance tick at which the lock was observed. The
        caller must hold position and cast within this same tick boundary,
        with no intervening reads, mirroring the established test pattern.
        """
        from server import roster
        scheduled_at = self.world.sim_tick + 2
        self.controller.intent(scheduled_at, 1060, roster.build_target_entity(enemy.eid),
                               f"target enemy {enemy.eid} for basic-attack lock")
        for _waited in range(max_wait):
            self.ticks(1)
            if kit.locked_target is enemy:
                self.controller.note(f"lock established at tick {self.world.sim_tick}")
                return self.world.sim_tick
        raise StageFailure("SETUP",
                           f"basic-hit lock on enemy {enemy.eid} not established "
                           f"within {max_wait} ticks of tick {scheduled_at}")

    def hold_position(self, hero) -> None:
        """Production stop order plus fixture stop, applied in the established
        lock->cast order (1012 intent, stop, then the cast) inside one tick
        boundary, exactly as test_skye_session.establish_lock does."""
        from server import roster
        tick = self.world.sim_tick
        self.controller.intent(tick, 1012, roster.build_move(hero.x, hero.y),
                               "move-to-current-position to stop auto-attack pursuit")
        self.controller.step(tick)          # apply 1012 immediately
        self.world._emit_frames(hero.stop())
        self.controller.fixture("stop", eid=hero.eid)


# ---------------------------------------------------------------------------
# Scenario: skye-a
# ---------------------------------------------------------------------------

def scenario_skye_a(seed: int, out_dir: Path, navmesh_path: Path) -> dict:
    run = ScenarioRun("skye-a", seed, out_dir, navmesh_path, keep_frames=True)
    result = run.result
    try:
        setup = run.prepare_skye_duel()
        hero, enemy, kit = setup["hero"], setup["enemy"], run.skye_actors()[2]
        run.controller.intent(2, 1078, bytes((0,)) + bytes(5), "learn A slot 0")
        run.freeze_initial()
        cast_tick = 4
        energy_before = hero.energy

        def monitor() -> None:
            tick = run.world.sim_tick
            if tick == 3:
                if kit.ranks.get(0, 0) < 1:
                    raise StageFailure("SETUP", "A rank not registered after 1078 learn slot 0")
                _stage(result, "SETUP", "PASS", json.dumps(setup["placement"], sort_keys=True))
            if tick == cast_tick:
                run.controller.intent(cast_tick, 1042,
                                      struct.pack(">fffBB", enemy.x, 0.0, enemy.y, 0, 0),
                                      "cast A (native action 0) at enemy position")
            if tick == cast_tick + 1:
                if hero.energy >= energy_before:
                    raise StageFailure("INPUT_UNACKNOWLEDGED",
                                       "energy unchanged after A cast — intent not processed")
                _stage(result, "INPUT_UNACKNOWLEDGED", "PASS",
                       f"energy {energy_before} -> {hero.energy}")

        run.ticks(72, monitor=monitor)
        run.finish()

        window = [(op, p) for t, _phase, op, p in run.frames if t >= cast_tick]
        attributed = [(v, a, d) for v, a, d in damage_records(window)
                      if v == enemy.eid and a == hero.eid]
        acks = cast_ack_payloads(window, 0)
        if not acks:
            raise StageFailure("ACCEPTED", "no 1046 action=0 acknowledgment recorded")
        if not attributed:
            raise StageFailure("AUTHORITATIVE_EFFECT",
                               f"no 1054 from hero({hero.eid}) to enemy({enemy.eid}) in A window")
        _stage(result, "ACCEPTED", "PASS", f"{len(acks)} 1046 action=0 acknowledgments")
        _stage(result, "AUTHORITATIVE_EFFECT", "PASS",
               f"{len(attributed)} attributed damage events")
        _stage(result, "PRESENTATION", "UNVERIFIED",
               "wire frames only; rendered-client review is a separate phase")
        spent = round(1000.0 - hero.energy, 4)
        _pass(result, {
            "energy_spent": spent,
            "damage_events": [[v, a, round(d, 4)] for v, a, d in attributed],
            "ack_count": len(acks),
            "enemy_hp_after": round(enemy.hp, 4),
        }, {"energy_paid": True, "damage_attributed_to_hero": True, "ack_action_0": True})
        result["observed_metrics"] = {
            "energy_spent": spent,
            "damage_event_count": len(attributed),
            "first_damage_amount": round(attributed[0][2], 4),
            "total_damage": round(sum(d for _, _, d in attributed), 4),
            "ack_count": len(acks),
        }
    except StageFailure as exc:
        _fail(result, exc)
        run.finish()
    except Exception as exc:  # infrastructure error: preserve detail, never PASS
        result["status"] = "ERROR"
        result["error"] = repr(exc)
        run.finish()
    return result


# ---------------------------------------------------------------------------
# Scenario: skye-b
# ---------------------------------------------------------------------------

def scenario_skye_b(seed: int, out_dir: Path, navmesh_path: Path) -> dict:
    run = ScenarioRun("skye-b", seed, out_dir, navmesh_path, keep_frames=True)
    result = run.result
    try:
        setup = run.prepare_skye_duel()
        hero, enemy, kit = setup["hero"], setup["enemy"], run.skye_actors()[2]
        run.controller.intent(2, 1078, bytes((1,)) + bytes(5), "learn B slot 1")
        run.freeze_initial()
        energy_full = hero.energy

        # -- Negative control: B without a lock -----------------------------
        run.controller.intent(8, 1042,
                              struct.pack(">fffBB", enemy.x, 0.0, enemy.y, 2, 0),
                              "cast B (native action 2) without lock — negative control")
        run.ticks(13)
        if kit.ranks.get(1, 0) < 1:
            raise StageFailure("SETUP", "B rank not registered after 1078 learn slot 1")
        _stage(result, "SETUP", "PASS", json.dumps(setup["placement"], sort_keys=True))
        window = run.frames_since(8)
        neg_acks = cast_ack_payloads(window, 2)
        neg_damage = [(v, a, d) for v, a, d in damage_records(window)
                      if v == enemy.eid and a == hero.eid]
        if neg_acks or neg_damage or hero.energy != energy_full:
            raise StageFailure("ACCEPTED",
                               f"B produced output without a lock (acks={len(neg_acks)}, "
                               f"damage={len(neg_damage)}, energy_changed="
                               f"{hero.energy != energy_full}) — negative case broken")
        _stage(result, "INPUT_NOT_OBSERVED", "PASS",
               "no-lock B produced no 1046 acknowledgment, no damage, no energy change")

        # -- Real basic-attack lock, then immediate cast --------------------
        lock_tick = run.wait_for_lock(hero, enemy, kit)
        lock_frames = run.frames_since(lock_tick - 1)
        if not lock_buff_payloads(lock_frames, enemy.eid):
            raise StageFailure("AUTHORITATIVE_EFFECT",
                               "lock buff kind=602 not emitted after basic hit")
        # 1012 + stop + cast all resolve inside this same tick boundary.
        run.hold_position(hero)
        before_hp = enemy.hp
        energy_before = hero.energy
        cast_tick = run.world.sim_tick
        run.controller.intent(cast_tick, 1042,
                              struct.pack(">fffBB", enemy.x, 0.0, enemy.y, 2, 0),
                              "cast B (native action 2) with lock — same tick boundary")
        run.ticks(20)

        window = run.frames_since(cast_tick)
        b_acks = cast_ack_payloads(window, 2)
        if not b_acks:
            raise StageFailure("INPUT_UNACKNOWLEDGED",
                               "B with a valid lock produced no 1046 acknowledgment — "
                               "reason unknown (not an observed rejection)")
        _stage(result, "INPUT_UNACKNOWLEDGED", "PASS", "intent reached the server")
        _stage(result, "ACCEPTED", "PASS", f"{len(b_acks)} 1046 action=2 acknowledgments")
        if hero.energy >= energy_before:
            raise StageFailure("ACCEPTED", "B energy not paid despite acknowledgment")
        missiles = [(v, a, d) for v, a, d in damage_records(window)
                    if v == enemy.eid and a == hero.eid]
        dash_distance = math.dist((0.0, 35.0), (hero.x, hero.y))
        if len(missiles) != 4:
            raise StageFailure("AUTHORITATIVE_EFFECT",
                               f"expected exactly 4 missile 1054 hits in the 20-tick "
                               f"window; got {len(missiles)}")
        if enemy.hp >= before_hp:
            raise StageFailure("AUTHORITATIVE_EFFECT", "enemy HP unchanged after B missiles")
        _stage(result, "AUTHORITATIVE_EFFECT", "PASS",
               f"4 missile hits, dash {dash_distance:.3f}u")
        _stage(result, "PRESENTATION", "UNVERIFIED",
               "wire frames only; rendered-client review is a separate phase")
        run.finish()
        _pass(result, {
            "nolock_acks": len(neg_acks),
            "ack_count": len(b_acks),
            "missile_hits": [[v, a, round(d, 4)] for v, a, d in missiles],
            "energy_spent": round(energy_before - hero.energy, 4),
            "dash_distance": round(dash_distance, 4),
            "enemy_hp_before": round(before_hp, 4),
            "enemy_hp_after": round(enemy.hp, 4),
            "lock_tick": lock_tick,
            "cast_tick": cast_tick,
        }, {"nolock_B_rejected": True, "with_lock_accepted": True,
            "missile_hits_exactly_4": True, "enemy_hp_reduced": True})
        result["observed_metrics"] = {
            "nolock_ack_count": len(neg_acks),
            "missile_hit_count": len(missiles),
            "total_missile_damage": round(sum(d for _, _, d in missiles), 4),
            "energy_spent": round(energy_before - hero.energy, 4),
            "dash_distance": round(dash_distance, 4),
        }
    except StageFailure as exc:
        _fail(result, exc)
        run.finish()
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = repr(exc)
        run.finish()
    return result


# ---------------------------------------------------------------------------
# Scenario: skye-c
# ---------------------------------------------------------------------------

def scenario_skye_c(seed: int, out_dir: Path, navmesh_path: Path) -> dict:
    run = ScenarioRun("skye-c", seed, out_dir, navmesh_path, keep_frames=True)
    result = run.result
    try:
        from server.status_effects import StatusType
        setup = run.prepare_skye_duel()
        hero, enemy, kit = setup["hero"], setup["enemy"], run.skye_actors()[2]
        run.controller.intent(2, 1078, bytes((2,)) + bytes(5), "learn C slot 2")
        run.freeze_initial()
        run.ticks(4)
        if kit.ranks.get(2, 0) < 1:
            raise StageFailure("SETUP", "C rank not registered after 1078 learn slot 2")
        _stage(result, "SETUP", "PASS", json.dumps(setup["placement"], sort_keys=True))

        lock_tick = run.wait_for_lock(hero, enemy, kit)
        run.hold_position(hero)
        before_hp, before_energy = enemy.hp, hero.energy
        cast_tick = run.world.sim_tick
        run.controller.intent(cast_tick, 1042,
                              struct.pack(">fffBB", enemy.x, 0.0, enemy.y, 4, 0),
                              "cast C (native action 4) with lock — same tick boundary")
        # Energy payment is observable only between intent application and the
        # simulation advance; afterwards regen drifts the value every tick.
        paid = {"energy": None}

        def capture_energy() -> None:
            if paid["energy"] is None and hero.energy != before_energy:
                paid["energy"] = hero.energy

        run.ticks(26, after_intents=capture_energy)
        if paid["energy"] is None:
            raise StageFailure("INPUT_UNACKNOWLEDGED", "C energy was not paid on cast")
        spent = round(before_energy - paid["energy"], 4)
        if spent != 70.0:
            raise StageFailure("ACCEPTED",
                               f"C energy cost {spent} != the native 70 at rank 1")
        _stage(result, "INPUT_UNACKNOWLEDGED", "PASS",
               f"energy {before_energy} -> {paid['energy']} immediately on cast")
        stunned_at_damage = run.world.status_manager.has_effect(
            enemy.eid, StatusType.STUN, run.world.sim_time)
        run.ticks(39)

        window = run.frames_since(cast_tick)
        c_acks = cast_ack_payloads(window, 4)
        if not c_acks:
            raise StageFailure("ACCEPTED", "no 1046 action=4 acknowledgment recorded")
        pulses = [(t, d) for t, _phase, op, p in run.frames if op == 1054 and t >= cast_tick
                  for (v, a, d) in damage_records([(1054, p)])
                  if v == enemy.eid and a == hero.eid]
        if not pulses:
            raise StageFailure("AUTHORITATIVE_EFFECT", "no delayed C damage landed")
        first_damage_tick = pulses[0][0]
        if first_damage_tick != cast_tick + 25:
            raise StageFailure("AUTHORITATIVE_EFFECT",
                               f"first C damage at tick {first_damage_tick}, expected the "
                               f"26th tick after cast ({cast_tick + 25})")
        if not stunned_at_damage:
            raise StageFailure("AUTHORITATIVE_EFFECT", "C stun not applied to the enemy")
        if enemy.hp >= before_hp:
            raise StageFailure("AUTHORITATIVE_EFFECT", "enemy HP unchanged after C")
        _stage(result, "ACCEPTED", "PASS", f"{len(c_acks)} 1046 action=4 acknowledgments")
        _stage(result, "AUTHORITATIVE_EFFECT", "PASS",
               f"damage delayed {first_damage_tick - cast_tick} ticks, "
               f"{len(pulses)} pulses in window, stun applied at the damage tick")
        _stage(result, "PRESENTATION", "UNVERIFIED",
               "wire frames only; rendered-client review is a separate phase")
        run.finish()
        _pass(result, {
            "energy_spent": spent,
            "first_damage_tick": first_damage_tick,
            "delay_ticks": first_damage_tick - cast_tick,
            "pulse_count": len(pulses),
            "total_damage": round(sum(d for _, d in pulses), 4),
            "stun_applied": bool(stunned_at_damage),
            "enemy_hp_after": round(enemy.hp, 4),
        }, {"energy_paid_immediately": True, "damage_delayed_26_ticks": True,
            "stun_applied": True})
        result["observed_metrics"] = {
            "energy_spent": spent,
            "delay_ticks": first_damage_tick - cast_tick,
            "pulse_count": len(pulses),
            "total_damage": round(sum(d for _, d in pulses), 4),
            "stun_applied": bool(stunned_at_damage),
        }
    except StageFailure as exc:
        _fail(result, exc)
        run.finish()
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = repr(exc)
        run.finish()
    return result


# ---------------------------------------------------------------------------
# Scenario: skye-lock-neg
# ---------------------------------------------------------------------------

def scenario_skye_lock_neg(seed: int, out_dir: Path, navmesh_path: Path) -> dict:
    run = ScenarioRun("skye-lock-neg", seed, out_dir, navmesh_path, keep_frames=True)
    result = run.result
    try:
        setup = run.prepare_skye_duel()
        hero, enemy, kit = setup["hero"], setup["enemy"], run.skye_actors()[2]
        run.controller.intent(2, 1078, bytes((1,)) + bytes(5), "learn B slot 1")
        run.controller.intent(4, 1078, bytes((2,)) + bytes(5), "learn C slot 2")
        run.freeze_initial()
        run.ticks(6)
        if kit.ranks.get(1, 0) < 1 or kit.ranks.get(2, 0) < 1:
            raise StageFailure("SETUP", "B/C ranks not registered after 1078 learns")
        _stage(result, "SETUP", "PASS", json.dumps(setup["placement"], sort_keys=True))

        def negative_cast(action: int, label: str) -> int:
            tick = run.world.sim_tick + 1
            energy_before = hero.energy
            run.controller.intent(tick, 1042,
                                  struct.pack(">fffBB", enemy.x, 0.0, enemy.y, action, 0),
                                  f"cast native action {action} ({label}) — negative control")
            run.ticks(5)
            window = run.frames_since(tick)
            acks = cast_ack_payloads(window, action)
            damage = [(v, a, d) for v, a, d in damage_records(window)
                      if v == enemy.eid and a == hero.eid]
            if acks or damage or hero.energy != energy_before:
                raise StageFailure(
                    "ACCEPTED",
                    f"{label} produced output in negative case (acks={len(acks)}, "
                    f"damage={len(damage)}, energy_changed={hero.energy != energy_before})")
            return len(acks)

        nolock_b = negative_cast(2, "B without lock")
        nolock_c = negative_cast(4, "C without lock")

        lock_tick = run.wait_for_lock(hero, enemy, kit)
        # Stop the basic-attack cycle the production QA way so hits stop
        # refreshing the lock; otherwise the lock never reaches its expiry.
        hero.set_target_eid(None)
        run.world.attacks.cancel(hero.eid)
        run.controller.fixture("cancel-attacks", eid=hero.eid)
        run.hold_position(hero)
        lock_expires_at = kit.lock_expires_at
        guard = 0
        while run.world.sim_time < lock_expires_at + 0.15:
            run.ticks(1)
            guard += 1
            if guard > 120:
                raise StageFailure("SETUP", "lock expiry not reached within 120 ticks")
        if kit._valid_lock(run.world.sim_time):
            raise StageFailure("SETUP", "lock still valid after expiry wait — design error")
        stale_b = negative_cast(2, "B with expired lock")

        _stage(result, "INPUT_NOT_OBSERVED", "PASS",
               f"all negative casts produced no output (B={nolock_b}, C={nolock_c}, "
               f"stale B={stale_b})")
        _stage(result, "INPUT_UNACKNOWLEDGED", "PASS", "expected: nothing to acknowledge")
        _stage(result, "ACCEPTED", "PASS", "expected: no acceptance in negative cases")
        _stage(result, "AUTHORITATIVE_EFFECT", "PASS", "expected: no effects in negative cases")
        _stage(result, "PRESENTATION", "UNVERIFIED",
               "no positive effect in this scenario; nothing to present")
        run.finish()
        _pass(result, {"nolock_b_acks": nolock_b, "nolock_c_acks": nolock_c,
                       "stalelock_b_acks": stale_b},
              {"all_negative_acks_zero": True})
        result["observed_metrics"] = {"nolock_b_acks": nolock_b,
                                      "nolock_c_acks": nolock_c,
                                      "stalelock_b_acks": stale_b}
    except StageFailure as exc:
        _fail(result, exc)
        run.finish()
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = repr(exc)
        try:
            run.finish()
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Scenario: minion-push (full world, no authored hero intents)
# ---------------------------------------------------------------------------

OUTER_TURRETS = {"left_pushes": 3539, "right_pushes": 3545}   # team-2 outer / team-1 outer
MINION_PUSH_WINDOW_TICKS = 1500        # 75 s of production simulation
REGRESSION_WINDOW_TICKS = 1700         # 85 s


def _minion_eids(world) -> set[int]:
    return {m.eid for m in world.wave_director.minions} if world.wave_director else set()


def _survivor_advance(evidence: WorldEvidence, side: int) -> float:
    """Max signed progress of a side's minions from the fixture snapshot to
    their peak toward-enemy position at any point in the run. Survivors may
    die under turret fire after advancing; the peak captures the push."""
    best = 0.0
    for eid, start in evidence.minion_pos_at_fixture.items():
        minion = next((m for m in evidence.world.wave_director.minions if m.eid == eid), None)
        if minion is None or minion.side != side:
            continue
        peak = evidence.minion_peak.get(eid)
        if peak is None:
            continue
        progress = (peak[0] - start[0]) if side == 1 else (start[0] - peak[0])
        best = max(best, progress)
    return best


def _guard_deltas(evidence: WorldEvidence, world) -> list[dict]:
    """Per-minion distance change to its enemy outer turret across the guard window.

    A healthy survivor advances (negative delta); the reverted bad experiment
    (guard removed) would chase a distant wave and produce a large positive
    delta at the 4.5 u/s march speed.
    """
    by_eid: dict[int, list[tuple[int, float, float]]] = {}
    for tick, eid, x, y, _target_none, _engaged in evidence.guard_samples:
        by_eid.setdefault(eid, []).append((tick, x, y))
    outer = {3539: world.structures.structures[3539],
             3545: world.structures.structures[3545]}
    deltas = []
    for eid, samples in sorted(by_eid.items()):
        if len(samples) < 2:
            continue
        minion = next((m for m in world.wave_director.minions if m.eid == eid), None)
        if minion is None:
            continue
        turret = outer[3539] if minion.side == 1 else outer[3545]
        first, last = samples[0], samples[-1]
        d0 = math.dist((first[1], first[2]), (turret.x, turret.y))
        d1 = math.dist((last[1], last[2]), (turret.x, turret.y))
        deltas.append({"eid": eid, "first_tick": first[0], "last_tick": last[0],
                       "distance_before": round(d0, 4), "distance_after": round(d1, 4),
                       "delta": round(d1 - d0, 4)})
    return deltas


def _minion_scenario_common(run: ScenarioRun, result: dict, *, window: int,
                            require_guard: bool) -> dict:
    """Shared full-world lane run with staged assertions; returns metrics dict.

    Natural production dynamics first: wave 1 walks the A001 navmesh and the
    two sides meet at lane center (measured mutual annihilation — the same
    lane-center stalemate the live acceptance leaf documents). After the first
    minion-vs-minion contact, one recorded fixture operation eliminates the
    opposing wave — the accepted test_wave_sandbox pattern transplanted into
    the full production world — so a post-combat survivor cohort resumes
    toward the vulnerable structure through normal navigation and stepped
    turret fire. Nothing else is placed, boosted or injected.
    """
    world = run.world
    hero, enemy, _kit = run.skye_actors()
    if not (hero.is_alive and enemy.is_alive):
        raise StageFailure("SETUP", "heroes must be alive at spawn")
    if len(world.structures.structures) != 12:
        raise StageFailure("SETUP", "expected the full 12-structure set")
    _stage(result, "SETUP", "PASS",
           f"full production world on A001 mesh ({len(run.mesh.triangles)} triangles), "
           "waves/structures/jungle enabled")
    _stage(result, "INPUT_NOT_OBSERVED", "N/A",
           "no authored intents; natural waves plus one recorded fixture elimination")
    run.freeze_initial()
    fixture = {"eliminated": False, "contact_tick": None}
    eliminate_side = 2        # side 2 marches toward 3545; removing it frees side 1

    def monitor() -> None:
        tick = world.sim_tick
        if tick == 600 and world.wave_director.wave_index < 1:
            raise StageFailure("ACCEPTED", "wave 1 had not spawned by tick 600 (30 s)")
        if not fixture["eliminated"] and fixture["contact_tick"] is None:
            minions = _minion_eids(world)
            if any(v in minions and a in minions for _t, v, a, _d in run.evidence.damage):
                fixture["contact_tick"] = tick
        if (not fixture["eliminated"] and fixture["contact_tick"] is not None
                and tick >= fixture["contact_tick"] + 2):
            victims = sorted(m.eid for m in world.wave_director.minions
                             if m.alive and m.side == eliminate_side)
            for m in world.wave_director.minions:
                if m.alive:
                    if m.side == eliminate_side:
                        m.alive = False
                    else:
                        run.evidence.minion_pos_at_fixture[m.eid] = (m.x, m.y)
            run.controller.fixture("eliminate-wave", side=eliminate_side,
                                   eids=victims, after_contact_tick=fixture["contact_tick"],
                                   note="post-contact combat-resolution fixture; survivors "
                                        "resume through production navigation and turrets")
            fixture["eliminated"] = True
        if (require_guard and run.evidence.guard_window is None
                and world.wave_director.wave_index >= 2):
            # Measure the survivor cohort for 7 s after wave 2 exists.
            run.evidence.guard_window = (tick, min(tick + 140, window))

    run.ticks(window, monitor=monitor)
    run.finish()

    evidence = run.evidence
    minion_eids = _minion_eids(world)
    minion_combat = [(t, v, a, d) for t, v, a, d in evidence.damage
                     if v in minion_eids and a in minion_eids]
    if not minion_combat:
        raise StageFailure("AUTHORITATIVE_EFFECT",
                           "no minion-vs-minion combat occurred within the window")
    if not fixture["eliminated"] or fixture["contact_tick"] is None:
        raise StageFailure("SETUP", "contact/elimination fixture never armed")
    turret_fire = [(t, v, a, d) for t, v, a, d in evidence.damage
                   if a in (3539, 3545) and v in minion_eids]
    if not turret_fire:
        raise StageFailure("AUTHORITATIVE_EFFECT",
                           "no turret fire on advancing minions — structure stepping "
                           "did not engage the pushing cohort")
    _stage(result, "ACCEPTED", "PASS",
           f"waves spawned: {world.wave_director.wave_index}, natural contact at tick "
           f"{fixture['contact_tick']}, elimination fixture after it, "
           f"{len(turret_fire)} turret shots on the push")
    _stage(result, "INPUT_UNACKNOWLEDGED", "N/A",
           "no authored intents; natural waves plus one recorded fixture elimination")

    left_advance = _survivor_advance(evidence, 1)    # side 1 marches toward 3539
    right_advance = _survivor_advance(evidence, 2)   # side 2 marches toward 3545
    advance = max(left_advance, right_advance)
    if advance < 5.0:
        raise StageFailure("AUTHORITATIVE_EFFECT",
                           f"no survivor advanced >=5u after combat "
                           f"(left {left_advance:.3f}, right {right_advance:.3f})")

    damaged = {}
    for eid in OUTER_TURRETS.values():
        structure = world.structures.structures[eid]
        if structure.hp < structure.max_hp:
            attributed = [(t, a) for t, v, a, _d in evidence.damage
                          if v == eid and a in minion_eids]
            if attributed:
                damaged[eid] = {"hp": structure.hp, "hits": len(attributed)}
    if not damaged:
        raise StageFailure("AUTHORITATIVE_EFFECT",
                           "no enemy outer turret took minion-attributed damage "
                           f"(3539={world.structures.structures[3539].hp}, "
                           f"3545={world.structures.structures[3545].hp})")
    _stage(result, "AUTHORITATIVE_EFFECT", "PASS",
           f"combat {len(minion_combat)} events, advance {advance:.3f}u, "
           f"turret damage {sorted(damaged)}")
    _stage(result, "PRESENTATION", "UNVERIFIED",
           "wire frames only; rendered-client review is a separate phase")

    observed = {
        "wave_count": world.wave_director.wave_index,
        "first_combat_tick": minion_combat[0][0],
        "combat_event_count": len(minion_combat),
        "left_advance": round(left_advance, 4),
        "right_advance": round(right_advance, 4),
        "turret_shots_on_minions": len(turret_fire),
        "damaged_outer_turrets": {str(k): v for k, v in sorted(damaged.items())},
        "turret_hp_final": {str(eid): round(world.structures.structures[eid].hp, 4)
                            for eid in sorted(OUTER_TURRETS.values())},
    }
    metrics = {
        "combat_event_count": len(minion_combat),
        "survivor_advance": round(advance, 4),
        "turret_shots_on_minions": len(turret_fire),
        "damaged_outer_count": len(damaged),
    }
    if require_guard:
        wave_two_tick = next((t for t, idx in evidence.wave_index_changes if idx >= 2), None)
        if wave_two_tick is None:
            raise StageFailure("AUTHORITATIVE_EFFECT", "wave 2 never spawned within the window")
        deltas = _guard_deltas(evidence, world)
        if not deltas:
            raise StageFailure(
                "AUTHORITATIVE_EFFECT",
                "guard condition never exercised: no engaged survivor without a "
                "current target was sampled after wave 2 spawned")
        worst = max(d["delta"] for d in deltas)
        if worst > 2.0:
            raise StageFailure(
                "AUTHORITATIVE_EFFECT",
                f"a survivor moved {worst:.3f}u AWAY from its enemy outer turret after "
                "wave 2 spawned — check the wave.py targeting guard for regression")
        observed.update({"wave2_spawn_tick": wave_two_tick, "guard_samples": deltas,
                         "guard_max_delta": round(worst, 4)})
        metrics.update({"wave2_spawned": 1, "guard_max_delta": round(worst, 4),
                        "guard_sample_minions": len(deltas)})
    _pass(result, observed, {
        "minion_combat_occurred": True,
        "survivor_advanced_toward_structure": True,
        "turret_stepped_and_fired": True,
        "outer_turret_damaged_by_minion": True,
        **({"distant_wave_did_not_block_survivor": True} if require_guard else {}),
    })
    return metrics


def scenario_minion_push(seed: int, out_dir: Path, navmesh_path: Path) -> dict:
    run = ScenarioRun("minion-push", seed, out_dir, navmesh_path)
    result = run.result
    try:
        metrics = _minion_scenario_common(run, result, window=MINION_PUSH_WINDOW_TICKS,
                                          require_guard=False)
        result["observed_metrics"] = metrics
    except StageFailure as exc:
        _fail(result, exc)
        run.finish()
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = repr(exc)
        run.finish()
    return result


def scenario_minion_wave_regression(seed: int, out_dir: Path, navmesh_path: Path) -> dict:
    run = ScenarioRun("minion-wave-regression", seed, out_dir, navmesh_path)
    result = run.result
    try:
        metrics = _minion_scenario_common(run, result, window=REGRESSION_WINDOW_TICKS,
                                          require_guard=True)
        result["observed_metrics"] = metrics
    except StageFailure as exc:
        _fail(result, exc)
        run.finish()
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = repr(exc)
        run.finish()
    return result


SCENARIO_TABLE: dict[str, Callable[..., dict]] = {
    "skye-a": scenario_skye_a,
    "skye-b": scenario_skye_b,
    "skye-c": scenario_skye_c,
    "skye-lock-neg": scenario_skye_lock_neg,
    "minion-push": scenario_minion_push,
    "minion-wave-regression": scenario_minion_wave_regression,
}


# ---------------------------------------------------------------------------
# External semantic reference fixtures
# ---------------------------------------------------------------------------

REFERENCE_SCHEMA_VERSION = 1


def load_reference(path: Path) -> dict:
    """Load and validate one externally authored reference fixture.

    The fixture must carry explicit provenance and compatibility conditions
    plus per-metric expected values with tolerances. Expected values are never
    generated from the run under test; a fixture without provenance is
    MALFORMED.
    """
    try:
        fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ReferenceFixtureError("MALFORMED", f"unreadable reference: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReferenceFixtureError("MALFORMED", f"reference is not JSON: {exc}") from exc
    if not isinstance(fixture, dict):
        raise ReferenceFixtureError("MALFORMED", "reference must be a JSON object")
    if fixture.get("schema_version") != REFERENCE_SCHEMA_VERSION:
        raise ReferenceFixtureError(
            "MALFORMED", f"schema_version must be {REFERENCE_SCHEMA_VERSION}")
    provenance = fixture.get("provenance")
    if not isinstance(provenance, dict) or not provenance.get("source") \
            or not provenance.get("captured_at"):
        raise ReferenceFixtureError(
            "MALFORMED", "provenance requires non-empty source and captured_at")
    compatibility = fixture.get("compatibility")
    if not isinstance(compatibility, dict):
        raise ReferenceFixtureError("MALFORMED", "compatibility object required")
    metrics = fixture.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ReferenceFixtureError("MALFORMED", "metrics must be a non-empty list")
    for metric in metrics:
        if not isinstance(metric, dict) or not isinstance(metric.get("name"), str):
            raise ReferenceFixtureError("MALFORMED", "each metric requires a name")
        if isinstance(metric.get("expected"), bool) \
                or not isinstance(metric.get("expected"), (int, float)):
            raise ReferenceFixtureError("MALFORMED",
                                        f"metric {metric.get('name')!r} expected must be a number")
        expected = metric["expected"]
        tolerance = metric.get("tolerance", 0.0)
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) \
                or not math.isfinite(tolerance) or tolerance < 0:
            raise ReferenceFixtureError(
                "MALFORMED", f"metric {metric['name']!r} tolerance must be a finite >=0 number")
        if not math.isfinite(expected):
            raise ReferenceFixtureError("MALFORMED",
                                        f"metric {metric['name']!r} expected must be finite")
    return fixture


def check_reference_compatibility(fixture: dict, configuration: dict) -> None:
    compatibility = fixture["compatibility"]
    reasons = []
    if compatibility.get("scenario") != configuration["scenario_id"]:
        reasons.append(f"scenario {compatibility.get('scenario')!r} != "
                       f"{configuration['scenario_id']!r}")
    for key, column in (("hero_id", "hero_id"), ("enemy_hero_id", "enemy_hero_id")):
        if key in compatibility and compatibility[key] != configuration[column]:
            reasons.append(f"{key} {compatibility[key]!r} != {configuration[column]!r}")
    fixture_nav = compatibility.get("navmesh_sha256")
    if fixture_nav and fixture_nav != configuration["navmesh"]["sha256"]:
        reasons.append(f"navmesh {fixture_nav} != {configuration['navmesh']['sha256']}")
    fixture_mode = compatibility.get("mode")
    if fixture_mode and fixture_mode != configuration.get("mode"):
        reasons.append(f"mode {fixture_mode!r} != {configuration.get('mode')!r}")
    if reasons:
        raise ReferenceFixtureError("INCOMPATIBLE", "; ".join(reasons))


def compare_reference(fixture: dict, observed_metrics: dict) -> dict:
    rows = []
    verified = True
    for metric in fixture["metrics"]:
        name = metric["name"]
        if name not in observed_metrics:
            verified = False
            rows.append({"name": name, "expected": metric["expected"], "observed": None,
                         "tolerance": metric.get("tolerance", 0.0), "pass": False,
                         "detail": "metric not present in observed results"})
            continue
        observed = observed_metrics[name]
        if isinstance(observed, bool) or not isinstance(observed, (int, float)):
            verified = False
            rows.append({"name": name, "expected": metric["expected"], "observed": observed,
                         "tolerance": metric.get("tolerance", 0.0), "pass": False,
                         "detail": "observed metric is not numeric"})
            continue
        delta = abs(float(observed) - float(metric["expected"]))
        within = delta <= float(metric.get("tolerance", 0.0))
        verified &= within
        rows.append({"name": name, "expected": metric["expected"], "observed": observed,
                     "tolerance": metric.get("tolerance", 0.0), "delta": round(delta, 6),
                     "pass": bool(within)})
    return {"status": "VERIFIED" if verified else "FAILED",
            "provenance": fixture["provenance"],
            "note": "semantic comparison within stated tolerances; never a raw-packet "
                    "equality claim and never official fidelity",
            "metrics": rows}


# ---------------------------------------------------------------------------
# Worker (one pinned-source process) and orchestrator (two seeded processes)
# ---------------------------------------------------------------------------

def _assert_pinned_runtime(expected_root: Path) -> dict:
    import server.match_server
    import Tools.verify_sandbox as verify_sandbox_module
    resolved = expected_root.resolve()
    runtime = {}
    for label, module in (("server.match_server", server.match_server),
                          ("Tools.verify_sandbox", verify_sandbox_module),
                          ("Tools.run_scenarios", sys.modules[__name__])):
        location = Path(module.__file__).resolve()
        if not location.is_relative_to(resolved):
            raise AssertionError(
                f"pinned runtime violation: {label} resolved to {location}, "
                f"expected inside {resolved}")
        runtime[label] = str(location)
    return runtime


def run_worker(args: argparse.Namespace) -> int:
    """One worker process: pinned source, fixed seed, evidence into args.output."""
    for name in ISOLATED_ENVIRONMENT:
        os.environ.pop(name, None)
    os.environ["HALCYON_NO_TAPE"] = "1"
    names = [name.strip() for name in args.scenario.split(",") if name.strip()]
    unknown = [name for name in names if name not in SCENARIO_TABLE]
    if unknown:
        print(f"unknown scenario(s): {unknown}", file=sys.stderr)
        return 2
    navmesh_path = Path(args.navmesh) if args.navmesh else default_navmesh_path()
    if not navmesh_path.is_file():
        print(f"A001 navmesh not available at {navmesh_path}; refusing to "
              f"simulate without the real external mesh", file=sys.stderr)
        return 2
    try:
        out_dir = resolve_output_dir(args.output)
    except OutputPathError as exc:
        print(f"invalid output directory: {exc}", file=sys.stderr)
        return 2
    if args.expect_manifest and args.expect_manifest != manifest_digest(source_manifest()):
        print("pinned manifest mismatch: worker source is not the expected snapshot",
              file=sys.stderr)
        return 3
    pinned_root = ROOT
    if args.expect_manifest:
        runtime = _assert_pinned_runtime(pinned_root)
    else:
        runtime = {"Tools.run_scenarios": str(Path(__file__).resolve())}
    overall = "PASS"
    for name in names:
        scenario_dir = out_dir / name
        scenario_dir.mkdir(parents=True, exist_ok=True)
        result = SCENARIO_TABLE[name](args.seed, scenario_dir, navmesh_path)
        result["runtime_modules"] = runtime
        if args.expect_manifest:
            result["pinned_manifest_sha256"] = args.expect_manifest
        (scenario_dir / "result.json").write_bytes(json_bytes(result))
        if result["status"] != "PASS":
            overall = result["status"]
        print(f"[worker seed={args.seed}] {name}: {result['status']}"
              f"{'' if result['status'] == 'PASS' else ' — ' + str(result.get('failure_detail') or result.get('error'))}",
              flush=True)
    (out_dir / "worker-summary.json").write_bytes(json_bytes({
        "seed": args.seed, "scenarios": names, "status": overall,
        "navmesh": str(navmesh_path), "output": str(out_dir)}))
    print(f"[worker seed={args.seed}] overall {overall}", flush=True)
    return 0 if overall == "PASS" else 1


def identical_files(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as a, right.open("rb") as b:
        while chunk := a.read(1024 * 1024):
            if chunk != b.read(len(chunk)):
                return False
    return True


def run_headless(names: list[str], out_dir: Path, navmesh_path: Path,
                 reference_path: Path | None) -> dict:
    """Pin source, run two independent seeded processes, compare exact bytes."""
    snapshot, pinned = pin_sources(out_dir)
    pinned_digest = manifest_digest(pinned)
    runs: dict[int, dict[int, dict]] = {seed: {} for seed in SEEDS}
    processes = {}
    for seed in SEEDS:
        run_dir = out_dir / f"run-seed{seed}"
        run_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        # Workers execute a source-only snapshot outside the checkout. Resolve
        # owned inputs here so Local/ is not mistaken for a snapshot-relative path.
        from server import entity_spawn, paths
        env["HALCYON_LOCAL_ROOT"] = str(paths.local_root().resolve())
        env["HALCYON_STACK_DIR"] = str(paths.stack_dir().resolve())
        env["HALCYON_SPAWN_CORPUS"] = os.pathsep.join(
            str(Path(path).resolve()) for path in entity_spawn._source_paths())
        env["HALCYON_SKYE_VOLLEY_CORPUS"] = str(Path(
            os.environ.get("HALCYON_SKYE_VOLLEY_CORPUS") or
            paths.runtime_corpus_dir()).resolve())
        for name in ISOLATED_ENVIRONMENT:
            env.pop(name, None)
        env["HALCYON_NO_TAPE"] = "1"
        env["PYTHONHASHSEED"] = str(seed)
        command = [sys.executable, str(snapshot / "Tools" / "run_scenarios.py"),
                   "--worker", "--seed", str(seed),
                   "--scenario", ",".join(names),
                   "--output", str(run_dir),
                   "--navmesh", str(navmesh_path),
                   "--expect-manifest", pinned_digest]
        print(f"Starting independent process seed={seed}", flush=True)
        completed = subprocess.run(command, env=env, cwd=ROOT, capture_output=True,
                                   text=True)
        (run_dir / "process-stdout.log").write_text(completed.stdout or "", encoding="utf-8")
        (run_dir / "process-stderr.log").write_text(completed.stderr or "", encoding="utf-8")
        processes[seed] = {"returncode": completed.returncode, "command": command}
        for name in names:
            path = run_dir / name / "result.json"
            if path.is_file():
                runs[seed][name] = json.loads(path.read_text(encoding="utf-8"))

    summary: dict[str, Any] = {
        "mode": "headless",
        "output_dir": str(out_dir),
        "source_snapshot": str(snapshot),
        "source_pin_sha256": pinned_digest,
        "workspace_matches_snapshot": source_manifest() == pinned,
        "processes": {str(seed): processes[seed] for seed in SEEDS},
        "scenarios": {},
        "reference": {"status": "UNAVAILABLE",
                      "detail": "no external reference fixture provided"},
        "overall": "PASS",
    }

    for name in names:
        left = runs[SEEDS[0]].get(name)
        right = runs[SEEDS[1]].get(name)
        entry: dict[str, Any] = {"status": "FAIL", "repeatable": False}
        if left is None or right is None:
            entry["detail"] = "a worker process did not produce this scenario result"
            summary["overall"] = "FAIL"
            summary["scenarios"][name] = entry
            continue
        entry["seed_statuses"] = {str(seed): runs[seed][name]["status"] for seed in SEEDS}
        comparisons = {}
        for artifact in COMPARED_ARTIFACTS:
            first = out_dir / f"run-seed{SEEDS[0]}" / name / artifact
            second = out_dir / f"run-seed{SEEDS[1]}" / name / artifact
            if first.is_file() and second.is_file():
                comparisons[artifact] = identical_files(first, second)
            else:
                comparisons[artifact] = False
        entry["byte_identical"] = comparisons
        statuses_pass = all(runs[seed][name]["status"] == "PASS" for seed in SEEDS)
        entry["repeatable"] = statuses_pass and all(comparisons.values())
        entry["status"] = "PASS" if entry["repeatable"] else "FAIL"
        if not statuses_pass:
            entry["detail"] = {
                str(seed): {"first_failed_stage": runs[seed][name].get("first_failed_stage"),
                            "failure_detail": runs[seed][name].get("failure_detail"),
                            "error": runs[seed][name].get("error")}
                for seed in SEEDS if runs[seed][name]["status"] != "PASS"}
        elif not entry["repeatable"]:
            entry["detail"] = "both runs PASS but deterministic artifacts differ"
        if not entry["repeatable"]:
            summary["overall"] = "FAIL"
        if reference_path is not None:
            try:
                fixture = load_reference(reference_path)
                check_reference_compatibility(fixture, runs[SEEDS[0]][name]["configuration"]
                                              | {"scenario_id": name, "mode": "headless"})
                evaluation = compare_reference(fixture, runs[SEEDS[0]][name]["observed_metrics"])
                evaluation["fixture_path"] = str(reference_path)
                entry["reference"] = evaluation
                if evaluation["status"] != "VERIFIED":
                    summary["overall"] = "FAIL"
            except ReferenceFixtureError as exc:
                entry["reference"] = {"status": exc.kind, "detail": str(exc),
                                      "fixture_path": str(reference_path)}
                summary["overall"] = "FAIL"
            except Exception as exc:   # noqa: BLE001 — evidence, never a silent pass
                entry["reference"] = {"status": "ERROR", "detail": repr(exc),
                                      "fixture_path": str(reference_path)}
                summary["overall"] = "FAIL"
        summary["scenarios"][name] = entry

    if processes[SEEDS[0]]["returncode"] or processes[SEEDS[1]]["returncode"]:
        summary["overall"] = "FAIL"
    if not summary["workspace_matches_snapshot"]:
        summary["overall"] = "FAIL"
        summary["detail"] = "worktree source changed while the pilot ran"
    summary_path = out_dir / "summary.json"
    summary_path.write_bytes(json_bytes(summary))
    summary["summary_path"] = str(summary_path)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_scenarios",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=["headless", "client", "compare-pair"],
                        default="headless",
                        help="execution mode (default: headless); "
                             "compare-pair judges two client results")
    parser.add_argument("--scenario", default="all",
                        help="scenario name or comma-separated list, or 'all'")
    parser.add_argument("--output", default=None,
                        help="explicit output directory (must be outside the repo, "
                             "never overwritten; default a unique temp directory)")
    parser.add_argument("--navmesh", default=None,
                        help="external A001 navmesh file (default HALCYON_NAVMESH or "
                             "the production DEFAULT_A001_PATH)")
    parser.add_argument("--reference", default=None,
                        help="[headless] external semantic reference fixture JSON")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=SEEDS[0], help=argparse.SUPPRESS)
    parser.add_argument("--expect-manifest", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--adb-serial", default=None,
                        help="[client] ADB device serial (e.g. emulator-5554)")
    parser.add_argument("--qa-dir", default=None,
                        help="[client] absolute HALCYON_QA_DIR of the running server")
    parser.add_argument("--wire-trace", default=None,
                        help="[client] live wire trace JSONL for c2s/s2c correlation")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="[client] bounded wait in seconds per stage")
    parser.add_argument("--connection", type=int, default=None,
                        help="[client] specific trace connection id to own")
    parser.add_argument("--client-profile", default=None,
                        help="[client] explicit client profile JSON (default built-in 960x540)")
    parser.add_argument("--result-a", default=None,
                        help="[compare-pair] first serialized client result")
    parser.add_argument("--result-b", default=None,
                        help="[compare-pair] second serialized client result")
    args = parser.parse_args(argv)

    if args.mode == "compare-pair":
        if not args.result_a or not args.result_b:
            parser.error("--mode compare-pair requires --result-a and --result-b")
        for label, path in (("A", args.result_a), ("B", args.result_b)):
            if not Path(path).is_file():
                parser.error(f"result {label} not found: {path}")
        from Tools.scenario_client import compare_pair

        def _load_strict(path):
            raw = Path(path).read_text(encoding="utf-8")

            def reject_constant(token):
                raise ValueError(f"non-finite JSON constant {token!r}")

            try:
                parsed = json.loads(raw, parse_constant=reject_constant)
            except (json.JSONDecodeError, ValueError) as exc:
                report = {
                    "error": f"malformed result JSON in {path}: {exc}",
                    "input_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                }
                print(json.dumps(report, indent=1), file=sys.stderr)
                sys.exit(2)
            if not isinstance(parsed, dict):
                report = {
                    "error": f"result {path} is not a JSON object",
                    "input_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                }
                print(json.dumps(report, indent=1), file=sys.stderr)
                sys.exit(2)
            return parsed, hashlib.sha256(raw.encode()).hexdigest()

        a, input_a_hash = _load_strict(args.result_a)
        b, input_b_hash = _load_strict(args.result_b)
        # position tolerance is bound to each run's recorded declared
        # contract, not to a per-invocation CLI override
        verdict = compare_pair(a, b)
        verdict["inputs"] = {
            "result_a": {"path": str(Path(args.result_a).resolve()),
                         "sha256": input_a_hash},
            "result_b": {"path": str(Path(args.result_b).resolve()),
                         "sha256": input_b_hash},
        }
        print(json.dumps(verdict, indent=1, sort_keys=True))
        return 0 if verdict.get("controlled_pair") is True else 1

    if args.worker:
        if args.output is None:
            parser.error("a worker requires --output")
        return run_worker(args)

    if args.mode == "client":
        from Tools.scenario_client import CLIENT_SCENARIOS, run_client
        if args.scenario == "all":
            parser.error("--mode client requires an explicit --scenario")
        if args.scenario not in CLIENT_SCENARIOS:
            parser.error(f"unknown client scenario: {args.scenario}; "
                         f"available: {list(CLIENT_SCENARIOS)}")
        reference_path = Path(args.reference) if args.reference else None
        if reference_path is not None and not reference_path.is_file():
            parser.error(f"reference fixture not found: {reference_path}")
        result = run_client(args.scenario, args)
        if reference_path is not None:
            metrics = {key: value for key, value in (result.get("observed") or {}).items()
                       if isinstance(value, (int, float)) and not isinstance(value, bool)}
            try:
                fixture = load_reference(reference_path)
                check_reference_compatibility(
                    fixture, {"scenario_id": args.scenario, "mode": "client"})
                result["reference"] = compare_reference(fixture, metrics)
                result["reference"]["fixture_path"] = str(reference_path)
                if result["reference"]["status"] != "VERIFIED":
                    result["status"] = "FAIL"
            except ReferenceFixtureError as exc:
                result["reference"] = {"status": exc.kind, "detail": str(exc),
                                       "fixture_path": str(reference_path)}
                result["status"] = "FAIL"
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result.get("status") == "PASS" else 1

    names = (list(SCENARIO_TABLE) if args.scenario == "all"
             else [name.strip() for name in args.scenario.split(",") if name.strip()])
    unknown = [name for name in names if name not in SCENARIO_TABLE]
    if unknown:
        parser.error(f"unknown scenario(s): {unknown}; available: {list(SCENARIO_TABLE)}")
    navmesh_path = Path(args.navmesh) if args.navmesh else default_navmesh_path()
    if not navmesh_path.is_file():
        parser.error(f"A001 navmesh not available at {navmesh_path}; this pilot "
                     "refuses to simulate without the real external mesh")
    try:
        out_dir = resolve_output_dir(args.output)
    except OutputPathError as exc:
        parser.error(str(exc))
    reference_path = Path(args.reference) if args.reference else None
    if reference_path is not None and not reference_path.is_file():
        parser.error(f"reference fixture not found: {reference_path}")

    summary = run_headless(names, out_dir, navmesh_path, reference_path)
    print(f"Output: {out_dir}")
    for name, info in summary["scenarios"].items():
        line = f"  {name}: {info['status']}"
        line += " (byte-identical across seeds)" if info.get("repeatable") \
            else " (NOT repeatable)"
        if "reference" in info:
            line += f"  reference={info['reference']['status']}"
        print(line)
    print(f"Overall: {summary['overall']}")
    print(f"Summary: {summary.get('summary_path')}")
    return 0 if summary["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
