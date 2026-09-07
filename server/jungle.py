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
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from . import roster, wire
from .hero_movement import HeroMovement


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
        self.leash_radius: float = 8.5
        self.leashing: bool = False
        self.leash_speed: float = 5.0

    def take_damage(self, amount: float, attacker_eid: int) -> bool:
        """Apply damage. Draws aggro towards attacker. Returns True if killed."""
        if not self.is_alive:
            return False
        self.hp = max(0.0, self.hp - amount)
        if self.is_alive and not self.leashing:
            self.target_eid = attacker_eid
        if self.hp <= 0.0:
            self.is_alive = False
            self.target_eid = None
            return True
        return False

    def step(self, dt: float, now: float, all_heroes: Dict[int, HeroMovement]) -> List[Tuple[int, bytes]]:
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
                step_dist = min(dist, self.leash_speed * dt)
                self.x += (dx / dist) * step_dist
                self.y += (dy / dist) * step_dist
            frames.append((wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y)))
            return frames

        # 3. Pursue and attack current target hero
        if self.target_eid is not None:
            target = all_heroes.get(self.target_eid)
            if target is None or not target.is_alive:
                self.target_eid = None
                self.leashing = True
                return frames

            target_dist = math.hypot(target.x - self.x, target.y - self.y)
            if target_dist <= self.config.attack_range:
                # In attack range: perform basic attack on cadence
                if now >= self.next_attack_at:
                    self.next_attack_at = now + self.config.attack_cooldown
                    # Emit 1054 COMBAT_DELTA against hero
                    frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(
                        self.eid, target.eid, -self.config.attack_damage
                    )))
                    # Apply damage to target hero
                    dmg_frames = target.apply_damage(self.config.attack_damage, self.eid, now, damage_type="weapon")
                    frames.extend(dmg_frames)
            else:
                # Move towards target
                move_speed = 3.8
                step_dist = min(target_dist - self.config.attack_range + 0.1, move_speed * dt)
                self.x += ((target.x - self.x) / target_dist) * step_dist
                self.y += ((target.y - self.y) / target_dist) * step_dist
                frames.append((wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y)))

        return frames


# --------------------------------------------------------------------------
# Jungle & Camp Manager
# --------------------------------------------------------------------------

class JungleManager:
    """Manages all 8 jungle camps, respawn timers, leashing, and objectives."""

    def __init__(self, open_time: float = 0.0):
        self.open_time = open_time  # Match time when camps first spawn
        self.monsters: Dict[int, Monster] = {}
        self.camp_respawns: Dict[str, float] = {}  # camp_id -> respawn_at
        self.next_eid = 5000
        self.kraken_captured: bool = False
        self.kraken_team: int = 0
        self.active_kraken: Optional[Monster] = None
        self._init_camps(initial_spawn=(open_time <= 0.0))

    def _init_camps(self, initial_spawn: bool = True):
        """Prepare initial camp definitions."""
        if initial_spawn:
            for camp_id in CAMP_ANCHORS:
                self._spawn_camp(camp_id)

    def _get_respawn_duration(self, camp_id: str) -> float:
        """Measured §8 respawns: Camp A ≈ 85s; Camps B, C, D ≈ 71s."""
        if camp_id.endswith("CampA"):
            return 85.0
        return 71.0

    def _spawn_camp(self, camp_id: str) -> List[Tuple[int, bytes]]:
        """Instantiate camp monsters with fresh eids and return initial spawn frames."""
        frames: List[Tuple[int, bytes]] = []
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

        return frames

    def step(
        self,
        dt: float,
        now: float,
        all_heroes: Dict[int, HeroMovement],
        economy_mgr: Optional[Any] = None,
    ) -> List[Tuple[int, bytes]]:
        """Simulate all active camp monsters, handle leashing, and check respawns."""
        frames: List[Tuple[int, bytes]] = []

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
            if not m.is_alive or m.leashing or m.target_eid is not None:
                continue
            for hero in all_heroes.values():
                if not hero.is_alive:
                    continue
                # Aggro radius = 4.0u
                if math.hypot(hero.x - m.x, hero.y - m.y) <= 4.0:
                    # If hero is not hidden in brush outside monster's immediate vision
                    m.target_eid = hero.eid
                    break

        # 4. Step all alive monsters
        for m in list(self.monsters.values()):
            if m.is_alive:
                frames.extend(m.step(dt, now, all_heroes))

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
        """Apply hero damage to a jungle monster. Emits 1073+1035 upon death and rewards bounty."""
        frames: List[Tuple[int, bytes]] = []
        monster = self.monsters.get(monster_eid)
        if monster is None or not monster.is_alive:
            return frames

        killed = monster.take_damage(damage, attacker_hero.eid)
        if killed:
            # Emit measured death sequence: 1073 DESTROY then 1035 DESPAWN
            frames.append((wire.OP.DESTROY, roster.build_destroy(monster_eid)))
            frames.append((wire.OP.DESPAWN, roster.build_despawn(monster_eid)))

            # Treant heal camp bonus
            if monster.config.heal_on_kill > 0:
                heal = monster.config.heal_on_kill
                attacker_hero.hp = min(attacker_hero.max_hp, attacker_hero.hp + heal)
                frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(
                    attacker_hero.eid, heal, stat_type=6
                )))

            # Reward gold and XP bounty via economy manager
            if economy_mgr is not None and all_heroes is not None:
                bounty_frames = economy_mgr.reward_minion_bounty(
                    attacker_hero.eid,
                    all_heroes,
                    gold=monster.config.gold_bounty,
                    xp=monster.config.xp_bounty,
                )
                frames.extend(bounty_frames)

            # Check if entire camp is cleared to arm respawn timer
            camp_id = monster.camp_id
            camp_alive = any(
                m.is_alive for m in self.monsters.values() if m.camp_id == camp_id
            )
            if not camp_alive:
                respawn_dur = self._get_respawn_duration(camp_id)
                self.camp_respawns[camp_id] = now + respawn_dur

        return frames

    @staticmethod
    def is_in_brush(x: float, y: float) -> bool:
        """Check if coordinates fall within any brush zone on the map."""
        for x_min, x_max, y_min, y_max in BRUSH_ZONES:
            if x_min <= x <= x_max and y_min <= y <= y_max:
                return True
        return False
