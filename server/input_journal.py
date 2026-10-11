"""Opt-in application-order evidence, never an alternate simulation engine.

An operation owns the production state lock. Nested production calls remain
nested; only the outer call is replayed. WORLD batches record the wall scheduler's
decisions (tape cursor and tick count), not replacement gameplay results.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import time
import uuid

CADENCE = 200
METHODS = frozenset(("add_client", "remove_client", "_apply_event", "_begin_lock",
                     "_finalize", "_dump_world", "_dump_world_to", "_enter_world",
                     "advance_simulation", "_broadcast_snapshot"))
TRANSITIONS = frozenset(("_begin_lock", "_finalize", "_dump_world_to", "_enter_world"))
# Every exclusion is named, including Python Thread bookkeeping. No wildcard
# exclusion may accidentally conceal a newly added gameplay field.
STATE_EXCLUSIONS = {
    **dict.fromkeys(("_target", "_name", "_args", "_kwargs", "_daemonic", "_ident",
                     "_native_id", "_tstate_lock", "_started", "_is_stopped",
                     "_initialized", "_stderr", "_invoke_excepthook", "_handle",
                     "_context", "_os_thread_handle"),
                    "Python Thread identity/lifecycle; not simulation state"),
    **dict.fromkeys(("conn", "_send", "log", "_clients_lock", "_state_lock",
                     "_stop_event", "events"),
                    "Transport/locks/queued-not-applied inputs; journal records application order"),
    **dict.fromkeys(("lock_requested_at", "lock_deadline", "dump_fallback_at",
                     "world_entered_at", "world_had_clients", "zero_clients_since",
                     "_last_snapshot_at", "_pick_deadline", "wave_t0"),
                    "Wall scheduler; resulting transitions/publication batches are journaled"),
    "frames_sent": "Transport count includes wall-paced menu snapshots and 1116 pings",
    "trace_movement_ticks": "Diagnostic timing switch; no rule input",
    "_movement_phase_ms": "Measured wall work; no rule input",
    "journal": "Evidence writer and monotonic measurement bookkeeping",
}
EVENT_EXCLUSIONS = {
    1113: "Menu roster countdown snapshots contain wall time; roster state is compared",
    1116: "Wall-paced slot liveness ping; connected identities/ready sets are compared",
}
FIELD_EXCLUSIONS = {
    "clients[*].send_callback": "Transport callback replaced by ordered (connection, player) pairs",
    "native_navigation.scratch_and_counters": "Query scratch pointers/diagnostics; geometry and implementation are pinned",
    "initial_socket_opener": "Pre-session 1001/1108/catalog/menu burst; no gameplay application or state transition",
    "apply_monotonic_ns": "Live measurement; replay preserves order and fixed ticks, not OS latency",
}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def file_digest(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def dependencies():
    """Pin all files eligible for the production corpus loaders, not just tape."""
    from server import entity_spawn, match_server, navigation, paths
    from Tools.verification_support import owned_input_environment
    env = owned_input_environment()
    nav = Path(os.environ.get("HALCYON_NAVMESH") or navigation.DEFAULT_CLASSIC_NAVMESH).resolve()
    files = {nav, Path(match_server.WORLD_TAPE_PATH).resolve(),
             (paths.stack_dir() / "suppress_1070.json").resolve()}
    roots = [Path(p) for p in entity_spawn._source_paths()]
    roots.append(Path(env["HALCYON_SKYE_VOLLEY_CORPUS"]))
    inventory = {}
    for root in roots:
        candidates = [root.resolve()] if root.is_file() else sorted(p.resolve() for p in root.glob("*.vgr"))
        files.update(candidates)
        inventory[str(root.resolve())] = sorted(str(path) for path in candidates)
    if env.get("HALCYON_NATIVE_STEERING_LIBRARY"):
        files.add(Path(env["HALCYON_NATIVE_STEERING_LIBRARY"]))
    env["HALCYON_NAVMESH"] = str(nav)
    return env, {str(path): file_digest(path) for path in sorted(files)}, inventory


def validate_dependencies(header):
    for path, digest in header["inputs"].items():
        if file_digest(path) != digest:
            raise ValueError(f"journal dependency changed: {path}")
    for name, expected in header["input_inventory"].items():
        root = Path(name)
        actual = [str(root.resolve())] if root.is_file() else sorted(str(p.resolve()) for p in root.glob("*.vgr"))
        if actual != expected:
            raise ValueError(f"journal corpus inventory changed: {name}")


def open_journal(world, directory):
    directory = Path(directory).absolute()
    from server.paths import project_root
    from Tools.verification_support import reject_link_traversal
    reject_link_traversal(directory)
    evidence = (project_root() / "Local" / "evidence").resolve()
    if evidence not in directory.resolve().parents or not directory.is_dir():
        raise ValueError("journal requires an existing explicit directory under Local/evidence")
    return InputJournal(world, path=directory / f"inputs-{uuid.uuid4().hex}.jsonl")


class InputJournal:
    def __init__(self, world, *, path=None, header=None):
        if world.qa is not None:
            raise ValueError("application journal does not accept external QA commands")
        self.world = world
        self.path = Path(path) if path else None
        self.output = None
        self.connections = {}
        self.connection_objects = {}  # Prevent Python id reuse after detach.
        self.generations = {}
        self.eids = {}
        self.active = None
        self.sequence = 0
        self.last = None
        self.expected = None
        self.closed = False
        self.failure = None
        self.checkpoint_count = 0
        self.world_start_count = 0
        if header is None:
            from Tools.run_scenarios import source_manifest, manifest_digest, ISOLATED_ENVIRONMENT
            from Tools.verification_support import RUNTIME_SWITCHES
            env, inputs, inventory = dependencies()
            names = set(ISOLATED_ENVIRONMENT) | set(RUNTIME_SWITCHES) | {"HALCYON_NO_TAPE"}
            names.discard("HALCYON_INPUT_JOURNAL_DIR")
            self.header = {"kind": "header", "version": 1, "cadence": CADENCE,
                           "match_id": world.match_id,
                           "players": [{k: getattr(p, k) for k in p.__slots__} for p in world.players],
                           "initial_connection": world.conn is not None,
                           "environment": {name: os.environ.get(name) for name in sorted(names)},
                           "input_environment": env, "inputs": inputs, "input_inventory": inventory,
                           "source_manifest": source_manifest(),
                           "state_exclusions": STATE_EXCLUSIONS,
                           "event_exclusions": EVENT_EXCLUSIONS,
                           "field_exclusions": FIELD_EXCLUSIONS}
            self.header["source_sha256"] = manifest_digest(self.header["source_manifest"])
        else:
            self.header = header
        if self.path:
            self.output = self.path.open("xb", buffering=1024 * 1024)
        world.journal = self
        for conn, (player, sender) in list(world.clients.items()):
            self.attach(conn, player.uuid, player.eid)
            wrapped = self.sender(conn, sender)
            world.clients[conn] = (player, wrapped)
            if conn is world.conn:
                world._send = wrapped
        if header is None:
            self.header["initial_attachment"] = ({"seq": 0, "sim_tick": world.sim_tick,
                "phase": world.phase, **self.identity(world.conn)} if world.conn is not None else None)
        self.write(self.header)

    def write(self, row):
        if self.output is not None:
            try:
                self.output.write(encoded(row) + b"\n")
            except Exception as exc:
                self.failure = repr(exc)
                raise RuntimeError(f"input journal write failed: {self.path}: {exc}") from exc

    def attach(self, conn, identity, eid):
        generation = self.generations.get(identity, 0) + 1
        self.generations[identity] = generation
        self.connections[id(conn)] = (identity, generation)
        self.connection_objects[id(conn)] = conn
        self.eids[id(conn)] = eid

    def identity(self, conn):
        if conn is None:
            return {"uuid": None, "generation": None, "eid": None}
        identity, generation = self.connections[id(conn)]
        return {"uuid": identity, "generation": generation, "eid": self.eids[id(conn)]}

    def sender(self, conn, send):
        def publish(opcode, payload):
            if self.active is None:
                return send(opcode, payload)
            if conn in self.world.clients:
                self.eids[id(conn)] = self.world.clients[conn][0].eid
            attempt = {**self.identity(conn), "tick": self.world.sim_tick,
                       "opcode": int(opcode), "send_error": False}
            index = len(self.active["sends"])
            self.active["sends"].append(attempt)
            row = None
            if opcode not in EVENT_EXCLUSIONS:
                row = {**attempt, "payload_hex": payload.hex()}
                self.active["events"].append(row)
            try:
                # Reproduce observed transport failure at its exact send ordinal.
                # Payload/recipient are still independently regenerated and checked.
                if self.expected and index < len(self.expected["sends"]) and self.expected["sends"][index]["send_error"]:
                    raise OSError("recorded send failure")
                return send(opcode, payload)
            except OSError:
                attempt["send_error"] = True
                if row is not None:
                    row["send_error"] = True
                raise
        return publish

    def state(self):
        from Tools.verify_sandbox import freeze_state
        mesh = self.header["inputs"][self.header["input_environment"]["HALCYON_NAVMESH"]]
        return freeze_state(self.world, None, mesh, replay=True)

    def checkpoint(self, label):
        state = self.state()
        self.active["checkpoints"].append({"tick": self.world.sim_tick, "label": label,
                                            "sha256": hashlib.sha256(state).hexdigest(),
                                            "state": json.loads(state)})
        self.checkpoint_count += 1
        if label == "world-start":
            self.world_start_count += 1

    @contextmanager
    def operation(self, method, arguments=None):
        if self.closed:
            raise RuntimeError("operation after input journal close")
        if self.active is not None:
            yield
            return
        world = self.world
        self.sequence += 1
        self.active = {"kind": "operation", "seq": self.sequence, "method": method,
                       "sim_tick": world.sim_tick, "phase": world.phase,
                       "apply_monotonic_ns": time.monotonic_ns(),
                       "arguments": arguments or {}, "events": [], "sends": [], "transitions": [],
                       "checkpoints": []}
        try:
            yield
            self.active["end_tick"] = world.sim_tick
            self.active["end_phase"] = world.phase
            self.active["schedule"] = {"tape_i": world.tape_i, "tape_done": world.tape_done,
                                        "world_tick": world.world_tick,
                                        "jungle_published": world._jungle_published,
                                        "wall_ping": self.active.pop("wall_ping", False)}
            if method not in ("world_batch", "advance_simulation", "_broadcast_snapshot"):
                self.checkpoint("operation-end")
            self.last = self.active
            self.write(self.active)
            if self.output is not None and self.active["checkpoints"]:
                self.output.flush()
        except Exception as exc:
            self.failure = repr(exc)
            raise
        finally:
            self.active = None

    def call(self, method, args, kwargs):
        name = method.__name__
        if name not in METHODS:
            return method(self.world, *args, **kwargs)
        bound = inspect.signature(method).bind(self.world, *args, **kwargs)
        bound.apply_defaults()
        params = bound.arguments
        conn = params.get("conn")
        arguments = {}
        if name == "add_client":
            identity = params["session_uuid"]
            # The production slot allocator resolves the EID during attachment.
            self.attach(conn, identity, None)
            params["send"] = self.sender(conn, params["send"])
            arguments = {"session_uuid": identity, **self.identity(conn)}
        elif name in ("remove_client", "_apply_event", "_dump_world_to"):
            arguments = self.identity(conn)
        if name == "_apply_event":
            arguments.update(opcode=int(params["opcode"]), payload_hex=params["payload"].hex(),
                             bot_eid=params["bot_eid"],
                             receive_monotonic_ns=params["received_monotonic_ns"])
        elif name == "_begin_lock":
            arguments["send_commit_ack"] = params["send_commit_ack"]
        elif name == "_broadcast_snapshot":
            arguments["countdown"] = list(params["countdown"])
        with self.operation(name, arguments):
            before_phase = self.world.phase
            result = method(*bound.args, **bound.kwargs)
            if name == "add_client":
                self.eids[id(conn)] = result.eid
                self.active["arguments"]["eid"] = result.eid
            if name in TRANSITIONS or (name == "_apply_event" and params["opcode"] in (1134, 1137)):
                transition = {"method": name, "phase": self.world.phase,
                              "previous_phase": before_phase, "tick": self.world.sim_tick}
                if name == "_apply_event":
                    transition["ready"] = conn in self.world.ready_clients
                self.active["transitions"].append(transition)
            if name == "_enter_world" and before_phase != self.world.WORLD:
                self.checkpoint("world-start")
            elif name == "advance_simulation" and self.world.sim_tick % CADENCE == 0:
                self.checkpoint("periodic")
            return result

    def close(self):
        if self.closed:
            return
        try:
            if self.failure:
                raise RuntimeError(f"incomplete input journal: {self.failure}")
            from Tools.run_scenarios import source_manifest
            if source_manifest() != self.header["source_manifest"]:
                raise RuntimeError("journal source changed during recording")
            validate_dependencies(self.header)
            with self.operation("close"):
                pass
            self.write({"kind": "footer", "records": self.sequence,
                        "checkpoints": self.checkpoint_count, "world_starts": self.world_start_count})
            if self.output:
                self.output.flush()
        finally:
            self.closed = True
            if self.output:
                self.output.close()

