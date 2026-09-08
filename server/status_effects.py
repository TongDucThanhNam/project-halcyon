"""Status-effect engine and Damage-modifier priority queue (T3 Milestone 2).

Provides:
1. Generic StatusManager:
   - Tracks timed status effects: STUN, SLOW, SILENCE, ROOT, KNOCKBACK, DISARM, BARRIER.
   - Deterministic query hooks for movement (can_move, speed_multiplier, knockback displacement)
     and combat (can_attack, can_cast, barrier absorption).
2. DamageModifierQueue:
   - Authoritative combat math pipeline:
     * D = W / (1 + A / 100) for weapon vs armor
     * D = C / (1 + S / 100) for crystal vs shield
     * Armor/Shield pierce: p * raw + (1 - p) * raw / (1 + A_eff / 100)
     * True damage: ignores armor/shield
     * Flat/Crit multipliers
     * Damage reduction / mitigation
     * Barrier absorption before HP deduction
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
import math
from typing import Callable, Dict, List, Optional, Tuple

from .buff_wire import BuffLifecycle


class StatusType(Enum):
    STUN = "stun"              # cannot move, cannot attack, cannot cast
    SLOW = "slow"              # movement speed reduced by magnitude (0.0..1.0)
    SILENCE = "silence"        # cannot cast abilities
    ROOT = "root"              # cannot move; can attack and cast non-dash abilities
    KNOCKBACK = "knockback"    # forced displacement vector; interrupts motion
    DISARM = "disarm"          # cannot basic attack
    BARRIER = "barrier"        # temporary damage absorption shield pool
    CC_IMMUNITY = "cc_immunity"
    MOVE_SPEED_FLAT = "move_speed_flat"  # units / second, before slows
    MOVE_SPEED_BUFF = "move_speed_buff"  # fractional base-speed bonus
    ATTACK_SPEED_BUFF = "attack_speed_buff"  # percentage points
    ATTACK_SPEED_SLOW = "attack_speed_slow"  # fractional final-speed reduction
    WOUND = "wound"            # fractional healing reduction
    FORTIFIED_HEALTH = "fortified_health"  # absorbs half incoming damage
    PERIODIC_HEAL = "periodic_heal"  # lifecycle marker; ItemManager resolves ticks
    PERIODIC_DAMAGE = "periodic_damage"


@dataclass
class StatusEffect:
    effect_id: str
    effect_type: StatusType
    source_eid: int
    target_eid: int
    duration: float
    applied_at: float
    expires_at: float
    magnitude: float = 1.0               # slow ratio (0.3 = 30%), reduction, or barrier HP
    direction: Tuple[float, float] = (0.0, 0.0)  # unit vector (dx, dy) for knockback
    speed: float = 0.0                  # displacement speed (u/s) for knockback
    native_buff_kind: Optional[int] = None
    native_buff_key: Optional[str] = None  # one native buff may own several mechanics


class StatusManager:
    """Manages active status effects and barriers for all match entities."""

    def __init__(self, instance_allocator: Optional[Callable[[], int]] = None):
        self.effects: Dict[int, List[StatusEffect]] = {}  # target_eid -> [StatusEffect]
        self._interrupt_serial: Dict[int, int] = {}
        self._attack_interrupt_serial: Dict[int, int] = {}
        self.presentation = BuffLifecycle(instance_allocator)

    def apply_effect(self, effect: StatusEffect) -> bool:
        """Add or refresh a status, rejecting debuffs during CC immunity.

        Immunity prevents incoming debuffs; it does not cleanse an existing stun.
        Interruption serials remember short effects that expire between steps,
        so channels and attack windups still cancel after expiry or cleanse.
        """
        debuffs = (StatusType.STUN, StatusType.SLOW, StatusType.SILENCE,
                   StatusType.ROOT, StatusType.KNOCKBACK, StatusType.DISARM,
                   StatusType.ATTACK_SPEED_SLOW, StatusType.WOUND)
        if effect.effect_type in debuffs and self.has_effect(
                effect.target_eid, StatusType.CC_IMMUNITY, effect.applied_at):
            return False
        if effect.expires_at <= effect.applied_at:
            return False
        if effect.native_buff_kind is not None:
            self.apply_presentation(effect.native_buff_key or effect.effect_id,
                                    effect.source_eid, effect.target_eid, effect.native_buff_kind,
                                    effect.applied_at, effect.expires_at - effect.applied_at)
        if effect.target_eid not in self.effects:
            self.effects[effect.target_eid] = []
        previous = [e for e in self.effects[effect.target_eid] if e.effect_id == effect.effect_id]
        # Replace existing effect with same id if present.
        self.effects[effect.target_eid] = [
            e for e in self.effects[effect.target_eid] if e.effect_id != effect.effect_id
        ]
        self.effects[effect.target_eid].append(effect)
        for old in previous:
            self._remove_unlinked_presentation(old, now=effect.applied_at)
        if effect.effect_type in (StatusType.STUN, StatusType.SILENCE, StatusType.KNOCKBACK):
            eid = effect.target_eid
            self._interrupt_serial[eid] = self._interrupt_serial.get(eid, 0) + 1
        if effect.effect_type in (StatusType.STUN, StatusType.KNOCKBACK, StatusType.DISARM):
            eid = effect.target_eid
            self._attack_interrupt_serial[eid] = self._attack_interrupt_serial.get(eid, 0) + 1
        return True

    def get_interrupt_serial(self, target_eid: int) -> int:
        return self._interrupt_serial.get(target_eid, 0)

    def get_attack_interrupt_serial(self, target_eid: int) -> int:
        """Remember attack-disabling CC after expiry or cleanse between ticks."""
        return self._attack_interrupt_serial.get(target_eid, 0)

    def remove_effect(self, target_eid: int, effect_id: str, *, now: Optional[float] = None):
        """Manually cleanse or remove an effect by id."""
        if target_eid in self.effects:
            removed = [e for e in self.effects[target_eid] if e.effect_id == effect_id]
            self.effects[target_eid] = [
                e for e in self.effects[target_eid] if e.effect_id != effect_id
            ]
            for effect in removed:
                self._remove_unlinked_presentation(effect, now=now)

    def _remove_unlinked_presentation(self, effect: StatusEffect, *, now: Optional[float] = None):
        if effect.native_buff_kind is None:
            return
        key = effect.native_buff_key or effect.effect_id
        if not any(e.native_buff_kind is not None and (e.native_buff_key or e.effect_id) == key
                   for e in self.effects.get(effect.target_eid, [])):
            self.remove_presentation(effect.target_eid, key, now=now)

    def apply_presentation(self, key: str, source_eid: int, target_eid: int, kind: int,
                           now: float, duration: float) -> int:
        return self.presentation.apply(key, source_eid, target_eid, kind, now, duration)

    def remove_presentation(self, target_eid: int, key: str, *, now: Optional[float] = None):
        self.presentation.remove(target_eid, key, now=now)

    def shorten_presentation(self, target_eid: int, key: str, expires_at: float, now: float) -> bool:
        return self.presentation.shorten(target_eid, key, expires_at, now)

    def clear_target(self, target_eid: int, *, now: Optional[float] = None):
        """Death/despawn clears target statuses and cancels their native buffs."""
        self.effects.pop(target_eid, None)
        self.presentation.clear_target(target_eid, now=now)

    def drain_frames(self) -> List[Tuple[int, bytes]]:
        return self.presentation.drain_frames()

    def snapshot_frames(self, now: float) -> List[Tuple[int, bytes]]:
        return self.presentation.snapshot_frames(now)

    def clean_expired(self, now: float):
        """Prune expired status effects."""
        for eid in list(self.effects.keys()):
            self.effects[eid] = [e for e in self.effects[eid] if e.expires_at > now]
            if not self.effects[eid]:
                del self.effects[eid]
        self.presentation.expire(now)

    def has_effect(self, target_eid: int, effect_type: StatusType, now: float) -> bool:
        """Check if target has an active effect of given type."""
        active = self.effects.get(target_eid, [])
        return any(e.effect_type == effect_type and e.applied_at <= now < e.expires_at for e in active)

    def can_move(self, target_eid: int, now: float) -> bool:
        """Entity can move unless stunned, rooted, or actively knocked back."""
        active = self.effects.get(target_eid, [])
        for e in active:
            if e.applied_at <= now < e.expires_at and e.effect_type in (StatusType.STUN, StatusType.ROOT, StatusType.KNOCKBACK):
                return False
        return True

    def can_attack(self, target_eid: int, now: float) -> bool:
        """Entity can basic attack unless stunned or disarmed."""
        active = self.effects.get(target_eid, [])
        for e in active:
            if e.applied_at <= now < e.expires_at and e.effect_type in (StatusType.STUN, StatusType.DISARM, StatusType.KNOCKBACK):
                return False
        return True

    def can_cast(self, target_eid: int, now: float) -> bool:
        """Entity can cast abilities unless stunned or silenced."""
        active = self.effects.get(target_eid, [])
        for e in active:
            if e.applied_at <= now < e.expires_at and e.effect_type in (StatusType.STUN, StatusType.SILENCE, StatusType.KNOCKBACK):
                return False
        return True

    def get_speed_multiplier(self, target_eid: int, now: float) -> float:
        """Compute net move speed multiplier from active slows (highest slow dominates)."""
        active = self.effects.get(target_eid, [])
        max_slow = 0.0
        for e in active:
            if e.applied_at <= now < e.expires_at and e.effect_type == StatusType.SLOW:
                max_slow = max(max_slow, min(1.0, e.magnitude))
        return max(0.10, 1.0 - max_slow)  # minimum 10% movement speed floor

    def _magnitudes(self, target_eid: int, kind: StatusType, now: float):
        return (e.magnitude for e in self.effects.get(target_eid, [])
                if e.effect_type == kind and e.applied_at <= now < e.expires_at)

    def get_flat_speed_bonus(self, target_eid: int, now: float) -> float:
        return sum(self._magnitudes(target_eid, StatusType.MOVE_SPEED_FLAT, now))

    def get_move_speed_bonus_ratio(self, target_eid: int, now: float) -> float:
        return sum(self._magnitudes(target_eid, StatusType.MOVE_SPEED_BUFF, now))

    def get_attack_speed_bonus(self, target_eid: int, now: float) -> float:
        return sum(self._magnitudes(target_eid, StatusType.ATTACK_SPEED_BUFF, now))

    def get_attack_speed_multiplier(self, target_eid: int, now: float) -> float:
        slow = max(self._magnitudes(target_eid, StatusType.ATTACK_SPEED_SLOW, now), default=0.0)
        return max(0.0, 1.0 - slow)

    def get_healing_multiplier(self, target_eid: int, now: float) -> float:
        wound = max(self._magnitudes(target_eid, StatusType.WOUND, now), default=0.0)
        return max(0.0, 1.0 - wound)

    def get_fortified_health(self, target_eid: int, now: float) -> float:
        return sum(self._magnitudes(target_eid, StatusType.FORTIFIED_HEALTH, now))

    def get_knockback_displacement(self, target_eid: int, dt: float, now: float) -> Tuple[float, float]:
        """Compute displacement (dx, dy) from active knockbacks during slice dt."""
        active = self.effects.get(target_eid, [])
        total_dx, total_dy = 0.0, 0.0
        for e in active:
            if e.effect_type == StatusType.KNOCKBACK:
                overlap = max(0.0, min(now, e.expires_at) - max(now - dt, e.applied_at))
                step_dist = e.speed * overlap
                total_dx += e.direction[0] * step_dist
                total_dy += e.direction[1] * step_dist
        return total_dx, total_dy

    def get_barrier(self, target_eid: int, now: float) -> float:
        """Sum of all active barrier shield amounts."""
        active = self.effects.get(target_eid, [])
        return sum(self._magnitudes(target_eid, StatusType.BARRIER, now))

    def absorb_damage_with_barrier(self, target_eid: int, damage: float, now: float) -> Tuple[float, float]:
        """Absorb damage through active barrier pools.
        Returns (remaining_damage_to_hp, absorbed_amount)."""
        if damage <= 0.0:
            return 0.0, 0.0
        active = self.effects.get(target_eid, [])
        barriers = [e for e in active if e.applied_at <= now < e.expires_at and e.effect_type == StatusType.BARRIER]
        # Consume barriers ordered by expiry (earliest first)
        barriers.sort(key=lambda e: e.expires_at)
        remaining_damage = damage
        total_absorbed = 0.0

        for b in barriers:
            if remaining_damage <= 0.0:
                break
            absorbed = min(b.magnitude, remaining_damage)
            b.magnitude -= absorbed
            total_absorbed += absorbed
            remaining_damage -= absorbed

        # Fortified health is a second, distinct pool: it absorbs half the
        # damage left after ordinary barriers, until its capacity is exhausted.
        fortified = sorted((e for e in active if e.applied_at <= now < e.expires_at
                            and e.effect_type == StatusType.FORTIFIED_HEALTH),
                           key=lambda e: (e.expires_at, e.effect_id))
        fortified_budget = remaining_damage * 0.5
        for pool in fortified:
            absorbed = min(max(0.0, pool.magnitude), fortified_budget)
            pool.magnitude -= absorbed
            fortified_budget -= absorbed
            remaining_damage -= absorbed
            total_absorbed += absorbed

        # Clean depleted barriers
        for effect in list(self.effects.get(target_eid, [])):
            if effect.effect_type in (StatusType.BARRIER, StatusType.FORTIFIED_HEALTH) and effect.magnitude <= 0.0:
                self.remove_effect(target_eid, effect.effect_id, now=now)

        return remaining_damage, total_absorbed


# ---------------------------------------------------------------------------
# Damage Modifier Priority Queue
# ---------------------------------------------------------------------------


class DamageType(Enum):
    WEAPON = "weapon"
    CRYSTAL = "crystal"
    SHIELD_PIERCING_CRYSTAL = "shield_piercing_crystal"
    TRUE = "true"
    HEAL = "heal"


@dataclass
class DamageContext:
    source_eid: int
    target_eid: int
    damage_type: DamageType
    raw_amount: float
    now: float
    armor_pierce: float = 0.0          # 0.0 .. 1.0 (e.g. 0.25 = 25% pierce)
    shield_pierce: float = 0.0
    crit_multiplier: float = 1.0       # 1.0 = normal, 1.5 = crit
    armor: float = 0.0                 # defender armor
    shield: float = 0.0                # defender shield
    damage_reduction: float = 0.0      # 0.0 .. 1.0 (fortified / passive mitigation)
    barrier: float = 0.0               # available barrier


@dataclass
class DamageResult:
    final_damage: float
    absorbed_by_barrier: float
    mitigated_by_defense: float
    is_critical: bool
    breakdown: Dict[str, float] = field(default_factory=dict)


class ModifierPriority(IntEnum):
    CRIT_MULTIPLIER = 10
    DEFENSE_CALCULATION = 20
    PERCENT_REDUCTION = 30
    BARRIER_ABSORPTION = 40


class DamageModifierQueue:
    """Deterministic priority queue resolving combat damage formulas."""

    def __init__(self):
        self._modifiers: List[Tuple[ModifierPriority, Callable[[DamageContext, float], Tuple[float, dict]]]] = []
        self._install_default_pipeline()

    def _install_default_pipeline(self):
        """Install canonical Vainglory combat formulas:
        1. Crit multiplier (1.5x)
        2. Base resistance: D = W/(1+A/100) or C/(1+S/100) with pierce
        3. Percentage damage reduction
        4. Barrier absorption
        """
        self.add_modifier(ModifierPriority.CRIT_MULTIPLIER, self._step_crit)
        self.add_modifier(ModifierPriority.DEFENSE_CALCULATION, self._step_defense)
        self.add_modifier(ModifierPriority.PERCENT_REDUCTION, self._step_reduction)

    def add_modifier(self, priority: ModifierPriority,
                     fn: Callable[[DamageContext, float], Tuple[float, dict]]):
        self._modifiers.append((priority, fn))
        self._modifiers.sort(key=lambda item: item[0])

    @staticmethod
    def _step_crit(ctx: DamageContext, current_dmg: float) -> Tuple[float, dict]:
        if ctx.crit_multiplier > 1.0:
            crit_dmg = current_dmg * ctx.crit_multiplier
            return crit_dmg, {"crit_multiplier": ctx.crit_multiplier, "crit_bonus": crit_dmg - current_dmg}
        return current_dmg, {}

    @staticmethod
    def _step_defense(ctx: DamageContext, current_dmg: float) -> Tuple[float, dict]:
        if ctx.damage_type in (DamageType.TRUE, DamageType.SHIELD_PIERCING_CRYSTAL):
            return current_dmg, {"defense_mitigated": 0.0}

        if ctx.damage_type == DamageType.WEAPON:
            armor = ctx.armor
            if not math.isfinite(armor) or armor <= -100.0:
                raise ValueError("armor must be finite and greater than -100")
            pierce = max(0.0, min(1.0, ctx.armor_pierce))
            # Pierce formula: p * D + (1 - p) * D / (1 + A / 100)
            pierced_dmg = current_dmg * pierce
            resisted_pool = current_dmg * (1.0 - pierce)
            effective_armor = armor * (1.0 - pierce)
            resisted_dmg = resisted_pool / (1.0 + effective_armor / 100.0)
            final_dmg = pierced_dmg + resisted_dmg
            mitigated = current_dmg - final_dmg
            return final_dmg, {"armor": armor, "pierce": pierce, "defense_mitigated": mitigated}

        if ctx.damage_type == DamageType.CRYSTAL:
            shield = ctx.shield
            if not math.isfinite(shield) or shield <= -100.0:
                raise ValueError("shield must be finite and greater than -100")
            pierce = max(0.0, min(1.0, ctx.shield_pierce))
            pierced_dmg = current_dmg * pierce
            resisted_pool = current_dmg * (1.0 - pierce)
            effective_shield = shield * (1.0 - pierce)
            resisted_dmg = resisted_pool / (1.0 + effective_shield / 100.0)
            final_dmg = pierced_dmg + resisted_dmg
            mitigated = current_dmg - final_dmg
            return final_dmg, {"shield": shield, "pierce": pierce, "defense_mitigated": mitigated}

        return current_dmg, {}

    @staticmethod
    def _step_reduction(ctx: DamageContext, current_dmg: float) -> Tuple[float, dict]:
        if ctx.damage_reduction > 0.0:
            factor = max(0.0, min(1.0, ctx.damage_reduction))
            mitigated = current_dmg * factor
            return current_dmg - mitigated, {"reduction_pct": factor, "reduction_amount": mitigated}
        return current_dmg, {}

    def resolve(self, ctx: DamageContext, status_manager: Optional[StatusManager] = None) -> DamageResult:
        """Process damage through priority pipeline, then apply barrier absorption."""
        if ctx.damage_type == DamageType.HEAL:
            multiplier = (status_manager.get_healing_multiplier(ctx.target_eid, ctx.now)
                          if status_manager is not None else 1.0)
            healing = max(0.0, ctx.raw_amount) * multiplier
            return DamageResult(healing, 0.0, 0.0, False,
                                {"raw_amount": ctx.raw_amount, "healing_multiplier": multiplier})
        current_dmg = ctx.raw_amount
        breakdown: Dict[str, float] = {"raw_amount": current_dmg}
        total_mitigated = 0.0

        for prio, mod in self._modifiers:
            current_dmg, step_info = mod(ctx, current_dmg)
            breakdown.update(step_info)
            if "defense_mitigated" in step_info:
                total_mitigated += step_info["defense_mitigated"]
            if "reduction_amount" in step_info:
                total_mitigated += step_info["reduction_amount"]

        # Barrier absorption
        absorbed = 0.0
        if status_manager is not None:
            current_dmg, absorbed = status_manager.absorb_damage_with_barrier(
                ctx.target_eid, current_dmg, ctx.now
            )
        elif ctx.barrier > 0.0:
            absorbed = min(ctx.barrier, current_dmg)
            current_dmg -= absorbed

        breakdown["barrier_absorbed"] = absorbed
        breakdown["final_hp_damage"] = current_dmg

        return DamageResult(
            final_damage=current_dmg,
            absorbed_by_barrier=absorbed,
            mitigated_by_defense=total_mitigated,
            is_critical=ctx.crit_multiplier > 1.0,
            breakdown=breakdown,
        )
