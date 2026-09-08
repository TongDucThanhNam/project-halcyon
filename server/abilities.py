"""Authoritative ability timing, energy consumption and geometric targeting.

Rank-one anchors below come from 4.13 INST/PTCH records (mechanics matrix
section 18). Effects are original implementations. coverage_notes identify
remaining hero-specific gaps; unknown heroes never inherit another hero's kit.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, IntEnum
import math
from typing import Any, Callable, Optional

from . import ability_wire, cooldown_wire, hitboxes, roster, wire
from .hero_movement import HeroMovement
from .status_effects import DamageContext, DamageModifierQueue, DamageType, StatusEffect, StatusManager, StatusType

Frames = list[tuple[int, bytes]]
DamageCallback = Callable[[HeroMovement, Any, float, DamageType, float], Frames]

# Exact A/B/C symbols observed in these heroes' external INST metadata.
# Taka's internal Sayoc symbol has not been joined in this pass.
NATIVE_TIMER_HEROES = frozenset(("Ringo", "Catherine", "Gwen", "Celeste",
                               "Lance", "Adagio", "Koshka", "Amael", "Taka", "Skye"))

# Shared built-in types in both native KindredBuffs revisions. Own replays
# contain 1086 stun 22 and silence 32 (31 is the distinct item-silence buff).
NATIVE_STATUS_KINDS = {StatusType.STUN: 22, StatusType.SILENCE: 32}


class AbilitySlot(IntEnum):
    A = 0
    B = 1
    ULT = 2


class AbilityType(Enum):
    TARGET_ENEMY = "target_enemy"
    TARGET_ALLY = "target_ally"
    SELF_BUFF = "self_buff"
    SELF_AOE = "self_aoe"
    SKILLSHOT = "skillshot"
    POINT_AOE = "point_aoe"
    CONE = "cone"
    VECTOR_DASH = "vector_dash"
    DIRECTION_DASH = "direction_dash"


@dataclass
class AbilityDefinition:
    slot: AbilitySlot
    name: str
    ability_type: AbilityType
    cooldown: float
    range: float
    base_damage: float = 0.0
    damage_type: DamageType = DamageType.CRYSTAL
    tag_inst: Optional[int] = None
    execute_fn: Optional[Callable[..., Frames]] = None
    energy_cost: float = 0.0
    crystal_ratio: float = 0.0
    weapon_ratio: float = 0.0
    radius: float = 0.0
    cone_angle: float = 60.0
    pierce: bool = False
    stop_on_hero: bool = False
    delay: float = 0.0
    channel_duration: float = 0.0
    dash_behind: float = 1.0
    status_type: Optional[StatusType] = None
    status_duration: float = 0.0
    status_magnitude: float = 1.0
    minion_damage_multiplier: float = 1.0
    native_action: Optional[int] = None
    cast_while_disabled: bool = False
    rank_values: dict[str, tuple[float, ...]] = field(default_factory=dict)

    def __post_init__(self):
        values = (self.cooldown, self.range, self.energy_cost, self.base_damage,
                  self.delay, self.channel_duration, self.radius, self.dash_behind)
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError("ability costs, timing, damage and geometry must be finite and nonnegative")
        if not 0 < self.cone_angle <= 360:
            raise ValueError("ability cone angle must be in (0,360]")


@dataclass
class PendingCast:
    sequence: int
    ability: AbilityDefinition
    execute_at: float
    origin: tuple[float, float]
    target_eid: Optional[int]
    target_pos: tuple[float, float]
    interrupt_serial: int
    channel: bool = False


@dataclass
class ScheduledPulse:
    target: Any
    at: float
    amount: float
    damage_type: DamageType


@dataclass
class HomingProjectile:
    sequence: int
    ability: AbilityDefinition
    target_eid: int
    x: float
    y: float
    last_at: float
    speed: float
    impact_damage: float
    burn_damage: float


@dataclass
class BurningTarget:
    target_eid: int
    next_at: float
    expires_at: float
    amount: float


@dataclass
class ReflectedHit:
    at: float
    origin: tuple[float, float]
    amount: float


@dataclass
class ChargedCast:
    ability: AbilityDefinition
    started_at: float
    expires_at: float
    interrupt_serial: int


def _alive(target: Any) -> bool:
    return bool(getattr(target, "is_alive", getattr(target, "alive", False)))


def _team(target: Any) -> Any:
    return getattr(target, "team", getattr(target, "side", None))


def _effect(manager, caster, target, kind, now, duration, magnitude=1.0, key="ability",
            native_buff_kind=None):
    if manager is not None:
        if native_buff_kind is None:
            native_buff_kind = NATIVE_STATUS_KINDS.get(kind)
        return manager.apply_effect(StatusEffect(
            effect_id=f"{key}_{caster.eid}_{target.eid}", effect_type=kind,
            source_eid=caster.eid, target_eid=target.eid, duration=duration,
            applied_at=now, expires_at=now + duration, magnitude=magnitude,
            native_buff_kind=native_buff_kind))
    return False


class HeroKit:
    """One hero's cooldowns and scheduled effects, advanced by fixed sim ticks."""

    def __init__(self, hero: HeroMovement, *, name: str = "Unsupported"):
        self.hero = hero
        self.name = name
        self.abilities: dict[AbilitySlot, AbilityDefinition] = {}
        self._base_abilities: dict[AbilitySlot, AbilityDefinition] = {}
        self.ranks: dict[AbilitySlot, int] = {}
        self.cooldowns = {slot: 0.0 for slot in AbilitySlot}
        self.pending: list[PendingCast] = []
        self._sequence = 0
        self._channel: Optional[PendingCast] = None
        self._channel_status_manager: Optional[StatusManager] = None
        self._channel_order_version = 0
        self.on_cast: Optional[Callable[[HeroMovement, float], Optional[Frames]]] = None
        self.last_cast_at: Optional[float] = None
        self.last_interruption_at: Optional[float] = None
        self.coverage_notes: tuple[str, ...] = ()
        self._empowered_until = 0.0
        self._empowered_stacks = 0
        self._stars: list[tuple[float, float, float, float]] = []
        self._pulses: list[ScheduledPulse] = []
        self._charge: Optional[ChargedCast] = None
        # Spell metadata belongs to the caster kit. Lane Minion uses slots,
        # so attaching arbitrary fields to a target crashes the world loop.
        self._arcane_fire: dict[int, float] = {}
        self._projectiles: list[HomingProjectile] = []
        self._hellfire_burns: list[BurningTarget] = []
        # Travel speed has no recovered named scalar. Keep the implementation
        # policy adjustable and identified in Ringo's coverage notes.
        self.hellfire_projectile_speed = 12.0
        self._stormguard_until = 0.0
        self._stormguard_next_at = 0.0
        self._stormguard_damage = 0.0
        self._stormguard_reflect_bonus = 0.0
        self._reflections: list[ReflectedHit] = []

    @property
    def is_channeling(self) -> bool:
        return self._channel is not None

    def register_ability(self, ability: AbilityDefinition):
        if ability.native_action is None:
            ability = replace(ability, native_action=ability_wire.hero_action_variant(
                self.name, 'ABC'[int(ability.slot)]))
        if ability.tag_inst is None and self.name in NATIVE_TIMER_HEROES:
            native = f"Ability__{self.name}__{'ABC'[int(ability.slot)]}"
            ability = replace(ability, tag_inst=cooldown_wire.native_ability_tag(native))
        curves = RANK_CURVES.get(self.name, {}).get(ability.slot, {})
        if curves:
            ability = replace(ability, rank_values=curves)
        self.abilities[ability.slot] = ability
        self._base_abilities[ability.slot] = ability
        self.ranks[ability.slot] = 1

    def reset_ranks(self):
        """Runtime matches start unlearned; standalone named factories use rank one."""
        self.ranks = {slot: 0 for slot in self.abilities}
        self.abilities = dict(self._base_abilities)

    def upgrade_ability(self, slot: AbilitySlot, hero_level: int) -> bool:
        if slot not in self.abilities:
            return False
        next_rank = self.ranks.get(slot, 0) + 1
        # Basic overdrives unlock at level eight; ultimate ranks at 6/9/12.
        # Intermediate basic gates remain a rule-layer prior pending a client capture.
        levels = (6, 9, 12) if slot == AbilitySlot.ULT else (1, 2, 4, 6, 8)
        if next_rank > len(levels) or hero_level < levels[next_rank - 1]:
            return False
        base = self._base_abilities[slot]
        changes = {name: values[next_rank - 1] for name, values in base.rank_values.items()}
        self.abilities[slot] = replace(base, **changes)
        self.ranks[slot] = next_rank
        return True

    def can_cast(self, slot: AbilitySlot, now: float,
                 status_manager: Optional[StatusManager] = None) -> bool:
        if (not math.isfinite(now) or not self.hero.is_alive or slot not in self.abilities
                or self.ranks.get(slot, 0) == 0 or self.is_channeling):
            return False
        ability = self.abilities[slot]
        if status_manager is not None:
            if not ability.cast_while_disabled and not status_manager.can_cast(self.hero.eid, now):
                return False
            if ability.ability_type in (AbilityType.VECTOR_DASH, AbilityType.DIRECTION_DASH) and not status_manager.can_move(self.hero.eid, now):
                return False
        if self._charge is not None and ability.name == "Super Punch" and now < self._charge.expires_at:
            return status_manager is None or (status_manager.can_move(self.hero.eid, now)
                and status_manager.get_interrupt_serial(self.hero.eid) == self._charge.interrupt_serial)
        return (now >= self.cooldowns.get(slot, 0.0)
                and self.hero.energy >= ability.energy_cost)

    def _targets(self, all_heroes, all_minions):
        targets = {entity.eid: entity for entity in list((all_heroes or {}).values()) + list(all_minions or [])
                   if _alive(entity) and entity.eid != self.hero.eid and _team(entity) != self.hero.team}
        return dict(sorted(targets.items()))

    def _resolve_aim(self, ability, target_eid, target_pos, enemies):
        target = enemies.get(target_eid)
        if ability.ability_type in (AbilityType.TARGET_ENEMY, AbilityType.TARGET_ALLY, AbilityType.VECTOR_DASH):
            if target is None:
                return None
            point = target.x, target.y
            if math.dist((self.hero.x, self.hero.y), point) > ability.range:
                return None
        elif ability.ability_type in (AbilityType.SELF_BUFF, AbilityType.SELF_AOE):
            point = self.hero.x, self.hero.y
        else:
            if target_pos is not None:
                point = tuple(target_pos)
            elif target is not None:
                point = target.x, target.y
            else:
                return None
            if len(point) != 2 or not all(math.isfinite(v) for v in point):
                return None
            distance = math.dist((self.hero.x, self.hero.y), point)
            if ability.ability_type == AbilityType.POINT_AOE and distance > ability.range:
                return None
            if ability.ability_type in (AbilityType.SKILLSHOT, AbilityType.CONE, AbilityType.DIRECTION_DASH) and distance <= 1e-9:
                return None
        return point if all(math.isfinite(v) for v in point) else None

    def _cast_frames(self, ability, target_eid, point):
        """One native action start, never a synthetic impact marker."""
        if ability.native_action is None:
            return []
        ground = ability.ability_type in (AbilityType.POINT_AOE, AbilityType.CONE,
            AbilityType.SKILLSHOT, AbilityType.DIRECTION_DASH)
        if ground:
            return [(wire.OP.POSITION_EVENT, ability_wire.build_ground_cast(
                self.hero.eid, *point, ability.native_action))]
        return [(wire.OP.TARGET_ACQUIRE, ability_wire.build_target_cast(
            self.hero.eid, target_eid, ability.native_action))]

    def cast_ability(self, slot: AbilitySlot, now: float, target_eid: Optional[int] = None,
                     target_pos: Optional[tuple[float, float]] = None,
                     status_manager: Optional[StatusManager] = None,
                     damage_queue: Optional[DamageModifierQueue] = None,
                     all_heroes: Optional[dict[int, HeroMovement]] = None,
                     all_minions: Optional[list[Any]] = None,
                     damage_callback: Optional[DamageCallback] = None,
                     cast_callback: Optional[Callable] = None) -> Frames:
        if not self.can_cast(slot, now, status_manager):
            return []
        ability = self.abilities[slot]
        requested_target_eid = target_eid
        targets = self._targets(all_heroes, all_minions)
        if self._charge is not None and ability.name == "Super Punch" and now < self._charge.expires_at:
            charge = self._charge
            dash = replace(charge.ability, ability_type=AbilityType.DIRECTION_DASH, delay=0.0,
                           crystal_ratio=1.5 if now - charge.started_at >= 1.4 else 1.0)
            if target_pos is None and target_eid is None:
                target_pos = (self.hero.x + self.hero.facing[0] * dash.range,
                              self.hero.y + self.hero.facing[1] * dash.range)
            point = self._resolve_aim(dash, target_eid, target_pos, targets)
            if point is None:
                return []
            self._charge = None
            self._sequence += 1
            pending = PendingCast(self._sequence, dash, now, (self.hero.x, self.hero.y), target_eid, point, 0)
            return self._cast_frames(dash, target_eid, point) + self._execute(
                        pending, now, status_manager, damage_queue, all_heroes, all_minions, damage_callback)
        if ability.ability_type == AbilityType.TARGET_ALLY:
            targets = {entity.eid: entity for entity in (all_heroes or {}).values()
                       if _alive(entity) and _team(entity) == self.hero.team}
            targets[self.hero.eid] = self.hero
            target_eid = self.hero.eid if target_eid is None else target_eid
        point = self._resolve_aim(ability, target_eid, target_pos, targets)
        if point is None:
            return []
        # All validation precedes resource/cooldown mutation.
        frames = self.hero.spend_energy(ability.energy_cost)
        cooldown = ability.cooldown / (1.0 + max(0.0, getattr(self.hero, "cooldown_reduction", 0.0)))
        self.cooldowns[slot] = now + cooldown
        self.last_cast_at = now
        frames.extend(self._cast_frames(ability, requested_target_eid, point))
        if ability.tag_inst is not None:
            frames.append((wire.OP.TIMER_TICK, cooldown_wire.build_ability_timer(
                self.hero.eid, ability.tag_inst, cooldown, cooldown,
                ultimate=slot == AbilitySlot.ULT)))
        callback = cast_callback or self.on_cast
        if callback is not None:
            frames.extend(callback(self.hero, now) or [])
        if ability.name == "Lawn Mower":
            ux, uy = hitboxes.direction((self.hero.x, self.hero.y), point)
            frames.extend(self.hero.dash_to(self.hero.x - 3.0 * ux, self.hero.y - 3.0 * uy, now=now))
        if self.name == "Celeste" and slot == AbilitySlot.A:
            self._stars = [star for star in self._stars if star[3] > now]
            for star in self._stars:
                if star[2] <= now and math.dist(point, star[:2]) <= ability.radius:
                    self._stars.remove(star)
                    ability = replace(ability, base_damage=80.0 + 65.0 * (self.ranks[slot] - 1),
                                      crystal_ratio=1.75, radius=3.5, delay=0.4)
                    break
            else:
                self._stars.append((point[0], point[1], now + ability.delay, now + ability.delay + 10.0))
        self._sequence += 1
        serial = status_manager.get_interrupt_serial(self.hero.eid) if status_manager is not None else 0
        pending = PendingCast(self._sequence, ability, now + ability.channel_duration + ability.delay,
                              (self.hero.x, self.hero.y), target_eid, point, serial,
                              channel=ability.channel_duration > 0)
        if pending.channel:
            self._channel = pending
            self._channel_status_manager = status_manager
            self.hero.channeling = True
            frames.extend(self.hero.stop())
            self._channel_order_version = getattr(self.hero, "order_version", 0)
            if ability.name == "Verse of Judgement":
                _effect(status_manager, self.hero, self.hero, StatusType.FORTIFIED_HEALTH,
                        now, ability.channel_duration, 300.0 + 250.0 * (self.ranks[slot] - 1), "verse_fortified")
        if pending.execute_at > now:
            self.pending.append(pending)
        else:
            frames.extend(self._execute(pending, now, status_manager, damage_queue, all_heroes, all_minions, damage_callback))
        return frames

    def interrupt_channel(self, now: float) -> bool:
        if self._channel is None:
            return False
        self.pending = [pending for pending in self.pending if pending is not self._channel]
        if self._channel_status_manager is not None:
            self._channel_status_manager.remove_effect(self.hero.eid, f"verse_fortified_{self.hero.eid}_{self.hero.eid}")
        self._channel = None
        self._channel_status_manager = None
        self.hero.channeling = False
        self.last_interruption_at = now
        return True

    def step(self, now: float, status_manager: Optional[StatusManager] = None,
             damage_queue: Optional[DamageModifierQueue] = None,
             all_heroes: Optional[dict[int, HeroMovement]] = None,
             all_minions: Optional[list[Any]] = None,
             damage_callback: Optional[DamageCallback] = None) -> Frames:
        if not math.isfinite(now):
            raise ValueError("simulation time must be finite")
        if self._charge is not None:
            if (now >= self._charge.expires_at or not self.hero.is_alive
                    or (status_manager is not None and status_manager.get_interrupt_serial(self.hero.eid) != self._charge.interrupt_serial)):
                self._charge = None
        if self._channel is not None:
            interrupted = not self.hero.is_alive
            interrupted |= getattr(self.hero, "order_version", 0) != self._channel_order_version
            if status_manager is not None:
                interrupted |= status_manager.get_interrupt_serial(self.hero.eid) != self._channel.interrupt_serial
                interrupted |= not status_manager.can_cast(self.hero.eid, now)
            if interrupted:
                self.interrupt_channel(now)
        frames: Frames = []
        due = sorted((pending for pending in self.pending if pending.execute_at <= now + 1e-9),
                     key=lambda pending: (pending.execute_at, pending.sequence))
        self.pending = [pending for pending in self.pending if pending not in due]
        for pending in due:
            if pending.ability.ability_type == AbilityType.DIRECTION_DASH and (
                    not self.hero.is_alive or (status_manager is not None
                    and status_manager.get_interrupt_serial(self.hero.eid) != pending.interrupt_serial)):
                continue
            if pending is self._channel:
                self._channel = None
                self._channel_status_manager = None
                self.hero.channeling = False
            frames.extend(self._execute(pending, pending.execute_at, status_manager, damage_queue,
                                        all_heroes, all_minions, damage_callback))
        frames.extend(self._step_projectiles(now, status_manager, damage_queue,
                                            all_heroes, all_minions, damage_callback))
        frames.extend(self._step_stormguard(now, status_manager, damage_queue,
                                            all_heroes, all_minions, damage_callback))
        pulses = sorted((pulse for pulse in self._pulses if pulse.at <= now + 1e-9),
                        key=lambda pulse: (pulse.at, pulse.target.eid))
        self._pulses = [pulse for pulse in self._pulses if pulse not in pulses and _alive(pulse.target)]
        for pulse in pulses:
            if not _alive(pulse.target):
                continue
            if pulse.damage_type == DamageType.HEAL:
                frames.extend(pulse.target.heal(pulse.amount, pulse.at, status_manager))
            else:
                frames.extend(self._damage(pulse.target, pulse.amount, pulse.damage_type, pulse.at,
                                           status_manager, damage_queue, damage_callback))
        # Mutate in place: allied Wrath buffs share this caster-owned map.
        for eid, expires_at in list(self._arcane_fire.items()):
            if expires_at <= now:
                del self._arcane_fire[eid]
        return frames

    def _step_projectiles(self, now, status_manager, damage_queue, all_heroes, all_minions, callback):
        if not self._projectiles and not self._hellfire_burns:
            return []
        frames = []
        targets = self._targets(all_heroes, all_minions)
        remaining = []
        for shot in sorted(self._projectiles, key=lambda item: item.sequence):
            target = targets.get(shot.target_eid)
            if target is None:
                continue
            point = target.x, target.y
            distance = math.dist((shot.x, shot.y), point)
            travelled = max(0.0, now - shot.last_at) * shot.speed
            if distance > travelled + 1e-9:
                ux, uy = hitboxes.direction((shot.x, shot.y), point)
                shot.x += ux * travelled
                shot.y += uy * travelled
                shot.last_at = now
                remaining.append(shot)
                continue
            # The target's position on this sim tick defines impact and splash.
            # Once launched, the projectile survives its caster's death or CC.
            impact_at = now
            amount = shot.impact_damage
            for victim in targets.values():
                if _alive(victim) and math.dist((victim.x, victim.y), point) <= 3.5 + getattr(victim, 'collision_radius', 0.0):
                    frames.extend(self._damage(victim, amount, DamageType.SHIELD_PIERCING_CRYSTAL, impact_at,
                                               status_manager, damage_queue, callback))
            if _alive(target):
                self._hellfire_burns.append(BurningTarget(target.eid, impact_at + 1.0,
                                                          impact_at + 4.0, shot.burn_damage))
                if status_manager is not None:
                    status_manager.apply_presentation(f'hellfire_{self.hero.eid}', self.hero.eid,
                        target.eid, 382, impact_at, 4.0)
        self._projectiles = remaining
        burns = []
        for burn in self._hellfire_burns:
            target = targets.get(burn.target_eid)
            if target is None or not _alive(target):
                if status_manager is not None:
                    status_manager.remove_presentation(burn.target_eid, f'hellfire_{self.hero.eid}', now=now)
                continue
            while burn.next_at <= min(now, burn.expires_at) + 1e-9 and _alive(target):
                for victim in targets.values():
                    if _alive(victim) and math.dist((victim.x, victim.y), (target.x, target.y)) <= 3.0 + getattr(victim, 'collision_radius', 0.0):
                        frames.extend(self._damage(victim, burn.amount, DamageType.CRYSTAL, burn.next_at,
                                                   status_manager, damage_queue, callback))
                burn.next_at += 1.0
            if _alive(target) and burn.next_at <= burn.expires_at + 1e-9:
                burns.append(burn)
        self._hellfire_burns = burns
        return frames

    def modify_incoming_damage(self, raw: float, now: float, *, status_manager=None):
        """Cap one raw hit before resistance; queue its excess as a reflection.

        The world calls this before DamageContext resolution. Ordinary damage
        application still owns barriers, HP, deaths, kill credit and item procs.
        """
        if not math.isfinite(raw) or raw < 0 or not math.isfinite(now):
            raise ValueError('incoming damage and simulation time must be finite')
        if not self.hero.is_alive or now >= self._stormguard_until:
            return raw, []
        base_health = (self.hero.base_max_hp + max(0, self.hero.level - 1)
                       * getattr(self.hero, 'hp_per_level', 0.0))
        cap = base_health * 0.075
        if raw <= cap:
            return raw, []
        self._stormguard_until = max(now, self._stormguard_until - 0.2)
        self._reflections.append(ReflectedHit(now, (self.hero.x, self.hero.y),
            (raw - cap) * (1.0 + self._stormguard_reflect_bonus)))
        if status_manager is not None:
            status_manager.shorten_presentation(self.hero.eid, 'stormguard', self._stormguard_until, now)
        return cap, [(wire.OP.TARGET_ACQUIRE, ability_wire.build_target_cast(
            self.hero.eid, self.hero.eid, 4))]

    def _step_stormguard(self, now, status_manager, damage_queue, all_heroes, all_minions, callback):
        frames = []
        targets = None
        # Reflections already created by a hit survive subsequent death.
        reflections, self._reflections = self._reflections, []
        if reflections:
            targets = self._targets(all_heroes, all_minions)
        for reflection in reflections:
            nearby = sorted((target for target in targets.values()
                if math.dist((target.x, target.y), reflection.origin) <= 10.0),
                key=lambda target: (math.dist((target.x, target.y), reflection.origin), target.eid))
            for target in nearby[:3]:
                if _alive(target):
                    frames.extend(self._damage(target, reflection.amount, DamageType.CRYSTAL,
                                               reflection.at, status_manager, damage_queue, callback))
        if not self.hero.is_alive:
            self._stormguard_until = 0.0
            if status_manager is not None:
                status_manager.remove_presentation(self.hero.eid, 'stormguard', now=now)
        # Captured burn ticks start immediately, then repeat every half second.
        while self._stormguard_next_at < self._stormguard_until - 1e-9 and self._stormguard_next_at <= now + 1e-9:
            if targets is None:
                targets = self._targets(all_heroes, all_minions)
            for target in targets.values():
                if _alive(target) and math.dist((target.x, target.y), (self.hero.x, self.hero.y)) <= 3.2 + getattr(target, 'collision_radius', 0.0):
                    frames.extend(self._damage(target, self._stormguard_damage * 0.5,
                        DamageType.CRYSTAL, self._stormguard_next_at, status_manager, damage_queue, callback))
            self._stormguard_next_at += 0.5
        return frames

    def _damage(self, target, amount, damage_type, now, status_manager, damage_queue, callback):
        if callback is not None:
            return callback(self.hero, target, amount, damage_type, now)
        # Report actual HP loss after mitigation, rather than unmitigated raw damage.
        queue = damage_queue or DamageModifierQueue()
        result = queue.resolve(DamageContext(
            source_eid=self.hero.eid, target_eid=target.eid, damage_type=damage_type,
            raw_amount=amount, now=now, armor=getattr(target, "armor", 0.0),
            shield=getattr(target, "shield", 0.0),
            armor_pierce=getattr(self.hero, "armor_pierce", 0.0),
            shield_pierce=getattr(self.hero, "shield_pierce", 0.0),
            damage_reduction=getattr(target, "damage_reduction", 0.0)), status_manager)
        before = target.hp
        frames: Frames = []
        if isinstance(target, HeroMovement):
            frames.extend(target.apply_damage(result.final_damage, self.hero.eid, now, damage_type="true"))
        else:
            target.hp = max(0.0, target.hp - result.final_damage)
            if target.hp == 0:
                target.alive = False
                frames.extend([(wire.OP.DESTROY, roster.build_destroy(target.eid)),
                               (wire.OP.DESPAWN, roster.build_despawn(target.eid))])
        tail = roster.COMBAT_DELTA_HERO_TAIL if isinstance(target, HeroMovement) else roster.COMBAT_DELTA_TAIL
        return [(wire.OP.COMBAT_DELTA, roster.build_combat_delta(self.hero.eid, target.eid, target.hp - before, tail=tail))] + frames

    def _execute(self, pending, now, status_manager, damage_queue, all_heroes, all_minions, damage_callback):
        ability = pending.ability
        if ability.execute_fn is not None:
            return ability.execute_fn(caster=self.hero, ability=ability, target_eid=pending.target_eid,
                target_pos=pending.target_pos, now=now, status_manager=status_manager,
                damage_queue=damage_queue, all_heroes=all_heroes or {}, all_minions=all_minions or [])
        if ability.ability_type == AbilityType.SELF_BUFF:
            frames = self._self_buff(ability, now, status_manager)
            if ability.name == 'Stormguard':
                frames.extend(self._step_stormguard(now, status_manager, damage_queue,
                                                   all_heroes, all_minions, damage_callback))
            return frames
        if ability.ability_type == AbilityType.TARGET_ALLY:
            ally = self.hero if pending.target_eid == self.hero.eid else (all_heroes or {}).get(pending.target_eid)
            if ally is None or not _alive(ally) or _team(ally) != self.hero.team:
                return []
            return self._ally_ability(ability, ally, now, status_manager, all_heroes, all_minions)
        targets = self._targets(all_heroes, all_minions)
        if ability.name == 'Hellfire Brew':
            if pending.target_eid in targets:
                self._projectiles.append(HomingProjectile(pending.sequence, ability,
                    pending.target_eid, self.hero.x, self.hero.y, now, self.hellfire_projectile_speed,
                    ability.base_damage + self.hero.crystal_power * ability.crystal_ratio,
                    55.0 + 35.0 * (self.ranks[AbilitySlot.ULT] - 1) + self.hero.crystal_power * 0.4))
            return []
        disks = [hitboxes.TargetDisk(eid, entity.x, entity.y, getattr(entity, "collision_radius", 0.0))
                 for eid, entity in targets.items()]
        point = pending.target_pos
        frames: Frames = []
        if ability.ability_type == AbilityType.DIRECTION_DASH:
            start = self.hero.x, self.hero.y
            ux, uy = hitboxes.direction(start, point)
            end = start[0] + ability.range * ux, start[1] + ability.range * uy
            frames.extend(self.hero.dash_to(*end, now=now))
            travelled = math.dist(start, (self.hero.x, self.hero.y))
            ids = hitboxes.line_hits(start, point, travelled, ability.radius, disks, pierce=ability.pierce)
        elif ability.ability_type in (AbilityType.TARGET_ENEMY, AbilityType.VECTOR_DASH):
            target = targets.get(pending.target_eid)
            if target is None:
                return []
            point = target.x, target.y
            ids = [target.eid]
            if ability.ability_type == AbilityType.VECTOR_DASH:
                start = self.hero.x, self.hero.y
                end = hitboxes.dash_endpoint(start, point, ability.range + ability.dash_behind,
                                             behind=ability.dash_behind, facing=self.hero.facing)
                frames.extend(self.hero.dash_to(*end, now=now))
                # Terrain-clipped contact abilities cannot deal damage through a wall.
                if hitboxes.segment_distance(point, start, (self.hero.x, self.hero.y)) > max(ability.radius, 0.5):
                    ids = []
            if ability.name == "The Bull-Dozer" and ids and status_manager is not None:
                if status_manager.has_effect(target.eid, StatusType.STUN, now) or status_manager.has_effect(target.eid, StatusType.ROOT, now):
                    ability = replace(ability, base_damage=400.0 + 125.0 * (self.ranks[AbilitySlot.ULT] - 1))
                    ids = hitboxes.circle_hits(point, 3.5, disks)
        elif ability.ability_type in (AbilityType.POINT_AOE, AbilityType.SELF_AOE):
            ids = hitboxes.circle_hits(point, ability.radius, disks)
        elif ability.ability_type == AbilityType.CONE:
            ids = hitboxes.cone_hits(pending.origin, point, ability.range, ability.cone_angle, disks)
        else:
            ids = hitboxes.line_hits(pending.origin, point, ability.range, ability.radius, disks,
                                     pierce=ability.pierce or ability.stop_on_hero)
            if ability.stop_on_hero:
                first_hero = next((index for index, eid in enumerate(ids) if isinstance(targets[eid], HeroMovement)), None)
                if first_hero is not None:
                    ids = ids[:first_hero + 1]
        raw = ability.base_damage + self.hero.crystal_power * ability.crystal_ratio + self.hero.attack_damage * ability.weapon_ratio
        for eid in ids:
            target = targets[eid]
            amount = raw if isinstance(target, HeroMovement) else raw * ability.minion_damage_multiplier
            if amount:
                frames.extend(self._damage(target, amount, ability.damage_type, now, status_manager, damage_queue, damage_callback))
            if ability.status_type is not None and _alive(target):
                if not ability.stop_on_hero or isinstance(target, HeroMovement):
                    _effect(status_manager, self.hero, target, ability.status_type, now,
                            ability.status_duration, ability.status_magnitude, f"ability_{ability.slot}",
                            native_buff_kind=380 if ability.name == 'Achilles Shot' else None)
            if ability.name == "Verse of Judgement" and _alive(target):
                if self._arcane_fire.get(target.eid, 0.0) > now:
                    _effect(status_manager, self.hero, target, StatusType.STUN, now,
                            ability.status_duration, key="verse_stun")
            if ability.name == "Super Punch" and status_manager is not None and _alive(target):
                ux, uy = hitboxes.direction(pending.origin, point)
                status_manager.apply_effect(StatusEffect(
                    f"super_punch_{self.hero.eid}_{target.eid}", StatusType.KNOCKBACK,
                    self.hero.eid, target.eid, 8.0 / 24.0, now, now + 8.0 / 24.0,
                    direction=(ux, uy), speed=24.0))
        if ability.name == "Twirly Death" and ids:
            self._set_attack_buff(self.hero, now, 4.0, 2,
                                  40.0 + self.hero.crystal_power * 1.5 + self.hero.attack_damage * 0.3)
            _effect(status_manager, self.hero, self.hero, StatusType.BARRIER, now, 2.0,
                    len(ids) * (25.0 + self.hero.crystal_power * 0.3), "twirly_barrier")
        return frames

    def _set_attack_buff(self, ally, now, duration, stacks, amount, burn_bonus=0.0):
        if not hasattr(ally, "ability_attack_buffs"):
            ally.ability_attack_buffs = {}
        ally.ability_attack_buffs[self.hero.eid] = {
            "expires_at": now + duration, "stacks": stacks, "amount": amount,
            "burn_bonus": burn_bonus, "arcane_fire": self._arcane_fire}

    def _ally_ability(self, ability, ally, now, status_manager, all_heroes, all_minions):
        frames = []
        cp = self.hero.crystal_power
        rank = self.ranks[ability.slot]
        index, overdrive = rank - 1, rank == 5
        if ability.name == "Agent of Wrath":
            raw = 30.0 + 20.0 * index + 20.0 * overdrive + cp * 0.6
            if ally is self.hero:
                raw += 5.0 + 5.0 * index + 5.0 * overdrive + cp * 0.3
            self._set_attack_buff(ally, now, 6.0, 7 if overdrive else 5, raw,
                                  5.0 + 10.0 * index + 10.0 * overdrive + cp * 0.6)
        elif ability.name == "Gift of Fire":
            frames.extend(ally.heal(40.0 + 20.0 * index + 20.0 * overdrive + cp * 0.3
                                   + self.hero.max_hp * 0.09, now, status_manager))
            for tick in range(1, 7):
                self._pulses.append(ScheduledPulse(ally, now + tick * 0.5,
                                                  (10.0 + 10.0 * index + cp * 0.1) * 0.5, DamageType.HEAL))
            for target in self._targets(all_heroes, all_minions).values():
                if math.dist((target.x, target.y), (ally.x, ally.y)) > 5.0:
                    continue
                self._arcane_fire[target.eid] = now + 5.0 + 0.5 * index
                if ally is self.hero:
                    _effect(status_manager, self.hero, target, StatusType.SLOW, now, 0.9, 0.7, "gift_slow")
                # Burning damage is a separate damage record. This implementation
                # keeps its unverified coefficient explicit in coverage_notes.
                for tick in range(1, 11 + index):
                    self._pulses.append(ScheduledPulse(target, now + tick * 0.5,
                                                       (20.0 + cp * 0.2) * 0.5, DamageType.CRYSTAL))
        return frames

    def _self_buff(self, ability, now, status_manager):
        hero = self.hero
        if ability.name == "Super Punch":
            serial = status_manager.get_interrupt_serial(hero.eid) if status_manager is not None else 0
            self._charge = ChargedCast(ability, now, now + 5.0, serial)
        elif ability.name == "Twirling Silver":
            rank = self.ranks[AbilitySlot.B]
            hero.add_speed_modifier("twirling_silver", bonus=0.8 if rank == 5 else 0.5, expires_at=now + 4.0)
            _effect(status_manager, hero, hero, StatusType.ATTACK_SPEED_BUFF, now, 4.0,
                    30.0 + 10.0 * (rank - 1) + (10.0 if rank == 5 else 0.0), "twirling_silver",
                    native_buff_kind=381)
        elif ability.name == "Merciless Pursuit":
            duration = 2.0 if self.ranks[AbilitySlot.A] == 5 else 1.5
            hero.add_speed_modifier("merciless_pursuit", bonus=2.75, expires_at=now + duration)
            self._empowered_until = now + duration
            if status_manager is not None:
                status_manager.apply_presentation('merciless_pursuit_attack', hero.eid, hero.eid, 371, now, duration)
                status_manager.apply_presentation('merciless_pursuit_speed', hero.eid, hero.eid, 372, now, duration)
        elif ability.name == 'Stormguard':
            rank = self.ranks[AbilitySlot.B]
            self._stormguard_until = now + 4.0
            self._stormguard_next_at = now
            self._stormguard_damage = ability.base_damage + hero.crystal_power * ability.crystal_ratio
            self._stormguard_reflect_bonus = (rank - 1) * 0.05 + (0.05 if rank == 5 else 0.0)
            if status_manager is not None:
                status_manager.apply_presentation('stormguard', hero.eid, hero.eid, 373, now, 4.0)
        elif ability.name == "Skedaddle":
            if status_manager is not None:
                removable = {StatusType.STUN, StatusType.SLOW, StatusType.SILENCE, StatusType.ROOT,
                             StatusType.KNOCKBACK, StatusType.DISARM, StatusType.ATTACK_SPEED_SLOW}
                for effect in list(status_manager.effects.get(hero.eid, [])):
                    if effect.effect_type in removable:
                        status_manager.remove_effect(hero.eid, effect.effect_id)
            rank = self.ranks[AbilitySlot.B]
            hero.add_speed_modifier("skedaddle", bonus=2.5 + 0.3 * (rank - 1) + (0.3 if rank == 5 else 0.0),
                                    expires_at=now + 2.2)
            _effect(status_manager, hero, hero, StatusType.CC_IMMUNITY, now, 0.5, key="skedaddle")
        return []

    def basic_attack_damage_profile(self) -> Optional[tuple[float, str]]:
        """Resolve a replacement basic hit at release; impact runs normal procs."""
        if self.name != "Celeste":
            return None
        # Current native Julia's Light tooltip, celeste-perk-help.png:
        # 75-125 at levels 1-12, +75% CP, +100% WP, all crystal damage.
        # The endpoint interpolation remains a rule-layer policy until measured.
        level = max(1, min(12, self.hero.level))
        damage = (75.0 + (level - 1) * (50.0 / 11.0)
                  + 0.75 * self.hero.crystal_power + self.hero.attack_damage)
        return damage, "crystal"

    def basic_attack_variant(self, now: float) -> Optional[int]:
        """Native empowered action override, measured Catherine .4 row 532."""
        return 0 if self.name == 'Catherine' and now < self._empowered_until else None

    def on_basic_attack(self, target, now, status_manager=None, damage_queue=None, damage_callback=None) -> Frames:
        """Called once at basic attack impact by match combat."""
        if not _alive(target) or _team(target) == self.hero.team:
            return []
        frames = []
        buffs = getattr(self.hero, "ability_attack_buffs", {})
        for source in sorted(buffs):
            buff = buffs[source]
            if buff["stacks"] <= 0 or now >= buff["expires_at"]:
                continue
            buff["stacks"] -= 1
            amount = buff["amount"]
            if buff.get("arcane_fire", {}).get(target.eid, 0.0) > now:
                amount += buff["burn_bonus"]
            frames.extend(self._damage(target, amount, DamageType.CRYSTAL,
                                       now, status_manager, damage_queue, damage_callback))
        if self.name == "Catherine" and now < self._empowered_until:
            self._empowered_until = 0.0
            self.hero.remove_speed_modifier("merciless_pursuit")
            rank = self.ranks[AbilitySlot.A]
            _effect(status_manager, self.hero, target, StatusType.STUN, now,
                    0.8 if rank == 5 else 0.7, key="merciless_pursuit", native_buff_kind=22)
            if status_manager is not None:
                status_manager.remove_presentation(self.hero.eid, 'merciless_pursuit_attack', now=now)
                status_manager.remove_presentation(self.hero.eid, 'merciless_pursuit_speed', now=now)
            frames.extend(self._damage(target, 35.0 + 25.0 * (rank - 1) + self.hero.crystal_power, DamageType.CRYSTAL,
                                       now, status_manager, damage_queue, damage_callback))
        return frames


@dataclass
class SkyeBarrage:
    ability: AbilityDefinition
    direction: tuple[float, float]
    next_at: float
    expires_at: float
    interrupt_serial: int


@dataclass
class SkyeDash:
    ability: AbilityDefinition
    origin: tuple[float, float]
    destination: tuple[float, float]
    target_position: tuple[float, float]
    started_at: float
    ends_at: float
    interrupt_serial: int
    rank: int
    crystal_power: float
    fired: int = 0
    hit_targets: set[int] = field(default_factory=set)


@dataclass
class SkyeMissile:
    impact_at: float
    position: tuple[float, float]
    ability: AbilityDefinition
    rank: int
    crystal_power: float
    hit_targets: set[int]


@dataclass
class SkyeMissileField:
    ability: AbilityDefinition
    center: tuple[float, float]
    line_direction: Optional[tuple[float, float]]
    next_at: float
    expires_at: float
    crystal_power: float
    stunned: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class SkyeFieldAim:
    line_direction: Optional[tuple[float, float]]
    duration: float
    crystal_power: float


class SkyeKit(HeroKit):
    """Skye's lock-dependent kit, not three interchangeable ground spells.

    Named 4.13 records provide ranks, resources and timing. The narrow barrage
    width, C footprint and directional speed magnitudes are explicit policies
    until owned runtime measurements supply those engine-only coefficients.
    """

    LOCK_BASE_SECONDS = 3.0  # Owned rank-one B lock602 is four seconds.
    LOCK_BASE_RANGE = 8.5  # Official 1.22 base-range correction.
    STRAFE_SECONDS = 1.8  # Owned match6 circle-strafe604 half-float duration.
    STRAFE_BONUS = 2.0  # Calibration policy; not a decoded named scalar.
    BACKWARD_BONUS = 0.2  # Calibration policy for the documented reduced bonus.
    BARRAGE_SECONDS = 3.0
    BARRAGE_INTERVAL = 0.1
    DASH_SPEED = 18.0
    MISSILE_TRAVEL_SECONDS = 0.7
    C_CLUSTER_THRESHOLD = 2.0
    C_CLUSTER_RADIUS = 2.0  # Footprint policy, distinct from selection threshold.
    C_LINE_LENGTH = 12.0  # Footprint policy pending volley-actor calibration.
    C_LINE_RADIUS = 1.0
    C_TICK = 0.1  # Own hit-by-volley618 lifetime is one tenth of a second.

    def __init__(self, hero):
        super().__init__(hero, name="Skye")
        self.locked_target = None
        self.lock_expires_at = 0.0
        self._lock_status_manager = None
        self._strafe_until = 0.0
        self._barrage: Optional[SkyeBarrage] = None
        self._suri: Optional[SkyeDash] = None
        self._suri_missiles: list[SkyeMissile] = []
        self._missile_fields: list[SkyeMissileField] = []
        self._field_aims: dict[int, SkyeFieldAim] = {}
        self.volley_presentation: Optional[Callable[..., Frames]] = None
        self.additional_targets: Optional[Callable[[], Any]] = None
        hero.basic_attack_disabled = False
        hero.revealed_targets = {}

    @property
    def is_channeling(self):
        # Forward Barrage deliberately does not immobilize the hero.
        return self._suri is not None or super().is_channeling

    def _targets(self, all_heroes, all_minions):
        extra = self.additional_targets() if self.additional_targets is not None else ()
        return super()._targets(all_heroes, list(all_minions or []) + list(extra))

    @property
    def lock_duration(self):
        rank = self.ranks.get(AbilitySlot.B, 0)
        return self.LOCK_BASE_SECONDS + ((1 + .5 * (rank - 1) + (1 if rank == 5 else 0)) if rank else 0)

    @property
    def lock_range(self):
        rank = self.ranks.get(AbilitySlot.ULT, 0)
        return self.LOCK_BASE_RANGE + (2 + rank - 1 if rank else 0)

    def _valid_lock(self, now):
        target = self.locked_target
        return (self.hero.is_alive and target is not None and _alive(target)
                and _team(target) != self.hero.team and now < self.lock_expires_at
                and math.dist((self.hero.x, self.hero.y), (target.x, target.y)) <= self.lock_range)

    def _clear_lock(self, now):
        target = self.locked_target
        manager = self._lock_status_manager
        if target is not None and manager is not None:
            for eid, key in ((target.eid, "target"), (target.eid, "indicator"), (self.hero.eid, "self")):
                manager.remove_presentation(eid, f"skye_lock_{key}_{self.hero.eid}", now=now)
        self.locked_target = None
        self.lock_expires_at = 0.0
        self.hero.revealed_targets = {}

    def _refresh_strafe(self, now, manager):
        self._strafe_until = now + self.STRAFE_SECONDS
        if manager is not None:
            manager.apply_presentation(f"skye_strafe_{self.hero.eid}", self.hero.eid,
                                       self.hero.eid, 604, now, self.STRAFE_SECONDS)
        self.prepare_movement(now, manager)

    def prepare_movement(self, now, status_manager=None):
        """Called before locomotion so a new retreat order gets reduced speed."""
        bonus = self.STRAFE_BONUS
        target = self.locked_target
        if now >= self._strafe_until or not self.hero.is_alive:
            self.hero.remove_speed_modifier("skye_target_lock")
            return
        if target is not None and self.hero.waypoints:
            move = hitboxes.direction((self.hero.x, self.hero.y), self.hero.waypoints[0])
            toward = hitboxes.direction((self.hero.x, self.hero.y), (target.x, target.y))
            if move[0] * toward[0] + move[1] * toward[1] < 0:
                bonus = self.BACKWARD_BONUS
        self.hero.add_speed_modifier("skye_target_lock", bonus=bonus, expires_at=self._strafe_until)

    def on_basic_attack(self, target, now, status_manager=None, damage_queue=None, damage_callback=None):
        frames = super().on_basic_attack(target, now, status_manager, damage_queue, damage_callback)
        if not self.hero.is_alive or not _alive(target) or _team(target) == self.hero.team:
            return frames
        if math.dist((self.hero.x, self.hero.y), (target.x, target.y)) > self.lock_range:
            return frames
        if self.locked_target is not target:
            self._clear_lock(now)
        self.locked_target = target
        self.lock_expires_at = now + self.lock_duration
        self._lock_status_manager = status_manager
        self.hero.revealed_targets = {target.eid: self.lock_expires_at}
        if status_manager is not None:
            # Own match6 rows3358–3361, immediately after the ordinary hit.
            for eid, key, kind, duration in ((target.eid, "target", 602, self.lock_duration),
                                           (target.eid, "indicator", 603, -1.0),
                                           (self.hero.eid, "self", 601, -1.0)):
                status_manager.apply_presentation(f"skye_lock_{key}_{self.hero.eid}",
                                                   self.hero.eid, eid, kind, now, duration)
        self._refresh_strafe(now, status_manager)
        return frames

    def can_cast(self, slot, now, status_manager=None):
        if slot == AbilitySlot.A and self._barrage is not None:
            return math.isfinite(now) and self.hero.is_alive
        if not super().can_cast(slot, now, status_manager):
            return False
        if slot in (AbilitySlot.B, AbilitySlot.ULT) and not self._valid_lock(now):
            return False
        return (slot != AbilitySlot.B or status_manager is None
                or status_manager.can_move(self.hero.eid, now))

    def _resolve_aim(self, ability, target_eid, target_pos, enemies):
        if ability.slot == AbilitySlot.A:
            return super()._resolve_aim(ability, target_eid, target_pos, enemies)
        target = self.locked_target
        if target is None or target.eid not in enemies:
            return None
        point = tuple(target_pos) if target_pos is not None else (target.x, target.y)
        if (len(point) != 2 or not all(math.isfinite(v) for v in point)
                or math.dist(point, (target.x, target.y)) > ability.range):
            return None
        return point

    def _cancel_barrage(self):
        self._barrage = None
        self.hero.basic_attack_disabled = self._suri is not None

    def _cancel_suri(self):
        self._suri = None
        self.hero.channeling = False
        self.hero.basic_attack_disabled = self._barrage is not None

    def interrupt_channel(self, now):
        interrupted = super().interrupt_channel(now)
        if self._suri is not None:
            self._cancel_suri()
            self.last_interruption_at = now
            interrupted = True
        return interrupted

    def cancel_native_action(self, action, now, status_manager=None):
        if action != 1:
            return None
        if not math.isfinite(now) or self._barrage is None:
            return []
        self._cancel_barrage()
        return [(wire.OP.TARGET_ACQUIRE, ability_wire.build_target_cast(self.hero.eid, None, 1))]

    def cast_ability(self, slot, now, *args, **kwargs):
        if slot == AbilitySlot.A and self._barrage is not None:
            return self.cancel_native_action(1, now, kwargs.get("status_manager"))
        before = self._sequence
        frames = super().cast_ability(slot, now, *args, **kwargs)
        if self._sequence != before and slot == AbilitySlot.ULT:
            self._cancel_barrage()
            point = self.pending[-1].target_pos
            target = self.locked_target
            direction = None
            if math.dist(point, (target.x, target.y)) > self.C_CLUSTER_THRESHOLD:
                ux, uy = hitboxes.direction((target.x, target.y), point)
                direction = (uy, -ux)
            else:
                # Native chunk43:1449 cluster center exactly equals the
                # marked target's last1018 pose, not the nearby1046 aim.
                point = (target.x, target.y)
                self.pending[-1].target_pos = point
            self._field_aims[self._sequence] = SkyeFieldAim(
                direction, 1.0 + self.ranks[AbilitySlot.ULT], self.hero.crystal_power)
            if self.volley_presentation is not None:
                aim = self._field_aims[self._sequence]
                frames.extend(self.volley_presentation(self.hero, point, aim.line_direction, now,
                    activation_at=now + self.abilities[slot].delay, duration=aim.duration))
        return frames

    def _execute(self, pending, now, status_manager, damage_queue, all_heroes, all_minions, damage_callback):
        ability = pending.ability
        if ability.slot == AbilitySlot.A:
            self.hero.cancel_recall()
            self.hero.clear_target()
            self._barrage = SkyeBarrage(ability, hitboxes.direction(pending.origin, pending.target_pos),
                                        now + self.BARRAGE_INTERVAL, now + self.BARRAGE_SECONDS,
                                        status_manager.get_interrupt_serial(self.hero.eid) if status_manager else 0)
            self.hero.basic_attack_disabled = True
        elif ability.slot == AbilitySlot.B:
            self._cancel_barrage()
            self.hero.clear_target()
            origin = self.hero.x, self.hero.y
            destination = (self.hero.navigation.dash_endpoint(origin, pending.target_pos)
                           if self.hero.navigation is not None else pending.target_pos)
            self._suri = SkyeDash(ability, origin, destination,
                                  (self.locked_target.x, self.locked_target.y), now,
                                  now + math.dist(origin, destination) / self.DASH_SPEED,
                                  status_manager.get_interrupt_serial(self.hero.eid) if status_manager else 0,
                                  self.ranks[AbilitySlot.B], self.hero.crystal_power)
            self.hero.stop()
            self.hero.channeling = self.hero.basic_attack_disabled = True
            # The named reset curve is a fraction of the remaining A cooldown.
            reset = .4 + .15 * (self.ranks[AbilitySlot.B] - 1)
            self.cooldowns[AbilitySlot.A] = now + max(0.0, self.cooldowns[AbilitySlot.A] - now) * (1 - reset)
            self._launch_suri_missiles(now)
            a = self.abilities[AbilitySlot.A]
            if a.tag_inst is not None and self.ranks[AbilitySlot.A]:
                return [(wire.OP.TIMER_TICK, cooldown_wire.build_ability_timer(
                    self.hero.eid, a.tag_inst, max(0.0, self.cooldowns[AbilitySlot.A] - now),
                    a.cooldown / (1 + max(0.0, self.hero.cooldown_reduction))))]
        else:
            aim = self._field_aims.pop(pending.sequence)
            self._missile_fields.append(SkyeMissileField(ability, pending.target_pos, aim.line_direction,
                                                        now, now + aim.duration, aim.crystal_power))
        return []

    def _launch_suri_missiles(self, now):
        dash = self._suri
        while dash is not None and dash.fired < 4:
            fraction = dash.fired / 3
            launch_at = dash.started_at + (dash.ends_at - dash.started_at) * fraction
            if launch_at > now + 1e-9:
                break
            point = tuple(dash.target_position[k] + (dash.destination[k] - dash.target_position[k]) * fraction
                          for k in (0, 1))
            self._suri_missiles.append(SkyeMissile(launch_at + self.MISSILE_TRAVEL_SECONDS, point,
                dash.ability, dash.rank, dash.crystal_power, dash.hit_targets))
            dash.fired += 1

    @staticmethod
    def _objective(target):
        kind = getattr(getattr(target, "config", None), "monster_type", getattr(target, "monster_type", None))
        return hasattr(target, "is_crystal") or kind in ("GoldMiner", "Kraken")

    def step(self, now, status_manager=None, damage_queue=None, all_heroes=None, all_minions=None, damage_callback=None):
        if not math.isfinite(now):
            raise ValueError("simulation time must be finite")
        recalling = self.hero.recall_started_at is not None
        if not self._valid_lock(now) or recalling:
            self._clear_lock(now)
        serial = status_manager.get_interrupt_serial(self.hero.eid) if status_manager else 0
        if self._barrage is not None and (not self.hero.is_alive or recalling
                or serial != self._barrage.interrupt_serial):
            self._cancel_barrage()
        frames = super().step(now, status_manager, damage_queue, all_heroes, all_minions, damage_callback)
        targets = self._targets(all_heroes, all_minions)
        if self._suri is not None:
            dash = self._suri
            if (not self.hero.is_alive or recalling or serial != dash.interrupt_serial
                    or status_manager is not None and not status_manager.can_move(self.hero.eid, now)):
                self._cancel_suri()
            else:
                self._launch_suri_missiles(now)
                duration = dash.ends_at - dash.started_at
                fraction = min(1.0, (now - dash.started_at) / duration) if duration > 0 else 1.0
                frames.extend(self.hero.teleport(*(dash.origin[k] + (dash.destination[k] - dash.origin[k]) * fraction
                                                   for k in (0, 1))))
                if now + 1e-9 >= dash.ends_at:
                    self._cancel_suri()
        barrage = self._barrage
        if barrage is not None:
            while barrage.next_at <= min(now, barrage.expires_at) + 1e-9:
                at = barrage.next_at
                origin = self.hero.x, self.hero.y
                aim = tuple(origin[k] + barrage.direction[k] for k in (0, 1))
                disks = [hitboxes.TargetDisk(eid, target.x, target.y, getattr(target, "collision_radius", 0))
                         for eid, target in targets.items() if _alive(target)]
                ids = hitboxes.line_hits(origin, aim, barrage.ability.range, barrage.ability.radius, disks)
                if ids:
                    target = targets[ids[0]]
                    amount = (barrage.ability.base_damage + self.hero.crystal_power * barrage.ability.crystal_ratio
                              + self.hero.attack_damage * barrage.ability.weapon_ratio) * self.BARRAGE_INTERVAL
                    if self._valid_lock(at) and target is self.locked_target:
                        amount *= 1.1 + .002 * self.hero.crystal_power
                        self._refresh_strafe(at, status_manager)
                    if self._objective(target):
                        amount *= .5
                    frames.extend(self._damage(target, amount, DamageType.CRYSTAL, at,
                                                status_manager, damage_queue, damage_callback))
                    slow = min(.6, .003 * self.hero.attack_damage)
                    if slow and _alive(target):
                        _effect(status_manager, self.hero, target, StatusType.SLOW, at, .2,
                                slow, "skye_barrage_slow", native_buff_kind=608)
                barrage.next_at += self.BARRAGE_INTERVAL
            if now + 1e-9 >= barrage.expires_at:
                self._cancel_barrage()
            else:
                self.hero.facing = barrage.direction
        from .wave import Minion
        for missile in sorted((shot for shot in self._suri_missiles if shot.impact_at <= now + 1e-9),
                              key=lambda shot: shot.impact_at):
            self._suri_missiles.remove(missile)
            for target in targets.values():
                if not _alive(target) or math.dist(missile.position, (target.x, target.y)) > 2.2 + getattr(target, "collision_radius", 0):
                    continue
                amount = missile.ability.base_damage + missile.crystal_power
                if isinstance(target, Minion):
                    # Official 1.13 wave-clear correction, independent of hero damage.
                    amount = 90 + 30 * (missile.rank - 1) + .3 * missile.crystal_power
                if target.eid in missile.hit_targets:
                    amount *= .2
                missile.hit_targets.add(target.eid)
                frames.extend(self._damage(target, amount, DamageType.CRYSTAL, missile.impact_at,
                                            status_manager, damage_queue, damage_callback))
                if status_manager is not None and _alive(target):
                    status_manager.apply_presentation(f"skye_suri_hit_{self.hero.eid}", self.hero.eid,
                                                       target.eid, 611, missile.impact_at, 1.0)
        for area in self._missile_fields:
            while area.next_at <= now + 1e-9 and area.next_at < area.expires_at - 1e-9:
                at = area.next_at
                disks = [hitboxes.TargetDisk(eid, target.x, target.y, getattr(target, "collision_radius", 0))
                         for eid, target in targets.items() if _alive(target)]
                if area.line_direction is None:
                    ids = hitboxes.circle_hits(area.center, self.C_CLUSTER_RADIUS, disks)
                else:
                    start = tuple(area.center[k] - area.line_direction[k] * self.C_LINE_LENGTH / 2 for k in (0, 1))
                    aim = tuple(start[k] + area.line_direction[k] for k in (0, 1))
                    ids = hitboxes.line_hits(start, aim, self.C_LINE_LENGTH, self.C_LINE_RADIUS, disks, pierce=True)
                for eid in ids:
                    target = targets[eid]
                    if eid not in area.stunned:
                        _effect(status_manager, self.hero, target, StatusType.STUN, at, .5, key="skye_volley_stun")
                        area.stunned.add(eid)
                    amount = (area.ability.base_damage + .5 * area.crystal_power) * self.C_TICK
                    if self._objective(target):
                        amount *= .4  # Official post-1.14 objective-damage adjustment.
                    frames.extend(self._damage(target, amount, DamageType.CRYSTAL, at,
                                                status_manager, damage_queue, damage_callback))
                    if _alive(target):
                        _effect(status_manager, self.hero, target, StatusType.SLOW, at, self.C_TICK,
                                area.ability.status_magnitude, "skye_volley_slow", native_buff_kind=618)
                area.next_at += self.C_TICK
        self._missile_fields = [area for area in self._missile_fields if area.next_at < area.expires_at - 1e-9]
        self.prepare_movement(now, status_manager)
        return frames


def create_skye_kit(hero: HeroMovement) -> SkyeKit:
    kit = SkyeKit(hero)
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Forward Barrage", AbilityType.SKILLSHOT,
        cooldown=6, range=10, base_damage=140, energy_cost=40, crystal_ratio=1.8, weapon_ratio=1.2, radius=.3))
    # B/C modality is centered on the locked target. The 12/16 UI-header
    # bounds remain to be calibrated against actual client selection rings.
    kit.register_ability(AbilityDefinition(AbilitySlot.B, "Suri Strike", AbilityType.POINT_AOE,
        cooldown=16, range=12, base_damage=90, energy_cost=70, crystal_ratio=1, radius=2.2))
    kit.register_ability(AbilityDefinition(AbilitySlot.ULT, "Death From Above", AbilityType.POINT_AOE,
        cooldown=30, range=16, base_damage=250, energy_cost=70, crystal_ratio=.5, delay=1.3,
        status_duration=.5, status_magnitude=.55))
    kit.coverage_notes = (
        "Skye is implemented explicitly; A is mobile and cancellable, B/C require the most recent basic-hit lock.",
        "Barrage width/flight, C area dimensions and selection bounds require native runtime calibration.",
        "Directional perk speed magnitudes remain policies; lock and strafe buff lifetimes have owned wire anchors.",
        "C uses the session's separate native volley actor publisher; live field visuals still require client verification.",
    )
    return kit


def create_ringo_kit(hero: HeroMovement, *, projectile_speed: float = 12.0) -> HeroKit:
    if not math.isfinite(projectile_speed) or projectile_speed <= 0:
        raise ValueError('Hellfire projectile speed must be finite and positive')
    kit = HeroKit(hero, name="Ringo")
    kit.hellfire_projectile_speed = projectile_speed
    # INST/PTCH A CD1468 EP1532 range1596 slow1656/1724;
    # B CD2308 EP2372 duration2436 ASPD2508 MSPD2580; C CD3280 EP3344 range3408.
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Achilles Shot", AbilityType.TARGET_ENEMY,
        9.0, 8.0, 80.0, energy_cost=40.0, crystal_ratio=1.25,
        status_type=StatusType.SLOW, status_duration=1.5, status_magnitude=0.3))
    kit.register_ability(AbilityDefinition(AbilitySlot.B, "Twirling Silver", AbilityType.SELF_BUFF,
        8.0, 0.0, energy_cost=40.0))
    kit.register_ability(AbilityDefinition(AbilitySlot.ULT, "Hellfire Brew", AbilityType.TARGET_ENEMY,
        90.0, 13.0, 250.0, energy_cost=100.0, crystal_ratio=0.75,
        channel_duration=1.5))
    kit.coverage_notes = ("Hellfire homing speed12 is an adjustable simulation policy; native speed and channel1.5 timing need runtime measurement.",
                          "Damage-spec overdrive modifiers and Double Down perk pending.")
    return kit


def create_catherine_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Catherine")
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Merciless Pursuit", AbilityType.SELF_BUFF,
        16.0, 0.0, energy_cost=30.0))
    kit.register_ability(AbilityDefinition(AbilitySlot.B, 'Stormguard', AbilityType.SELF_BUFF,
        13.0, 0.0, 45.0, energy_cost=40.0, crystal_ratio=0.5))
    kit.register_ability(AbilityDefinition(AbilitySlot.ULT, "Blast Tremor", AbilityType.CONE,
        90.0, 11.0, 400.0, energy_cost=120.0, crystal_ratio=1.5, cone_angle=60.0,
        delay=0.966, status_type=StatusType.SILENCE, status_duration=1.5))
    kit.coverage_notes = ("Stormguard burns at measured0.5s intervals; DamageSpec amount-to-tick scaling needs runtime calibration.",
                          "Stormguard reflects to the nearest three enemies within native range10; target cap and projectile travel are provisional.",
                          "Captain of the Guard perk pending.",
                          "Blast Tremor cone angle requires runtime measurement.")
    return kit


def create_gwen_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Gwen")
    # Primary semantics: https://www.vainglorygame.com/heroes/gwen/
    # INST/PTCH A CD1712 EP1776 range1840 startup2032; C shot speed3980.
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Buckshot Bonanza", AbilityType.CONE,
        7.0, 10.0, 60.0, damage_type=DamageType.WEAPON, energy_cost=50.0,
        crystal_ratio=2.0, weapon_ratio=0.65, cone_angle=60.0, delay=0.3))
    kit.register_ability(AbilityDefinition(AbilitySlot.B, "Skedaddle", AbilityType.SELF_BUFF,
        19.0, 0.0, energy_cost=60.0, cast_while_disabled=True))
    kit.register_ability(AbilityDefinition(AbilitySlot.ULT, "Aces High", AbilityType.SKILLSHOT,
        90.0, 14.0, 300.0, damage_type=DamageType.WEAPON, energy_cost=100.0,
        weapon_ratio=1.0, crystal_ratio=2.5, radius=0.5, stop_on_hero=True, delay=0.6,
        status_type=StatusType.STUN, status_duration=0.9))
    kit.coverage_notes = ("Cone angle/line radius need runtime confirmation.",
                          "Aces High travel, Buckshot slow/reveal, Boomstick and passive speed pending.")
    return kit


def create_celeste_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Celeste")
    # Primary semantics https://www.vainglorygame.com/heroes/celeste/;
    # 4.13 PTCH A damage1332 delay1720 radius1792; B damage2664 delay2920 radius2988.
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Heliogenesis", AbilityType.POINT_AOE,
        2.8, 7.0, 60.0, energy_cost=30.0, crystal_ratio=0.8, radius=2.1, delay=0.6,
        minion_damage_multiplier=0.5))
    kit.register_ability(AbilityDefinition(AbilitySlot.B, "Core Collapse", AbilityType.POINT_AOE,
        14.0, 7.0, 100.0, energy_cost=100.0, crystal_ratio=0.4, radius=2.1, delay=0.8,
        status_type=StatusType.STUN, status_duration=1.0))
    kit.coverage_notes = ("Solar Storm, Julia's Light reveal and star visibility pending.",
                          "Julia's Light damage uses native tooltip endpoints/ratios; intermediate-level interpolation needs runtime measurement.",
                          "Core Collapse cast range uses Heliogenesis range pending runtime confirmation.")
    return kit


def create_lance_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Lance")
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Impale", AbilityType.SKILLSHOT,
        11.0, 6.0, 220.0, damage_type=DamageType.WEAPON, energy_cost=30.0,
        weapon_ratio=0.8, crystal_ratio=0.8, radius=0.5, pierce=True, delay=0.7,
        status_type=StatusType.ROOT, status_duration=1.0))
    kit.coverage_notes = ("Impale displacement/width/range need runtime verification; stamina and B/Ult pending.",)
    return kit


def create_taka_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Taka")
    # Internal store name Sayoc: damage1324 EP1488 range1552 cooldown1424.
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Kaiten", AbilityType.VECTOR_DASH,
        9.0, 3.5, 80.0, energy_cost=55.0, crystal_ratio=1.4, dash_behind=1.0, radius=0.5))
    kit.coverage_notes = ("Kaiten dash timing/invulnerability and behind distance need runtime verification; B/Ult/perk pending.",)
    return kit


def create_adagio_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Adagio")
    # https://www.vainglorygame.com/heroes/adagio/ for semantics. Values from
    # PTCH A CD1508 energy1572 heal1964; B CD2832 energy2896 stacks3020;
    # C damage3828 energy4000 radius4064 channel4132 fortified4204 stun4280.
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Gift of Fire", AbilityType.TARGET_ALLY,
        12.0, 7.5, energy_cost=120.0))
    kit.register_ability(AbilityDefinition(AbilitySlot.B, "Agent of Wrath", AbilityType.TARGET_ALLY,
        9.0, 7.5, energy_cost=105.0))
    kit.register_ability(AbilityDefinition(AbilitySlot.ULT, "Verse of Judgement", AbilityType.SELF_AOE,
        100.0, 9.0, 800.0, energy_cost=140.0, crystal_ratio=1.0, radius=9.0,
        channel_duration=2.0, status_duration=1.6))
    kit.coverage_notes = ("Arcane Fire DoT coefficient and burst-heal health-ratio ownership need runtime validation.",
                          "Arcane Renewal energy gain pending.")
    return kit


def create_koshka_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Koshka")
    # PTCH A damage block1716 energy1876 range1940 speed2000; B damage2516,
    # energy2776 radius2840; C damage3568 energy3752 channel/stun3876.
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Pouncy Fun", AbilityType.VECTOR_DASH,
        6.0, 8.0, 10.0, energy_cost=30.0, crystal_ratio=0.8, dash_behind=0.0, radius=0.5))
    kit.register_ability(AbilityDefinition(AbilitySlot.B, "Twirly Death", AbilityType.SELF_AOE,
        6.0, 0.0, 60.0, energy_cost=30.0, crystal_ratio=0.8, radius=3.9))
    kit.coverage_notes = ("Pounce travel, Yummy Catnip Frenzy, Bloodrush and damage-spec overdrive modifiers pending.",)
    return kit


def create_amael_kit(hero: HeroMovement) -> HeroKit:
    kit = HeroKit(hero, name="Amael")
    # Launch source: https://www.vainglorygame.com/news/update-413-amael-the-mercenary-menace/
    # PTCH A damage1208 CD1356 EP1420 range1484 charge1544; B damage2544,
    # backstep2860 forward3008; C damage3640/3740 CD3860 EP3924 range3988.
    kit.register_ability(AbilityDefinition(AbilitySlot.A, "Super Punch", AbilityType.SELF_BUFF,
        14.0, 10.0, 100.0, damage_type=DamageType.WEAPON, energy_cost=40.0,
        crystal_ratio=1.0, weapon_ratio=1.5, radius=0.75))
    kit.register_ability(AbilityDefinition(AbilitySlot.B, "Lawn Mower", AbilityType.DIRECTION_DASH,
        8.0, 9.0, 125.0, damage_type=DamageType.WEAPON, energy_cost=50.0,
        crystal_ratio=0.6, weapon_ratio=0.8, radius=0.75, pierce=True, delay=0.5))
    kit.register_ability(AbilityDefinition(AbilitySlot.ULT, "The Bull-Dozer", AbilityType.VECTOR_DASH,
        80.0, 7.0, 300.0, damage_type=DamageType.WEAPON, energy_cost=80.0,
        crystal_ratio=1.8, weapon_ratio=1.5, dash_behind=0.0,
        status_type=StatusType.KNOCKBACK, status_duration=0.5))
    kit.coverage_notes = (
        "Super Punch reactivation/charge multiplier and dash widths need client confirmation.",
        "Dash paths are terrain-safe but instant between stage boundaries; visual interpolation pending.",
        "Bull-Dozer splash radius3.5 and knockup duration0.5 are provisional; Pump It Up perk pending.")
    return kit


def create_hero_kit(hero: HeroMovement, hero_id: int = 924, *, hero_name: Optional[str] = None) -> HeroKit:
    # Catalog order does not encode selection IDs. Old 924=Ringo/245=Catherine
    # aliases were false: 924 is Viola and 245 is Koshka (header stat fingerprints).
    from .hero_balance import HERO_NAMES
    source_name = hero_name or HERO_NAMES.get(hero_id)
    name = {"Sayoc": "Taka", "Hero009": "Krul", "Hero010": "Skaarf", "Hero016": "Rona"}.get(source_name, source_name)
    factories = {"Ringo": create_ringo_kit, "Catherine": create_catherine_kit,
                 "Gwen": create_gwen_kit, "Celeste": create_celeste_kit,
                 "Lance": create_lance_kit, "Taka": create_taka_kit,
                 "Adagio": create_adagio_kit, "Koshka": create_koshka_kit,
                 "Amael": create_amael_kit, "Skye": create_skye_kit}
    if name in factories:
        kit = factories[name](hero)
        kit.reset_ranks()
        return kit
    kit = HeroKit(hero, name=name or f"Unsupported hero {hero_id}")
    kit.coverage_notes = ("Hero kit has not been implemented; no substitute hero abilities are served.",)
    return kit


def _curve(base, increment=0.0, overdrive=0.0, count=5):
    return tuple(base + increment * index + (overdrive if index == count - 1 else 0.0)
                 for index in range(count))


# Named record fields, never positional DB slot labels (those are shifted).
# Third-field overdrive modifiers are supported; damage-spec overdrive layouts
# not verified by the scalar record reader remain explicit coverage gaps.
RANK_CURVES = {
    "Skye": {
        AbilitySlot.A: {"cooldown": _curve(6, overdrive=-1), "energy_cost": _curve(40, 10),
                        "base_damage": _curve(140, 40, 40)},
        AbilitySlot.B: {"cooldown": _curve(16, -2, -2), "base_damage": _curve(90, 60)},
        AbilitySlot.ULT: {"cooldown": _curve(30, -6, count=3), "energy_cost": _curve(70, 20, count=3),
                          "base_damage": _curve(250, 50, count=3), "status_magnitude": _curve(.55, .05, count=3)},
    },
    "Amael": {
        AbilitySlot.A: {"cooldown": _curve(14, -1, -2), "energy_cost": _curve(40, 5),
                        "base_damage": _curve(100, 70), "range": _curve(10, overdrive=1)},
        AbilitySlot.B: {"cooldown": _curve(8, -0.5), "energy_cost": _curve(50, 10),
                        "base_damage": _curve(125, 35)},
        AbilitySlot.ULT: {"cooldown": _curve(80, -15, count=3), "energy_cost": _curve(80, 15, count=3),
                          "base_damage": _curve(300, 100, count=3)},
    },
    "Ringo": {
        AbilitySlot.A: {"cooldown": _curve(9, -0.5), "energy_cost": _curve(40, 5),
                        "base_damage": _curve(80, 45), "status_magnitude": _curve(0.3, 0.05),
                        "status_duration": _curve(1.5, overdrive=1.0)},
        AbilitySlot.B: {"energy_cost": _curve(40, 5)},
        AbilitySlot.ULT: {"cooldown": _curve(90, -10, count=3), "energy_cost": _curve(100, 15, count=3),
                          "base_damage": _curve(250, 150, count=3)},
    },
    "Catherine": {
        AbilitySlot.A: {"cooldown": _curve(16, -1), "energy_cost": _curve(30, 10)},
        AbilitySlot.B: {"cooldown": _curve(13, -0.5), "energy_cost": _curve(40, 10),
                        "base_damage": _curve(45, 20)},
        AbilitySlot.ULT: {"cooldown": _curve(90, -10, count=3), "energy_cost": _curve(120, 20, count=3),
                          "base_damage": _curve(400, 150, count=3), "status_duration": _curve(1.5, 0.5, count=3)},
    },
    "Gwen": {
        AbilitySlot.A: {"cooldown": _curve(7, -0.5, -1), "energy_cost": _curve(50, 5),
                        "base_damage": _curve(60, 45)},
        AbilitySlot.B: {"cooldown": _curve(19, -2, -1), "energy_cost": _curve(60, 5)},
        AbilitySlot.ULT: {"cooldown": _curve(90, -15, count=3), "energy_cost": _curve(100, -15, count=3),
                          "base_damage": _curve(300, 100, count=3), "status_duration": _curve(0.9, 0.3, count=3)},
    },
    "Celeste": {
        AbilitySlot.A: {"cooldown": _curve(2.8, -0.2, -0.2), "energy_cost": _curve(30, 5),
                        "base_damage": _curve(60, 50), "range": _curve(7, overdrive=2)},
        AbilitySlot.B: {"cooldown": _curve(14, -1, -1), "energy_cost": _curve(100, overdrive=-100),
                        "base_damage": _curve(100, 75, 75), "status_duration": _curve(1, overdrive=0.5)},
    },
    "Lance": {AbilitySlot.A: {"cooldown": _curve(11, -1, -1), "base_damage": _curve(220, 70),
                              "status_duration": _curve(1, overdrive=0.2)}},
    "Taka": {AbilitySlot.A: {"cooldown": _curve(9, overdrive=-1.5), "energy_cost": _curve(55, overdrive=-55),
                             "base_damage": _curve(80, 40)}},
    "Adagio": {
        AbilitySlot.A: {"cooldown": _curve(12, -1), "energy_cost": _curve(120, 15)},
        AbilitySlot.B: {"energy_cost": _curve(105, 25)},
        AbilitySlot.ULT: {"cooldown": _curve(100, -20, count=3), "energy_cost": _curve(140, 50, count=3),
                          "base_damage": _curve(800, 200, count=3), "status_duration": _curve(1.6, 0.7, count=3)},
    },
    "Koshka": {
        AbilitySlot.A: {"cooldown": _curve(6, overdrive=-0.5), "energy_cost": _curve(30, 5),
                        "base_damage": _curve(10, 30)},
        AbilitySlot.B: {"cooldown": _curve(6, overdrive=-1), "energy_cost": _curve(30, 10),
                        "base_damage": _curve(60, 40)},
    },
}
