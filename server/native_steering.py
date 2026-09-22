"""Opt-in client-compatible steering with independent integer collision guards.

Native capped/partial/unsupported routes retain the existing planar policy,
with explicit counters; they are not claimed as qualified native steering.
"""
import math
from collections import Counter
from .navigation import SCALE, fixed


class SurfacePath(list):
    def __init__(self, points, heights, origin_height):
        super().__init__(points)
        self.height_fixed = [fixed(h) for h in heights]
        if len(self) != len(self.height_fixed):
            raise ValueError('surface path height count mismatch')
        self.cursor_height_fixed = fixed(origin_height)

    def pop(self, index=-1):
        self.height_fixed.pop(index)
        return super().pop(index)

    def extend(self, other):
        if not isinstance(other,SurfacePath):
            raise ValueError('cannot append an unqualified planar segment to a surface path')
        self.height_fixed.extend(other.height_fixed)
        super().extend(other)


class NativeSteeringMesh:
    surface_steering = True

    def __init__(self, mesh, query):
        self.mesh,self.query = mesh,query
        self.query_counts = Counter()
        self.last_query = None
        self.source_metadata = dict(getattr(mesh,'source_metadata',{}),
            steering='experimental-pinned-detour',library_sha256=query.manifest['library_sha256'])

    def __getattr__(self,name):
        return getattr(self.mesh,name)

    def _fallback(self,reason,start,end):
        self.query_counts['fallback:'+reason] += 1
        return self.mesh.find_path(start,end)

    def find_path_with_height(self,start,end,start_height=None):
        self.query_counts['queries'] += 1
        if not self.mesh.contains(start):
            return self._fallback('origin-outside',start,end)
        goal = self.mesh.nearest_point(end)
        height = self.mesh.height_at(start) if start_height is None else start_height
        result = self.query.query([start[0],height,start[1]],
                                  [goal[0],self.mesh.height_at(goal),goal[1]])
        self.last_query = result
        if result['capped'] or not result['ended'] or not result['destination_polygon_reached']:
            return self._fallback('partial-or-capped',start,end)
        if result['height_fallbacks']:
            # Zero-initialized native height on failed queries remains a
            # measured edge case, not a newly adopted server surface policy.
            return self._fallback('height-query',start,end)
        route,heights = [],[]
        previous,previous_height = tuple(start),height
        for x,h,z in result['points'][1:]:
            proposed = (fixed(x)/SCALE,fixed(z)/SCALE)
            accepted = self.mesh.nearest_point(proposed)
            if math.dist(proposed,accepted) > .000005:
                return self._fallback('surface-projection',start,end)
            bridge = [accepted]
            if not self.mesh.segment_walkable(previous,accepted):
                bridge = self.mesh.find_path(previous,accepted)
                length = sum(math.dist(a,b) for a,b in zip([previous]+bridge,bridge))
                if not bridge or length-math.dist(previous,accepted) > .002:
                    return self._fallback('collision-bridge',start,end)
                self.query_counts['rounding-bridges'] += 1
            total = sum(math.dist(a,b) for a,b in zip([previous]+bridge,bridge))
            travelled,last = 0.0,previous
            for p in bridge:
                travelled += math.dist(last,p)
                route.append(p)
                heights.append(previous_height+(h-previous_height)*(travelled/total) if total else h)
                last = p
            previous,previous_height = accepted,h
        self.query_counts['qualified'] += 1
        return SurfacePath(route,heights,height)
