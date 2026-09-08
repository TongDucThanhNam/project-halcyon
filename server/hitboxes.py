"""Deterministic 2D ability intersections; no client rendering dependencies.

Targets are disks. A line is a swept disk along a finite segment, and a cone
is a circular sector. Results have a stable entry-distance, then eid order.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

Point = tuple[float, float]
EPSILON = 1e-9


@dataclass(frozen=True)
class TargetDisk:
    eid: int
    x: float
    y: float
    radius: float = 0.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.x, self.y, self.radius)) or self.radius < 0:
            raise ValueError("target disk must have finite coordinates and nonnegative radius")


def direction(origin: Point, target: Point, fallback: Point = (1.0, 0.0)) -> Point:
    if not all(math.isfinite(v) for v in (*origin, *target, *fallback)):
        raise ValueError("coordinates must be finite")
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    length = math.hypot(dx, dy)
    if length <= EPSILON:
        dx, dy = fallback
        length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > EPSILON else (1.0, 0.0)


def segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    t = 0.0 if denominator <= EPSILON else max(0.0, min(1.0,
        ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator))
    return math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)


def line_hits(origin: Point, aim: Point, length: float, radius: float,
              targets: Iterable[TargetDisk], *, pierce: bool = False) -> list[int]:
    """Return disks intersecting a line, ordered by first contact along it."""
    if not all(math.isfinite(v) and v >= 0 for v in (length, radius)):
        raise ValueError("line length and radius must be finite and nonnegative")
    ux, uy = direction(origin, aim)
    end = origin[0] + ux * length, origin[1] + uy * length
    hits = []
    for target in targets:
        total_radius = radius + target.radius
        if segment_distance((target.x, target.y), origin, end) > total_radius + EPSILON:
            continue
        dx, dy = target.x - origin[0], target.y - origin[1]
        along = dx * ux + dy * uy
        across = abs(dx * uy - dy * ux)
        entry = max(0.0, along - math.sqrt(max(0.0, total_radius**2 - across**2)))
        hits.append((entry, target.eid))
    result = [eid for _, eid in sorted(hits)]
    return result if pierce else result[:1]


def circle_hits(center: Point, radius: float, targets: Iterable[TargetDisk]) -> list[int]:
    if not all(math.isfinite(v) for v in (*center, radius)) or radius < 0:
        raise ValueError("circle must have finite coordinates and nonnegative radius")
    return sorted(target.eid for target in targets
                  if math.hypot(target.x - center[0], target.y - center[1]) <= radius + target.radius + EPSILON)


def cone_hits(origin: Point, aim: Point, length: float, angle_degrees: float,
              targets: Iterable[TargetDisk]) -> list[int]:
    """Intersect target disks with both cone edges and its outer circular arc."""
    if not math.isfinite(length) or length < 0 or not 0 < angle_degrees <= 360:
        raise ValueError("cone length must be nonnegative and angle in (0,360]")
    ux, uy = direction(origin, aim)
    half = math.radians(angle_degrees / 2)
    cos_half, sin_half = math.cos(half), math.sin(half)
    ends = [(origin[0] + length * (ux * cos_half - sign * uy * sin_half),
             origin[1] + length * (uy * cos_half + sign * ux * sin_half)) for sign in (-1, 1)]
    hits = []
    for target in targets:
        point = target.x, target.y
        dx, dy = target.x - origin[0], target.y - origin[1]
        distance = math.hypot(dx, dy)
        if distance > length + target.radius + EPSILON:
            continue
        inside_angle = distance <= EPSILON or (dx * ux + dy * uy) / distance >= cos_half - EPSILON
        if inside_angle or min(segment_distance(point, origin, end) for end in ends) <= target.radius + EPSILON:
            hits.append(target.eid)
    return sorted(hits)


def dash_endpoint(origin: Point, target: Point, range_: float, *, behind: float = 1.0,
                  facing: Point = (1.0, 0.0)) -> Point:
    """Desired vector dash destination; caller must apply the terrain dash query."""
    if not all(math.isfinite(v) and v >= 0 for v in (range_, behind)):
        raise ValueError("dash range and behind distance must be finite and nonnegative")
    ux, uy = direction(origin, target, facing)
    distance = min(range_, math.dist(origin, target) + behind)
    return origin[0] + ux * distance, origin[1] + uy * distance
