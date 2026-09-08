"""Project Halcyon — Authoritative Structure and Turret Simulation (T3 Slice 1 / Milestone 2).

Implements 3v3 Halcyon Fold static structures (10 turrets + 2 Vain crystals):
  - Team 1 (Blue / Home / Left):
      Outer (3545), Middle (3546), Base (3547), Vain1 (3548), Vain2 (3549), VainCrystal (3550)
  - Team 2 (Red / Away / Right):
      Outer (3539), Middle (3540), Base (3541), Vain1 (3542), Vain2 (3543), VainCrystal (3544)

Rules & Mechanics:
  - Turret tiers & maxHP: Outer 2500, Middle 3000, Base 3500, Vain 3000, Crystal 10000.
  - Progression gate: Outer -> Middle -> Base -> Vain Turrets -> Crystal.
  - Aggro (s2c 1045):
      * Lock target: [turret_eid][target_eid][flag=1][5B 0]
      * Drop target: [turret_eid][0xffffffff][flag=0][5B 0]
      * Priority: Aggro on enemy attacking ally hero > Closest enemy minion > Closest enemy hero.
  - Attacks (s2c 1054): 1.0s attack cadence, -160.0 damage to heroes, -100.0 to minions.
  - Death: final 1054 damage followed by 1072 victim/killer attribution.
    Destroyed structures persist at zero HP (natural match-six corpus).
  - Win Condition: destruction of Vain Crystal ends the match and sets winning team.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if __package__ in (None, ""):
    import roster
    import wire
    import match_end
else:
    from . import roster
    from . import wire
    from . import match_end

if TYPE_CHECKING:
    from .hero_movement import HeroMovement


@dataclass
class Structure:
    eid: int
    name: str
    team: int  # 1 = Blue (Left), 2 = Red (Right)
    x: float
    y: float
    max_hp: float
    hp: float
    tier: int  # 1: Outer, 2: Middle, 3: Base, 4: Vain Turret, 5: Crystal
    is_crystal: bool = False
    attack_range: float = 8.5
    attack_damage: float = 160.0
    attack_cooldown: float = 1.0
    last_attack_at: float = 0.0
    current_target_eid: int | None = None
    facing: tuple[float, float] = (0.0, 1.0)
    is_alive: bool = True
    heat_shots: int = 0


# Canonical placement from 3v3 Halcyon Fold layout (vainglory-3v3-map-structure.md §11)
STRUCTURE_TEMPLATES = [
    # Team 1 (Blue / Left)
    Structure(3545, "LTurret_Outer", 1, -17.06, 1.93, 2500.0, 2500.0, tier=1, attack_range=8.5, facing=(1.0, 0.0)),
    Structure(3546, "LTurret_Middle", 1, -35.78, 1.17, 3000.0, 3000.0, tier=2, attack_range=8.5, facing=(1.0, 0.0)),
    Structure(3547, "LTurret_Base", 1, -54.00, 2.92, 3500.0, 3500.0, tier=3, attack_range=8.5, facing=(1.0, 0.0)),
    Structure(3548, "LTurret_Vain1", 1, -75.48, 11.96, 3000.0, 3000.0, tier=4, attack_range=8.5, facing=(0.7660444378852844, -0.6427876949310303)),
    Structure(3549, "LTurret_Vain2", 1, -68.59, 19.97, 3000.0, 3000.0, tier=4, attack_range=8.5, facing=(0.7660444378852844, -0.6427876949310303)),
    Structure(3550, "LVainCrystal", 1, -76.12, 19.90, 10000.0, 10000.0, tier=5, is_crystal=True, attack_range=0.0),

    # Team 2 (Red / Right)
    Structure(3539, "RTurret_Outer", 2, 17.06, 1.93, 2500.0, 2500.0, tier=1, attack_range=8.5, facing=(-1.0, 0.0)),
    Structure(3540, "RTurret_Middle", 2, 35.78, 1.17, 3000.0, 3000.0, tier=2, attack_range=8.5, facing=(-1.0, 0.0)),
    Structure(3541, "RTurret_Base", 2, 54.00, 2.92, 3500.0, 3500.0, tier=3, attack_range=8.5, facing=(-1.0, 0.0)),
    Structure(3542, "RTurret_Vain1", 2, 75.48, 11.96, 3000.0, 3000.0, tier=4, attack_range=8.5, facing=(-0.7660444378852844, -0.6427876949310303)),
    Structure(3543, "RTurret_Vain2", 2, 68.59, 19.97, 3000.0, 3000.0, tier=4, attack_range=8.5, facing=(-0.7660444378852844, -0.6427876949310303)),
    Structure(3544, "RVainCrystal", 2, 76.12, 19.90, 10000.0, 10000.0, tier=5, is_crystal=True, attack_range=0.0),
]


class StructureManager:
    """Manages full lifecycle of static structures, attacks, aggro, and win condition."""

    def __init__(self, templates: list[Structure] | None = None, *, spawn_catalog=None, actor_slots=None):
        self.structures: dict[int, Structure] = {}
        for t in (templates or STRUCTURE_TEMPLATES):
            # Clone dataclass instances
            self.structures[t.eid] = Structure(**t.__dict__)
        self.winner_team: int | None = None
        self.match_finished: bool = False
        self.spawn_catalog = spawn_catalog
        self.actor_slots = actor_slots

    def is_vulnerable(self, eid: int) -> bool:
        """Check if prior tier structures on the same team have been destroyed."""
        s = self.structures.get(eid)
        if s is None or not s.is_alive:
            return False
        if s.tier == 1:
            return True
        team_structs = [st for st in self.structures.values() if st.team == s.team]
        if s.tier == 2:
            # Requires Outer destroyed
            return not any(st.tier == 1 and st.is_alive for st in team_structs)
        if s.tier == 3:
            # Requires Middle destroyed
            return not any(st.tier in (1, 2) and st.is_alive for st in team_structs)
        if s.tier == 4:
            # Requires Base destroyed
            return not any(st.tier in (1, 2, 3) and st.is_alive for st in team_structs)
        if s.tier == 5:
            return not any(st.tier < 5 and st.is_alive for st in team_structs)
        return False

    def apply_damage(self, tgt_eid: int, damage: float, src_eid: int | None = None,
                     *, source_is_hero: bool = False, minions=None) -> list[tuple[int, bytes]]:
        """Apply damage to structure; returns wire frames (1054 + death chain if killed)."""
        s = self.structures.get(tgt_eid)
        if s is None or not s.is_alive or self.match_finished or damage <= 0:
            return []
        if not self.is_vulnerable(tgt_eid):
            # Invulnerable structures take 0 damage
            return []

        out: list[tuple[int, bytes]] = []
        if source_is_hero and not s.is_crystal and not any(
                m.alive and m.side != s.team
                and (m.x - s.x) ** 2 + (m.y - s.y) ** 2 <= 100.0
                for m in (minions or [])):
            damage *= 0.25
        actual_damage = min(s.hp, damage)
        s.hp = max(0.0, s.hp - actual_damage)
        source = src_eid if src_eid is not None else tgt_eid
        out.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(source, tgt_eid, -actual_damage)))

        if s.hp <= 0.0 and s.is_alive:
            s.is_alive = False
            # Native 1072 ends the dead turret's action. Action 0 is a shot,
            # so sending it against a null target is not a target-clear message.
            s.current_target_eid = None

            if s.is_crystal:
                self.winner_team = 1 if s.team == 2 else 2
                self.match_finished = True
                out.append((wire.OP.CRYSTAL_DESTROYED, match_end.build_crystal_destroyed()))
            out.append((wire.OP.ENTITY_DEATH, match_end.build_structure_death(s.eid, source)))

        return out

    def on_hero_damaged(self, attacker, victim):
        """Immediately protect an allied hero, including during shot cooldown."""
        out = []
        if attacker.team == victim.team or not attacker.is_alive:
            return out
        for s in self.structures.values():
            if not s.is_alive or s.is_crystal or s.team != victim.team:
                continue
            if ((attacker.x - s.x) ** 2 + (attacker.y - s.y) ** 2 > s.attack_range ** 2
                    or (victim.x - s.x) ** 2 + (victim.y - s.y) ** 2 > s.attack_range ** 2):
                continue
            if s.current_target_eid != attacker.eid:
                s.current_target_eid = attacker.eid
                s.heat_shots = 0
                out.append((wire.OP.TARGET_ACQUIRE,
                            roster.build_target_acquire(s.eid, attacker.eid, flag=1)))
        return out

    def step(self, now: float,
             heroes: dict[int, HeroMovement],
             minions: list[any] | None = None, damage_callback=None) -> list[tuple[int, bytes]]:
        """Step all active turrets: targeting, aggro acquisition (1045), attacks (1054)."""
        out: list[tuple[int, bytes]] = []
        if self.match_finished:
            return out

        minion_list = minions or []

        for s in self.structures.values():
            if not s.is_alive or s.is_crystal:
                continue

            # Check if current target is still valid
            if s.current_target_eid is not None:
                tgt_valid = False
                # Is it a hero?
                if s.current_target_eid in heroes:
                    h = heroes[s.current_target_eid]
                    if h.is_alive and h.team != s.team:
                        dist = math.hypot(h.x - s.x, h.y - s.y)
                        if dist <= s.attack_range:
                            tgt_valid = True
                # Is it a minion?
                else:
                    for m in minion_list:
                        if m.eid == s.current_target_eid and m.alive:
                            dist = math.hypot(m.x - s.x, m.y - s.y)
                            if dist <= s.attack_range:
                                tgt_valid = True
                            break

                if not tgt_valid:
                    # vgfull 6299/6302: self-targeted release then idle.
                    out.extend((wire.OP.TARGET_ACQUIRE,
                                roster.build_target_acquire(s.eid, s.eid, flag=action))
                               for action in (2, 3))
                    s.current_target_eid = None
                    s.heat_shots = 0

            # If no target, acquire new target
            if s.current_target_eid is None:
                new_tgt_eid = None
                # Priority 1: enemy minions in attack range (closest)
                best_minion_dist = s.attack_range + 1.0
                for m in minion_list:
                    # Enemy minion has different side (side 1=left/blue, 2=right/red)
                    m_team = getattr(m, "side", None)
                    if m.alive and m_team != s.team:
                        dist = math.hypot(m.x - s.x, m.y - s.y)
                        if dist <= s.attack_range and dist < best_minion_dist:
                            best_minion_dist = dist
                            new_tgt_eid = m.eid

                # Priority 2: if no minion in range, target closest enemy hero in range
                if new_tgt_eid is None:
                    best_hero_dist = s.attack_range + 1.0
                    for h in heroes.values():
                        if h.is_alive and h.team != s.team:
                            dist = math.hypot(h.x - s.x, h.y - s.y)
                            if dist <= s.attack_range and dist < best_hero_dist:
                                best_hero_dist = dist
                                new_tgt_eid = h.eid

                if new_tgt_eid is not None:
                    s.current_target_eid = new_tgt_eid
                    s.heat_shots = 0
                    out.append((wire.OP.TARGET_ACQUIRE, roster.build_target_acquire(s.eid, new_tgt_eid, flag=1)))

            # Attack current target on cooldown
            if s.current_target_eid is not None:
                if now - s.last_attack_at >= s.attack_cooldown:
                    s.last_attack_at = now
                    out.append((wire.OP.TARGET_ACQUIRE,
                                roster.build_target_acquire(s.eid, s.current_target_eid, flag=0)))
                    # Deal damage
                    if s.current_target_eid in heroes:
                        h = heroes[s.current_target_eid]
                        heat = (1.0, 1.62, 1.62 * 1.36, 1.62 * 1.36 * 1.20)
                        damage = s.attack_damage * heat[min(s.heat_shots, len(heat) - 1)]
                        s.heat_shots += 1
                        if damage_callback is not None:
                            out.extend(damage_callback(s, h, damage, "weapon", now))
                        else:
                            out.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(s.eid, h.eid, -damage)))
                            out.extend(h.apply_damage(damage, s.eid, now))
                    else:
                        for m in minion_list:
                            if m.eid == s.current_target_eid and m.alive:
                                minion_dmg = 100.0
                                if damage_callback is not None:
                                    out.extend(damage_callback(s, m, minion_dmg, "weapon", now))
                                    break
                                out.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(s.eid, m.eid, -minion_dmg)))
                                m.hp -= minion_dmg
                                if m.hp <= 0.0:
                                    m.alive = False
                                    out.append((wire.OP.DESTROY, roster.build_destroy(m.eid)))
                                    out.append((wire.OP.DESPAWN, roster.build_despawn(m.eid)))
                                break

        return out

    @staticmethod
    def archetype(structure):
        if structure.is_crystal:
            return 292 if structure.team == 1 else 293
        return {1: 371, 2: 370, 3: 369, 4: 372}[structure.tier]

    def _bind_actor_catalog(self, actor_slots, catalog):
        from .actor_slots import ActorSlots
        from .entity_spawn import load_native_actor_catalog
        if actor_slots is not None:
            self.actor_slots = actor_slots
        if self.actor_slots is None:
            self.actor_slots = ActorSlots()
        if catalog is not None:
            self.spawn_catalog = catalog
        if self.spawn_catalog is None:
            self.spawn_catalog = load_native_actor_catalog()

    def get_spawn_1010_frames(self, tick_base: int = 3539, *, actor_slots=None,
                              catalog=None) -> list[tuple[int, bytes]]:
        """Actual 126-byte creations for every persistent structure.

        `tick_base` is retained for callers but does not control any identity.
        +0 is the native archetype, +8 is the real EID, +116 is its stable slot.
        Dead structures still need an actor before the reconnect death/state
        messages. Measured authored facing and height come from their template.
        """
        self._bind_actor_catalog(actor_slots, catalog)
        return [(wire.OP.ENTITY_FULL_UPDATE, self.spawn_catalog.build(
                    self.archetype(s), s.eid, s.x, s.y, self.actor_slots.allocate(s.eid), team=s.team))
                for s in sorted(self.structures.values(), key=lambda s: s.eid)]

    def get_state_1010_frames(self, *, actor_slots=None, catalog=None) -> list[tuple[int, bytes]]:
        """122-byte HP/maxHP snapshots; VGR-proved, live reconnect experimental.

        Creation must precede these records for a newly joined renderer.
        Structures retain their actor and slot at zero HP after destruction.
        """
        self._bind_actor_catalog(actor_slots, catalog)
        return [(wire.OP.ENTITY_FULL_UPDATE, self.spawn_catalog.build(
                    self.archetype(s), s.eid, s.x, s.y, self.actor_slots.allocate(s.eid),
                    team=s.team, snapshot=True, hp=(max(0.0, s.hp), s.max_hp)))
                for s in sorted(self.structures.values(), key=lambda s: s.eid)]
