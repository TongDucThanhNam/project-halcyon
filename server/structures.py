"""Project Halcyon — Authoritative Structure and Turret Simulation (T3 Slice 1 / Milestone 2).

Implements 3v3 Halcyon Fold static structures (10 turrets + 2 Vain crystals):
  - Team 1 (Blue / Home / Left):
      Outer (3545), Middle (3546), Base (3547), Vain1 (3548), Vain2 (3549), VainCrystal (3550)
  - Team 2 (Red / Away / Right):
      Outer (3539), Middle (3540), Base (3541), Vain1 (3542), Vain2 (3543), VainCrystal (3544)

Rules & Mechanics:
  - Turret tiers & maxHP: Outer 2500, Middle 3000, Base 3500, Vain 5000, Crystal 10000.
  - Progression gate: Outer -> Middle -> Base -> Vain Turrets -> Crystal.
  - Aggro (s2c 1045):
      * Lock target: [turret_eid][target_eid][flag=1][5B 0]
      * Drop target: [turret_eid][0xffffffff][flag=0][5B 0]
      * Priority: Aggro on enemy attacking ally hero > Closest enemy minion > Closest enemy hero.
  - Attacks (s2c 1054): 1.0s attack cadence, -160.0 damage to heroes, -100.0 to minions.
  - Measured death chain (ground-truthed on 3563 in vgfull.pcap chunks 22-23):
      1068 (02 03) -> 1067 (02 01) -> 1067 (02 00) -> 1068 (02 02) ->
      1054 overkill (-10000.0) -> 1068 (00 01) -> 1072 clear -> 1073 destroy -> 1035 despawn.
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
else:
    from . import roster
    from . import wire

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


# Canonical placement from 3v3 Halcyon Fold layout (vainglory-3v3-map-structure.md §11)
STRUCTURE_TEMPLATES = [
    # Team 1 (Blue / Left)
    Structure(3545, "LTurret_Outer", 1, -17.06, 1.93, 2500.0, 2500.0, tier=1, attack_range=8.5, facing=(1.0, 0.0)),
    Structure(3546, "LTurret_Middle", 1, -35.78, 1.17, 3000.0, 3000.0, tier=2, attack_range=8.5, facing=(1.0, 0.0)),
    Structure(3547, "LTurret_Base", 1, -54.00, 2.92, 3500.0, 3500.0, tier=3, attack_range=8.5, facing=(1.0, 0.0)),
    Structure(3548, "LTurret_Vain1", 1, -75.48, 11.96, 5000.0, 5000.0, tier=4, attack_range=8.5, facing=(0.64, 0.76)),
    Structure(3549, "LTurret_Vain2", 1, -68.59, 19.97, 5000.0, 5000.0, tier=4, attack_range=8.5, facing=(0.64, 0.76)),
    Structure(3550, "LVainCrystal", 1, -76.12, 19.90, 10000.0, 10000.0, tier=5, is_crystal=True, attack_range=0.0),

    # Team 2 (Red / Right)
    Structure(3539, "RTurret_Outer", 2, 17.06, 1.93, 2500.0, 2500.0, tier=1, attack_range=8.5, facing=(-1.0, 0.0)),
    Structure(3540, "RTurret_Middle", 2, 35.78, 1.17, 3000.0, 3000.0, tier=2, attack_range=8.5, facing=(-1.0, 0.0)),
    Structure(3541, "RTurret_Base", 2, 54.00, 2.92, 3500.0, 3500.0, tier=3, attack_range=8.5, facing=(-1.0, 0.0)),
    Structure(3542, "RTurret_Vain1", 2, 75.48, 11.96, 5000.0, 5000.0, tier=4, attack_range=8.5, facing=(-0.64, 0.76)),
    Structure(3543, "RTurret_Vain2", 2, 68.59, 19.97, 5000.0, 5000.0, tier=4, attack_range=8.5, facing=(-0.64, 0.76)),
    Structure(3544, "RVainCrystal", 2, 76.12, 19.90, 10000.0, 10000.0, tier=5, is_crystal=True, attack_range=0.0),
]


class StructureManager:
    """Manages full lifecycle of static structures, attacks, aggro, and win condition."""

    def __init__(self, templates: list[Structure] | None = None):
        self.structures: dict[int, Structure] = {}
        for t in (templates or STRUCTURE_TEMPLATES):
            # Clone dataclass instances
            self.structures[t.eid] = Structure(**t.__dict__)
        self.winner_team: int | None = None
        self.match_finished: bool = False

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
            # Requires at least one Vain Turret destroyed (or both)
            vain_turrets = [st for st in team_structs if st.tier == 4]
            return any(not st.is_alive for st in vain_turrets)
        return False

    def apply_damage(self, tgt_eid: int, damage: float, src_eid: int | None = None) -> list[tuple[int, bytes]]:
        """Apply damage to structure; returns wire frames (1054 + death chain if killed)."""
        s = self.structures.get(tgt_eid)
        if s is None or not s.is_alive:
            return []
        if not self.is_vulnerable(tgt_eid):
            # Invulnerable structures take 0 damage
            return []

        out: list[tuple[int, bytes]] = []
        actual_damage = min(s.hp, damage)
        s.hp = max(0.0, s.hp - actual_damage)
        source = src_eid if src_eid is not None else tgt_eid
        out.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(source, tgt_eid, -actual_damage)))

        if s.hp <= 0.0 and s.is_alive:
            s.is_alive = False
            # Clear target if it was targeting someone
            if s.current_target_eid is not None:
                out.append((wire.OP.TARGET_ACQUIRE, roster.build_target_acquire(s.eid, 0xFFFFFFFF, flag=0)))
                s.current_target_eid = None

            # Measured death chain (vgfull.pcap 3563)
            out.append((wire.OP.ENTITY_SUBSTATE, roster.build_entity_substate(s.eid, 0x02, 0x03)))
            out.append((wire.OP.ENTITY_STATE, roster.build_hero_death_state(s.eid)))
            out.append((wire.OP.ENTITY_STATE, struct.pack(">IBB", s.eid, 0x02, 0x00) + bytes(8)))
            out.append((wire.OP.ENTITY_SUBSTATE, roster.build_entity_substate(s.eid, 0x02, 0x02)))
            out.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(s.eid, s.eid, -10000.0)))
            out.append((wire.OP.ENTITY_SUBSTATE, roster.build_entity_substate(s.eid, 0x00, 0x01)))
            out.append((wire.OP.ENTITY_CLEAR, roster.build_entity_clear(s.eid)))
            out.append((wire.OP.DESTROY, roster.build_destroy(s.eid)))
            out.append((wire.OP.DESPAWN, roster.build_despawn(s.eid)))

            if s.is_crystal:
                self.winner_team = 1 if s.team == 2 else 2
                self.match_finished = True

        return out

    def step(self, now: float,
             heroes: dict[int, HeroMovement],
             minions: list[any] | None = None) -> list[tuple[int, bytes]]:
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
                    out.append((wire.OP.TARGET_ACQUIRE, roster.build_target_acquire(s.eid, 0xFFFFFFFF, flag=0)))
                    s.current_target_eid = None

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
                    out.append((wire.OP.TARGET_ACQUIRE, roster.build_target_acquire(s.eid, new_tgt_eid, flag=1)))

            # Attack current target on cooldown
            if s.current_target_eid is not None:
                if now - s.last_attack_at >= s.attack_cooldown:
                    s.last_attack_at = now
                    # Deal damage
                    if s.current_target_eid in heroes:
                        h = heroes[s.current_target_eid]
                        out.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(s.eid, h.eid, -s.attack_damage)))
                        dmg_frames = h.apply_damage(s.attack_damage, s.eid, now)
                        out.extend(dmg_frames)
                    else:
                        for m in minion_list:
                            if m.eid == s.current_target_eid and m.alive:
                                minion_dmg = 100.0
                                out.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(s.eid, m.eid, -minion_dmg)))
                                m.hp -= minion_dmg
                                if m.hp <= 0.0:
                                    m.alive = False
                                    out.append((wire.OP.DESTROY, roster.build_destroy(m.eid)))
                                    out.append((wire.OP.DESPAWN, roster.build_despawn(m.eid)))
                                break

        return out

    def get_spawn_1010_frames(self, tick_base: int = 3539) -> list[tuple[int, bytes]]:
        """Return 1010 ENTITY_FULL_UPDATE frames for all static structures."""
        out = []
        tick = tick_base
        seq = 1
        for s in self.structures.values():
            body = roster.build_entity_full_update(
                eid=s.eid, tick=tick, x=s.x, y=s.y,
                seq=seq, facing=s.facing,
                hp=(s.hp, s.max_hp)
            )
            out.append((wire.OP.ENTITY_FULL_UPDATE, body))
            tick += 1
            seq = (seq + 1) & 0xFF
        return out
