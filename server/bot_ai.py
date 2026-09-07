"""Bot AI decision layer for Project Halcyon (T3 Milestone 3).

Provides deterministic rule-based AI for bot heroes (Alpha...Echo):
1. State Machine:
   - IDLE / SHOPPING: buys items when gold is available at base.
   - PUSH_LANE: advances down the lane polyline accompanying minion waves.
   - COMBAT: attacks nearby enemy minions, turrets, and enemy heroes; casts abilities off cooldown.
   - RETREAT: when HP < 25%, falls back to nearest friendly turret or base.
2. Deterministic & Input-Driven:
   - Decisions evaluate purely from sim tick and entity states.
   - Emits intents (1012 move, 1060 target, 1078 ability cast) directly to the authoritative sim.
"""
from __future__ import annotations

from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple

from . import abilities, economy, hero_movement, roster, wire


class BotState(Enum):
    SHOPPING = "shopping"
    PUSHING = "pushing"
    COMBAT = "combat"
    RETREAT = "retreat"


class BotAI:
    """Deterministic AI controller for one bot hero."""

    def __init__(self, eid: int, team: int):
        self.eid = eid
        self.team = team
        self.state = BotState.PUSHING
        self.waypoint_idx = 0
        self.last_decision_at = 0.0
        self.decision_interval = 0.5  # Evaluate AI state every 0.5s

        # Determine lane path anchors depending on team
        if self.team == 1:
            self.lane_anchors = [
                (-76.0, 0.88),   # Base
                (-54.0, 0.0),    # Base Turret
                (-35.0, 0.0),    # Middle Turret
                (-17.0, 0.0),    # Outer Turret
                (0.0, 0.0),      # Center lane
                (17.0, 0.0),     # Enemy Outer
                (35.0, 0.0),     # Enemy Middle
                (54.0, 0.0),     # Enemy Base
                (76.0, 0.88),    # Enemy Vain Crystal
            ]
        else:
            self.lane_anchors = [
                (76.0, 0.88),
                (54.0, 0.0),
                (35.0, 0.0),
                (17.0, 0.0),
                (0.0, 0.0),
                (-17.0, 0.0),
                (-35.0, 0.0),
                (-54.0, 0.0),
                (-76.0, 0.88),
            ]

    def step(
        self,
        now: float,
        hero: hero_movement.HeroMovement,
        all_heroes: Dict[int, hero_movement.HeroMovement],
        minions: List[Any],
        structures: Dict[int, Any],
        hero_kit: Optional[abilities.HeroKit] = None,
        econ: Optional[economy.PlayerEconomy] = None,
    ) -> List[Tuple[int, bytes]]:
        """Evaluate AI rules and return generated client intents (1012, 1060, 1078)."""
        intents: List[Tuple[int, bytes]] = []
        if not hero.is_alive:
            self.state = BotState.PUSHING
            self.waypoint_idx = 0
            return intents

        # Evaluate decision on interval
        if now - self.last_decision_at < self.decision_interval:
            return intents
        self.last_decision_at = now

        hp_ratio = hero.hp / hero.max_hp

        # 1. State Transition: Retreat when low HP
        if hp_ratio < 0.25 and self.state != BotState.RETREAT:
            self.state = BotState.RETREAT
        elif hp_ratio > 0.80 and self.state == BotState.RETREAT:
            self.state = BotState.PUSHING

        # 2. State Actions:
        if self.state == BotState.RETREAT:
            # Move towards friendly base spawn
            spawn_x = -78.18 if self.team == 1 else 78.18
            spawn_y = 0.88
            hero.clear_target()
            intents.append((wire.OP.MOVE_CAST, roster.build_move(spawn_x, spawn_y)))
            return intents

        # 3. Find enemy targets in vision / threat range
        closest_enemy_hero: Optional[hero_movement.HeroMovement] = None
        closest_hero_dist = 9.0  # Hero threat radius
        for h in all_heroes.values():
            if h.is_alive and h.team != self.team:
                d = math.hypot(h.x - hero.x, h.y - hero.y)
                if d < closest_hero_dist:
                    closest_hero_dist = d
                    closest_enemy_hero = h

        closest_enemy_minion: Optional[Any] = None
        closest_minion_dist = 6.5
        for m in minions:
            if getattr(m, "alive", False) and getattr(m, "side", None) != self.team:
                d = math.hypot(m.x - hero.x, m.y - hero.y)
                if d < closest_minion_dist:
                    closest_minion_dist = d
                    closest_enemy_minion = m

        closest_enemy_struct: Optional[Any] = None
        closest_struct_dist = 7.5
        for s in structures.values():
            if s.is_alive and s.team != self.team:
                d = math.hypot(s.x - hero.x, s.y - hero.y)
                if d < closest_struct_dist:
                    closest_struct_dist = d
                    closest_enemy_struct = s

        # 4. Target Acquisition & Combat
        target_eid: Optional[int] = None
        if closest_enemy_hero is not None:
            target_eid = closest_enemy_hero.eid
        elif closest_enemy_struct is not None:
            target_eid = closest_enemy_struct.eid
        elif closest_enemy_minion is not None:
            target_eid = closest_enemy_minion.eid

        if target_eid is not None:
            self.state = BotState.COMBAT
            intents.append((wire.OP.TARGET_ENTITY, roster.build_target_entity(target_eid)))

            # Try to cast abilities if kit is available
            if hero_kit is not None:
                # Cast B (Twirling Silver steroid) if off cooldown
                if hero_kit.can_cast(abilities.AbilitySlot.B, now):
                    intents.append((wire.OP.ABILITY_CAST, roster.build_ability_cast(int(abilities.AbilitySlot.B))))
                # Cast A (Achilles Shot) if off cooldown
                elif hero_kit.can_cast(abilities.AbilitySlot.A, now):
                    intents.append((wire.OP.ABILITY_CAST, roster.build_ability_cast(int(abilities.AbilitySlot.A))))
                # Cast Ult if available and enemy hero is targeted
                elif closest_enemy_hero and hero_kit.can_cast(abilities.AbilitySlot.ULT, now):
                    intents.append((wire.OP.ABILITY_CAST, roster.build_ability_cast(int(abilities.AbilitySlot.ULT))))
            return intents

        # 5. Pushing Lane along anchors
        self.state = BotState.PUSHING
        if self.waypoint_idx < len(self.lane_anchors):
            target_pt = self.lane_anchors[self.waypoint_idx]
            dist_to_wp = math.hypot(target_pt[0] - hero.x, target_pt[1] - hero.y)
            if dist_to_wp < 3.0:
                self.waypoint_idx = min(self.waypoint_idx + 1, len(self.lane_anchors) - 1)
                target_pt = self.lane_anchors[self.waypoint_idx]
            intents.append((wire.OP.MOVE_CAST, roster.build_move(target_pt[0], target_pt[1])))

        # 6. Purchasing items if gold available
        if econ is not None:
            if econ.gold >= 3100.0 and econ.can_buy_item(487):
                intents.append((wire.OP.SHOP_BUY, roster.build_shop_buy(hero.eid, 487)))
            elif econ.gold >= 1150.0 and econ.can_buy_item(504):
                intents.append((wire.OP.SHOP_BUY, roster.build_shop_buy(hero.eid, 504)))
            elif econ.gold >= 300.0 and econ.can_buy_item(467):
                intents.append((wire.OP.SHOP_BUY, roster.build_shop_buy(hero.eid, 467)))

        return intents
