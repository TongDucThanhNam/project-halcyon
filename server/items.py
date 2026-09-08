"""Deterministic item actives and combat passives for the solo sandbox.

The acceptance brief supplies the listed effect magnitudes and durations.
Other parameters use verified native records where available; the remaining
damage/barrier calibration values stay explicit in ItemRules. Wire IDs/timer tags are separate
from these rules; ItemActivation only emits a HUD timer when a tag is bound from
evidence. The caller routes damage_callback through its normal combat/death path.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import buff_wire, cooldown_wire, economy, roster, wire
from .status_effects import StatusEffect, StatusManager, StatusType

Frames = List[Tuple[int, bytes]]
DamageCallback = Callable[[Any, Any, float, str, float], Frames]


@dataclass(frozen=True)
class ItemRules:
    sprint_speed: float = 2.0
    sprint_duration: float = 3.0
    fountain_duration: int = 3
    fountain_flat_heal: float = 2.0
    fountain_missing_hp_ratio: float = 0.01
    ally_radius: float = 12.0         # native RANGE in Fountain and Crucible
    reflex_duration: float = 1.0
    crucible_duration: float = 1.2
    barrier_max_hp_ratio: float = 0.25
    atlas_delay: float = 0.8
    atlas_radius: float = 4.0
    atlas_slow: float = 0.65
    atlas_duration: float = 5.0
    aftershock_ratio: float = 0.15
    aftershock_ready_duration: float = 5.0
    aftershock_cooldown: float = 1.0  # native COOLDOWN
    spellfire_duration: int = 3
    spellfire_ticks_per_second: float = 2.0  # native TICKS_PER_SECOND
    spellfire_wound: float = 0.33
    spellfire_damage_per_second: float = 20.0
    spellfire_cp_per_second: float = 0.05
    alternating_cp_ratio: float = 0.70
    husk_burst_ratio: float = 0.20
    husk_burst_window: float = 1.0
    husk_duration: float = 3.0        # native Fortified_Health_Duration
    husk_cooldown: float = 30.0


@dataclass(frozen=True)
class ItemActivation:
    success: bool
    reason: str = ""
    cooldown: float = 0.0
    cooldown_tag: Optional[int] = None

    def frames(self, eid: int) -> Frames:
        if not self.success or self.cooldown_tag is None:
            return []
        return [(wire.OP.TIMER_TICK, cooldown_wire.build_item_timer(
            eid, self.cooldown_tag, self.cooldown, self.cooldown))]


@dataclass
class PeriodicEffect:
    source_eid: int
    target_eid: int
    kind: str
    next_tick: float
    expires_at: float
    amount: float = 0.0
    interval: float = 1.0
    status_id: Optional[str] = None


class ItemManager:
    def __init__(self, economy_manager: economy.EconomyManager,
                 status_manager: StatusManager, rules: Optional[ItemRules] = None):
        self.economy = economy_manager
        self.status = status_manager
        self.rules = rules or ItemRules()
        self._periodic: Dict[Tuple[str, int, int], PeriodicEffect] = {}
        self._atlas: List[Tuple[float, int]] = []
        self._aftershock_ready: Dict[int, float] = {}
        self._aftershock_cooldown: Dict[int, float] = {}
        self._alternating_hits: Dict[int, int] = {}
        self._husk_hits: Dict[int, List[Tuple[float, float]]] = {}
        self._husk_cooldown: Dict[int, float] = {}
        self._cooldown_timers: Dict[Tuple[int, str], Tuple[int, float, float]] = {}

    def has_passive(self, eid: int, passive: str) -> bool:
        player = self.economy.players.get(eid)
        return player is not None and any(item is not None and item.passive == passive
                                          for item in player.inventory)

    @staticmethod
    def _entities(heroes: Dict[int, Any], entities: Optional[Dict[int, Any]]) -> Dict[int, Any]:
        combined = dict(entities or {})
        combined.update(heroes)
        return combined

    @staticmethod
    def _alive(entity: Any) -> bool:
        return bool(getattr(entity, "is_alive", getattr(entity, "alive",
                    getattr(entity, "active", True)))) and getattr(entity, "hp", 0.0) > 0.0

    @staticmethod
    def _near(source: Any, target: Any, radius: float) -> bool:
        return math.hypot(source.x - target.x, source.y - target.y) <= radius

    def _effect(self, key: str, kind: StatusType, source: int, target: int,
                now: float, duration: float, magnitude: float = 1.0,
                *, native_kind: Optional[int] = None, native_key: Optional[str] = None) -> bool:
        return self.status.apply_effect(StatusEffect(key, kind, source, target,
                                                    duration, now, now + duration, magnitude,
                                                    native_buff_kind=native_kind, native_buff_key=native_key))

    def activate(self, eid: int, slot: int, now: float, all_heroes: Dict[int, Any],
                 all_entities: Optional[Dict[int, Any]] = None) -> ItemActivation:
        hero = all_heroes.get(eid)
        player = self.economy.players.get(eid)
        if hero is None or not self._alive(hero) or player is None:
            return ItemActivation(False, "hero unavailable")
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < len(player.inventory):
            return ItemActivation(False, "invalid item slot")
        item = player.inventory[slot]
        if item is None or not item.active:
            return ItemActivation(False, "slot has no active item")
        # Reflex items are usable while silenced; hard control stops activation.
        if any(self.status.has_effect(eid, kind, now)
               for kind in (StatusType.STUN, StatusType.KNOCKBACK)):
            return ItemActivation(False, "hero controlled")
        group = "reflex" if item.active == "crucible" else item.active
        if now < player.item_cooldowns.get(group, 0.0):
            return ItemActivation(False, "item on cooldown")
        entities = self._entities(all_heroes, all_entities)
        allies = [target for _, target in sorted(entities.items())
                  if self._alive(target) and getattr(target, "team", None) == hero.team
                  and self._near(hero, target, self.rules.ally_radius)]
        if item.active == "sprint":
            native_kind = {477: buff_wire.ITEM_BUFF_KINDS["sprint_boots_sprint"],
                           478: buff_wire.ITEM_BUFF_KINDS["travel_boots_sprint"],
                           490: buff_wire.ITEM_BUFF_KINDS["halcyon_chargers_sprint"]}[item.id]
            self._effect(f"sprint:{eid}", StatusType.MOVE_SPEED_FLAT, eid, eid, now,
                         self.rules.sprint_duration, self.rules.sprint_speed, native_kind=native_kind)
        elif item.active == "fountain":
            for target in allies:
                key = ("fountain", eid, target.eid)
                status_id = f"fountain:{eid}"
                self._effect(status_id, StatusType.PERIODIC_HEAL, eid, target.eid, now,
                             self.rules.fountain_duration,
                             native_kind=buff_wire.ITEM_BUFF_KINDS["fountain_of_renewal"])
                self._periodic[key] = PeriodicEffect(eid, target.eid, "fountain", now + 1.0,
                                                      now + self.rules.fountain_duration, status_id=status_id)
        elif item.active in ("reflex", "crucible"):
            targets = allies if item.active == "crucible" else [hero]
            duration = self.rules.crucible_duration if item.active == "crucible" else self.rules.reflex_duration
            for target in targets:
                native_key = f"reflex:{eid}:{target.eid}"
                self._effect(f"reflex-barrier:{eid}:{target.eid}", StatusType.BARRIER, eid,
                             target.eid, now, duration, target.max_hp * self.rules.barrier_max_hp_ratio,
                             native_kind=buff_wire.ITEM_BUFF_KINDS["reflex_block"], native_key=native_key)
                self._effect(f"reflex-immunity:{eid}:{target.eid}", StatusType.CC_IMMUNITY,
                             eid, target.eid, now, duration,
                             native_kind=buff_wire.ITEM_BUFF_KINDS["reflex_block"], native_key=native_key)
        elif item.active == "atlas":
            self._atlas.append((now + self.rules.atlas_delay, eid))
        else:
            return ItemActivation(False, "unsupported active item")
        player.item_cooldowns[group] = now + item.cooldown
        if item.cooldown_tag is not None:
            self._cooldown_timers[(eid, group)] = (item.cooldown_tag, item.cooldown, now + item.cooldown)
        return ItemActivation(True, cooldown=item.cooldown, cooldown_tag=item.cooldown_tag)

    def cooldown_frames(self, eid: int, now: float) -> Frames:
        """Authoritative active-family timers for reconnect, including sold items."""
        return [(wire.OP.TIMER_TICK, cooldown_wire.build_item_timer(eid, tag, max(0.0, expires - now), duration))
                for (owner, _group), (tag, duration, expires) in sorted(self._cooldown_timers.items())
                if owner == eid]

    def on_ability_cast(self, hero: Any, now: float):
        """Call only after a valid ability has spent energy and begun its cast."""
        if self.has_passive(hero.eid, "aftershock") and now >= self._aftershock_cooldown.get(hero.eid, 0.0):
            self._aftershock_ready[hero.eid] = now + self.rules.aftershock_ready_duration

    def on_basic_attack(self, source: Any, target: Any, now: float,
                        damage_callback: DamageCallback) -> Frames:
        """Apply procs once on a released attack's impact, never on its windup."""
        frames: Frames = []
        eid = source.eid
        if self.has_passive(eid, "aftershock") and now < self._aftershock_ready.get(eid, 0.0):
            self._aftershock_ready.pop(eid, None)
            self._aftershock_cooldown[eid] = now + self.rules.aftershock_cooldown
            # A lethal ordinary hit still spends the armed next-hit effect.
            if self._alive(target):
                frames.extend(damage_callback(source, target, target.max_hp * self.rules.aftershock_ratio,
                                              "crystal", now))
        if self.has_passive(eid, "alternating_current"):
            self._alternating_hits[eid] = self._alternating_hits.get(eid, 0) + 1
            if self._alternating_hits[eid] % 2 == 0 and self._alive(target):
                amount = getattr(source, "crystal_power", 0.0) * self.rules.alternating_cp_ratio
                if amount > 0.0:
                    frames.extend(damage_callback(source, target, amount, "crystal", now))
        else:
            self._alternating_hits.pop(eid, None)
        return frames

    def on_crystal_damage(self, source: Any, target: Any, now: float):
        """Call on direct crystal damage; periodic item damage must not recurse."""
        if not self._alive(target) or not self.has_passive(source.eid, "spellfire"):
            return
        duration = self.rules.spellfire_duration
        self._effect(f"spellfire-wound:{source.eid}", StatusType.WOUND, source.eid,
                     target.eid, now, duration, self.rules.spellfire_wound)
        key = ("spellfire", source.eid, target.eid)
        previous = self._periodic.get(key)
        interval = 1.0 / self.rules.spellfire_ticks_per_second
        next_tick = previous.next_tick if previous is not None and previous.expires_at >= now else now + interval
        damage_per_second = self.rules.spellfire_damage_per_second + getattr(source, "crystal_power", 0.0) * self.rules.spellfire_cp_per_second
        self._periodic[key] = PeriodicEffect(source.eid, target.eid, "spellfire", next_tick,
                                            now + duration, damage_per_second * interval, interval)

    def before_damage(self, target: Any, post_mitigation_damage: float, now: float) -> bool:
        """Trigger Husk before barrier/fortified absorption and HP subtraction."""
        eid = target.eid
        if not self._alive(target) or post_mitigation_damage <= 0.0 or not self.has_passive(eid, "slumbering_husk"):
            return False
        if now < self._husk_cooldown.get(eid, 0.0):
            return False
        hits = [(at, amount) for at, amount in self._husk_hits.get(eid, [])
                if at > now - self.rules.husk_burst_window]
        hits.append((now, post_mitigation_damage))
        self._husk_hits[eid] = hits
        if sum(amount for _, amount in hits) <= target.max_hp * self.rules.husk_burst_ratio:
            return False
        self._husk_hits.pop(eid, None)
        self._husk_cooldown[eid] = now + self.rules.husk_cooldown
        self._effect(f"husk:{eid}", StatusType.FORTIFIED_HEALTH, eid, eid, now,
                     self.rules.husk_duration, target.hp)
        return True

    def _heal(self, source: Any, target: Any, now: float) -> Frames:
        amount = self.rules.fountain_flat_heal + (target.max_hp - target.hp) * self.rules.fountain_missing_hp_ratio
        if hasattr(target, "heal"):
            return target.heal(amount, now, self.status)
        # Lane actors have no heal method or periodic HP snapshot. Publish the
        # same resource delta as heroes so live clients receive every pulse.
        actual = min(max(0.0, amount * self.status.get_healing_multiplier(target.eid, now)),
                     max(0.0, target.max_hp - target.hp))
        target.hp += actual
        return [(wire.OP.ENTITY_STAT, roster.build_hero_stat(
            target.eid, actual, stat_type=roster.STAT_HEALTH,
            tail=bytes.fromhex('0001000000')))] if actual else []

    def step(self, now: float, all_heroes: Dict[int, Any],
             all_entities: Optional[Dict[int, Any]] = None,
             damage_callback: Optional[DamageCallback] = None) -> Frames:
        """Resolve due item events in time/EID order; coarse steps lose no ticks."""
        entities = self._entities(all_heroes, all_entities)
        frames: Frames = []
        # Retained corpse history has no work once its last status and native
        # presentation are cleared. Preserve EID order for actual removals.
        status_targets = set(self.status.effects)
        status_targets.update(eid for eid, _key in self.status.presentation.active)
        for eid in sorted(status_targets):
            if eid in entities and not self._alive(entities[eid]):
                self.status.clear_target(eid, now=now)
        for identity, (tag, duration, expires) in sorted(list(self._cooldown_timers.items())):
            if expires <= now:
                frames.append((wire.OP.TIMER_TICK, cooldown_wire.build_item_timer(identity[0], tag, 0.0, duration)))
                del self._cooldown_timers[identity]
        atlas_due = sorted(event for event in self._atlas if event[0] <= now)
        self._atlas = [event for event in self._atlas if event[0] > now]
        for at, source_eid in atlas_due:
            source = entities.get(source_eid)
            if source is None or not self._alive(source):
                continue
            for eid, target in sorted(entities.items()):
                if (self._alive(target) and getattr(target, "team", 0) != source.team
                        and self._near(source, target, self.rules.atlas_radius)):
                    self._effect(f"atlas:{source_eid}", StatusType.ATTACK_SPEED_SLOW,
                                 source_eid, eid, at, self.rules.atlas_duration, self.rules.atlas_slow,
                                 native_kind=buff_wire.ITEM_BUFF_KINDS["atlas_pauldron_slow"])
        while True:
            due = [(effect.next_tick, key, effect) for key, effect in self._periodic.items()
                   if effect.next_tick <= now and effect.next_tick <= effect.expires_at]
            if not due:
                break
            at, key, effect = min(due, key=lambda event: (event[0], event[1]))
            target = entities.get(effect.target_eid)
            source = entities.get(effect.source_eid)
            if target is None or not self._alive(target) or source is None:
                self._periodic.pop(key, None)
                continue
            if effect.status_id is not None and not any(
                    status.effect_id == effect.status_id for status in self.status.effects.get(effect.target_eid, [])):
                self._periodic.pop(key, None)
                continue
            if effect.kind == "fountain":
                frames.extend(self._heal(source, target, at))
            elif damage_callback is not None:
                frames.extend(damage_callback(source, target, effect.amount, "crystal", at))
            else:
                raise ValueError("item DoT requires the authoritative damage callback")
            effect.next_tick += effect.interval
            if effect.next_tick > effect.expires_at:
                self._periodic.pop(key, None)
        return frames
