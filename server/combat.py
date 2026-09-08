"""Fixed-time basic attacks and homing projectiles.

The attack is committed at release; cancelling recovery never retracts a
projectile. Positions are millimetres and deadlines are integer milliseconds.
Native projectile presentation is supplied by the committed-release callback.
"""
from dataclasses import dataclass
from math import isqrt
from .navigation import within_distance


def milliseconds(now):
    return round(now * 1000)


def alive(entity):
    return getattr(entity, "is_alive", getattr(entity, "alive", False))


def team(entity):
    return getattr(entity, "team", getattr(entity, "side", 0))


@dataclass
class AttackState:
    phase: str = "idle"
    target_eid: int | None = None
    release_ms: int = 0
    ready_ms: int = 0
    order_version: int = 0
    interrupt_serial: int = 0
    presentation_variant: int | None = None


@dataclass
class Projectile:
    eid: int
    source_eid: int
    target_eid: int
    x_mm: int
    y_mm: int
    damage: float
    speed_mm_s: int = 22000
    remainder: int = 0
    damage_type: str = "weapon"
    presentation_variant: int | None = None


@dataclass(frozen=True)
class AttackImpact:
    source_eid: int
    target_eid: int
    damage: float
    damage_type: str = "weapon"


class BasicAttackEngine:
    def __init__(self):
        self.states = {}
        self.projectiles = []
        self.next_projectile_eid = 1000000

    def cancel(self, eid):
        """Cancel a windup or recovery, preserving the attack cooldown."""
        state = self.states.get(eid)
        if state:
            if state.phase == "windup":
                state.ready_ms = 0
            state.phase = "idle"
            state.target_eid = None

    @staticmethod
    def durations(hero, speed_multiplier=1.0):
        bonus = getattr(hero, "bonus_attack_speed", 0.0)
        scale = max(0.05, (1.0 + bonus / 100.0) * speed_multiplier)
        cooldown = max(1, round(hero.attack_cooldown * 1000 / scale))
        windup = max(1, round(getattr(hero, "attack_windup", hero.attack_cooldown * 0.3) * 1000 / scale))
        return cooldown, min(windup, cooldown)

    def step_attacker(self, hero, target, now, status_manager=None, *, on_windup=None,
                      damage_profile=None, on_release=None):
        state = self.states.setdefault(hero.eid, AttackState())
        now_ms = milliseconds(now)
        order = getattr(hero, "order_version", 0)
        interrupt_serial = (status_manager.get_attack_interrupt_serial(hero.eid)
                            if status_manager is not None else 0)
        allowed = (alive(hero) and not getattr(hero, "channeling", False)
                   and not getattr(hero, "basic_attack_disabled", False)
                   and (status_manager is None or status_manager.can_attack(hero.eid, now)))
        valid = target is not None and alive(target) and team(target) != team(hero)
        if valid:
            valid = within_distance((hero.x, hero.y), (target.x, target.y), hero.attack_range)
        if (not allowed or not valid or hero.target_eid != state.target_eid
                or order != state.order_version
                or (state.phase == "windup" and interrupt_serial != state.interrupt_serial)):
            self.cancel(hero.eid)
        if not allowed or not valid or hero.target_eid != target.eid:
            return []
        if state.phase == "recovery" and now_ms >= state.ready_ms:
            state.phase = "idle"
        if state.phase == "idle":
            if now_ms < state.ready_ms:
                return []
            speed_multiplier = 1.0
            if status_manager is not None and hasattr(status_manager, "get_attack_speed_multiplier"):
                speed_multiplier = status_manager.get_attack_speed_multiplier(hero.eid, now)
            cooldown, windup = self.durations(hero, speed_multiplier)
            state.phase = "windup"
            state.target_eid = target.eid
            state.order_version = order
            state.interrupt_serial = interrupt_serial
            state.release_ms = now_ms + windup
            state.ready_ms = now_ms + cooldown
            hero.next_attack_at = state.ready_ms / 1000
            state.presentation_variant = (on_windup(hero, target)
                                          if on_windup is not None else None)
        if state.phase != "windup" or now_ms < state.release_ms:
            return []
        state.phase = "recovery"
        damage, damage_type = (damage_profile(hero, target) if damage_profile is not None
                               else (hero.attack_damage, "weapon"))
        if getattr(hero, "is_ranged", hero.attack_range > 3.0):
            projectile = Projectile(
                self.next_projectile_eid, hero.eid, target.eid,
                round(hero.x * 1000), round(hero.y * 1000), damage,
                round(getattr(hero, "projectile_speed", 22.0) * 1000),
                damage_type=damage_type, presentation_variant=state.presentation_variant)
            self.projectiles.append(projectile)
            self.next_projectile_eid += 1
            if on_release is not None:
                on_release(hero, target, projectile)
            return []
        return [AttackImpact(hero.eid, target.eid, damage, damage_type)]

    def step_projectiles(self, dt, entities):
        impacts = []
        surviving = []
        dt_ms = milliseconds(dt)
        for projectile in self.projectiles:
            target = entities.get(projectile.target_eid)
            if target is None or not alive(target):
                continue
            dx = round(target.x * 1000) - projectile.x_mm
            dy = round(target.y * 1000) - projectile.y_mm
            distance = isqrt(dx * dx + dy * dy)
            travel, projectile.remainder = divmod(projectile.speed_mm_s * dt_ms + projectile.remainder, 1000)
            if distance <= travel:
                impacts.append(AttackImpact(projectile.source_eid, target.eid, projectile.damage,
                                            projectile.damage_type))
            else:
                projectile.x_mm += dx * travel // distance
                projectile.y_mm += dy * travel // distance
                surviving.append(projectile)
        self.projectiles = surviving
        return impacts
