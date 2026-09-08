"""Opt-in local fixture mailbox, executed only by the simulation thread.

No listener or executable commands: six fixed JSON operations prepare a
client scenario. Their effects are diagnostic setup, never acceptance evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import tempfile

from . import combat, economy, roster, wire
from .abilities import NATIVE_STATUS_KINDS
from .status_effects import StatusEffect, StatusType


MAX_REQUEST_BYTES = 4096
MAX_COMMANDS_PER_PUMP = 8
MAX_GOLD = 100000
_NAME = re.compile(r"command-([A-Za-z0-9_-]{1,64})\.json\Z")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_SCHEMAS = {
    "snapshot": ({"command"}, set()),
    "teleport": ({"command", "eid", "x", "y"}, set()),
    "resources": ({"command", "eid"}, {"hp", "energy", "gold"}),
    "damage": ({"command", "source", "target", "amount", "kind"}, set()),
    "status": ({"command", "eid", "type", "duration"}, {"magnitude", "dx", "dy", "speed"}),
    "learn": ({"command", "eid", "slot"}, set()),
}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and within [{low}, {high}]")
    return value


def validate_command(command):
    if not isinstance(command, dict) or not isinstance(command.get("command"), str):
        raise ValueError("request must be an object with a command")
    name = command["command"]
    if name not in _SCHEMAS:
        raise ValueError("unknown QA command")
    required, optional = _SCHEMAS[name]
    if not required <= command.keys() or command.keys() - required - optional:
        raise ValueError("missing or unknown command fields")
    for field in ("eid", "source", "target"):
        if field in command:
            value = command[field]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 0xffffffff:
                raise ValueError(f"{field} must be a positive u32 entity ID")
    if name == "teleport":
        for field in ("x", "y"):
            _number(command[field], field, -1000, 1000)
    elif name == "resources":
        if not optional & command.keys():
            raise ValueError("resources requires hp, energy or gold")
        for field in optional & command.keys():
            _number(command[field], field, 1 if field == "hp" else 0,
                    MAX_GOLD if field == "gold" else 1000000)
    elif name == "damage":
        _number(command["amount"], "amount", 0.001, 100000)
        if command["kind"] not in ("weapon", "crystal", "true"):
            raise ValueError("damage kind must be weapon, crystal or true")
    elif name == "learn":
        if (isinstance(command["slot"], bool) or not isinstance(command["slot"], int)
                or command["slot"] not in (0, 1, 2)):
            raise ValueError("ability slot must be 0, 1 or 2")
    elif name == "status":
        kind = command["type"]
        if kind not in ("STUN", "SILENCE", "KNOCKBACK", "SLOW"):
            raise ValueError("unsupported fixture status")
        _number(command["duration"], "duration", .001, 10)
        allowed = {"magnitude"} if kind == "SLOW" else {"dx", "dy", "speed"} if kind == "KNOCKBACK" else set()
        if (command.keys() & optional) - allowed:
            raise ValueError("fields do not apply to this status type")
        if kind == "SLOW":
            _number(command.get("magnitude", .5), "magnitude", 0, .95)
        if kind == "KNOCKBACK":
            dx = _number(command.get("dx", 1), "dx", -1000, 1000)
            dy = _number(command.get("dy", 0), "dy", -1000, 1000)
            if not math.hypot(dx, dy):
                raise ValueError("knockback direction must be nonzero")
            _number(command.get("speed", 6), "speed", .001, 20)
    return command


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def read_command(path):
    """Read one bounded regular file, refusing links and replacement races."""
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or path.is_symlink()
            or getattr(before, "st_file_attributes", 0) & _REPARSE):
        raise ValueError("QA command must be a regular non-symlink file")
    if before.st_size > MAX_REQUEST_BYTES:
        raise ValueError("QA command exceeds 4096 bytes")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("QA command changed while opening")
        raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("QA command exceeds 4096 bytes")
    command = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON value")))
    return validate_command(command)


def atomic_json(path, value):
    """Publish a complete result/request using a same-directory replace."""
    encoded = (json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".qa-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SandboxQA:
    def __init__(self, directory):
        requested = Path(directory)
        if not requested.is_absolute():
            raise ValueError("HALCYON_QA_DIR must be an absolute external path")
        for parent in (requested, *requested.parents):
            if parent.exists() or parent.is_symlink():
                attributes = parent.lstat()
                if parent.is_symlink() or getattr(attributes, "st_file_attributes", 0) & _REPARSE:
                    raise ValueError("QA directory must not traverse a symlink or junction")
        self.directory = requested.resolve()
        repository = Path(__file__).resolve().parents[1]
        if self.directory == repository or repository in self.directory.parents:
            raise ValueError("HALCYON_QA_DIR must stay outside the repository")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.consumed = self.directory / "consumed"
        self.consumed.mkdir(exist_ok=True)
        if self.consumed.is_symlink() or getattr(self.consumed.lstat(), "st_file_attributes", 0) & _REPARSE:
            raise ValueError("QA consumed directory must not be a link")
        self._last_snapshot_tick = None
        self._snapshot_pending = False
        self._pending_acks = {}
        self._io_failures = set()

    @classmethod
    def from_environment(cls):
        directory = os.environ.get("HALCYON_QA_DIR")
        return cls(directory) if directory and directory.strip() else None

    def _journal(self, value):
        path = self.directory / "journal.jsonl"
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & _REPARSE):
            raise ValueError("QA journal must not be a link")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()

    def _io_error(self, world, operation, error):
        # A persistent read lock must not flood the match log every 50 ms.
        if operation not in self._io_failures:
            world.log(f"[qa] {operation} failed; gameplay continues: {error!r}")
            self._io_failures.add(operation)

    def _publish(self, world, path, value):
        operation = f"publish {path.name}"
        try:
            atomic_json(path, value)
        except OSError as error:
            self._io_error(world, operation, error)
            return False
        self._io_failures.discard(operation)
        return True

    def _acknowledge(self, world, path, result):
        if not self._publish(world, path, result):
            self._pending_acks[path] = result

    def _remove_request(self, world, path):
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except OSError as error:
            # Its durable marker still prevents a second execution next tick.
            self._io_error(world, f"remove {path.name}", error)

    def pump(self, world):
        """Call on the world thread before advancing its next fixed tick."""
        tick, now = world.sim_tick, world.sim_time
        processed = []
        for path, result in list(self._pending_acks.items()):
            if self._publish(world, path, result):
                del self._pending_acks[path]
        # At most eight completed results can await publication. If they stay
        # locked, pause new fixture work while ordinary gameplay keeps ticking.
        capacity = MAX_COMMANDS_PER_PUMP - len(self._pending_acks)
        try:
            paths = sorted(self.directory.glob("command*.json"), key=lambda path: path.name)[:capacity] if capacity else []
        except OSError as error:
            self._io_error(world, "list requests", error)
            paths = []
        for path in paths:
            matched = _NAME.fullmatch(path.name)
            request_id = matched[1] if matched else "invalid-" + hashlib.sha256(path.name.encode()).hexdigest()[:16]
            result_path = self.directory / f"ack-{request_id}.json"
            marker = self.consumed / f"command-{request_id}.json"
            # Exclusive durable reservation provides at-most-once execution,
            # including restarts. An interrupted claimed command is not retried.
            try:
                with marker.open("x", encoding="utf-8") as stream:
                    json.dump({"tick": tick, "time": now, "filename": path.name}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                self._remove_request(world, path)
                if result_path not in self._pending_acks and not result_path.exists():
                    self._acknowledge(world, result_path, {"id": request_id, "ok": False, "tick": tick,
                                      "time": now, "error": "already consumed; earlier result unavailable"})
                continue
            except OSError as error:
                # Do not execute unless the exclusive reservation was flushed.
                # A partially created marker is conservatively treated as used.
                self._io_error(world, f"reserve {request_id}", error)
                continue
            command = None
            result = {"id": request_id, "tick": tick, "time": now, "ok": False}
            try:
                if matched is None:
                    raise ValueError("filename must be command-<1..64 letter/digit/underscore/hyphen>.json")
                command = read_command(path)
                self._journal({"event": "accepted", "id": request_id, "tick": tick, "time": now, "command": command})
                result["result"] = self._execute(world, command, request_id)
                result["ok"] = True
            except (ValueError, KeyError, TypeError, OSError, UnicodeError, RecursionError) as error:
                result["error"] = str(error)
            finally:
                self._remove_request(world, path)
            self._acknowledge(world, result_path, result)
            try:
                self._journal({"event": "completed", **result})
                self._io_failures.discard("append completion journal")
            except (OSError, ValueError) as error:
                # Retrying an append after a partial write can corrupt or
                # duplicate the journal. The marker and ack retain the result;
                # never reapply its effect to repair a failed publication.
                self._io_error(world, "append completion journal", error)
            processed.append(result)
            world.log(f"[qa] tick={tick} id={request_id} command={command and command['command']} ok={result['ok']}")
        if (processed or self._snapshot_pending or self._last_snapshot_tick is None
                or tick - self._last_snapshot_tick >= 10):
            self._snapshot_pending = not self._publish(world, self.directory / "state.json", self.snapshot(world))
            if not self._snapshot_pending:
                self._last_snapshot_tick = tick
        return processed

    def _hero(self, world, eid):
        hero = world.hero_sims.get(eid)
        if hero is None or not hero.is_alive:
            raise ValueError("fixture requires an existing living hero")
        return hero

    def _execute(self, world, command, request_id):
        name, now = command["command"], world.sim_time
        if name == "snapshot":
            return self.snapshot(world)
        if world.phase != world.WORLD or world.structures.match_finished:
            raise ValueError("fixture changes require an active WORLD phase")
        if name == "damage":
            actors = world._entities()
            source, target = actors.get(command["source"]), actors.get(command["target"])
            if source is None or target is None or not combat.alive(source) or not combat.alive(target):
                raise ValueError("damage requires two existing living actors")
            before = target.hp
            frames = world._deal_damage(source, target, command["amount"], command["kind"], now)
            actual = sum(-struct.unpack_from(">f", payload, 8)[0] for opcode, payload in frames
                         if opcode == 1054 and struct.unpack_from(">I", payload)[0] == command["target"])
            world._emit_frames(frames)
            world._drain_effect_frames()
            return {"target": command["target"], "hp_before": before, "hp_after": target.hp,
                    "current_eid": target.eid, "actual_damage": max(0, actual)}
        hero = self._hero(world, command["eid"])
        if name == "teleport":
            if world.navigation is None:
                raise ValueError("teleport requires the authoritative navigation mesh")
            x, y = world.navigation.nearest_point((command["x"], command["y"]))
            hero.set_target_eid(None)
            world.attacks.cancel(hero.eid)
            frames = hero.stop() + hero.teleport(x, y)
            world._emit_frames(frames)
            world._drain_effect_frames()
            return {"eid": hero.eid, "x": hero.x, "y": hero.y}
        if name == "resources":
            econ = world.economy.get_or_create(hero.eid)
            frames = []
            for field, maximum, channel, owner in (("hp", hero.max_hp, 0, hero),
                    ("energy", hero.max_energy, 2, hero), ("gold", MAX_GOLD, 6, econ)):
                if field in command:
                    value = min(command[field], maximum)
                    delta = value - getattr(owner, field)
                    if field == "gold":
                        econ.add_gold(delta)
                    else:
                        setattr(owner, field, value)
                    if delta:
                        frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(hero.eid, delta, channel)))
            world._emit_frames(frames)
            return {"eid": hero.eid, "hp": hero.hp, "energy": hero.energy, "gold": econ.gold}
        if name == "status":
            duration, kind = command["duration"], StatusType[command["type"]]
            dx, dy = command.get("dx", 1), command.get("dy", 0)
            norm = math.hypot(dx, dy)
            effect = StatusEffect(f"qa:{request_id}", kind, hero.eid, hero.eid, duration, now, now + duration,
                                  magnitude=command.get("magnitude", .5), direction=(dx / norm, dy / norm),
                                  speed=command.get("speed", 6) if kind == StatusType.KNOCKBACK else 0,
                                  native_buff_kind=NATIVE_STATUS_KINDS.get(kind))
            applied = world.status_manager.apply_effect(effect)
            return {"eid": hero.eid, "applied": applied, "type": command["type"], "expires_at": now + duration}
        return self._learn(world, hero, command["slot"])

    def _learn(self, world, hero, slot):
        kit = world.hero_kits.get(hero.eid)
        if kit is None or slot not in kit.abilities:
            raise ValueError("hero has no implemented ability in this slot")
        econ = world.economy.get_or_create(hero.eid)
        level = None
        for candidate in range(econ.level, len(economy.XP_LEVEL_THRESHOLDS) + 1):
            # Each actual level grants one native ability point. A rank may
            # already be legal at the current level while all points are spent;
            # silently inventing a fixture point leaves the client unable to
            # consume the following 1082 rank notification.
            if econ.ability_points + candidate - econ.level < 1:
                continue
            # Ask the actual rank validator, without changing the live kit.
            probe = copy.copy(kit)
            probe.ranks, probe.abilities = dict(kit.ranks), dict(kit.abilities)
            if probe.upgrade_ability(slot, candidate):
                level = candidate
                break
        if level is None:
            raise ValueError("no legal rank with an available ability point by level 12")
        xp = max(0, economy.XP_LEVEL_THRESHOLDS[level - 1] - econ.xp)
        if xp:
            world._emit_frames(world.economy.reward_minion_bounty(hero.eid, world.hero_sims, gold=0, xp=xp))
        if not world.economy.upgrade_ability(hero.eid, slot, kit):
            raise ValueError("actual ability upgrade rejected")
        # 1078 is owner-local and carries no EID. Broadcasting it would learn
        # a skill for every connected player's HUD; only 1082 is broadcast.
        with world._clients_lock:
            owners = [conn for conn, (player, _) in world.clients.items() if player.eid == hero.eid]
            no_clients = not world.clients
        for conn in owners:
            world._send_to(conn, 1078, roster.build_ability_cast(slot))
        if no_clients and hero.eid == world.players[0].eid:
            world._send_to(None, 1078, roster.build_ability_cast(slot))
        world._emit_frames(world._learned_ability_frames(hero.eid, slot))
        return {"eid": hero.eid, "slot": slot, "rank": kit.ranks[slot], "level": econ.level,
                "xp_granted": xp, "extra_points_granted": 0}

    @staticmethod
    def snapshot(world):
        """Read the authoritative state without creating economies or timers."""
        now = world.sim_time
        heroes = []
        for eid, hero in sorted(world.hero_sims.items()):
            econ, kit = world.economy.players.get(eid), world.hero_kits.get(eid)
            row = {"eid": eid, "team": hero.team, "hero_id": getattr(hero, "hero_id", None),
                   "x": hero.x, "y": hero.y, "hp": hero.hp, "max_hp": hero.max_hp,
                   "energy": hero.energy, "max_energy": hero.max_energy, "alive": hero.is_alive,
                   "target": hero.target_eid, "recall_completes_at": hero.recall_completes_at,
                   "respawn_at": hero.respawn_at, "ranks": {}, "ability_cooldowns": {},
                   "gold": None, "xp": None, "level": hero.level, "ability_points": None,
                   "inventory": [], "item_cooldowns": {}, "default_items": []}
            if kit is not None:
                row["ranks"] = {str(int(slot)): rank for slot, rank in sorted(kit.ranks.items())}
                row["ability_cooldowns"] = {str(int(slot)): max(0, ready - now) for slot, ready in sorted(kit.cooldowns.items())}
            if econ is not None:
                row.update(gold=econ.gold, xp=econ.xp, level=econ.level, ability_points=econ.ability_points,
                    inventory=[{"slot": slot, "item": item.id, "instance": econ.inventory_instances[slot]}
                               for slot, item in enumerate(econ.inventory) if item is not None],
                    item_cooldowns={key: max(0, ready - now) for key, ready in sorted(econ.item_cooldowns.items())},
                    default_items=[{"instance": instance, "item": item.item_id, "remaining": max(0, item.cooldown_until - now)}
                                   for instance, item in sorted(econ.default_items.items())])
            row["statuses"] = [{"type": effect.effect_type.name, "remaining": effect.expires_at - now}
                               for effect in world.status_manager.effects.get(eid, []) if effect.applied_at <= now < effect.expires_at]
            heroes.append(row)
        def actor_row(actor):
            distance = min((math.hypot(actor.x - hero.x, actor.y - hero.y) for hero in world.hero_sims.values()), default=0)
            return {"eid": actor.eid, "team": combat.team(actor), "x": actor.x, "y": actor.y,
                    "hp": actor.hp, "max_hp": getattr(actor, "max_hp", getattr(getattr(actor, "config", None), "max_hp", None)),
                    "alive": combat.alive(actor), "distance": round(distance, 3),
                    "kind": getattr(getattr(actor, "kind", None), "value", None)}
        creatures = [actor_row(actor) for actor in world._ability_targets()]
        nearby = sorted((row for row in creatures if row["distance"] <= 40), key=lambda row: (row["distance"], row["eid"]))[:64]
        return {"diagnostic_fixture": True, "match_id": world.match_id, "phase": world.phase,
                "tick": world.sim_tick, "time": now, "heroes": heroes, "nearby_creatures": nearby,
                "structures": [actor_row(actor) for _, actor in sorted(world.structures.structures.items())][:32],
                "match_finished": world.structures.match_finished, "winner_team": world.structures.winner_team}
