"""Exercise the production sandbox for sixteen minutes in independent processes.

Uses the operator's external A001 navmesh, normal waves, structures and jungle
rules, and six authored player controllers. No sockets, replayed captures,
stat boosts, accelerated timers, or disabled structures are used. Artifacts
are written outside the repository by default.

Run: python Tools/verify_sandbox.py
Optional short diagnostic: --seconds 60 (reported as incomplete coverage).
"""
from __future__ import annotations

import argparse
from collections import Counter
import cProfile
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import pstats
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MINIMUM_SECONDS = 16 * 60
TICK_SECONDS = 0.05
ASPIRATIONAL_MS = 2.0
DEADLINE_MS = TICK_SECONDS * 1000
ISOLATED_ENVIRONMENT = (
    "HALCYON_QA_DIR", "HALCYON_BOTS", "HALCYON_NO_WAVE", "HALCYON_HERO_1010",
    "HALCYON_SPARSE_1070", "HALCYON_HERO_KEEPALIVE", "HALCYON_HERO_SPAWN_X",
    "HALCYON_HERO_SPAWN_Y", "HALCYON_TEAM_ALLOCATION", "HALCYON_EXPERIMENTAL_CAPTURE",
    "HALCYON_SUPPRESS_PERIODIC_1070_SEC", "HALCYON_SUPPRESS_PERIODIC_1070_MOVE",
)


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, str]:
    paths = sorted((ROOT / "server").glob("*.py")) + [Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): digest_file(path) for path in paths}


def pin_sources(directory: Path) -> tuple[Path, dict[str, str]]:
    """Copy only authored Python source, retrying if a concurrent edit races it."""
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
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="source-snapshot-", dir=directory))
    for name, data in contents.items():
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return snapshot, before


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def freeze_state(world, controller, mesh_digest: str) -> bytes:
    """Canonical complete gameplay-object graph, including pending effects.

    Navigation geometry is an immutable external dependency identified by its
    digest. Thread locks, sockets, queues, wall-clock menu deadlines and log
    callbacks belong to transport/scheduling, outside advance_simulation.
    Callable rule hooks are identified by their qualified names.
    """
    from server.navigation import NavMesh

    seen: dict[int, int] = {}

    def freeze(value):
        if value is None or isinstance(value, (bool, str, int)):
            return value
        if isinstance(value, float):
            if math.isnan(value):
                raise AssertionError("NaN gameplay state value")
            # Permanent buffs and not-yet-stepped managers deliberately use
            # infinity sentinels. Preserve them as strings; live resources are
            # still required to be finite by invariant_checks every tick.
            return {"float64": value.hex()}
        if isinstance(value, Enum):
            return {"enum": f"{type(value).__module__}.{type(value).__qualname__}.{value.name}"}
        if isinstance(value, bytes):
            return {"bytes": value.hex()}
        if isinstance(value, NavMesh):
            return {"external_navmesh": mesh_digest}
        if isinstance(value, Path):
            return {"path": str(value)}
        if callable(value):
            return {"callable": f"{value.__module__}.{value.__qualname__}"}
        if isinstance(value, dict):
            return {"map": [[freeze(key), freeze(value[key])]
                            for key in sorted(value, key=lambda item: (type(item).__name__, repr(item)))]}
        if isinstance(value, (list, tuple)):
            return {type(value).__name__: [freeze(item) for item in value]}
        if isinstance(value, (set, frozenset)):
            return {"set": sorted((freeze(item) for item in value), key=json_bytes)}
        identity = id(value)
        if identity in seen:
            return {"ref": seen[identity]}
        reference = len(seen)
        seen[identity] = reference
        attrs = dict(getattr(value, "__dict__", {}))
        for cls in type(value).__mro__:
            slots = getattr(cls, "__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for name in slots:
                if name not in ("__dict__", "__weakref__") and hasattr(value, name):
                    attrs[name] = getattr(value, name)
        if not attrs:
            raise TypeError(f"unhandled gameplay state type: {type(value)}")
        return {"object": f"{type(value).__module__}.{type(value).__qualname__}",
                "id": reference, "fields": {key: freeze(attrs[key]) for key in sorted(attrs)}}

    try:
        return json_bytes(freeze({
            "counters": {key: getattr(world, key) for key in (
                "sim_tick", "sim_time", "seq_1010", "world_tick", "hero_x", "hero_y",
                "hero_facing", "move_target", "_last_position_at", "_match_result_at_tick",
                "result_sent", "sparse_budget", "move_count", "suppress_active", "suppress_until",
                "suppressed_1070_count", "_next_buff_instance", "_jungle_published",
                "phase", "frames_sent")},
            "configuration": {key: getattr(world, key) for key in (
                "emit_trickle", "emit_waves", "enable_bots", "emit_hero_1010", "sparse_1070",
                "suppress_periodic_1070_sec", "suppress_periodic_1070_move")},
            "roster": world.players, "actor_slots": world.actor_slots,
            "world_entities": world.world_entities,
            "reconnect": {"last_death_frames": world._last_death_frames,
                          "resource_catchup": world._resource_catchup},
            "heroes": world.hero_sims, "kits": world.hero_kits,
            "statuses": world.status_manager, "damage_modifiers": world.damage_queue,
            "recall": world.recall_presentation, "shop": world.shop_presentation,
            "skye_volleys": world.skye_volleys,
            "vision": world.vision,
            "economy": world.economy, "items": world.items, "attacks": world.attacks,
            "waves": world.wave_director, "jungle": world.jungle, "structures": world.structures,
            "bots": world.bot_controllers, "script": controller.state,
        }))
    finally:
        # Recursive local functions otherwise retain themselves and their seen
        # tables until cyclic GC, even after a checkpoint has been serialized.
        # Traversal is synchronous, so the recursive cell is no longer needed.
        del freeze


class ScriptedPlayers:
    """Authored normal player inputs; all game outcomes use production rules."""

    def __init__(self, world):
        self.world = world
        self.state = {"next_order": {eid: 0 for eid in world.hero_sims},
                      "purchases": 0, "skills_learned": 0, "casts": 0,
                      "item_activations": 0, "recalls": 0, "intents": Counter(),
                      "recall_trip_started_at": None, "recall_trip_completed": False}
        self.intent_cost_ns = 0
        self.intent_cpu_ns = 0
        self.profile = None

    def intent(self, eid, opcode, payload):
        started = time.perf_counter_ns()
        cpu_started = time.thread_time_ns()
        if self.profile is not None:
            self.profile.enable()
        self.world._apply_event(opcode, payload, bot_eid=eid)
        if self.profile is not None:
            self.profile.disable()
        self.intent_cost_ns += time.perf_counter_ns() - started
        self.intent_cpu_ns += time.thread_time_ns() - cpu_started
        self.state["intents"][opcode] += 1

    def step(self, tick):
        from server import abilities, ability_wire, economy, item_input, roster, wire

        self.intent_cost_ns = 0
        self.intent_cpu_ns = 0
        now = self.world.sim_time
        for index, (eid, hero) in enumerate(sorted(self.world.hero_sims.items())):
            if tick < self.state["next_order"][eid]:
                continue
            # Stagger player decisions across the 20 Hz simulation.
            self.state["next_order"][eid] = tick + 20
            if not hero.is_alive or hero.recall_completes_at is not None:
                continue
            econ = self.world.economy.get_or_create(eid)
            kit = self.world.hero_kits[eid]
            for slot in (2, 0, 1):
                if econ.ability_points:
                    before = econ.ability_points
                    self.intent(eid, wire.OP.LEVELUP_B, bytes((slot,)) + bytes(5))
                    self.state["skills_learned"] += before - econ.ability_points
            if economy.can_shop(hero):
                names = {item.name.lower().replace(" ", "_") for item in econ.inventory if item}
                order = ("sprint_boots", "weapon_blade", "crystal_bit", "aftershock",
                         "travel_boots", "heavy_steel", "eclipse_prism")
                for key in order:
                    item = economy.ITEMS_BY_KEY.get(key)
                    if item is not None and item.id is not None and key not in names:
                        before = econ.gold
                        self.intent(eid, wire.OP.SHOP_BUY, roster.build_shop_buy(eid, item.id))
                        self.state["purchases"] += econ.gold < before
                        if econ.gold < before:
                            break
                if hero.hp < hero.max_hp * .95 or hero.energy < hero.max_energy * .90:
                    continue
            elif hero.hp < hero.max_hp * .28:
                action = ability_wire.hero_action_variant(kit.name, "recall")
                if action is None:
                    raise AssertionError(f"fixture has no native Recall action for {kit.name}")
                self.intent(eid, wire.OP.TARGETLESS_CAST, struct.pack(">IBB", 0xFFFFFFFF, action, 0))
                self.state["recalls"] += hero.recall_completes_at is not None
                continue

            # Exercise a deliberate return to shop even when the current combat
            # rules never lower anyone below the emergency-Recall threshold.
            # Walk to the friendly lane outside the base through native inputs;
            # use the normal four-second channel without changing world state.
            if index == 0 and now >= 120 and not self.state["recall_trip_completed"]:
                if self.state["recall_trip_started_at"] is None:
                    self.state["recall_trip_started_at"] = now
                if (hero.last_recall_completed_at is not None
                        and hero.last_recall_completed_at >= self.state["recall_trip_started_at"]):
                    self.state["recall_trip_completed"] = True
                else:
                    destination = (-72.0 if hero.team == 1 else 72.0, 2.0)
                    if math.dist((hero.x, hero.y), destination) > .75:
                        if hero.move_target != destination:
                            self.intent(eid, wire.OP.MOVE_CAST, roster.build_move(*destination))
                    else:
                        action = ability_wire.hero_action_variant(kit.name, "recall")
                        if action is None:
                            raise AssertionError(f"fixture has no native Recall action for {kit.name}")
                        self.intent(eid, wire.OP.TARGETLESS_CAST,
                                    struct.pack(">IBB", 0xFFFFFFFF, action, 0))
                        self.state["recalls"] += hero.recall_completes_at is not None
                    continue

            for slot, item in enumerate(econ.inventory):
                if item and item.active and tick % 1200 < 20:
                    before = dict(econ.item_cooldowns)
                    self.intent(eid, wire.OP.ITEM_USE,
                                item_input.build_item_use(econ.inventory_instances[slot]))
                    # Native 1096 echoes even a cooldown-time click. Count an
                    # activation only when authoritative cooldown state changes.
                    self.state["item_activations"] += econ.item_cooldowns != before

            # Contest the gold miner after 4:10 and the Kraken after 15:10;
            # normal jungle circuits occupy the intervening time.
            objective = (self.world.jungle.active_kraken if 910 <= now < 950
                         else self.world.jungle.gold_miner if 250 <= now < 295 else None)
            side = -1 if hero.team == 1 else 1
            camps = [monster for monster in self.world.jungle.monsters.values()
                     if monster.is_alive and monster.team == 0
                     and monster.camp_id.startswith("L" if side < 0 else "R")]
            if objective is not None and objective.is_alive and objective.team == 0:
                target = objective
            elif camps:
                target = min(camps, key=lambda monster: (
                    (monster.x - hero.x) ** 2 + (monster.y - hero.y) ** 2, monster.eid))
            else:
                target = None
            if target is None:
                destination = (side * (22 + (index % 3) * 7), 26 + (index % 2) * 5)
                if hero.move_target is None and math.dist((hero.x, hero.y), destination) > 1:
                    self.intent(eid, wire.OP.MOVE_CAST, roster.build_move(*destination))
                continue
            if hero.target_eid != target.eid:
                self.intent(eid, wire.OP.TARGET_ENTITY, roster.build_target_entity(target.eid))
            if math.dist((hero.x, hero.y), (target.x, target.y)) > 7:
                continue
            # These selected kits cover targeted, ground, dash and channel casts.
            for slot in (0, 1, 2):
                ability = kit.abilities.get(abilities.AbilitySlot(slot))
                if ability is None:
                    continue
                action = ability_wire.hero_action_variant(kit.name, "ABC"[slot])
                if action is None:
                    raise AssertionError(f"fixture has no native {kit.name} action for slot {slot}")
                before = hero.energy
                ground_types = (abilities.AbilityType.POINT_AOE, abilities.AbilityType.CONE,
                                abilities.AbilityType.SKILLSHOT, abilities.AbilityType.DIRECTION_DASH)
                if (ability.ability_type in ground_types
                        or ability.name == "Super Punch" and kit._charge is not None):
                    opcode = wire.OP.GROUND_CAST
                    payload = struct.pack(">fffBB", target.x, 0.0, target.y, action, 0)
                else:
                    opcode = wire.OP.TARGETLESS_CAST
                    targeted = ability.ability_type in (abilities.AbilityType.TARGET_ENEMY,
                                                        abilities.AbilityType.VECTOR_DASH)
                    payload = struct.pack(">IBB", target.eid if targeted else 0xFFFFFFFF, action, 0)
                self.intent(eid, opcode, payload)
                self.state["casts"] += hero.energy < before


def percentiles(samples: list[int]) -> dict[str, float]:
    ordered = sorted(samples)
    def point(fraction):
        position = (len(ordered) - 1) * fraction
        low = math.floor(position)
        high = math.ceil(position)
        return (ordered[low] + (ordered[high] - ordered[low]) * (position - low)) / 1_000_000
    return {"p50_ms": point(.50), "p95_ms": point(.95), "p99_ms": point(.99),
            "max_ms": ordered[-1] / 1_000_000,
            "mean_ms": sum(ordered) / len(ordered) / 1_000_000,
            "over_2ms": sum(ns > ASPIRATIONAL_MS * 1_000_000 for ns in ordered),
            "over_50ms": sum(ns > DEADLINE_MS * 1_000_000 for ns in ordered)}


def invariant_checks(world):
    """Runtime invariants, separate from measured production tick work."""
    ids = list(world.hero_sims) + list(world.structures.structures) + list(world.jungle.monsters)
    minions = world.wave_director.minions if world.wave_director else []
    ids.extend(minion.eid for minion in minions)
    if len(ids) != len(set(ids)):
        raise AssertionError("entity ids collide across gameplay systems")
    for hero in world.hero_sims.values():
        if not all(math.isfinite(value) for value in (hero.x, hero.y, hero.hp, hero.energy)):
            raise AssertionError(f"non-finite hero state for {hero.eid}")
        if not -1e-7 <= hero.hp <= hero.max_hp + 1e-7:
            raise AssertionError(f"hero {hero.eid} HP is outside its valid range")
        if not -1e-7 <= hero.energy <= hero.max_energy + 1e-7:
            raise AssertionError(f"hero {hero.eid} energy is outside its valid range")
    for player in world.economy.players.values():
        if player.gold < 0 or not math.isfinite(player.gold) or player.ability_points < 0:
            raise AssertionError(f"invalid economy state for {player.eid}")
    for minion in minions:
        if not math.isfinite(minion.hp) or minion.hp < 0:
            raise AssertionError(f"invalid minion HP for {minion.eid}")


def run_worker(args) -> dict:
    # Also isolate a directly invoked --worker before importing gameplay code.
    for name in ISOLATED_ENVIRONMENT:
        os.environ.pop(name, None)
    os.environ["HALCYON_NO_TAPE"] = "1"
    from server import match_server, navigation, roster

    manifest = source_manifest()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = Path(args.navmesh or os.environ.get("HALCYON_NAVMESH", navigation.DEFAULT_A001_PATH))
    mesh_digest = digest_file(path)
    started = time.perf_counter()
    mesh = navigation.load_halcyon_navmesh(path)
    mesh_load_ms = (time.perf_counter() - started) * 1000
    players = roster.default_solo_bots("authored-sandbox-player", "authored-sandbox-match")
    for index, player in enumerate(players):
        player.hero_id = (244, 243, 285, 925, 395, 242)[index]
        player.selection_hash = 0
        player.is_bot = False
        player.pick_flags = roster.PICK_FLAG_LOCKED
    pending = []
    world = match_server.SnapshotStream(None, players, "authored-sandbox-match",
        lambda opcode, payload: pending.append((opcode, payload)), log=lambda _: None,
        navigation_mesh=mesh)
    world._finalize()
    world._dump_world()
    world._enter_world()
    if world.qa is not None or world.tape_frames:
        raise AssertionError("verifier must not consume live QA commands or replay a world tape")
    # _run_world publishes initial jungle actors before its first fixed tick.
    # This harness calls advance_simulation directly, so reproduce that setup
    # using the same production publisher and shared actor-slot allocator.
    sequence = [world.seq_1010]
    world._emit_frames(world.jungle.get_spawn_frames(
        seq_1010=sequence, actor_slots=world.actor_slots))
    world.seq_1010 = sequence[0]
    world._jungle_published = True
    controller = ScriptedPlayers(world)
    for index, eid in enumerate(sorted(world.hero_sims)):
        controller.state["next_order"][eid] = index
    ticks = math.ceil(args.seconds / TICK_SECONDS)
    costs, sim_costs, cpu_costs, slowest = [], [], [], []
    counts = Counter()
    coverage = {"hero_deaths": 0, "hero_respawns": 0, "camp_deaths": 0,
                "camp_respawns": 0, "gold_miner_spawned": False, "kraken_spawned": False,
                "peak_live_minions": 0, "peak_entities": 0, "invariant_ticks": 0,
                "match_finished_at": None, "recalls_completed": 0, "level_increases": 0}
    previous_heroes = {eid: hero.is_alive for eid, hero in world.hero_sims.items()}
    previous_levels = {eid: world.economy.get_or_create(eid).level for eid in world.hero_sims}
    previous_monsters = {eid: monster.is_alive for eid, monster in world.jungle.monsters.items()}
    seen_minions = set()
    stream_path, state_path = directory / "stream.bin", directory / "final-state.json"
    checkpoint_path = directory / "state-checkpoints.jsonl"
    checkpoints = hashlib.sha256()
    profile = cProfile.Profile() if args.profile_from is not None else None
    started = time.perf_counter()
    last_progress = started
    with stream_path.open("wb") as stream, checkpoint_path.open("wb") as state_log:
        for tick in range(ticks):
            if profile is not None:
                active = args.profile_from <= world.sim_time < args.profile_from + args.profile_seconds
                controller.profile = profile if active else None
            controller.step(tick)
            before = time.perf_counter_ns()
            cpu_before = time.thread_time_ns()
            if controller.profile is not None:
                profile.enable()
            world.advance_simulation()
            if controller.profile is not None:
                profile.disable()
            sim_cost = time.perf_counter_ns() - before
            cost = sim_cost + controller.intent_cost_ns
            cpu_cost = time.thread_time_ns() - cpu_before + controller.intent_cpu_ns
            costs.append(cost)
            sim_costs.append(sim_cost)
            cpu_costs.append(cpu_cost)
            minions = world.wave_director.minions
            seen_minions.update(minion.eid for minion in minions)
            live_minions = sum(minion.alive for minion in minions)
            slowest.append((cost, tick, live_minions, len(world.jungle.monsters), len(pending), cpu_cost))
            slowest.sort(reverse=True)
            del slowest[20:]
            for opcode, payload in pending:
                stream.write(struct.pack(">IHI", tick, opcode, len(payload)))
                stream.write(payload)
                counts[opcode] += 1
            pending.clear()
            invariant_checks(world)
            coverage["invariant_ticks"] += 1
            coverage["peak_live_minions"] = max(coverage["peak_live_minions"], live_minions)
            coverage["peak_entities"] = max(coverage["peak_entities"],
                len(world.hero_sims) + len(minions) + len(world.jungle.monsters) + len(world.structures.structures))
            coverage["gold_miner_spawned"] |= world.jungle._gold_spawned
            coverage["kraken_spawned"] |= world.jungle._kraken_spawned
            if world.structures.match_finished and coverage["match_finished_at"] is None:
                coverage["match_finished_at"] = world.sim_time
            for eid, hero in world.hero_sims.items():
                coverage["hero_deaths"] += previous_heroes[eid] and not hero.is_alive
                coverage["hero_respawns"] += not previous_heroes[eid] and hero.is_alive
                coverage["recalls_completed"] += hero.last_recall_completed_at == world.sim_time
                previous_heroes[eid] = hero.is_alive
                level = world.economy.players[eid].level
                coverage["level_increases"] += level - previous_levels[eid]
                previous_levels[eid] = level
            for eid, monster in world.jungle.monsters.items():
                coverage["camp_respawns"] += eid not in previous_monsters and monster.camp_id[:1] in ("L", "R")
                coverage["camp_deaths"] += previous_monsters.get(eid, False) and not monster.is_alive
                previous_monsters[eid] = monster.is_alive
            if world.sim_tick % 20 == 0 or tick == ticks - 1:
                snapshot = freeze_state(world, controller, mesh_digest)
                record = json_bytes({"tick": world.sim_tick, "sha256": hashlib.sha256(snapshot).hexdigest()}) + b"\n"
                checkpoints.update(record)
                state_log.write(record)
            now = time.perf_counter()
            if now - last_progress >= 20 or world.sim_tick % 1200 == 0:
                print(f"progress sim={world.sim_time:.1f}s/{ticks * TICK_SECONDS:.1f}s "
                      f"live_minions={live_minions} tick_ms={cost / 1_000_000:.3f}", flush=True)
                last_progress = now
    if profile is not None:
        profile.disable()
        profile.dump_stats(directory / "tick-profile.pstats")
        with (directory / "tick-profile.txt").open("w", encoding="utf-8") as out:
            pstats.Stats(profile, stream=out).strip_dirs().sort_stats("cumulative").print_stats(40)
    state_path.write_bytes(freeze_state(world, controller, mesh_digest))
    source_unchanged = source_manifest() == manifest
    coverage.update({key: value for key, value in controller.state.items() if key != "next_order"})
    coverage["waves_spawned"] = world.wave_director.wave_index
    coverage["minions_spawned"] = len(seen_minions)
    coverage["damage_messages"] = counts[1054]
    coverage["visibility_messages"] = counts[1067]
    coverage["shop_permission_messages"] = counts[1087]
    expected_waves = max(0, math.floor((world.sim_time - roster.WAVE_FIRST_SPAWN_AT)
                                      / roster.WAVE_INTERVAL) + 1)
    coverage["expected_waves"] = expected_waves
    full_coverage = (args.seconds >= MINIMUM_SECONDS and coverage["kraken_spawned"]
                     and coverage["gold_miner_spawned"] and coverage["waves_spawned"] == expected_waves
                     and coverage["camp_deaths"] > 0 and coverage["camp_respawns"] > 0
                     and coverage["purchases"] > 0 and coverage["casts"] > 0
                     and coverage["item_activations"] > 0 and coverage["damage_messages"] > 0
                     and coverage["recalls_completed"] > 0 and coverage["level_increases"] > 0
                     and coverage["skills_learned"] > 0 and coverage["visibility_messages"] > 0
                     and coverage["shop_permission_messages"] > 0
                     and coverage["match_finished_at"] is None)
    result = {"seconds": world.sim_time, "ticks": world.sim_tick,
              "wall_seconds": time.perf_counter() - started, "mesh_load_ms": mesh_load_ms,
              "navmesh": {"path": str(path), "sha256": mesh_digest,
                          "vertices": len(mesh.vertices), "triangles": len(mesh.triangles)},
              "python": sys.version, "platform": platform.platform(),
              "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
              "profiled": profile is not None, "source_manifest": manifest,
              "source_pin_sha256": hashlib.sha256(json_bytes(manifest)).hexdigest(),
              "isolated_environment": list(ISOLATED_ENVIRONMENT),
              "qa_disabled": world.qa is None, "world_tape_disabled": not world.tape_frames,
              "source_unchanged_during_run": source_unchanged,
              "tick_cost": percentiles(costs), "simulation_only_cost": percentiles(sim_costs),
              "thread_cpu_cost": percentiles(cpu_costs),
              "slowest_ticks": [{"tick": tick, "seconds": (tick + 1) * TICK_SECONDS,
                    "cost_ms": cost / 1_000_000, "live_minions": nminions,
                    "monsters": nmonsters, "messages": messages, "thread_cpu_ms": cpu_cost / 1_000_000}
                    for cost, tick, nminions, nmonsters, messages, cpu_cost in slowest],
              "stream_sha256": digest_file(stream_path), "stream_bytes": stream_path.stat().st_size,
              "state_sha256": digest_file(state_path), "checkpoint_sha256": checkpoints.hexdigest(),
              "opcode_counts": dict(counts), "coverage": coverage,
              "full_duration_coverage": full_coverage,
              "deadline_met_every_tick": max(costs) <= DEADLINE_MS * 1_000_000,
              "artifacts": {"stream": str(stream_path), "state": str(state_path),
                            "checkpoints": str(checkpoint_path)}}
    (directory / "result.json").write_bytes(json_bytes(result))
    return result


def identical_files(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as a, right.open("rb") as b:
        while chunk := a.read(1024 * 1024):
            if chunk != b.read(len(chunk)):
                return False
    return True


def orchestrate(args) -> int:
    output = (args.output or Path(tempfile.mkdtemp(prefix="halcyon-sandbox-verify-"))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot, pinned_manifest = pin_sources(output)
    results = []
    for index, seed in enumerate((11, 7919), 1):
        directory = output / f"run-{index}"
        env = dict(os.environ)
        for name in ISOLATED_ENVIRONMENT:
            env.pop(name, None)
        env["HALCYON_NO_TAPE"] = "1"
        env["PYTHONHASHSEED"] = str(seed)
        command = [sys.executable, str(snapshot / "Tools" / "verify_sandbox.py"), "--worker",
                   "--seconds", str(args.seconds), "--output", str(directory)]
        if args.navmesh:
            command.extend(("--navmesh", args.navmesh))
        if args.profile_from is not None:
            command.extend(("--profile-from", str(args.profile_from),
                            "--profile-seconds", str(args.profile_seconds)))
        print(f"Starting independent process {index}, PYTHONHASHSEED={seed}", flush=True)
        completed = subprocess.run(command, env=env, cwd=ROOT)
        if completed.returncode:
            print(f"Worker {index} failed; artifacts: {directory}", flush=True)
            return completed.returncode
        results.append(json.loads((directory / "result.json").read_text()))
    equal = {name: identical_files(Path(results[0]["artifacts"][name]), Path(results[1]["artifacts"][name]))
             for name in ("stream", "state", "checkpoints")}
    same_source = (results[0]["source_manifest"] == results[1]["source_manifest"]
                   and all(result["source_unchanged_during_run"] for result in results))
    summary = {"identical": equal, "same_source": same_source,
               "source_snapshot": str(snapshot),
               "source_pin_sha256": hashlib.sha256(json_bytes(pinned_manifest)).hexdigest(),
               "workspace_matches_snapshot": source_manifest() == pinned_manifest,
               "full_duration_coverage": all(result["full_duration_coverage"] for result in results),
               "deadline_met_every_tick": all(result["deadline_met_every_tick"] for result in results),
               "runs": results, "output_directory": str(output)}
    (output / "summary.json").write_bytes(json_bytes(summary))
    print(json.dumps({key: value for key, value in summary.items() if key != "runs"}, indent=2))
    for index, result in enumerate(results, 1):
        print(f"Run {index} tick costs: {json.dumps(result['tick_cost'])}")
        print(f"Run {index} coverage: {json.dumps(result['coverage'])}")
    return 0 if (all(equal.values()) and same_source and summary["full_duration_coverage"]
                 and summary["deadline_met_every_tick"] and summary["workspace_matches_snapshot"]) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=MINIMUM_SECONDS)
    parser.add_argument("--navmesh")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile-from", type=float, help="Start optional cProfile at this simulation second")
    parser.add_argument("--profile-seconds", type=float, default=10)
    args = parser.parse_args()
    if args.seconds <= 0 or not math.isfinite(args.seconds):
        parser.error("seconds must be finite and positive")
    if args.worker:
        if args.output is None:
            parser.error("a worker requires --output")
        result = run_worker(args)
        print(f"Completed {result['seconds']:.1f}s: {result['tick_cost']}", flush=True)
        return 0
    return orchestrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
