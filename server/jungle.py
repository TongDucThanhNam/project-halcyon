"""Jungle camps, monsters, objectives, and brush simulation (T3 Milestone 2).

Anchored in Docs/Teardown:
- §8 Jungle & objectives (vainglory-mechanics-matrix.md §8)
- §3 3v3 map structure (vainglory-3v3-map-structure.md §3 & §11)

Features:
1. 8 Mirrored Jungle Camps (4 Left, 4 Right):
   - Camp A (Treant / Heal Camp): 1 monster, 750 HP, respawn 85s, heals killer on death.
   - Camp B (Big Bear + Small Bear): 2 monsters, 600 HP & 480 HP, respawn 71s.
   - Camp C (Treant / Buff Camp): 1 monster, 750 HP, respawn 71s.
   - Camp D (Two Small Bears): 2 monsters, 480 HP each, respawn 71s.
2. Leash Mechanics:
   - Aggro range (4.0u) when approached or attacked.
   - Leash range (8.5u from anchor): when pulled beyond leash, drops aggro,
     returns to anchor, and rapidly regenerates HP.
3. Objectives (Pit at (0.0, 23.6)):
   - Gold Miner: spawns at 240s (4:00), accumulates up to 300g, awards team gold upon capture.
   - Kraken: replaces Gold Miner at 900s (15:00), 271 WP + 70 true dmg, 400 armor, 100 shield.
     When captured, marches toward enemy turrets/vain crystal.
4. Brush & Stealth Zones:
   - Drops minion and turret aggro upon entering brush.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from . import roster, wire
from .hero_movement import HeroMovement
from .jungle_attack_wire import build_basic_attack
from .lifecycle_wire import build_hero_death
from .navigation import SCALE, fixed, within_distance
from .status_effects import StatusEffect, StatusType


@dataclass(frozen=True)
class JungleRules:
    """Unspecified timing/strength coefficients are explicit sandbox policy.

    Objective spawn times, gold cap and Kraken defenses come from the accepted
    task. Buff values and mine fill rate still require 4.13 runtime measurement.
    """
    gold_spawn_at: float = 240.0
    kraken_spawn_at: float = 900.0
    gold_cap: float = 300.0
    gold_per_second: float = 1.0
    buff_duration: float = 90.0
    weapon_slow: float = 0.15
    weapon_slow_seconds: float = 2.0
    weapon_burn_seconds: int = 3
    weapon_burn_per_second: float = 10.0
    crystal_power: float = 30.0
    energy_regen: float = 5.0
    kraken_move_speed: float = 3.0
    kraken_true_damage: float = 70.0
    bear_corpse_seconds: float = 3.8
    treant_corpse_seconds: float = 4.0
    objective_corpse_seconds: float = 3.8  # Gold measured; captured Kraken remains policy.


# --------------------------------------------------------------------------
# Map Anchors & Constants
# --------------------------------------------------------------------------

PIT_POSITION = (0.0, 23.6)
NEUTRAL_SHOP_POSITION = (0.2, 42.0)

# Jungle Camp Anchors (from vainglory-3v3-map-structure.md §11)
CAMP_ANCHORS = {
    # Left Team Camps (Team 1 side)
    "LCampA": (-40.9, 20.3),   # Heal Camp (Treant)
    "LCampB": (-44.4, 31.9),   # Double Camp (Big Bear + Small Bear)
    "LCampC": (-21.95, 24.0),  # Buff Camp (Treant)
    "LCampD": (-13.5, 37.7),   # Double Camp (Two Small Bears)

    # Right Team Camps (Team 2 side, mirrored)
    "RCampA": (40.9, 20.3),
    "RCampB": (44.4, 31.9),
    "RCampC": (21.95, 24.0),
    "RCampD": (13.5, 37.7),
}

# Brush Zones: (x_min, x_max, y_min, y_max)
BRUSH_ZONES = [
    # River / Pit brushes
    (-4.0, 4.0, 13.0, 17.0),
    (-4.0, 4.0, 26.0, 30.0),
    # Left jungle brushes
    (-30.0, -25.0, 21.0, 25.0),
    (-46.0, -42.0, 23.0, 27.0),
    # Right jungle brushes
    (25.0, 30.0, 21.0, 25.0),
    (42.0, 46.0, 23.0, 27.0),
]


# --------------------------------------------------------------------------
# Monster & Objective Definitions
# --------------------------------------------------------------------------

class MonsterType:
    TREANT = "Treant"
    BIG_BEAR = "BigBear"
    SMALL_BEAR = "SmallBear"
    GOLD_MINER = "GoldMiner"
    KRAKEN = "Kraken"


@dataclass
class MonsterConfig:
    monster_type: str
    max_hp: float
    attack_damage: float
    attack_range: float = 1.6
    attack_cooldown: float = 1.2
    armor: float = 20.0
    shield: float = 20.0
    gold_bounty: float = 45.0
    xp_bounty: float = 50.0
    heal_on_kill: float = 0.0


CONFIGS: Dict[str, MonsterConfig] = {
    MonsterType.TREANT: MonsterConfig(
        monster_type=MonsterType.TREANT,
        max_hp=750.0,
        attack_damage=42.0,
        attack_range=2.0,
        attack_cooldown=1.3,
        armor=30.0,
        shield=25.0,
        gold_bounty=65.0,
        xp_bounty=70.0,
        heal_on_kill=220.0,  # Treant heals killer
    ),
    MonsterType.BIG_BEAR: MonsterConfig(
        monster_type=MonsterType.BIG_BEAR,
        max_hp=600.0,
        attack_damage=36.0,
        attack_range=1.5,
        attack_cooldown=1.1,
        armor=25.0,
        shield=20.0,
        gold_bounty=50.0,
        xp_bounty=55.0,
    ),
    MonsterType.SMALL_BEAR: MonsterConfig(
        monster_type=MonsterType.SMALL_BEAR,
        max_hp=480.0,
        attack_damage=26.0,
        attack_range=1.5,
        attack_cooldown=1.0,
        armor=20.0,
        shield=15.0,
        gold_bounty=35.0,
        xp_bounty=40.0,
    ),
    MonsterType.GOLD_MINER: MonsterConfig(
        monster_type=MonsterType.GOLD_MINER,
        max_hp=1800.0,
        attack_damage=114.0,
        attack_range=3.0,
        attack_cooldown=1.5,
        armor=110.0,
        shield=100.0,
        gold_bounty=300.0,  # Team gold
        xp_bounty=250.0,
    ),
    MonsterType.KRAKEN: MonsterConfig(
        monster_type=MonsterType.KRAKEN,
        max_hp=5000.0,
        attack_damage=271.0,
        attack_range=3.5,
        attack_cooldown=1.6,
        armor=400.0,
        shield=100.0,
        gold_bounty=500.0,
        xp_bounty=600.0,
    ),
}


class Monster:
    """Simulates an authoritative neutral jungle monster."""

    def __init__(
        self,
        eid: int,
        camp_id: str,
        config: MonsterConfig,
        anchor_x: float,
        anchor_y: float,
        spawn_offset: Tuple[float, float] = (0.0, 0.0),
    ):
        self.eid = eid
        self.team = 0
        self.camp_id = camp_id
        self.config = config
        self.anchor_x = anchor_x
        self.anchor_y = anchor_y
        self.x = anchor_x + spawn_offset[0]
        self.y = anchor_y + spawn_offset[1]
        self.hp = config.max_hp
        self.max_hp = config.max_hp
        self.is_alive = True
        self.target_eid: Optional[int] = None
        self.next_attack_at: float = 0.0
        self.attack_ordinal: int = 0
        self.leash_radius: float = 8.5
        self.leashing: bool = False
        self.leash_speed: float = 5.0
        self.navigation = None
        self._movement = None
        self._move_destination = None

    @property
    def alive(self):
        return self.is_alive

    @alive.setter
    def alive(self, value):
        self.is_alive = value

    @property
    def side(self):
        return self.team

    @property
    def armor(self):
        return self.config.armor

    @property
    def shield(self):
        return self.config.shield

    def move_toward(self, destination, dt, speed, navigation=None):
        """Reuse the same fixed-point collision routing as heroes."""
        nav = navigation or self.navigation
        if self._movement is None:
            self._movement = HeroMovement(eid=self.eid, x=self.x, y=self.y, speed=speed, navigation=nav)
        mover = self._movement
        mover.navigation, mover.base_speed = nav, speed
        if (mover.x, mover.y) != (self.x, self.y):
            mover.teleport(self.x, self.y)
        changed = self._move_destination is None or sum((destination[k] - self._move_destination[k]) ** 2 for k in (0, 1)) >= 0.25 ** 2
        if changed or not mover.is_moving:
            mover.set_target(*destination)
            self._move_destination = destination
        frames = mover.step(dt)
        self.x, self.y = mover.x, mover.y
        return frames

    def take_damage(self, amount: float, attacker_eid: int) -> bool:
        """Apply damage. Draws aggro towards attacker. Returns True if killed."""
        if not self.is_alive or amount <= 0:
            return False
        self.hp = max(0.0, self.hp - amount)
        if self.is_alive and not self.leashing:
            self.target_eid = attacker_eid
        if self.hp <= 0.0:
            self.is_alive = False
            self.target_eid = None
            return True
        return False

    def attack_presentation(self, target_eid: int, archetype=None):
        if archetype is None:
            archetype = {MonsterType.TREANT: 357, MonsterType.BIG_BEAR: 359,
                         MonsterType.SMALL_BEAR: 360, MonsterType.GOLD_MINER: 362,
                         MonsterType.KRAKEN: 363}[self.config.monster_type]
        frame = build_basic_attack(self.eid, target_eid, archetype, self.attack_ordinal)
        self.attack_ordinal += 1
        return frame

    def step(self, dt: float, now: float, all_heroes: Dict[int, HeroMovement], damage_callback=None, navigation=None) -> List[Tuple[int, bytes]]:
        """Simulate monster movement, attacking, and leashing."""
        frames: List[Tuple[int, bytes]] = []
        if not self.is_alive:
            return frames

        dist_from_anchor = math.hypot(self.x - self.anchor_x, self.y - self.anchor_y)

        # 1. Check leash boundary
        if dist_from_anchor > self.leash_radius:
            self.leashing = True
            self.target_eid = None

        # 2. Return to anchor if leashing
        if self.leashing:
            # Rapidly regenerate HP while resetting
            self.hp = min(self.max_hp, self.hp + (self.max_hp * 0.40 * dt))
            dx = self.anchor_x - self.x
            dy = self.anchor_y - self.y
            dist = math.hypot(dx, dy)
            if dist < 0.2:
                self.x = self.anchor_x
                self.y = self.anchor_y
                self.hp = self.max_hp
                self.leashing = False
            else:
                return self.move_toward((self.anchor_x, self.anchor_y), dt, self.leash_speed, navigation)
            frames.append((wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y)))
            return frames

        # 3. Pursue and attack current target hero
        if self.target_eid is not None:
            target = all_heroes.get(self.target_eid)
            if target is None or not target.is_alive or target.team == self.team:
                self.target_eid = None
                self.leashing = True
                return frames

            if within_distance((self.x, self.y), (target.x, target.y), self.config.attack_range):
                # In attack range: perform basic attack on cadence
                if now >= self.next_attack_at:
                    self.next_attack_at = now + self.config.attack_cooldown
                    frames.append(self.attack_presentation(target.eid))
                    if damage_callback is not None:
                        frames.extend(damage_callback(self, target, self.config.attack_damage, "weapon", now))
                    else:
                        frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(self.eid, target.eid, -self.config.attack_damage)))
                        frames.extend(target.apply_damage(self.config.attack_damage, self.eid, now, damage_type="weapon"))
            else:
                fx, fy = fixed(target.x) - fixed(self.x), fixed(target.y) - fixed(self.y)
                squared = fx * fx + fy * fy
                distance = math.isqrt(squared)
                distance += distance * distance < squared
                # Fixed-point movement truncates each axis. Aim two coordinate
                # quanta inside the range so an oblique approach cannot stall.
                approach = max(0, distance - fixed(self.config.attack_range) + 2)
                move_speed = min(3.8, approach / SCALE / dt) if dt else 0
                frames.extend(self.move_toward((target.x, target.y), dt, move_speed, navigation))

        return frames


# --------------------------------------------------------------------------
# Jungle & Camp Manager
# --------------------------------------------------------------------------

class JungleManager:
    """Manages all 8 jungle camps, respawn timers, leashing, and objectives."""

    def __init__(self, open_time: float = 0.0, *, navigation=None, status_manager=None, rules=None,
                 spawn_catalog=None, seq_1010=None, experimental_capture=False, actor_slots=None,
                 state_catalog=None, capture_actor_index=None):
        self.open_time = open_time  # Match time when camps first spawn
        self.monsters: Dict[int, Monster] = {}
        self.camp_respawns: Dict[str, float] = {}  # camp_id -> respawn_at
        # Separate from lane eids (4610 upward): the old 5000 allocation collided
        # with the 40th lane wave during an ordinary fifteen-minute game.
        self.next_eid = 100000
        self.kraken_captured: bool = False
        self.kraken_team: int = 0
        self.active_kraken: Optional[Monster] = None
        self.gold_miner: Optional[Monster] = None
        self.navigation = navigation
        self.status_manager = status_manager
        self.rules = rules or JungleRules()
        self.spawn_catalog = spawn_catalog
        self.seq_1010 = seq_1010 if seq_1010 is not None else [0]
        self.actor_slots = actor_slots
        self.experimental_capture = experimental_capture
        self.state_catalog = state_catalog
        self.capture_actor_index = capture_actor_index
        self.pending_removals = {}  # eid -> (due, retained actor, killer eid, archetype)
        self.gold_accumulated = 0.0
        self.gold_reset_at = self.rules.gold_spawn_at
        self._gold_spawned = self._kraken_spawned = False
        self.weapon_buffs = {}  # hero eid -> expiry
        self.crystal_buffs = {}  # hero eid -> (expiry, CP added, regen added)
        self._burns = {}  # (source,target) -> (source, target, next_tick, remaining)
        self._init_camps(initial_spawn=(open_time <= 0.0))

    def _init_camps(self, initial_spawn: bool = True):
        """Prepare initial camp definitions."""
        if initial_spawn:
            for camp_id in CAMP_ANCHORS:
                self._spawn_camp(camp_id)

    def _get_respawn_duration(self, camp_id: str) -> float:
        """Native full-clear timers: Treants A/C 60 seconds, bears B/D 50.

        Twenty-six complete camp generations in two VGR matches replace
        the old chunk-index estimates; vgfull's TCP times cross-check them.
        """
        return 60.0 if camp_id.endswith(("CampA", "CampC")) else 50.0

    def _spawn_camp(self, camp_id: str) -> List[Tuple[int, bytes]]:
        """Instantiate camp monsters with fresh eids and return initial spawn frames."""
        frames: List[Tuple[int, bytes]] = []
        first_eid = self.next_eid
        anchor = CAMP_ANCHORS[camp_id]

        if camp_id.endswith("CampA") or camp_id.endswith("CampC"):
            # Single Treant (750 HP)
            eid = self.next_eid
            self.next_eid += 1
            m = Monster(eid, camp_id, CONFIGS[MonsterType.TREANT], anchor[0], anchor[1])
            self.monsters[eid] = m
            frames.append((wire.OP.POSITION, roster.build_position(eid, m.x, m.y)))
        elif camp_id.endswith("CampB"):
            # Big Bear (600 HP) + Small Bear (480 HP)
            eid1 = self.next_eid
            self.next_eid += 1
            m1 = Monster(eid1, camp_id, CONFIGS[MonsterType.BIG_BEAR], anchor[0], anchor[1], spawn_offset=(-0.6, 0.0))
            self.monsters[eid1] = m1
            frames.append((wire.OP.POSITION, roster.build_position(eid1, m1.x, m1.y)))

            eid2 = self.next_eid
            self.next_eid += 1
            m2 = Monster(eid2, camp_id, CONFIGS[MonsterType.SMALL_BEAR], anchor[0], anchor[1], spawn_offset=(0.6, 0.0))
            self.monsters[eid2] = m2
            frames.append((wire.OP.POSITION, roster.build_position(eid2, m2.x, m2.y)))
        elif camp_id.endswith("CampD"):
            # Two Small Bears (480 HP each)
            eid1 = self.next_eid
            self.next_eid += 1
            m1 = Monster(eid1, camp_id, CONFIGS[MonsterType.SMALL_BEAR], anchor[0], anchor[1], spawn_offset=(-0.5, 0.0))
            self.monsters[eid1] = m1
            frames.append((wire.OP.POSITION, roster.build_position(eid1, m1.x, m1.y)))

            eid2 = self.next_eid
            self.next_eid += 1
            m2 = Monster(eid2, camp_id, CONFIGS[MonsterType.SMALL_BEAR], anchor[0], anchor[1], spawn_offset=(0.5, 0.0))
            self.monsters[eid2] = m2
            frames.append((wire.OP.POSITION, roster.build_position(eid2, m2.x, m2.y)))

        for monster in self.monsters.values():
            if monster.camp_id == camp_id and monster.is_alive:
                self._attach_navigation(monster)
        if self.spawn_catalog is not None:
            frames = []
            for eid in range(first_eid, self.next_eid):
                frames.extend(self._unit_spawn_frames(self.monsters[eid]))
        return frames

    def _archetype(self, monster):
        if monster.eid in self.pending_removals:
            return self.pending_removals[monster.eid][3]
        if monster.config.monster_type == MonsterType.KRAKEN:
            return 364 if self.kraken_captured and monster is self.active_kraken else 363
        return {MonsterType.TREANT: 357, MonsterType.BIG_BEAR: 359,
                MonsterType.SMALL_BEAR: 360, MonsterType.GOLD_MINER: 362}[monster.config.monster_type]

    def _unit_spawn_frames(self, monster, *, include_state=False):
        from .actor_slots import ActorSlots
        if self.actor_slots is None:
            self.actor_slots = ActorSlots.from_legacy_tail(self.seq_1010[0])
        self.seq_1010[0] = self.actor_slots.allocate(monster.eid)
        payload = self.spawn_catalog.build(self._archetype(monster), monster.eid,
            monster.x, monster.y, self.seq_1010[0], team=monster.team,
            experimental_capture=self.experimental_capture,
            actor_index=self.capture_actor_index if monster.team else None)
        frames = [(wire.OP.ENTITY_FULL_UPDATE, payload)]
        if include_state:
            frames.append((wire.OP.ENTITY_FULL_UPDATE, self._state_payload(monster)))
        if monster.is_alive:
            frames.append((wire.OP.POSITION, roster.build_position(monster.eid, monster.x, monster.y)))
        return frames

    def get_spawn_frames(self, seq_1010=None, *, catalog=None, experimental_capture=None,
                         actor_slots=None, state_catalog=None):
        """Create living jungle actors and retained corpses for bootstrap/reconnect.

        Calling this binds the external catalog for subsequent respawns. The
        supplied one-int seq list is shared with the session and lane director.
        """
        from .entity_spawn import load_spawn_catalog
        if seq_1010 is not None:
            self.seq_1010 = seq_1010
        if actor_slots is not None:
            self.actor_slots = actor_slots
        if experimental_capture is not None:
            self.experimental_capture = experimental_capture
        if state_catalog is not None:
            self.state_catalog = state_catalog
        self.spawn_catalog = catalog or self.spawn_catalog or load_spawn_catalog()
        frames = []
        for eid in sorted(self.monsters):
            monster = self.monsters[eid]
            if monster.is_alive or eid in self.pending_removals:
                self._attach_navigation(monster)
                frames.extend(self._unit_spawn_frames(monster))
        return frames

    def _state_payload(self, monster):
        from .actor_slots import ActorSlots
        from .entity_spawn import load_native_actor_catalog
        self.state_catalog = self.state_catalog or load_native_actor_catalog()
        if self.actor_slots is None:
            self.actor_slots = ActorSlots.from_legacy_tail(self.seq_1010[0])
        return self.state_catalog.build(self._archetype(monster), monster.eid, monster.x, monster.y,
            self.actor_slots.allocate(monster.eid), team=monster.team, snapshot=True,
            hp=(max(0.0, monster.hp), monster.max_hp), experimental_capture=self.experimental_capture,
            actor_index=self.capture_actor_index if monster.team else None)

    def get_state_1010_frames(self, *, catalog=None, actor_slots=None):
        """Current HP/maxHP, including zero-HP corpses; creation must precede it.

        Native 122-byte replay snapshots are measured. Captured-team fallback
        from neutral362/363 is explicitly gated by experimental_capture.
        """
        if catalog is not None:
            self.state_catalog = catalog
        if actor_slots is not None:
            self.actor_slots = actor_slots
        return [(wire.OP.ENTITY_FULL_UPDATE, self._state_payload(monster))
                for eid, monster in sorted(self.monsters.items())
                if monster.is_alive or eid in self.pending_removals]

    def get_death_frames(self):
        """Restore retained jungle corpses after reconnect creations and HP state."""
        return [(wire.OP.ENTITY_DEATH, build_hero_death(eid, killer))
                for eid, (_, _, killer, _) in sorted(self.pending_removals.items())]

    def on_monster_death(self, monster, killer_eid, now):
        """Native death/retained actor, shared by hero and nonhero damage paths."""
        if monster.eid not in self.monsters or monster.eid in self.pending_removals:
            return []
        archetype = self._archetype(monster)
        kind = monster.config.monster_type
        corpse_seconds = (self.rules.treant_corpse_seconds if kind == MonsterType.TREANT else
                          self.rules.bear_corpse_seconds if kind in (MonsterType.BIG_BEAR, MonsterType.SMALL_BEAR) else
                          self.rules.objective_corpse_seconds)
        monster.hp, monster.is_alive = 0.0, False
        monster.target_eid = None
        monster.leashing = False
        self.pending_removals[monster.eid] = (now + corpse_seconds, monster, killer_eid, archetype)
        if monster.camp_id in CAMP_ANCHORS and not any(
                m.is_alive for m in self.monsters.values() if m.camp_id == monster.camp_id):
            self.camp_respawns[monster.camp_id] = now + self._get_respawn_duration(monster.camp_id)
        return [(wire.OP.ENTITY_DEATH, build_hero_death(monster.eid, killer_eid))]

    def _flush_removals(self, now):
        frames = []
        for eid, (due, _, _, _) in sorted(self.pending_removals.items(), key=lambda row: (row[1][0], row[0])):
            if due > now:
                continue
            frames.extend(((wire.OP.DESTROY, roster.build_destroy(eid)),
                           (wire.OP.DESPAWN, roster.build_despawn(eid))))
            if self.actor_slots is not None:
                self.actor_slots.release(eid)
            self.monsters.pop(eid, None)
            del self.pending_removals[eid]
        return frames

    def _capture_actor_replacement(self, monster, previous_actor, killer_eid, now):
        """Explicit own-client experiment: recreate with measured faction fields.

        A newly owned actor gets a fresh EID/slot and an explicit HP snapshot.
        The defeated actor remains as a corpse until its normal removal.
        Their composition for capture is not present in the external corpus.
        """
        if self.spawn_catalog is None or not self.experimental_capture:
            return []
        old_eid = previous_actor.eid
        self.monsters[old_eid] = previous_actor
        frames = self.on_monster_death(previous_actor, killer_eid, now)
        monster.eid = self.next_eid
        self.next_eid += 1
        monster._movement = None
        self.monsters[monster.eid] = monster
        frames.extend(self._unit_spawn_frames(monster, include_state=True))
        return frames

    def _attach_navigation(self, monster):
        if self.navigation is None or monster.navigation is self.navigation:
            return
        monster.navigation = self.navigation
        # Authored camp markers can lie in a prop footprint. Spawn beside the
        # prop on the nearest walkable surface, never inside the collision hole.
        monster.x, monster.y = self.navigation.nearest_point((monster.x, monster.y))
        monster.anchor_x, monster.anchor_y = self.navigation.nearest_point((monster.anchor_x, monster.anchor_y))

    def _spawn_objective(self, kind):
        eid = self.next_eid
        self.next_eid += 1
        monster = Monster(eid, kind, CONFIGS[kind], *PIT_POSITION)
        self._attach_navigation(monster)
        self.monsters[eid] = monster
        # The snapshot overrides native objective HP growth with the accepted
        # sandbox maxHP, including the requested5000 instead of recorded15500.
        frames = self._unit_spawn_frames(monster, include_state=self.experimental_capture) if self.spawn_catalog is not None else [
            (wire.OP.POSITION, roster.build_position(eid, monster.x, monster.y))]
        return monster, frames

    def _step_objective_schedule(self, now):
        frames = []
        if now >= self.rules.kraken_spawn_at and not self._kraken_spawned:
            self._kraken_spawned = True
            if self.gold_miner is not None:
                # Match6 .70 row940: scheduled mine retirement is a self-hit
                # of-10000, then1072; its corpse is removed~3.8s later.
                eid = self.gold_miner.eid
                frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(eid, eid, -10000,
                    tail=bytes((0, 2, 2)) + bytes(7))))
                frames.extend(self.on_monster_death(self.gold_miner, eid, now))
                self.gold_miner = None
            self.active_kraken, spawned = self._spawn_objective(MonsterType.KRAKEN)
            frames.extend(spawned)
        elif now >= self.rules.gold_spawn_at and not self._gold_spawned and not self._kraken_spawned:
            self._gold_spawned = True
            self.gold_miner, spawned = self._spawn_objective(MonsterType.GOLD_MINER)
            frames.extend(spawned)
        if self.gold_miner is not None:
            self.gold_accumulated = min(self.rules.gold_cap, max(0.0, now - self.gold_reset_at) * self.rules.gold_per_second)
        return frames

    def _grant_buff(self, monster, hero, now):
        if monster.config.monster_type != MonsterType.TREANT:
            return
        expiry = now + self.rules.buff_duration
        # The attachment requests both buffs. Camp assignment and strength are
        # explicit policy until the matching 3v3 buff records are measured.
        if monster.camp_id.endswith('CampA'):
            self.weapon_buffs[hero.eid] = expiry
            hero.weapon_buff_expires_at = expiry
        elif monster.camp_id.endswith('CampC'):
            old = self.crystal_buffs.get(hero.eid)
            old_cp, old_regen = (old[1], old[2]) if old else (0.0, 0.0)
            hero.buff_crystal_power = getattr(hero, 'buff_crystal_power', 0.0) + self.rules.crystal_power - old_cp
            hero.buff_energy_regen = getattr(hero, 'buff_energy_regen', 0.0) + self.rules.energy_regen - old_regen
            hero.crystal_power += self.rules.crystal_power - old_cp
            hero.energy_regen += self.rules.energy_regen - old_regen
            hero.crystal_buff_expires_at = expiry
            self.crystal_buffs[hero.eid] = expiry, self.rules.crystal_power, self.rules.energy_regen

    def on_basic_attack(self, source, target, now, damage_callback=None):
        """Weapon buff applies a refreshing slow and three timed burn ticks."""
        if self.weapon_buffs.get(source.eid, 0) <= now or not getattr(target, 'is_alive', getattr(target, 'alive', False)):
            return []
        if getattr(target, 'team', getattr(target, 'side', 0)) == source.team:
            return []
        if self.status_manager is not None:
            duration = self.rules.weapon_slow_seconds
            self.status_manager.apply_effect(StatusEffect(
                f'weapon_buff:{source.eid}', StatusType.SLOW, source.eid, target.eid,
                duration, now, now + duration, magnitude=self.rules.weapon_slow))
        key = source.eid, target.eid
        next_tick = self._burns[key][2] if key in self._burns else now + 1.0
        self._burns[key] = source, target, next_tick, self.rules.weapon_burn_seconds
        return []

    def _step_buffs(self, now, heroes, damage_callback):
        frames = []
        for eid, expiry in list(self.weapon_buffs.items()):
            hero = heroes.get(eid)
            if expiry <= now or hero is None or not hero.is_alive:
                self.weapon_buffs.pop(eid)
                if hero is not None:
                    hero.weapon_buff_expires_at = 0.0
        for eid, (expiry, cp, regen) in list(self.crystal_buffs.items()):
            hero = heroes.get(eid)
            if expiry <= now or hero is None or not hero.is_alive:
                self.crystal_buffs.pop(eid)
                if hero is not None:
                    hero.buff_crystal_power = max(0.0, getattr(hero, 'buff_crystal_power', 0.0) - cp)
                    hero.buff_energy_regen = max(0.0, getattr(hero, 'buff_energy_regen', 0.0) - regen)
                    hero.crystal_power = max(0.0, hero.crystal_power - cp)
                    hero.energy_regen = max(0.0, hero.energy_regen - regen)
                    hero.crystal_buff_expires_at = 0.0
        for key in sorted(self._burns):
            source, target, next_tick, remaining = self._burns[key]
            while remaining and next_tick <= now and getattr(target, 'is_alive', getattr(target, 'alive', False)):
                if damage_callback is not None:
                    frames.extend(damage_callback(source, target, self.rules.weapon_burn_per_second, 'true', next_tick))
                else:
                    before = target.hp
                    if isinstance(target, HeroMovement):
                        frames.extend(target.apply_damage(self.rules.weapon_burn_per_second, source.eid, next_tick, damage_type='true'))
                    elif target.eid in self.monsters:
                        frames.extend(self.apply_damage_to_monster(target.eid, self.rules.weapon_burn_per_second, source, next_tick))
                    else:
                        target.hp = max(0.0, target.hp - self.rules.weapon_burn_per_second)
                        if target.hp <= 0:
                            target.alive = False
                    frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(source.eid, target.eid, -(before - target.hp))))
                remaining -= 1
                next_tick += 1
            if not remaining or not getattr(target, 'is_alive', getattr(target, 'alive', False)):
                del self._burns[key]
            else:
                self._burns[key] = source, target, next_tick, remaining
        return frames

    def _step_captured_kraken(self, monster, dt, now, structures, damage_callback):
        if structures is None:
            return []
        if monster.siege_stage == 'exit_pit':
            lane = (0.0, 0.0)
            if self.navigation is not None:
                lane = self.navigation.nearest_point(lane)
            if math.hypot(monster.x - lane[0], monster.y - lane[1]) > 0.2:
                return monster.move_toward(lane, dt, self.rules.kraken_move_speed, self.navigation)
            monster.siege_stage = 'siege'
        targets = [s for s in structures.structures.values()
                   if s.is_alive and s.team != monster.team and structures.is_vulnerable(s.eid)]
        if not targets:
            return []
        target = min(targets, key=lambda s: (s.tier, (s.x - monster.x) ** 2 + (s.y - monster.y) ** 2, s.eid))
        monster.target_eid = target.eid
        distance = math.hypot(target.x - monster.x, target.y - monster.y)
        if distance > monster.config.attack_range:
            return monster.move_toward((target.x, target.y), dt, self.rules.kraken_move_speed, self.navigation)
        if now < monster.next_attack_at:
            return []
        monster.next_attack_at = now + monster.config.attack_cooldown
        frames = [monster.attack_presentation(target.eid, archetype=364)]
        if damage_callback is not None:
            frames.extend(damage_callback(monster, target, monster.config.attack_damage, 'weapon', now))
            frames.extend(damage_callback(monster, target, self.rules.kraken_true_damage, 'true', now))
        else:
            frames.extend(structures.apply_damage(target.eid, monster.config.attack_damage + self.rules.kraken_true_damage, monster.eid))
        return frames

    def step(
        self,
        dt: float,
        now: float,
        all_heroes: Dict[int, HeroMovement],
        economy_mgr: Optional[Any] = None,
        damage_callback=None,
        structures=None,
        navigation=None,
        status_manager=None,
    ) -> List[Tuple[int, bytes]]:
        """Simulate all active camp monsters, handle leashing, and check respawns."""
        frames: List[Tuple[int, bytes]] = self._flush_removals(now)
        if navigation is not None:
            self.navigation = navigation
        if status_manager is not None:
            self.status_manager = status_manager
        frames.extend(self._step_objective_schedule(now))
        frames.extend(self._step_buffs(now, all_heroes, damage_callback))

        # 1. Check camp opening time
        if self.open_time > 0.0 and now >= self.open_time:
            self.open_time = 0.0
            for camp_id in CAMP_ANCHORS:
                frames.extend(self._spawn_camp(camp_id))

        # 2. Check camp respawns
        for camp_id, respawn_at in list(self.camp_respawns.items()):
            if now >= respawn_at:
                del self.camp_respawns[camp_id]
                frames.extend(self._spawn_camp(camp_id))

        # 3. Aggro detection: idle monsters acquire nearby attacking/visible heroes
        for m in self.monsters.values():
            self._attach_navigation(m)
            if not m.is_alive or m.leashing or m.target_eid is not None:
                continue
            if m is self.active_kraken and self.kraken_captured:
                continue
            for hero in all_heroes.values():
                if not hero.is_alive or hero.team == m.team:
                    continue
                # Aggro radius = 4.0u
                if math.hypot(hero.x - m.x, hero.y - m.y) <= 4.0:
                    # If hero is not hidden in brush outside monster's immediate vision
                    m.target_eid = hero.eid
                    break

        # 4. Step all alive monsters
        for m in list(self.monsters.values()):
            if m.is_alive:
                if m is self.active_kraken and self.kraken_captured:
                    frames.extend(self._step_captured_kraken(m, dt, now, structures, damage_callback))
                else:
                    frames.extend(m.step(dt, now, all_heroes, damage_callback, self.navigation))

        return frames

    def apply_damage_to_monster(
        self,
        monster_eid: int,
        damage: float,
        attacker_hero: HeroMovement,
        now: float,
        economy_mgr: Optional[Any] = None,
        all_heroes: Optional[Dict[int, HeroMovement]] = None,
    ) -> List[Tuple[int, bytes]]:
        """Apply hero damage, native death/corpse retention, and one kill reward."""
        frames: List[Tuple[int, bytes]] = []
        monster = self.monsters.get(monster_eid)
        if monster is None or not monster.is_alive or (monster.team and monster.team == attacker_hero.team):
            return frames

        killed = monster.take_damage(damage, attacker_hero.eid)
        if killed:
            kind = monster.config.monster_type
            if kind == MonsterType.GOLD_MINER or (kind == MonsterType.KRAKEN and not self.kraken_captured):
                previous_actor = copy.copy(monster)
                monster.is_alive = True
                monster.hp = monster.max_hp
                monster.team = attacker_hero.team
                monster.target_eid = None
                monster.leashing = False
                monster.next_attack_at = now + monster.config.attack_cooldown
                monster.attack_ordinal = 0
                if kind == MonsterType.GOLD_MINER:
                    award = min(self.rules.gold_cap, max(0.0, now - self.gold_reset_at) * self.rules.gold_per_second)
                    self.gold_reset_at, self.gold_accumulated = now, 0.0
                    if economy_mgr is not None and all_heroes is not None:
                        for eid in sorted(all_heroes):
                            if all_heroes[eid].team == attacker_hero.team:
                                frames.extend(economy_mgr.reward_minion_bounty(eid, all_heroes,
                                    gold=award, xp=monster.config.xp_bounty))
                else:
                    self.kraken_captured, self.kraken_team = True, attacker_hero.team
                    monster.siege_stage = 'exit_pit'
                frames.extend(self._capture_actor_replacement(monster, previous_actor, attacker_hero.eid, now))
                return frames

            frames.extend(self.on_monster_death(monster, attacker_hero.eid, now))

            # Treant heal camp bonus
            if monster.config.heal_on_kill > 0:
                frames.extend(attacker_hero.heal(monster.config.heal_on_kill, now, self.status_manager))
            self._grant_buff(monster, attacker_hero, now)

            # Reward gold and XP bounty via economy manager
            if economy_mgr is not None and all_heroes is not None:
                bounty_frames = economy_mgr.reward_minion_bounty(
                    attacker_hero.eid,
                    all_heroes,
                    gold=monster.config.gold_bounty,
                    xp=monster.config.xp_bounty,
                )
                frames.extend(bounty_frames)

        return frames

    @staticmethod
    def is_in_brush(x: float, y: float) -> bool:
        """Check if coordinates fall within any brush zone on the map."""
        for x_min, x_max, y_min, y_max in BRUSH_ZONES:
            if x_min <= x <= x_max and y_min <= y <= y_max:
                return True
        return False
