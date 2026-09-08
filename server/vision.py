"""Measured 1067 visibility banks with an explicit minimal team-vision policy.

Native viewer indices 1/2 correspond to the two playing teams. Ordinary
visible/hidden values are (1, 1, 0)/(1, 0, 0); owner-team bootstrap uses
(1, 15, 0). The 12-unit radius is policy, not a recovered native coefficient.
Brush, wall occlusion, stealth and true-sight are intentionally unmodelled.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
import struct
from typing import Any, Dict, List, Optional

from . import combat, jungle
from .hero_movement import HeroMovement
from .navigation import fixed
from .structures import Structure
from .wave import Minion


VISIBILITY_OPCODE = 1067


@dataclass(frozen=True)
class VisibilityUpdate:
    eid: int
    viewer_index: int
    values: tuple[int, int, int]

    def encode(self):
        if type(self.eid) is not int or not 0 <= self.eid <= 0xffffffff:
            raise ValueError('visibility EID must fit u32')
        if type(self.viewer_index) is not int or not 0 <= self.viewer_index <= 7:
            raise ValueError('visibility viewer index must be 0..7')
        if len(self.values) != 3 or any(type(value) is not int or not 0 <= value <= 255 for value in self.values):
            raise ValueError('visibility update requires three byte values')
        return struct.pack('>IBBBB6x', self.eid, self.viewer_index, *self.values)


def parse_visibility(payload):
    if len(payload) != 14 or payload[8:] != bytes(6):
        raise ValueError('1067 requires EID, four fields and six zero bytes')
    eid, viewer, *values = struct.unpack_from('>IBBBB', payload)
    update = VisibilityUpdate(eid, viewer, tuple(values))
    update.encode()
    return update


@dataclass(frozen=True)
class VisionRules:
    radius: float = 12.0  # Explicit sandbox policy; native radii remain unmeasured.

    def __post_init__(self):
        if (type(self.radius) not in (int, float) or not math.isfinite(self.radius)
                or not 0.000001 <= self.radius <= 1000):
            raise ValueError('vision radius must be finite and within [0.000001, 1000]')


class Vision:
    """Shared hero/minion/turret sight, emitted on changes at fixed ticks.

    Supply the match's ActorSlots allocator to exclude actors before their
    creation and after removal. Without it, ``entities`` must already contain
    only client-created actors. Dead targets retain ordinary nearby/own-team
    visibility; dead observers no longer reveal other actors.
    """

    def __init__(self, rules: VisionRules | None = None, *, actor_slots=None):
        self.rules = rules or VisionRules()
        self.actor_slots = actor_slots
        self.values: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._last_update_at = -math.inf

    @staticmethod
    def _observer(actor):
        return combat.alive(actor) and (
            isinstance(actor, (HeroMovement, Minion))
            or isinstance(actor, Structure) and not actor.is_crystal)

    def update(self, now: float, entities: Mapping[int, object] | Iterable[object]):
        if not math.isfinite(now) or now < self._last_update_at:
            raise ValueError('vision update time must be finite and monotonic')
        actors = entities.values() if isinstance(entities, Mapping) else entities
        present = sorted((actor for actor in actors if getattr(actor, 'spawn_at', 0) <= now
                          and (self.actor_slots is None or actor.eid in self.actor_slots.by_eid)),
                         key=lambda actor: actor.eid)
        positions = {actor.eid: (fixed(actor.x), fixed(actor.y)) for actor in present}
        radius = fixed(self.rules.radius)
        radius_squared = radius ** 2
        observers = {1: {}, 2: {}}
        revealed = {1: set(), 2: set()}
        for actor in present:
            team = combat.team(actor)
            if team in observers and self._observer(actor):
                x, y = positions[actor.eid]
                observers[team].setdefault((x // radius, y // radius), []).append((x, y))
                revealed[team].update(eid for eid, expires in
                                      getattr(actor, 'revealed_targets', {}).items()
                                      if now < expires)
        current, frames = {}, []
        for actor in present:
            x, y = positions[actor.eid]
            cell_x, cell_y = x // radius, y // radius
            for team in (1, 2):
                own = combat.team(actor) == team
                # A point within one radius lies in this cell or one of its
                # eight neighbors. The final inclusive integer check is exact.
                nearby = own or actor.eid in revealed[team] or any((x - ox) ** 2 + (y - oy) ** 2 <= radius_squared
                                    for gx in (cell_x - 1, cell_x, cell_x + 1)
                                    for gy in (cell_y - 1, cell_y, cell_y + 1)
                                    for ox, oy in observers[team].get((gx, gy), ()))
                values = (1, 15 if own else int(nearby), 0)
                key = actor.eid, team
                current[key] = values
                if self.values.get(key) != values:
                    frames.append((VISIBILITY_OPCODE, VisibilityUpdate(actor.eid, team, values).encode()))
        # Removed actors are forgotten without sending a packet against an EID
        # whose native actor no longer exists. Reused EIDs start a new cache row.
        self.values = current
        self._last_update_at = now
        return frames

    def snapshot_frames(self):
        """Current banks after creation on reconnect; no mutation or allocation."""
        return [(VISIBILITY_OPCODE, VisibilityUpdate(eid, viewer, values).encode())
                for (eid, viewer), values in sorted(self.values.items())]


# Legacy standalone policy API retained for compatibility and its existing
# tests. These 10/6/9 radii and rectangular brush/true-sight model were never
# native measurements; the live match uses Vision and VisionRules above.
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
    """Legacy standalone brush/radius policy; live publication uses Vision."""

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
