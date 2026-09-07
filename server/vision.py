"""Fog of War (FoW) and Shared Team Vision System (T3 Milestone 2).

Anchored in Docs/Teardown §10 & §15 (vainglory-mechanics-matrix.md):
- Vision grammar: Buff_{Stealth, TrueSight, Revealed, UnobstructedVision}
- Standard radii: Hero 10.0u, Minion 6.0u, Turret 9.0u (with TrueSight)
- Shared Ally Vision:
  * Team 1 shares vision across all Team 1 heroes, minions, and structures.
  * Team 2 shares vision across all Team 2 heroes, minions, and structures.
- Brush Masking:
  * Units inside brush are invisible to enemy observers outside that brush,
    unless revealed by TrueSight (turret / flare) or an ally inside the same brush.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from . import jungle


HERO_VISION_RADIUS = 10.0
MINION_VISION_RADIUS = 6.0
TURRET_VISION_RADIUS = 9.0


@dataclass
class VisionSource:
    eid: int
    team: int
    x: float
    y: float
    radius: float
    has_true_sight: bool = False
    in_brush: bool = False


class VisionManager:
    """Computes authoritative shared team vision, brush masking, and stealth."""

    def __init__(self):
        self.revealed_entities: Dict[int, float] = {}  # eid -> revealed_until

    def reveal_entity(self, eid: int, duration: float, now: float):
        """Mark entity as revealed (e.g. Flare or attack in brush)."""
        self.revealed_entities[eid] = max(self.revealed_entities.get(eid, 0.0), now + duration)

    def is_entity_revealed(self, eid: int, now: float) -> bool:
        return now < self.revealed_entities.get(eid, 0.0)

    def collect_team_vision_sources(
        self,
        team: int,
        all_heroes: Dict[int, Any],
        minions: Optional[List[Any]] = None,
        structures: Optional[Dict[int, Any]] = None,
    ) -> List[VisionSource]:
        """Collect all active vision providers for a team (heroes, minions, alive turrets)."""
        sources: List[VisionSource] = []

        # 1. Heroes on this team
        for h in all_heroes.values():
            if h.team == team and h.is_alive:
                in_b = jungle.JungleManager.is_in_brush(h.x, h.y)
                sources.append(VisionSource(
                    eid=h.eid,
                    team=team,
                    x=h.x,
                    y=h.y,
                    radius=HERO_VISION_RADIUS,
                    has_true_sight=False,
                    in_brush=in_b,
                ))

        # 2. Minions on this team
        if minions:
            for m in minions:
                m_team = getattr(m, "side", None)
                if m_team == team and getattr(m, "alive", False):
                    sources.append(VisionSource(
                        eid=m.eid,
                        team=team,
                        x=m.x,
                        y=m.y,
                        radius=MINION_VISION_RADIUS,
                        has_true_sight=False,
                        in_brush=jungle.JungleManager.is_in_brush(m.x, m.y),
                    ))

        # 3. Turrets and structures on this team
        if structures:
            for s in structures.values():
                if s.team == team and s.is_alive:
                    sources.append(VisionSource(
                        eid=s.eid,
                        team=team,
                        x=s.x,
                        y=s.y,
                        radius=TURRET_VISION_RADIUS,
                        has_true_sight=True,  # Turrets grant TrueSight
                        in_brush=False,
                    ))

        return sources

    def is_visible_to_team(
        self,
        target_team: int,
        target_x: float,
        target_y: float,
        target_eid: int,
        team: int,
        sources: List[VisionSource],
        now: float,
    ) -> bool:
        """Determine if target entity is visible to observing team."""
        # 1. Allies on the same team are always visible
        if target_team == team:
            return True

        # 2. Revealed buff / Flare overrides stealth and brush
        if self.is_entity_revealed(target_eid, now):
            return True

        target_in_brush = jungle.JungleManager.is_in_brush(target_x, target_y)

        # 3. Check all ally vision sources
        for src in sources:
            dist = math.hypot(src.x - target_x, src.y - target_y)
            if dist <= src.radius:
                if not target_in_brush:
                    return True
                # Target is in brush:
                # - Visible if observer has TrueSight (turret / flare)
                if src.has_true_sight:
                    return True
                # - Visible if observer is in the SAME brush zone
                if src.in_brush and self._in_same_brush(src.x, src.y, target_x, target_y):
                    return True

        return False

    @staticmethod
    def _in_same_brush(x1: float, y1: float, x2: float, y2: float) -> bool:
        """Check if both positions lie within the same rectangular brush zone."""
        for x_min, x_max, y_min, y_max in jungle.BRUSH_ZONES:
            if (x_min <= x1 <= x_max and y_min <= y1 <= y_max) and \
               (x_min <= x2 <= x_max and y_min <= y2 <= y_max):
                return True
        return False
