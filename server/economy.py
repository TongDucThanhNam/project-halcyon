"""Economy and Shop simulation for Project Halcyon (T3 Milestone 2).

Implements:
1. Canonical Item Catalogue (IDs, costs, and stats anchored in Docs/Teardown §12 & §14).
2. Player Economy State:
   - Starting gold: 600g (measured 4.13 truth).
   - Passive income: +4.0 gold/sec.
   - Passive XP trickle: 3.594 XP/sec (measured 1086 trickle band).
   - Level progression: levels 1-12 with per-level stat growth.
   - Ability point unlock on level up.
   - 6 inventory slots (0..5).
3. Wire Protocol Integration:
   - c2s 1081 SHOP_BUY -> s2c 1082 INVENTORY_SLOT
   - s2c 1086 XP trickle and award deltas
   - c2s 1096 ABILITY_UPGRADE
   - Direct stat application to HeroMovement (damage modifier queue and combat math).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import roster, wire
from .hero_movement import HeroMovement


# --------------------------------------------------------------------------
# Item Catalogue
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    id: int
    name: str
    cost: int
    weapon_power: float = 0.0
    crystal_power: float = 0.0
    armor: float = 0.0
    shield: float = 0.0
    max_hp: float = 0.0
    cooldown_reduction: float = 0.0
    move_speed: float = 0.0
    attack_speed: float = 0.0
    tier: int = 1


# Canonical items anchored in mechanics matrix §12 / client balance DB
ITEMS: Dict[int, Item] = {
    # Weapon Items
    467: Item(id=467, name="Weapon Blade", cost=300, weapon_power=10.0, tier=1),
    504: Item(id=504, name="Heavy Steel", cost=1150, weapon_power=55.0, tier=2),
    487: Item(id=487, name="Sorrowblade", cost=3100, weapon_power=150.0, tier=3),

    # Defense Items
    502: Item(id=502, name="Light Armor", cost=250, armor=25.0, shield=20.0, tier=1),
    539: Item(id=539, name="Metal Jacket", cost=2100, armor=85.0, tier=3),
    470: Item(id=470, name="Oakheart", cost=300, max_hp=200.0, tier=1),
    480: Item(id=480, name="Aegis", cost=2250, shield=85.0, armor=30.0, max_hp=200.0, tier=3),

    # Crystal & Utility Items
    464: Item(id=464, name="Shatterglass", cost=3000, crystal_power=150.0, tier=3),
    472: Item(id=472, name="Clockwork", cost=2500, crystal_power=40.0, cooldown_reduction=0.30, tier=3),
}


# --------------------------------------------------------------------------
# Constants & Level Progression
# --------------------------------------------------------------------------

START_GOLD = 600.0
PASSIVE_GOLD_RATE = 4.0      # gold / second
XP_TRICKLE_RATE = 3.594      # XP / second (measured 1086 trickle band)
TRICKLE_INTERVAL = 1.0       # s2c 1086 trickle broadcast cadence

MINION_BOUNTY_GOLD = 45.0
MINION_BOUNTY_XP = 50.0
HERO_BOUNTY_GOLD = 200.0
HERO_BOUNTY_XP = 150.0

# 12 levels: cumulative XP thresholds to reach level
XP_LEVEL_THRESHOLDS = [
    0,      # Level 1
    100,    # Level 2
    250,    # Level 3
    450,    # Level 4
    700,    # Level 5
    1000,   # Level 6
    1350,   # Level 7
    1750,   # Level 8
    2200,   # Level 9
    2700,   # Level 10
    3250,   # Level 11
    3850,   # Level 12
]

# Per-level baseline stat growth
HP_PER_LEVEL = 70.0
WP_PER_LEVEL = 6.0
ARMOR_PER_LEVEL = 3.5
SHIELD_PER_LEVEL = 2.5


# --------------------------------------------------------------------------
# Player Economy
# --------------------------------------------------------------------------

class PlayerEconomy:
    """Tracks gold, inventory slots, experience, and levels for one hero."""

    def __init__(self, eid: int, start_gold: float = START_GOLD):
        self.eid = eid
        self.gold = start_gold
        self.xp = 0.0
        self.level = 1
        self.ability_points = 1  # 1 point available at level 1
        self.inventory: List[Optional[Item]] = [None] * 6

    def add_gold(self, amount: float) -> float:
        self.gold = max(0.0, self.gold + amount)
        return self.gold

    def add_xp(self, amount: float) -> List[int]:
        """Add XP and return any new levels reached."""
        self.xp += amount
        new_levels = []
        while self.level < len(XP_LEVEL_THRESHOLDS):
            next_threshold = XP_LEVEL_THRESHOLDS[self.level]
            if self.xp >= next_threshold:
                self.level += 1
                self.ability_points += 1
                new_levels.append(self.level)
            else:
                break
        return new_levels

    def can_buy_item(self, item_id: int) -> bool:
        if item_id not in ITEMS:
            return False
        item = ITEMS[item_id]
        if self.gold < item.cost:
            return False
        return any(slot is None for slot in self.inventory)

    def buy_item(self, item_id: int) -> Optional[int]:
        """Attempt to buy item. Returns slot index (0..5) on success, or None."""
        if not self.can_buy_item(item_id):
            return None
        item = ITEMS[item_id]
        slot_idx = self.inventory.index(None)
        self.gold -= item.cost
        self.inventory[slot_idx] = item
        return slot_idx

    def sell_item(self, slot_idx: int) -> Optional[Item]:
        """Sell item at slot index, refunding 50% gold."""
        if slot_idx < 0 or slot_idx >= 6 or self.inventory[slot_idx] is None:
            return None
        item = self.inventory[slot_idx]
        self.inventory[slot_idx] = None
        self.gold += item.cost * 0.5
        return item

    def get_total_item_stats(self) -> Dict[str, float]:
        stats = {
            "weapon_power": 0.0,
            "crystal_power": 0.0,
            "armor": 0.0,
            "shield": 0.0,
            "max_hp": 0.0,
            "cooldown_reduction": 0.0,
            "move_speed": 0.0,
            "attack_speed": 0.0,
        }
        for item in self.inventory:
            if item is not None:
                stats["weapon_power"] += item.weapon_power
                stats["crystal_power"] += item.crystal_power
                stats["armor"] += item.armor
                stats["shield"] += item.shield
                stats["max_hp"] += item.max_hp
                stats["cooldown_reduction"] += item.cooldown_reduction
                stats["move_speed"] += item.move_speed
                stats["attack_speed"] += item.attack_speed
        return stats

    def apply_to_hero(self, hero: HeroMovement):
        """Update hero stats based on level and item bonuses."""
        # Ensure base stats are preserved on hero
        if not hasattr(hero, "base_max_hp"):
            hero.base_max_hp = hero.max_hp
            hero.base_attack_damage = hero.attack_damage
            hero.base_armor = getattr(hero, "armor", 25.0)
            hero.base_shield = getattr(hero, "shield", 20.0)
            hero.base_speed = hero.speed

        item_stats = self.get_total_item_stats()
        lvl_bonus = self.level - 1

        old_max_hp = hero.max_hp
        hero.max_hp = hero.base_max_hp + (lvl_bonus * HP_PER_LEVEL) + item_stats["max_hp"]
        # Maintain HP proportion or grant flat bonus
        hp_delta = hero.max_hp - old_max_hp
        if hp_delta > 0:
            hero.hp = min(hero.max_hp, hero.hp + hp_delta)

        hero.attack_damage = hero.base_attack_damage + (lvl_bonus * WP_PER_LEVEL) + item_stats["weapon_power"]
        hero.armor = hero.base_armor + (lvl_bonus * ARMOR_PER_LEVEL) + item_stats["armor"]
        hero.shield = hero.base_shield + (lvl_bonus * SHIELD_PER_LEVEL) + item_stats["shield"]
        hero.crystal_power = item_stats["crystal_power"]
        hero.speed = hero.base_speed + item_stats["move_speed"]


# --------------------------------------------------------------------------
# Economy Manager
# --------------------------------------------------------------------------

class EconomyManager:
    """Manages match economy, passive gold/XP, store purchases, and bounties."""

    def __init__(self):
        self.players: Dict[int, PlayerEconomy] = {}
        self.last_trickle_at: float = 0.0
        self.trickle_seq: int = 0

    def get_or_create(self, eid: int) -> PlayerEconomy:
        if eid not in self.players:
            self.players[eid] = PlayerEconomy(eid)
        return self.players[eid]

    def step(
        self,
        dt: float,
        now: float,
        all_heroes: Dict[int, HeroMovement],
        emit_trickle: bool = True,
    ) -> List[Tuple[int, bytes]]:
        """Simulate passive gold and XP accumulation, emitting 1086 trickle packets if emit_trickle is True."""
        frames: List[Tuple[int, bytes]] = []

        # Ensure all active heroes have an economy record
        for eid, hero in all_heroes.items():
            econ = self.get_or_create(eid)
            # Accumulate passive gold and XP
            econ.add_gold(PASSIVE_GOLD_RATE * dt)
            new_levels = econ.add_xp(XP_TRICKLE_RATE * dt)
            if new_levels:
                econ.apply_to_hero(hero)
                # Emit HP stat update on level-up
                frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(eid, hero.hp, stat_type=6)))

        # Periodic s2c 1086 XP trickle broadcast
        if emit_trickle and now - self.last_trickle_at >= TRICKLE_INTERVAL:
            self.last_trickle_at = now
            for eid in all_heroes:
                self.trickle_seq = (self.trickle_seq + 1) & 0xFFFF
                frames.append((wire.OP.ENTITY_PROP, roster.build_xp_trickle(
                    eid, amount=XP_TRICKLE_RATE, seq=self.trickle_seq
                )))

        return frames

    def reward_minion_bounty(
        self,
        killer_eid: int,
        all_heroes: Dict[int, HeroMovement],
        gold: float = MINION_BOUNTY_GOLD,
        xp: float = MINION_BOUNTY_XP,
    ) -> List[Tuple[int, bytes]]:
        """Reward last-hit minion gold and XP to killer."""
        frames: List[Tuple[int, bytes]] = []
        if killer_eid not in all_heroes:
            return frames

        econ = self.get_or_create(killer_eid)
        hero = all_heroes[killer_eid]
        econ.add_gold(gold)
        new_levels = econ.add_xp(xp)
        if new_levels:
            econ.apply_to_hero(hero)
            frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(killer_eid, hero.hp, stat_type=6)))

        # Emit 1086 gold award delta
        self.trickle_seq = (self.trickle_seq + 1) & 0xFFFF
        frames.append((wire.OP.ENTITY_PROP, roster.build_entity_prop(
            killer_eid, 0x45, self.trickle_seq, int(gold)
        )))
        return frames

    def reward_hero_bounty(
        self,
        killer_eid: int,
        victim_eid: int,
        all_heroes: Dict[int, HeroMovement],
        gold: float = HERO_BOUNTY_GOLD,
        xp: float = HERO_BOUNTY_XP,
    ) -> List[Tuple[int, bytes]]:
        """Reward hero kill gold and XP to killer."""
        frames: List[Tuple[int, bytes]] = []
        if killer_eid not in all_heroes:
            return frames

        econ = self.get_or_create(killer_eid)
        hero = all_heroes[killer_eid]
        econ.add_gold(gold)
        new_levels = econ.add_xp(xp)
        if new_levels:
            econ.apply_to_hero(hero)
            frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(killer_eid, hero.hp, stat_type=6)))

        self.trickle_seq = (self.trickle_seq + 1) & 0xFFFF
        frames.append((wire.OP.ENTITY_PROP, roster.build_entity_prop(
            killer_eid, 0x45, self.trickle_seq, int(gold)
        )))
        return frames

    def purchase_item(
        self,
        eid: int,
        item_id: int,
        hero: HeroMovement,
    ) -> Tuple[bool, List[Tuple[int, bytes]]]:
        """Process c2s 1081 purchase intent: validates gold, assigns slot, updates stats.
        Returns (success, wire_frames)."""
        econ = self.get_or_create(eid)
        slot_idx = econ.buy_item(item_id)
        if slot_idx is None:
            return False, []

        econ.apply_to_hero(hero)
        frames: List[Tuple[int, bytes]] = [
            # s2c 1082 inventory slot confirmation
            (wire.OP.INVENTORY_SLOT, roster.build_inventory_slot(eid, slot_idx))
        ]
        # Emit HP stat update if item increased max_hp
        item = ITEMS[item_id]
        if item.max_hp > 0:
            frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(eid, hero.hp, stat_type=6)))

        return True, frames

    def upgrade_ability(
        self,
        eid: int,
        slot_idx: int,
        hero_kit: Optional[Any] = None,
    ) -> bool:
        """Upgrade hero ability point on level-up."""
        econ = self.get_or_create(eid)
        if econ.ability_points <= 0:
            return False

        econ.ability_points -= 1
        if hero_kit is not None and slot_idx in hero_kit.abilities:
            ability = hero_kit.abilities[slot_idx]
            # Increase base damage and decrease cooldown slightly per rank
            ability.base_damage += 30.0
            ability.cooldown = max(1.0, ability.cooldown - 0.5)
        return True
