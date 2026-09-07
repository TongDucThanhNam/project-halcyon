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


class StatusType(Enum):
    STUN = "stun"              # cannot move, cannot attack, cannot cast
    SLOW = "slow"              # movement speed reduced by magnitude (0.0..1.0)
    SILENCE = "silence"        # cannot cast abilities
    ROOT = "root"              # cannot move; can attack and cast non-dash abilities
    KNOCKBACK = "knockback"    # forced displacement vector; interrupts motion
    DISARM = "disarm"          # cannot basic attack
    BARRIER = "barrier"        # temporary damage absorption shield pool


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


class StatusManager:
    """Manages active status effects and barriers for all match entities."""

    def __init__(self):
        self.effects: Dict[int, List[StatusEffect]] = {}  # target_eid -> [StatusEffect]

    def apply_effect(self, effect: StatusEffect):
        """Add or refresh a status effect on target_eid."""
        if effect.target_eid not in self.effects:
            self.effects[effect.target_eid] = []
        # Replace existing effect with same id if present
        self.effects[effect.target_eid] = [
            e for e in self.effects[effect.target_eid] if e.effect_id != effect.effect_id
        ]
        self.effects[effect.target_eid].append(effect)

    def remove_effect(self, target_eid: int, effect_id: str):
        """Manually cleanse or remove an effect by id."""
        if target_eid in self.effects:
            self.effects[target_eid] = [
                e for e in self.effects[target_eid] if e.effect_id != effect_id
            ]

    def clean_expired(self, now: float):
        """Prune expired status effects."""
        for eid in list(self.effects.keys()):
            self.effects[eid] = [e for e in self.effects[eid] if e.expires_at > now]
            if not self.effects[eid]:
                del self.effects[eid]

    def has_effect(self, target_eid: int, effect_type: StatusType, now: float) -> bool:
        """Check if target has an active effect of given type."""
        active = self.effects.get(target_eid, [])
        return any(e.effect_type == effect_type and e.expires_at > now for e in active)

    def can_move(self, target_eid: int, now: float) -> bool:
        """Entity can move unless stunned, rooted, or actively knocked back."""
        active = self.effects.get(target_eid, [])
        for e in active:
            if e.expires_at > now and e.effect_type in (StatusType.STUN, StatusType.ROOT, StatusType.KNOCKBACK):
                return False
        return True

    def can_attack(self, target_eid: int, now: float) -> bool:
        """Entity can basic attack unless stunned or disarmed."""
        active = self.effects.get(target_eid, [])
        for e in active:
            if e.expires_at > now and e.effect_type in (StatusType.STUN, StatusType.DISARM):
                return False
        return True

    def can_cast(self, target_eid: int, now: float) -> bool:
        """Entity can cast abilities unless stunned or silenced."""
        active = self.effects.get(target_eid, [])
        for e in active:
            if e.expires_at > now and e.effect_type in (StatusType.STUN, StatusType.SILENCE):
                return False
        return True

    def get_speed_multiplier(self, target_eid: int, now: float) -> float:
        """Compute net move speed multiplier from active slows (highest slow dominates)."""
        active = self.effects.get(target_eid, [])
        max_slow = 0.0
        for e in active:
            if e.expires_at > now and e.effect_type == StatusType.SLOW:
                max_slow = max(max_slow, min(1.0, e.magnitude))
        return max(0.10, 1.0 - max_slow)  # minimum 10% movement speed floor

    def get_knockback_displacement(self, target_eid: int, dt: float, now: float) -> Tuple[float, float]:
        """Compute displacement (dx, dy) from active knockbacks during slice dt."""
        active = self.effects.get(target_eid, [])
        total_dx, total_dy = 0.0, 0.0
        for e in active:
            if e.expires_at > now and e.effect_type == StatusType.KNOCKBACK:
                step_dist = e.speed * dt
                total_dx += e.direction[0] * step_dist
                total_dy += e.direction[1] * step_dist
        return total_dx, total_dy

    def get_barrier(self, target_eid: int, now: float) -> float:
        """Sum of all active barrier shield amounts."""
        active = self.effects.get(target_eid, [])
        return sum(e.magnitude for e in active if e.expires_at > now and e.effect_type == StatusType.BARRIER)

    def absorb_damage_with_barrier(self, target_eid: int, damage: float, now: float) -> Tuple[float, float]:
        """Absorb damage through active barrier pools.
        Returns (remaining_damage_to_hp, absorbed_amount)."""
        if damage <= 0.0:
            return 0.0, 0.0
        active = self.effects.get(target_eid, [])
        barriers = [e for e in active if e.expires_at > now and e.effect_type == StatusType.BARRIER]
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

        # Clean depleted barriers
        if target_eid in self.effects:
            self.effects[target_eid] = [
                e for e in self.effects[target_eid]
                if not (e.effect_type == StatusType.BARRIER and e.magnitude <= 0.0)
            ]

        return remaining_damage, total_absorbed


# ---------------------------------------------------------------------------
# Damage Modifier Priority Queue
# ---------------------------------------------------------------------------


class DamageType(Enum):
    WEAPON = "weapon"
    CRYSTAL = "crystal"
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
        if ctx.damage_type == DamageType.TRUE:
            return current_dmg, {"defense_mitigated": 0.0}

        if ctx.damage_type == DamageType.WEAPON:
            armor = max(0.0, ctx.armor)
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
            shield = max(0.0, ctx.shield)
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
