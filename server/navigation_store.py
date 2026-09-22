"""Read owned Detour-v7 navigation data; no game geometry is bundled.

The pinned native loader df0380 consumes a tile count, dtNavMeshParams, then
(reference, byte length, tile) records. df16c4 qualifies the 100-byte header
and layout below. Compare Detour's public format declaration:
https://github.com/recastnavigation/recastnavigation/blob/main/Detour/Include/DetourNavMesh.h

Only ground polygons are supported. Off-mesh links are rejected explicitly,
not turned into walkable triangles. Runtime mutable link lists are irrelevant
to surface geometry and are never imported into the simulation.
"""
from __future__ import annotations

import math
import struct


def read_detour_store(data):
    if not 40 <= len(data) <= 64 * 1024 * 1024:
        raise ValueError('invalid Detour store size')
    count, *params = struct.unpack_from('<I5f2I', data)
    if (not 1 <= count <= 16384 or not all(math.isfinite(x) for x in params[:5])
            or min(params[3:5]) <= 0 or not count <= params[5] <= 16384
            or not 1 <= params[6] <= 65536):
        raise ValueError('invalid Detour store parameters')
    vertices, heights, triangles = [], [], []
    seen_tiles, seen_refs, agents = set(), set(), set()
    offset, polygon_count = 32, 0
    for _ in range(count):
        if offset + 8 > len(data):
            raise ValueError('truncated Detour tile record')
        reference, size = struct.unpack_from('<2I', data, offset)
        offset += 8
        if not reference or reference in seen_refs or not 100 <= size <= 1048576 or offset + size > len(data):
            raise ValueError('invalid Detour tile reference/size')
        seen_refs.add(reference)
        tile = memoryview(data)[offset:offset + size]
        offset += size
        header = struct.unpack_from('<15I10f', tile)
        if header[:2] != (0x444e4156, 7):
            raise ValueError('unsupported Detour tile magic/version')
        identity = header[2:5]
        if identity in seen_tiles or not all(math.isfinite(x) for x in header[15:]):
            raise ValueError('duplicate tile or nonfinite Detour header')
        seen_tiles.add(identity)
        npoly, nvert, nlink, ndetail, ndvert, ndtri, nbv, noff, offbase = header[6:15]
        if (not 1 <= npoly <= params[6] or not 3 <= nvert <= 65535
                or ndetail != npoly or noff or offbase != npoly):
            raise ValueError('unsupported Detour polygon/detail/off-mesh layout')
        expected = 100 + nvert * 12 + npoly * 32 + nlink * 12 + ndetail * 12 + ndvert * 12 + ndtri * 4 + nbv * 16
        if expected != size:
            raise ValueError('Detour tile byte accounting mismatch')
        agent = header[15:18]
        if min(agent) < 0:
            raise ValueError('negative Detour agent dimension')
        agents.add(agent)
        polygon_count += npoly
        poly_at = 100 + nvert * 12
        detail_at = poly_at + npoly * 32 + nlink * 12
        dvert_at = detail_at + ndetail * 12
        dtri_at = dvert_at + ndvert * 12
        base = len(vertices)
        for i in range(nvert):
            x, y, z = struct.unpack_from('<3f', tile, 100 + i * 12)
            if not all(math.isfinite(v) for v in (x, y, z)):
                raise ValueError('nonfinite Detour vertex')
            vertices.append((x, z))
            heights.append(y)
        for i in range(npoly):
            at = poly_at + i * 32
            flags, n, area_type = struct.unpack_from('<HBB', tile, at + 28)
            if area_type >> 6 or not 3 <= n <= 6:
                raise ValueError('unsupported Detour polygon type/size')
            indices = list(struct.unpack_from('<6H', tile, at + 4)[:n])
            if len(set(indices)) != n or max(indices) >= nvert:
                raise ValueError('invalid Detour polygon vertex')
            vbase, tbase, nv, nt = struct.unpack_from('<IIBB', tile, detail_at + i * 12)
            if vbase + nv > ndvert or tbase + nt > ndtri or not nt:
                raise ValueError('invalid Detour detail bounds')
            mapped = [base + index for index in indices]
            for j in range(nv):
                x, y, z = struct.unpack_from('<3f', tile, dvert_at + (vbase + j) * 12)
                if not all(math.isfinite(v) for v in (x, y, z)):
                    raise ValueError('nonfinite Detour detail vertex')
                mapped.append(len(vertices))
                vertices.append((x, z))
                heights.append(y)
            for j in range(nt):
                ids = tuple(tile[dtri_at + (tbase + j) * 4:dtri_at + (tbase + j) * 4 + 3])
                if len(set(ids)) != 3 or max(ids) >= len(mapped):
                    raise ValueError('invalid Detour detail triangle')
                # Native query filter includes bits 1..15 (df0978).
                if flags & 0xfffe:
                    triangles.append(tuple(mapped[k] for k in ids))
    if offset != len(data) or len(agents) != 1 or not triangles:
        raise ValueError('trailing Detour data, mixed agents or empty walkable mesh')
    height, radius, climb = next(iter(agents))
    return vertices, triangles, heights, {
        'format': 'detour-v7', 'tiles': count, 'polygons': polygon_count,
        'agent_height': height, 'agent_radius': radius, 'agent_climb': climb,
        'tile_width': params[3], 'tile_depth': params[4],
    }
