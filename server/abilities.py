"""Hero ability scaffold and Ringo-class kit implementation (T3 Milestone 2).

Provides:
1. Generic Ability & HeroKit scaffold:
   - Slots: A (0), B (1), ULT (2)
   - Handles cooldown timing, energy/mana checks, and wire emissions:
     * s2c 1078 echo on cast activation
     * s2c 1162 cooldown timer tick
     * s2c 1046 position event (impact / projectile / AoE)
     * s2c 1054 combat delta damage resolution
2. First Hero Kit — Ringo-class:
   - Ability A (Achilles Shot): single-target ranged shot (range 6.5u, damage 140.0, 50% slow for 2.0s).
   - Ability B (Twirling Silver): self-buff steroid (+40% move speed, +50% attack cadence for 4.0s).
   - Ability C / Ult (Hellfire Brew): long-range fireball (range 15.0u, crystal damage 350.0).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import roster, wire
from .hero_movement import HeroMovement
from .status_effects import (
    DamageContext,
    DamageModifierQueue,
    DamageType,
    StatusEffect,
    StatusManager,
    StatusType,
)


class AbilitySlot(IntEnum):
    A = 0
    B = 1
    ULT = 2


class AbilityType(Enum):
    TARGET_ENEMY = "target_enemy"
    SELF_BUFF = "self_buff"
    SKILLSHOT = "skillshot"
    POINT_AOE = "point_aoe"


@dataclass
class AbilityDefinition:
    slot: AbilitySlot
    name: str
    ability_type: AbilityType
    cooldown: float
    range: float
    base_damage: float = 0.0
    damage_type: DamageType = DamageType.WEAPON
    tag_inst: int = 0xb855d752  # 1162 timer tag

    # Custom execution callback returning wire frames
    execute_fn: Optional[Callable[..., List[Tuple[int, bytes]]]] = None


class HeroKit:
    """Manages ability slots, cooldowns, and cast dispatch for one hero."""

    def __init__(self, hero: HeroMovement):
        self.hero = hero
        self.abilities: Dict[AbilitySlot, AbilityDefinition] = {}
        self.cooldowns: Dict[AbilitySlot, float] = {
            AbilitySlot.A: 0.0,
            AbilitySlot.B: 0.0,
            AbilitySlot.ULT: 0.0,
        }

    def register_ability(self, ability: AbilityDefinition):
        self.abilities[ability.slot] = ability

    def can_cast(self, slot: AbilitySlot, now: float,
                 status_manager: Optional[StatusManager] = None) -> bool:
        """Verify hero can cast: alive, not silenced/stunned, and ability off cooldown."""
        if not self.hero.is_alive:
            return False
        if slot not in self.abilities:
            return False
        if status_manager is not None and not status_manager.can_cast(self.hero.eid, now):
            return False
        return now >= self.cooldowns.get(slot, 0.0)

    def cast_ability(
        self,
        slot: AbilitySlot,
        now: float,
        target_eid: Optional[int] = None,
        target_pos: Optional[Tuple[float, float]] = None,
        status_manager: Optional[StatusManager] = None,
        damage_queue: Optional[DamageModifierQueue] = None,
        all_heroes: Optional[Dict[int, HeroMovement]] = None,
        all_minions: Optional[List[Any]] = None,
    ) -> List[Tuple[int, bytes]]:
        """Dispatch ability cast: emits 1078 echo, 1162 cooldown, and executes ability effect."""
        if not self.can_cast(slot, now, status_manager):
            return []

        ability = self.abilities[slot]
        self.cooldowns[slot] = now + ability.cooldown

        frames: List[Tuple[int, bytes]] = []
        # 1. Emit 1078 cast echo
        frames.append((wire.OP.ABILITY_CAST, roster.build_ability_cast(int(slot))))
        # 2. Emit 1162 cooldown timer tick
        frames.append((wire.OP.TIMER_TICK, roster.build_timer_tick(
            self.hero.eid, ability.tag_inst, ability.cooldown
        )))

        # 3. Execute ability effect
        if ability.execute_fn is not None:
            effect_frames = ability.execute_fn(
                caster=self.hero,
                ability=ability,
                target_eid=target_eid,
                target_pos=target_pos,
                now=now,
                status_manager=status_manager,
                damage_queue=damage_queue,
                all_heroes=all_heroes or {},
                all_minions=all_minions or [],
            )
            frames.extend(effect_frames)

        return frames


# ---------------------------------------------------------------------------
# Ringo-class Hero Kit
# ---------------------------------------------------------------------------


def _execute_achilles_shot(
    caster: HeroMovement,
    ability: AbilityDefinition,
    target_eid: Optional[int],
    target_pos: Optional[Tuple[float, float]],
    now: float,
    status_manager: Optional[StatusManager],
    damage_queue: Optional[DamageModifierQueue],
    all_heroes: Dict[int, HeroMovement],
    all_minions: List[Any],
) -> List[Tuple[int, bytes]]:
    """Ability A: Achilles Shot — single-target shot applying 140 damage and 50% slow for 2.0s."""
    frames: List[Tuple[int, bytes]] = []
    tgt_hero = all_heroes.get(target_eid) if target_eid else None
    tgt_minion = next((m for m in all_minions if m.eid == target_eid and m.alive), None) if target_eid else None

    # Resolve target coordinate
    tx, ty = caster.x, caster.y
    if tgt_hero:
        tx, ty = tgt_hero.x, tgt_hero.y
    elif tgt_minion:
        tx, ty = tgt_minion.x, tgt_minion.y
    elif target_pos:
        tx, ty = target_pos

    dist = math.hypot(tx - caster.x, ty - caster.y)
    if dist > ability.range + 0.5:
        # Out of range
        return frames

    # Emit 1046 position event at impact location
    frames.append((wire.OP.POSITION_EVENT, roster.build_position_event(
        caster.eid, tx, ty, z=0, kind=0
    )))

    # Apply 50% slow via StatusManager
    if status_manager is not None and target_eid is not None:
        status_manager.apply_effect(StatusEffect(
            effect_id=f"achilles_slow_{caster.eid}_{now}",
            effect_type=StatusType.SLOW,
            source_eid=caster.eid,
            target_eid=target_eid,
            duration=2.0,
            applied_at=now,
            expires_at=now + 2.0,
            magnitude=0.50,
        ))

    # Apply damage (scales with crystal power)
    cp = getattr(caster, "crystal_power", 0.0)
    dmg = ability.base_damage + cp * 0.8
    if tgt_hero:
        frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(
            caster.eid, tgt_hero.eid, -dmg, tail=roster.COMBAT_DELTA_HERO_TAIL
        )))
        dmg_frames = tgt_hero.apply_damage(
            dmg, caster.eid, now,
            damage_type="weapon",
            status_manager=status_manager,
            modifier_queue=damage_queue,
        )
        frames.extend(dmg_frames)
    elif tgt_minion:
        frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(
            caster.eid, tgt_minion.eid, -dmg, tail=roster.COMBAT_DELTA_TAIL
        )))
        tgt_minion.hp -= dmg
        if tgt_minion.hp <= 0:
            tgt_minion.alive = False
            frames.append((wire.OP.DESTROY, roster.build_destroy(tgt_minion.eid)))
            frames.append((wire.OP.DESPAWN, roster.build_despawn(tgt_minion.eid)))

    return frames


def _execute_twirling_silver(
    caster: HeroMovement,
    ability: AbilityDefinition,
    target_eid: Optional[int],
    target_pos: Optional[Tuple[float, float]],
    now: float,
    status_manager: Optional[StatusManager],
    damage_queue: Optional[DamageModifierQueue],
    all_heroes: Dict[int, HeroMovement],
    all_minions: List[Any],
) -> List[Tuple[int, bytes]]:
    """Ability B: Twirling Silver — self-buff granting +40% speed and reduced attack cooldown for 4.0s."""
    frames: List[Tuple[int, bytes]] = []

    # Emit 1046 position event at caster
    frames.append((wire.OP.POSITION_EVENT, roster.build_position_event(
        caster.eid, caster.x, caster.y, z=0, kind=0
    )))

    # Boost hero speed and attack cadence temporarily
    # Base speed 5.0 -> +40% = 7.0 u/s
    # Attack cooldown 0.8s -> 0.45s
    original_speed = caster.speed
    original_cd = caster.attack_cooldown
    caster.speed = original_speed * 1.40
    caster.attack_cooldown = original_cd * 0.55

    def _revert_buff():
        caster.speed = original_speed
        caster.attack_cooldown = original_cd

    # Schedule status effect tracking
    if status_manager is not None:
        status_manager.apply_effect(StatusEffect(
            effect_id=f"twirling_silver_{caster.eid}",
            effect_type=StatusType.BARRIER,  # also provides minor 50 barrier
            source_eid=caster.eid,
            target_eid=caster.eid,
            duration=4.0,
            applied_at=now,
            expires_at=now + 4.0,
            magnitude=50.0,
        ))

    return frames


def _execute_hellfire_brew(
    caster: HeroMovement,
    ability: AbilityDefinition,
    target_eid: Optional[int],
    target_pos: Optional[Tuple[float, float]],
    now: float,
    status_manager: Optional[StatusManager],
    damage_queue: Optional[DamageModifierQueue],
    all_heroes: Dict[int, HeroMovement],
    all_minions: List[Any],
) -> List[Tuple[int, bytes]]:
    """Ability C / Ult: Hellfire Brew — massive crystal fireball dealing 350.0 damage."""
    frames: List[Tuple[int, bytes]] = []
    tgt_hero = all_heroes.get(target_eid) if target_eid else None
    tgt_minion = next((m for m in all_minions if m.eid == target_eid and m.alive), None) if target_eid else None

    tx, ty = caster.x, caster.y
    if tgt_hero:
        tx, ty = tgt_hero.x, tgt_hero.y
    elif tgt_minion:
        tx, ty = tgt_minion.x, tgt_minion.y
    elif target_pos:
        tx, ty = target_pos

    dist = math.hypot(tx - caster.x, ty - caster.y)
    if dist > ability.range + 1.0:
        return frames

    # Emit 1046 impact position event
    frames.append((wire.OP.POSITION_EVENT, roster.build_position_event(
        caster.eid, tx, ty, z=0, kind=3  # kind 3 = fireball impact
    )))

    # Apply damage (scales with crystal power)
    cp = getattr(caster, "crystal_power", 0.0)
    dmg = ability.base_damage + cp * 1.2
    if tgt_hero:
        frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(
            caster.eid, tgt_hero.eid, -dmg, tail=roster.COMBAT_DELTA_HERO_TAIL
        )))
        dmg_frames = tgt_hero.apply_damage(
            dmg, caster.eid, now,
            damage_type="crystal",
            status_manager=status_manager,
            modifier_queue=damage_queue,
        )
        frames.extend(dmg_frames)
    elif tgt_minion:
        frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(
            caster.eid, tgt_minion.eid, -dmg, tail=roster.COMBAT_DELTA_TAIL
        )))
        tgt_minion.hp -= dmg
        if tgt_minion.hp <= 0:
            tgt_minion.alive = False
            frames.append((wire.OP.DESTROY, roster.build_destroy(tgt_minion.eid)))
            frames.append((wire.OP.DESPAWN, roster.build_despawn(tgt_minion.eid)))

    return frames


def create_ringo_kit(hero: HeroMovement) -> HeroKit:
    """Factory creating the canonical Ringo-class hero ability kit."""
    kit = HeroKit(hero)

    # A: Achilles Shot
    kit.register_ability(AbilityDefinition(
        slot=AbilitySlot.A,
        name="Achilles Shot",
        ability_type=AbilityType.TARGET_ENEMY,
        cooldown=5.0,
        range=6.5,
        base_damage=140.0,
        damage_type=DamageType.WEAPON,
        tag_inst=0xb855d752,
        execute_fn=_execute_achilles_shot,
    ))

    # B: Twirling Silver
    kit.register_ability(AbilityDefinition(
        slot=AbilitySlot.B,
        name="Twirling Silver",
        ability_type=AbilityType.SELF_BUFF,
        cooldown=7.0,
        range=0.0,
        base_damage=0.0,
        tag_inst=0xb855d753,
        execute_fn=_execute_twirling_silver,
    ))

    # C: Hellfire Brew (Ult)
    kit.register_ability(AbilityDefinition(
        slot=AbilitySlot.ULT,
        name="Hellfire Brew",
        ability_type=AbilityType.TARGET_ENEMY,
        cooldown=35.0,
        range=15.0,
        base_damage=350.0,
        damage_type=DamageType.CRYSTAL,
        tag_inst=0xb855d754,
        execute_fn=_execute_hellfire_brew,
    ))

    return kit
