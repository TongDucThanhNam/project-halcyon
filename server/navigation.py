"""Deterministic navigation over the externally owned Classic baked surface.

Geometry is quantized once to millionths of a world unit. Collision clipping
uses rational arithmetic; graph costs and A* tie breaks use integers. No game
mesh is shipped here. See the map-structure leaf section 4 for the store format.
"""
from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from functools import cmp_to_key, lru_cache
import heapq
import math
import os
from pathlib import Path
import struct

from .paths import pc_data_dir

SCALE = 1_000_000
CELL = 8 * SCALE
DEFAULT_A001_PATH = pc_data_dir() / "4B/4BD271EAAC785AEB0C2BCED99515D401"
DEFAULT_CLASSIC_NAVMESH = pc_data_dir() / "4D/4D562D63B9D0796F7FCC5EC61ADB111B"


def fixed(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("coordinates and time must be finite")
    return round(value * SCALE)


def within_distance(a, b, distance):
    """Use the movement coordinate grid for gameplay range decisions."""
    dx = fixed(b[0]) - fixed(a[0])
    dy = fixed(b[1]) - fixed(a[1])
    return dx * dx + dy * dy <= fixed(distance) ** 2


def _point(point):
    return fixed(point[0]), fixed(point[1])


def _world(point):
    return point[0] / SCALE, point[1] / SCALE


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _distance(a, b):
    return math.isqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def _round_ratio(numerator, denominator):
    """Exact nearest-even rounding, equivalent to round(Fraction(n, d))."""
    quotient, remainder = divmod(numerator, denominator)
    doubled = remainder * 2
    return quotient + (doubled > denominator or (doubled == denominator and quotient % 2))


def _pull_string(origin, goal, portals):
    """Tighten a triangle corridor using exact integer left/right portals.

    Returns corners excluding origin. The apex advances to a portal endpoint
    when a side crosses the opposite side; no center/midpoint detour remains.
    """
    portals = [(origin, origin), *portals, (goal, goal)]
    apex = left = right = origin
    left_index = right_index = 0
    route, index = [], 1
    while index < len(portals):
        new_left, new_right = portals[index]
        if _cross(apex, right, new_right) >= 0:
            if apex == right or _cross(apex, left, new_right) < 0:
                right, right_index = new_right, index
            else:
                if left != apex:
                    route.append(left)
                apex = left
                index = left_index + 1
                left = right = apex
                right_index = left_index
                continue
        if _cross(apex, left, new_left) <= 0:
            if apex == left or _cross(apex, right, new_left) > 0:
                left, left_index = new_left, index
            else:
                if right != apex:
                    route.append(right)
                apex = right
                index = right_index + 1
                left = right = apex
                left_index = right_index
                continue
        index += 1
    if (route[-1] if route else origin) != goal:
        route.append(goal)
    return route


class NavMesh:
    def __init__(self, vertices, triangles, *, heights=None):
        self.vertices = tuple(_point(v) for v in vertices)
        vertex_heights = (tuple(fixed(h) for h in heights) if heights is not None
                          else (0,) * len(self.vertices))
        if len(vertex_heights) != len(self.vertices):
            raise ValueError('navmesh height count differs from vertex count')
        self.triangles = []
        self._triangle_heights = []
        self.centers = []
        self._bounds = []
        self._halfplanes = []
        self.adjacency = defaultdict(dict)
        self._portals = {}
        self._cells = defaultdict(set)
        edges = defaultdict(list)
        for indices in triangles:
            if len(indices) != 3 or any(i < 0 or i >= len(self.vertices) for i in indices):
                raise ValueError("invalid navmesh triangle indices")
            a, b, c = (self.vertices[i] for i in indices)
            area = _cross(a, b, c)
            if not area:
                continue
            tri = (a, b, c) if area > 0 else (a, c, b)
            index = len(self.triangles)
            self.triangles.append(tri)
            ordered = indices if area > 0 else (indices[0], indices[2], indices[1])
            self._triangle_heights.append(tuple(vertex_heights[i] for i in ordered))
            self.centers.append(tuple(sum(p[k] for p in tri) // 3 for k in (0, 1)))
            self._bounds.append((min(p[0] for p in tri), min(p[1] for p in tri),
                                 max(p[0] for p in tri), max(p[1] for p in tri)))
            # cross(a, b, point) = nx*x + ny*y + offset. Geometry is immutable;
            # preparing these exact integer coefficients avoids rebuilding an
            # edge and repeating coordinate differences for every path query.
            self._halfplanes.append(tuple(
                (a[1] - b[1], b[0] - a[0], a[0] * b[1] - b[0] * a[1])
                for a, b in zip(tri, tri[1:] + tri[:1])))
            for ix in range(min(p[0] for p in tri) // CELL, max(p[0] for p in tri) // CELL + 1):
                for iy in range(min(p[1] for p in tri) // CELL, max(p[1] for p in tri) // CELL + 1):
                    self._cells[ix, iy].add(index)
            for u, v in zip(tri, tri[1:] + tri[:1]):
                edges[tuple(sorted((u, v)))].append(index)
        if not self.triangles:
            raise ValueError("navmesh has no nondegenerate triangles")
        for (u, v), owners in edges.items():
            if len(owners) > 2:
                raise ValueError("non-manifold navmesh edge")
            if len(owners) == 2:
                left, right = owners
                portal = ((u[0] + v[0]) // 2, (u[1] + v[1]) // 2)
                self.adjacency[left][right] = portal
                self.adjacency[right][left] = portal
                # Triangles are CCW. Exiting across directed edge a->b,
                # endpoint b is on the traveller's left. This avoids using
                # rounded centers to guess a portal's orientation.
                tri = self.triangles[left]
                a, b = next((a, b) for a, b in zip(tri, tri[1:] + tri[:1])
                            if {a, b} == {u, v})
                self._portals[left, right] = b, a
                self._portals[right, left] = a, b

    @classmethod
    def from_file(cls, path):
        data = Path(path).read_bytes()
        if data[40:44] == b'VAND':
            from .navigation_store import read_detour_store
            points, triangles, heights, metadata = read_detour_store(data)
            mesh = cls(points, triangles, heights=heights)
            mesh.source_metadata = metadata
            return mesh
        if data[:4] == b"RSC0":
            try:
                data = data[data.index(0, 38) + 1:]
            except ValueError as exc:
                raise ValueError("truncated navmesh container") from exc
        if len(data) < 134:
            raise ValueError("truncated navmesh header")
        version, reserved, count = struct.unpack_from("<3I", data)
        vertices = struct.unpack_from("<I", data, 103)[0]
        size, record = struct.unpack_from("<2I", data, 109)
        width = 1 if vertices < 256 else 2
        if (version, reserved, record) != (1, 0, 24) or size != vertices * 24 or count % 3:
            raise ValueError("invalid navmesh header")
        if 134 + size + count * width != len(data):
            raise ValueError("navmesh byte accounting mismatch")
        points, heights = [], []
        for offset in range(134, 134 + size, 24):
            x, height, z = struct.unpack_from("<3f", data, offset)
            points.append((x, z))
            heights.append(height)
        indices = struct.unpack_from("<" + ("B" if width == 1 else "H") * count, data, 134 + size)
        return cls(points, [indices[i:i + 3] for i in range(0, count, 3)], heights=heights)

    def height_at(self, point):
        """Owned mesh surface height for explicit relocation, not 2D path cost.

        Barycentric weights use the same quantized triangle geometry. This
        does not invent a model/feet offset or change authoritative movement.
        """
        p = _point(point)
        index = self._locate(p)
        if index is None:
            raise ValueError('height query must be on the navigation mesh')
        a, b, c = self.triangles[index]
        ha, hb, hc = self._triangle_heights[index]
        return (_cross(b, c, p) * ha + _cross(c, a, p) * hb + _cross(a, b, p) * hc) / (_cross(a, b, c) * SCALE)

    def _candidates(self, a, b=None):
        b = a if b is None else b
        found = set()
        for ix in range(min(a[0], b[0]) // CELL, max(a[0], b[0]) // CELL + 1):
            for iy in range(min(a[1], b[1]) // CELL, max(a[1], b[1]) // CELL + 1):
                found.update(self._cells.get((ix, iy), ()))
        return sorted(found)

    def _locate(self, point):
        for index in self._candidates(point):
            tri = self.triangles[index]
            if all(_cross(a, b, point) >= 0 for a, b in zip(tri, tri[1:] + tri[:1])):
                return index
        return None

    def contains(self, point):
        return self._locate(_point(point)) is not None

    @lru_cache(maxsize=2048)
    def _nearest(self, point):
        index = self._locate(point)
        if index is not None:
            return point, index
        best = None
        # An axis-aligned triangle bound is a conservative distance lower
        # bound. Visit nearest bounds first and skip only strictly worse ones,
        # preserving the exhaustive search's distance/index/coordinate ties.
        px, py = point
        candidates = []
        for index, (x0, y0, x1, y1) in enumerate(self._bounds):
            dx, dy = max(x0 - px, 0, px - x1), max(y0 - py, 0, py - y1)
            candidates.append((dx * dx + dy * dy, index))
        for bound, index in sorted(candidates):
            if best is not None and bound > best[0]:
                break
            tri = self.triangles[index]
            for a, b in zip(tri, tri[1:] + tri[:1]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                denominator = dx * dx + dy * dy
                numerator = min(denominator, max(0, (px - a[0]) * dx + (py - a[1]) * dy))
                projected = a[0] * denominator + numerator * dx, a[1] * denominator + numerator * dy
                candidate = tuple(_round_ratio(value, denominator) for value in projected)
                # Rounding a projected boundary point can land one lattice unit
                # outside. Move toward the triangle's interior deterministically.
                if any(_cross(u, v, candidate) < 0 for u, v in zip(tri, tri[1:] + tri[:1])):
                    center = self.centers[index]
                    for divisor in (1_000_000, 100_000, 10_000, 1000, 100, 10, 1):
                        candidate = tuple(_round_ratio(projected[k] * (divisor - 1) + center[k] * denominator,
                                                       denominator * divisor) for k in (0, 1))
                        if all(_cross(u, v, candidate) >= 0 for u, v in zip(tri, tri[1:] + tri[:1])):
                            break
                distance = (point[0] - candidate[0]) ** 2 + (point[1] - candidate[1]) ** 2
                row = distance, index, candidate
                if best is None or row < best:
                    best = row
        return best[2], best[1]

    def nearest_point(self, point):
        return _world(self._nearest(_point(point))[0])

    @lru_cache(maxsize=16384)
    def _raw_intervals(self, start, end):
        """Clip using integer rational pairs without Fraction allocation per edge."""
        intervals = []
        sx, sy = start
        ex, ey = end
        x0, x1 = min(sx, ex), max(sx, ex)
        y0, y1 = min(sy, ey), max(sy, ey)
        for index in self._candidates(start, end):
            tx0, ty0, tx1, ty1 = self._bounds[index]
            # Grid cells conservatively include triangles beyond the segment's
            # own bounds. Strict rejection keeps edge and corner touches.
            if tx1 < x0 or tx0 > x1 or ty1 < y0 or ty0 > y1:
                continue
            ln, ld, hn, hd = 0, 1, 1, 1
            for nx, ny, offset in self._halfplanes[index]:
                initial = nx * sx + ny * sy + offset
                final = nx * ex + ny * ey + offset
                if initial < 0 and final < 0:
                    hn = -1
                    break
                if initial < 0:
                    num, den = -initial, final - initial
                    if num * ld > ln * den:
                        ln, ld = num, den
                elif final < 0:
                    num, den = initial, initial - final
                    if num * hd < hn * den:
                        hn, hd = num, den
                if ln * hd > hn * ld:
                    break
            if ln * hd <= hn * ld:
                # One convex triangle covers the whole segment. Every other
                # clipped interval lies within [0, 1], so their union is fixed.
                if ln == 0 and hn == hd:
                    return ((0, 1, 1, 1),)
                intervals.append((ln, ld, hn, hd))
        merged = []
        compare = lambda a, b: a[0] * b[1] - b[0] * a[1]
        for ln, ld, hn, hd in sorted(intervals, key=cmp_to_key(compare)):
            if merged and ln * merged[-1][3] <= merged[-1][2] * ld:
                old = merged[-1]
                if hn * old[3] > old[2] * hd:
                    merged[-1] = old[0], old[1], hn, hd
            else:
                merged.append((ln, ld, hn, hd))
        return tuple(merged)

    def _intervals(self, start, end):
        return [(Fraction(ln, ld), Fraction(hn, hd)) for ln, ld, hn, hd in self._raw_intervals(start, end)]

    def segment_walkable(self, start, end):
        intervals = self._raw_intervals(_point(start), _point(end))
        return bool(intervals and intervals[0][0] == 0 and intervals[0][2] == intervals[0][3])

    def find_path(self, start, end):
        """A* triangle corridor plus integer funnel, excluding start.

        Off-mesh clicks are projected to a walkable boundary. A disconnected
        destination returns no route; an invalid starting position never permits
        travel through a wall to recover itself.
        """
        # Return a fresh list so callers cannot mutate cached route geometry.
        return list(self._path_cached(_point(start), _point(end)))

    @lru_cache(maxsize=4096)
    def _path_cached(self, origin, destination):
        return tuple(self._find_path(_world(origin), _world(destination)))

    def _find_path(self, start, end):
        origin = _point(start)
        first = self._locate(origin)
        if first is None:
            return []
        goal, last = self._nearest(_point(end))
        if self.segment_walkable(start, _world(goal)):
            return [_world(goal)] if origin != goal else []
        costs, previous = {first: 0}, {}
        queue = [(_distance(self.centers[first], self.centers[last]), 0, first)]
        while queue:
            _, cost, current = heapq.heappop(queue)
            if cost != costs[current]:
                continue
            if current == last:
                break
            for neighbor in sorted(self.adjacency[current]):
                candidate = cost + _distance(self.centers[current], self.centers[neighbor])
                if candidate < costs.get(neighbor, 1 << 100):
                    costs[neighbor] = candidate
                    previous[neighbor] = current
                    heapq.heappush(queue, (candidate + _distance(self.centers[neighbor], self.centers[last]), candidate, neighbor))
        if last not in costs:
            return []
        corridor = [last]
        while corridor[-1] != first:
            corridor.append(previous[corridor[-1]])
        corridor.reverse()
        corners = _pull_string(origin, goal,
                               [self._portals[a, b] for a, b in zip(corridor, corridor[1:])])
        # Keep the existing independent collision guard: a route must not cut
        # rock even if unexpected/degenerate corridor geometry is encountered.
        if any(not self.segment_walkable(_world(a), _world(b))
               for a, b in zip([origin] + corners, corners)):
            return []
        return [_world(point) for point in corners]

    def clamp_walk_step(self, start, proposed, target, budget_fixed):
        """Repair coordinate rounding at a visible diagonal wall, not a wall hit.

        Component-wise integer truncation may fall outside a walkable edge.
        Search only the two-microunit neighbourhood, within the same distance
        budget, and require both new segments to remain walkable. Forced
        displacements continue to use clamp_segment with no such adjustment.
        """
        if self.segment_walkable(start, proposed) and self.segment_walkable(proposed, target):
            return proposed
        if self.segment_walkable(start, target):
            a, p, goal = _point(start), _point(proposed), _point(target)
            candidates = []
            old_distance = sum((goal[k] - a[k]) ** 2 for k in (0, 1))
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    q = p[0] + dx, p[1] + dy
                    travelled = sum((q[k] - a[k]) ** 2 for k in (0, 1))
                    remaining = sum((goal[k] - q[k]) ** 2 for k in (0, 1))
                    if 0 < travelled <= budget_fixed ** 2 and remaining < old_distance:
                        candidates.append((dx * dx + dy * dy, remaining, q))
            for _, _, q in sorted(candidates):
                point = _world(q)
                if self.segment_walkable(start, point) and self.segment_walkable(point, target):
                    return point
        return self.clamp_segment(start, proposed)

    def clamp_segment(self, start, end):
        """Stop a forced displacement at the first wall; never project past it."""
        a, b = _point(start), _point(end)
        intervals = self._intervals(a, b)
        if not intervals or intervals[0][0] != 0:
            return _world(a)
        ratio = intervals[0][1]
        if ratio == 1:
            return _world(b)
        # Back off one microunit along the ray before rounding at the wall.
        ratio = max(Fraction(0), ratio - Fraction(2, max(1, _distance(a, b))))
        result = tuple(round(a[k] + (b[k] - a[k]) * ratio) for k in (0, 1))
        return _world(result) if self._locate(result) is not None else _world(a)

    def dash_endpoint(self, start, end):
        """Cross a wall only when requested penetration exceeds its midpoint.

        The full ray determines wall thickness even when the requested endpoint
        lies inside rock. An endpoint beyond the midpoint exits on the far edge;
        a shorter dash stops at the near edge. Outside-map space has no far edge.
        """
        a, b = _point(start), _point(end)
        length = _distance(a, b)
        if not length or self._locate(a) is None:
            return _world(a)
        ray_length = max(length, 512 * SCALE)
        ray = tuple(a[k] + (b[k] - a[k]) * ray_length // length for k in (0, 1))
        intervals = self._intervals(a, ray)
        desired = Fraction(length, ray_length)
        if not intervals or intervals[0][0] != 0:
            return _world(a)
        current_end = intervals[0][1]
        for next_start, next_end in intervals[1:]:
            if desired <= current_end:
                return _world(b)
            if desired - current_end <= (next_start - current_end) / 2:
                endpoint = tuple(a[k] + round((ray[k] - a[k]) * current_end) for k in (0, 1))
                return self.clamp_segment(_world(a), _world(endpoint))
            if desired < next_start:
                ratio = min(next_end, next_start + Fraction(2, ray_length))
                endpoint = tuple(a[k] + round((ray[k] - a[k]) * ratio) for k in (0, 1))
                return self.nearest_point(_world(endpoint))
            current_end = next_end
        if desired <= current_end:
            return _world(b)
        endpoint = tuple(a[k] + round((ray[k] - a[k]) * current_end) for k in (0, 1))
        return self.nearest_point(_world(endpoint))


def load_halcyon_navmesh(path=None):
    """Load external geometry or fail explicitly; never silently disable walls."""
    selected = Path(path or os.environ.get("HALCYON_NAVMESH", DEFAULT_CLASSIC_NAVMESH))
    if not selected.is_file():
        raise FileNotFoundError(f"Classic navmesh unavailable; set HALCYON_NAVMESH to the external store record: {selected}")
    mesh = NavMesh.from_file(selected)
    library = os.environ.get('HALCYON_NATIVE_STEERING_LIBRARY')
    if library:
        from .detour_query import DetourRouteQuery
        from .native_steering import NativeSteeringMesh
        return NativeSteeringMesh(mesh,DetourRouteQuery(library,selected))
    return mesh
