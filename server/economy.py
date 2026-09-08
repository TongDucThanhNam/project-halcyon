"""Economy and Shop simulation for Project Halcyon (T3 Milestone 2).

Implements:
1. Canonical Item Catalogue (IDs, costs, and stats anchored in Docs/Teardown §12 & §14).
2. Player Economy State:
   - Starting gold: 600g (measured 4.13 truth).
   - Passive income: +6.0 gold/sec (1053 type 6).
   - Passive XP trickle: +1 XP/sec (paired 1053 type 8).
   - Level progression: levels 1-12 with per-level stat growth.
   - Ability point unlock on level up.
   - 6 inventory slots (0..5).
3. Wire Protocol Integration:
   - c2s 1081 SHOP_BUY -> echo, 1053 gold, 1099 consumption, 1085 creation
   - s2c 1053 gold/XP/HP deltas (types 6/8/0)
   - s2c 1076 level increments and 1052 next-level XP requirement setters
   - c2s 1078 skill-point allocation; item use is 1096 by inventory instance
   - Direct stat application to HeroMovement (damage modifier queue and combat math).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Any, Dict, List, Optional, Tuple

from . import cooldown_wire, level_wire, roster, wire
from .hero_movement import HeroMovement


# --------------------------------------------------------------------------
# Item Catalogue
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    id: Optional[int]
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
    max_energy: float = 0.0
    energy_regen: float = 0.0
    tier: int = 1
    active: str = ""
    passive: str = ""
    cooldown: float = 0.0
    cooldown_tag: Optional[int] = None  # measured FNV-1a of the native ability symbol
    components: Tuple[int, ...] = ()


# IDs are the recovered KindredManifest registry indices (store-format §5).
# Prior versions assigned several unrelated IDs to these names.
ITEMS: Dict[int, Item] = {
    # Weapon Items
    458: Item(id=458, name="Weapon Blade", cost=300, weapon_power=10.0, tier=1),
    505: Item(id=505, name="Heavy Steel", cost=1150, weapon_power=45.0, tier=2),
    464: Item(id=464, name="Sorrowblade", cost=3100, weapon_power=120.0, tier=3),

    # Defense Items
    469: Item(id=469, name="Light Armor", cost=300, armor=25.0, tier=1),
    471: Item(id=471, name="Metal Jacket", cost=1900, armor=95.0, tier=3),
    467: Item(id=467, name="Oakheart", cost=300, max_hp=150.0, tier=1),
    503: Item(id=503, name="Aegis", cost=2400, shield=45.0, armor=45.0, max_hp=200.0, tier=3,
              active="reflex", cooldown=45.0),

    # Crystal & Utility Items
    465: Item(id=465, name="Shatterglass", cost=3000, crystal_power=130.0, tier=3),
    476: Item(id=476, name="Clockwork", cost=2400, crystal_power=30.0, max_energy=400.0,
              energy_regen=5.0, cooldown_reduction=0.20, tier=3),
}

# Authoritative rule definitions are separate from client numeric identifiers.
# Numeric IDs are resolved through the manifest; per-item 1162 tags use the
# verified native Ability__ symbols in cooldown_wire. Costs are scalar facts from
# the recovered item records. Static stat arrays and named active cooldowns are
# checked against every catalog item's native 64-bit INST/PTCH records.
ITEMS_BY_KEY = {item.name.lower().replace(" ", "_"): item for item in ITEMS.values()}
ITEMS_BY_KEY.update({
    "sprint_boots": Item(477, "Sprint Boots", 300, move_speed=0.3,
                         active="sprint", cooldown=150.0),
    "halcyon_chargers": Item(490, "Halcyon Chargers", 1400, move_speed=0.5,
                             max_hp=150.0, max_energy=250.0, energy_regen=3.5,
                             cooldown_reduction=0.10, tier=3,
                             active="sprint", cooldown=45.0),
    "fountain_of_renewal": Item(487, "Fountain of Renewal", 2100, max_hp=400.0,
                                armor=40.0, shield=40.0, tier=3,
                                active="fountain", cooldown=75.0),
    "reflex_block": Item(485, "Reflex Block", 700, max_hp=150.0, tier=2,
                         active="reflex", cooldown=90.0),
    "crucible": Item(488, "Crucible", 2000, max_hp=550.0, tier=3,
                     active="crucible", cooldown=75.0),
    "atlas_pauldron": Item(498, "Atlas Pauldron", 1700, armor=65.0, tier=3,
                           active="atlas", cooldown=45.0),
    "aftershock": Item(492, "Aftershock", 2600, crystal_power=30.0, energy_regen=1.0,
                       cooldown_reduction=0.15, tier=3, passive="aftershock"),
    "spellfire": Item(522, "Spellfire", 2700, crystal_power=80.0, tier=3, passive="spellfire"),
    "alternating_current": Item(509, "Alternating Current", 2800, crystal_power=45.0,
                                attack_speed=40.0, tier=3,
                                passive="alternating_current"),
    "slumbering_husk": Item(525, "Slumbering Husk", 2100, armor=55.0, shield=55.0, tier=3,
                            passive="slumbering_husk"),
})
ITEMS.update({item.id: item for item in ITEMS_BY_KEY.values()})

# Component references recovered from the requested items' INST/PTCH records.
# Costs are combine fee + component costs, not the old DB's 2*sell estimate
# (Spellfire's estimate 3000 disagrees with its recovered 1000+1050+650 recipe).
_COMPONENT_ITEMS = (
    Item(459, "Crystal Bit", 300, crystal_power=15.0),
    Item(460, "Swift Shooter", 300, attack_speed=10.0),
    Item(461, "Six Sins", 650, weapon_power=25.0, tier=2),
    Item(462, "Eclipse Prism", 650, crystal_power=30.0, tier=2),
    Item(463, "Blazing Salvo", 700, attack_speed=20.0, tier=2),
    Item(468, "Dragonheart", 650, max_hp=350.0, tier=2),
    Item(470, "Coat of Plates", 750, armor=55.0, tier=2),
    Item(472, "Energy Battery", 300, max_energy=100.0, energy_regen=1.5),
    Item(473, "Hourglass", 250, cooldown_reduction=0.075, energy_regen=0.25),
    Item(474, "Void Battery", 700, max_energy=250.0, energy_regen=3.0, tier=2),
    Item(475, "Chronograph", 800, cooldown_reduction=0.15, energy_regen=0.75, tier=2),
    Item(478, "Travel Boots", 650, max_hp=100.0, move_speed=0.3, tier=2, active="sprint", cooldown=90.0),
    Item(501, "Light Shield", 300, shield=25.0),
    Item(502, "Kinetic Shield", 750, shield=55.0, tier=2),
    Item(504, "Lifespring", 800, max_hp=200.0, tier=2),
    Item(512, "Heavy Prism", 1050, crystal_power=45.0, tier=2),
    Item(538, "Warmail", 800, armor=30.0, shield=30.0, tier=2),
)
ITEMS.update({item.id: item for item in _COMPONENT_ITEMS})
_RECIPES = {
    461: (458,), 462: (459,), 463: (460,), 464: (461, 505), 465: (462, 512),
    468: (467,), 470: (469,), 471: (470,), 474: (472,), 475: (473,),
    476: (475, 474), 478: (477,), 485: (467,), 487: (538, 504),
    488: (485, 468), 490: (478, 474), 492: (475, 462), 498: (470,),
    502: (501,), 503: (538, 485), 504: (467,), 505: (458,),
    509: (463, 512), 522: (512, 462), 525: (502, 470), 538: (469, 501),
}
ITEMS = {
    item_id: replace(item, components=_RECIPES.get(item_id, ()),
                     cooldown_tag=cooldown_wire.ITEM_TAGS.get(item.name.lower().replace(" ", "_")))
    for item_id, item in ITEMS.items()
}
ITEMS_BY_KEY = {item.name.lower().replace(" ", "_"): item for item in ITEMS.values()}


def bind_item_identity(key: str, item_id: int, *, evidence: str,
                       cooldown_tag: Optional[int] = None) -> Item:
    """Bind a locally measured item identifier; callers retain its provenance.

    Intended for capture/metadata-derived configuration, never display-name hashes.
    A conflicting identity is refused rather than silently replacing a catalog.
    """
    if not evidence.strip():
        raise ValueError("a capture/reference identifying this item is required")
    if not isinstance(item_id, int) or isinstance(item_id, bool) or not 0 < item_id <= 0xFFFFFFFF:
        raise ValueError("item_id must be a positive u32")
    if cooldown_tag is not None and not 0 <= cooldown_tag <= 0xFFFFFFFF:
        raise ValueError("cooldown_tag must fit u32")
    item = ITEMS_BY_KEY[key]
    if item_id in ITEMS and ITEMS[item_id].name != item.name:
        raise ValueError("item identifier already belongs to a different item")
    if item.id is not None and item.id != item_id:
        raise ValueError("item already has a different bound identifier")
    bound = replace(item, id=item_id, cooldown_tag=cooldown_tag)
    ITEMS[item_id] = ITEMS_BY_KEY[key] = bound
    return bound


JUNGLE_SHOP_POSITION = (0.2, 42.0)
JUNGLE_SHOP_RADIUS = 6.0
BASE_SHOP_RADIUS = 8.0
# 1010 native shop kind 315, recorded actors 3565 (left) and 3564 (right).
BASE_SHOP_POSITIONS = {1: (-88.5, 2.0), 2: (88.56500244140625, 0.5099999904632568)}


def can_shop(hero: HeroMovement) -> bool:
    """Living heroes may shop at their own base or the neutral jungle shop."""
    if not hero.is_alive or not all(math.isfinite(v) for v in (hero.x, hero.y)):
        return False
    if math.hypot(hero.x - JUNGLE_SHOP_POSITION[0], hero.y - JUNGLE_SHOP_POSITION[1]) <= JUNGLE_SHOP_RADIUS:
        return True
    base_x, base_y = roster.HERO_SPAWNS[1500 if hero.team == 1 else 1517]
    shop_x, shop_y = BASE_SHOP_POSITIONS[hero.team]
    return (math.hypot(hero.x - base_x, hero.y - base_y) <= BASE_SHOP_RADIUS
            or math.hypot(hero.x - shop_x, hero.y - shop_y) <= BASE_SHOP_RADIUS)


# --------------------------------------------------------------------------
# Constants & Level Progression
# --------------------------------------------------------------------------

START_GOLD = 600.0
PASSIVE_GOLD_RATE = 6.0      # measured paired 1053 type-6 income
XP_TRICKLE_RATE = 1.0       # measured paired 1053 type-8 income
TRICKLE_INTERVAL = 1.0      # s2c resource delta broadcast cadence

MINION_BOUNTY_GOLD = 45.0
MINION_BOUNTY_XP = 50.0
HERO_BOUNTY_GOLD = 200.0
HERO_BOUNTY_XP = 150.0

# Native per-level requirements 68, 84, 100, ...; cumulative thresholds to
# reach each level are independent from 1011's within-level XP field.
XP_LEVEL_THRESHOLDS = level_wire.XP_LEVEL_THRESHOLDS

# Per-level baseline stat growth
HP_PER_LEVEL = 70.0
WP_PER_LEVEL = 6.0
ARMOR_PER_LEVEL = 3.5
SHIELD_PER_LEVEL = 2.5


# --------------------------------------------------------------------------
# Player Economy
# --------------------------------------------------------------------------

@dataclass
class DefaultItemState:
    """Native HUD utility instance outside the six purchasable equipment slots.

    The timer's state count is preserved from native snapshots. It is not
    interpreted as a mutable remaining-charge count: Totem's recorded value
    stays two both before and after use.
    """
    instance_id: int
    item_id: int
    key: str
    cooldown: float
    native_state_count: int = 1
    cooldown_until: float = 0.0

    def is_ready(self, now: float) -> bool:
        return now >= self.cooldown_until

    def begin_cooldown(self, now: float) -> bool:
        if not math.isfinite(now) or now < 0:
            raise ValueError("default item time must be finite and nonnegative")
        if not self.is_ready(now):
            return False
        self.cooldown_until = now + self.cooldown
        return True

    def timer_payload(self, eid: int, now: float) -> bytes:
        return cooldown_wire.build_item_timer(eid, cooldown_wire.ITEM_TAGS[self.key],
                                             max(0.0, self.cooldown_until - now), self.cooldown,
                                             state_count=self.native_state_count)


class PlayerEconomy:
    """Tracks gold, inventory slots, experience, and levels for one hero."""

    def __init__(self, eid: int, start_gold: float = START_GOLD):
        self.eid = eid
        self.gold = start_gold
        self.xp = 0.0
        self.level = 1
        self.ability_points = 1  # 1 point available at level 1
        self.inventory: List[Optional[Item]] = [None] * 6
        self.item_cooldowns: Dict[str, float] = {}  # survives sell/rebuy or slot changes
        self.inventory_instances: List[Optional[int]] = [None] * 6
        self.default_items: Dict[int, DefaultItemState] = {
            2000: DefaultItemState(2000, 457, "healing_flask", 120.0),
            2001: DefaultItemState(2001, 526, "vision_totem", 150.0, native_state_count=2),
        }
        self.next_item_instance = 2002  # corpus defaults occupy instances 2000/2001
        self.last_purchase_cost = 0.0
        self.last_consumed_instances: List[int] = []
        self.last_consumed_items: List[Tuple[Optional[int], Item]] = []

    def default_item_frames(self, now: float) -> List[Tuple[int, bytes]]:
        """Current default inventory and timer state for bootstrap/reconnect."""
        frames = []
        for _instance, item in sorted(self.default_items.items()):
            frames.append((wire.OP.INVENTORY_ITEM, roster.build_item_inventory(self.eid, item.item_id, item.instance_id)))
            frames.append((wire.OP.TIMER_TICK, item.timer_payload(self.eid, now)))
        return frames

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
        plan = self.purchase_plan(item_id)
        return plan is not None and self.gold >= plan[0]

    def purchase_plan(self, item_id: int) -> Optional[Tuple[int, List[int], int]]:
        """Price an upgrade, consuming each owned recipe component at most once."""
        item = ITEMS.get(item_id)
        if item is None:
            return None
        consumed: List[int] = []

        def collect(component_id: int):
            for slot, owned in enumerate(self.inventory):
                if slot not in consumed and owned is not None and owned.id == component_id:
                    consumed.append(slot)
                    return
            for child in ITEMS[component_id].components:
                collect(child)

        for component in item.components:
            collect(component)
        free_slots = [slot for slot, owned in enumerate(self.inventory) if owned is None or slot in consumed]
        if not free_slots:
            return None
        cost = item.cost - sum(self.inventory[slot].cost for slot in consumed)
        return max(0, cost), consumed, min(free_slots)

    def buy_item(self, item_id: int) -> Optional[int]:
        """Attempt to buy item. Returns slot index (0..5) on success, or None."""
        plan = self.purchase_plan(item_id)
        if plan is None or self.gold < plan[0]:
            return None
        item = ITEMS[item_id]
        cost, consumed, slot_idx = plan
        self.last_purchase_cost = cost
        self.last_consumed_instances = [self.inventory_instances[slot] for slot in consumed
                                        if self.inventory_instances[slot] is not None]
        self.last_consumed_items = [(self.inventory_instances[slot], self.inventory[slot]) for slot in consumed]
        for slot in consumed:
            self.inventory[slot] = None
            self.inventory_instances[slot] = None
        self.gold -= cost
        self.inventory[slot_idx] = item
        self.inventory_instances[slot_idx] = self.next_item_instance
        self.next_item_instance += 1
        return slot_idx

    def sell_item(self, slot_idx: int) -> Optional[Item]:
        """Sell item at slot index, refunding 50% gold."""
        if slot_idx < 0 or slot_idx >= 6 or self.inventory[slot_idx] is None:
            return None
        item = self.inventory[slot_idx]
        self.inventory[slot_idx] = None
        self.inventory_instances[slot_idx] = None
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
            "max_energy": 0.0,
            "energy_regen": 0.0,
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
                stats["max_energy"] += item.max_energy
                stats["energy_regen"] += item.energy_regen
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
        hero.max_hp = hero.base_max_hp + (lvl_bonus * getattr(hero, "hp_per_level", HP_PER_LEVEL)) + item_stats["max_hp"]
        # Maintain HP proportion or grant flat bonus
        hp_delta = hero.max_hp - old_max_hp
        if hp_delta > 0 and hero.is_alive:
            hero.hp = min(hero.max_hp, hero.hp + hp_delta)
        else:
            hero.hp = min(hero.hp, hero.max_hp)

        hero.attack_damage = hero.base_attack_damage + (lvl_bonus * getattr(hero, "weapon_per_level", WP_PER_LEVEL)) + item_stats["weapon_power"]
        hero.armor = hero.base_armor + (lvl_bonus * getattr(hero, "armor_per_level", ARMOR_PER_LEVEL)) + item_stats["armor"]
        hero.shield = hero.base_shield + (lvl_bonus * getattr(hero, "shield_per_level", SHIELD_PER_LEVEL)) + item_stats["shield"]
        hero.crystal_power = item_stats["crystal_power"] + getattr(hero, "buff_crystal_power", 0.0)
        hero.item_move_speed = item_stats["move_speed"]
        hero.bonus_attack_speed = item_stats["attack_speed"] + lvl_bonus * getattr(hero, "attack_speed_per_level", 0.0)
        hero.cooldown_reduction = item_stats["cooldown_reduction"]
        hero.level = self.level
        if hasattr(hero, "max_energy"):
            if not hasattr(hero, "base_max_energy"):
                hero.base_max_energy = hero.max_energy
                hero.base_energy_regen = hero.energy_regen
            old_max_energy = hero.max_energy
            hero.max_energy = hero.base_max_energy + item_stats["max_energy"] + lvl_bonus * getattr(hero, "energy_per_level", 0.0)
            hero.energy = min(hero.max_energy, hero.energy + max(0.0, hero.max_energy - old_max_energy))
            hero.energy_regen = (hero.base_energy_regen + item_stats["energy_regen"]
                                + lvl_bonus * getattr(hero, "energy_regen_per_level", 0.0)
                                + getattr(hero, "buff_energy_regen", 0.0))


# --------------------------------------------------------------------------
# Economy Manager
# --------------------------------------------------------------------------

class PendingResourceFrame(tuple):
    """A normal wire-frame pair whose delta was included in reconnect state."""
    resource_credit = True

    def __new__(cls, opcode, payload):
        return super().__new__(cls, (opcode, payload))


class EconomyManager:
    """Manages match economy, passive gold/XP, store purchases, and bounties."""

    def __init__(self):
        self.players: Dict[int, PlayerEconomy] = {}
        self.last_trickle_at: float = 0.0
        self.trickle_seq: int = 0
        self._pending_gold: Dict[int, float] = {}
        self._pending_xp: Dict[int, float] = {}

    def get_or_create(self, eid: int) -> PlayerEconomy:
        if eid not in self.players:
            self.players[eid] = PlayerEconomy(eid)
        return self.players[eid]

    def _flush_pending_xp(self, eid: int) -> List[Tuple[int, bytes]]:
        amount = self._pending_xp.pop(eid, 0.0)
        if amount == 0:
            return []
        return [PendingResourceFrame(wire.OP.ENTITY_STAT,
                                     roster.build_hero_stat(eid, amount, stat_type=8))]

    @staticmethod
    def _level_frames(econ: PlayerEconomy, hero: HeroMovement, levels: List[int]) -> List[Tuple[int, bytes]]:
        if not levels:
            return []
        # The native level action applies client-side base stat growth. Update
        # authoritative HP/stats once; a second 1053 HP delta would duplicate it.
        econ.apply_to_hero(hero)
        frames = []
        for level in levels:
            frames.append((level_wire.OP_LEVEL_INCREMENT, level_wire.build_level_increment(econ.eid)))
            frames.append((level_wire.OP_XP_REQUIREMENT, level_wire.build_xp_requirement(
                econ.eid, level_wire.next_level_requirement(level))))
        return frames

    def step(
        self,
        dt: float,
        now: float,
        all_heroes: Dict[int, HeroMovement],
        emit_trickle: bool = True,
    ) -> List[Tuple[int, bytes]]:
        """Accumulate resources, then send the measured 1053 resource channels."""
        frames: List[Tuple[int, bytes]] = []

        # Ensure all active heroes have an economy record
        for eid, hero in all_heroes.items():
            econ = self.get_or_create(eid)
            # Accumulate passive gold and XP
            econ.add_gold(PASSIVE_GOLD_RATE * dt)
            self._pending_gold[eid] = self._pending_gold.get(eid, 0.0) + PASSIVE_GOLD_RATE * dt
            self._pending_xp[eid] = self._pending_xp.get(eid, 0.0) + XP_TRICKLE_RATE * dt
            new_levels = econ.add_xp(XP_TRICKLE_RATE * dt)
            if new_levels:
                # 1076 rolls native XP into the next level. Deliver all XP that
                # caused the transition first, even between coarse flushes.
                frames.extend(self._flush_pending_xp(eid))
                frames.extend(self._level_frames(econ, hero, new_levels))

        # Coarse steps send the amount actually accumulated, never a single
        # fixed tick that would leave the HUD behind authoritative resources.
        if emit_trickle and now - self.last_trickle_at >= TRICKLE_INTERVAL:
            self.last_trickle_at = now
            for eid in all_heroes:
                frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(
                    eid, self._pending_gold.pop(eid, 0.0), stat_type=6)))
                frames.extend(self._flush_pending_xp(eid))

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
            frames.extend(self._flush_pending_xp(killer_eid))

        frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(killer_eid, gold, stat_type=6)))
        frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(killer_eid, xp, stat_type=8)))
        frames.extend(self._level_frames(econ, hero, new_levels))
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
            frames.extend(self._flush_pending_xp(killer_eid))

        frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(killer_eid, gold, stat_type=6)))
        frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(killer_eid, xp, stat_type=8)))
        frames.extend(self._level_frames(econ, hero, new_levels))
        return frames

    def purchase_item(
        self,
        eid: int,
        item_id: int,
        hero: HeroMovement,
    ) -> Tuple[bool, List[Tuple[int, bytes]]]:
        """Process c2s 1081 purchase intent: validates gold, assigns slot, updates stats.
        Returns (success, wire_frames)."""
        if eid != hero.eid or not can_shop(hero):
            return False, []
        econ = self.get_or_create(eid)
        slot_idx = econ.buy_item(item_id)
        if slot_idx is None:
            return False, []

        previous_hp = hero.hp
        econ.apply_to_hero(hero)
        frames: List[Tuple[int, bytes]] = [
            (wire.OP.SHOP_BUY, roster.build_shop_buy(eid, item_id)),
            (wire.OP.ENTITY_STAT, roster.build_hero_stat(eid, -econ.last_purchase_cost, stat_type=6)),
        ]
        for instance_id, consumed in econ.last_consumed_items:
            frames.extend(self._item_attribute_frames(eid, consumed, -1.0))
            if instance_id is not None:
                frames.append((1099, roster.build_item_remove(eid, instance_id)))
        # 1085 creates a particular inventory instance, then 1052 adds its stats.
        frames.append((1085, roster.build_item_inventory(eid, item_id, econ.inventory_instances[slot_idx])))
        item = ITEMS[item_id]
        frames.extend(self._item_attribute_frames(eid, item))
        if hero.hp != previous_hp:
            frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(eid, hero.hp - previous_hp, stat_type=0)))

        return True, frames

    @staticmethod
    def _item_attribute_frames(eid: int, item: Item, sign: float = 1.0) -> List[Tuple[int, bytes]]:
        # Measured adjacent 1085/1052 purchase signatures, including fractional
        # attack speed and cooldown reduction. Move-speed wire index is unbound.
        attributes = ((0, item.max_hp), (2, item.max_energy), (3, item.energy_regen),
                      (4, item.weapon_power), (5, item.crystal_power), (7, item.armor),
                      (8, item.shield), (15, item.attack_speed / 100.0),
                      (25, item.cooldown_reduction))
        return [(1052, roster.build_entity_attribute(eid, amount * sign, attribute_id))
                for attribute_id, amount in attributes if amount]

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
        if hero_kit is None or not hero_kit.upgrade_ability(slot_idx, econ.level):
            return False
        econ.ability_points -= 1
        return True
