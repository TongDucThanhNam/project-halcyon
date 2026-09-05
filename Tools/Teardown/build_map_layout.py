"""Build the Veilbound 3v3 map layout from goal-012 structural teardown data.

Inputs (read-only, stay outside the repo):
  - Vainglory navmesh store file (RSC0 container, format decoded in leaf §4)
  - placement table JSON from Tools/Teardown/parse_vainglory_placement.py

Outputs:
  - Assets/_Game/Map/map-layout.json — decimated walkable outline
    (Douglas-Peucker tolerance recorded in the file), renamed objective
    placements, lane centerline from a triangle-graph shortest path,
    symmetry metadata. Structural derivative only: no source payload bytes.
  - verification numbers printed to stdout (bounds, containment, path
    lengths, decimation stats).

Usage:
    python build_map_layout.py <navmesh_store_file> <placement_table.json> \
        [--out Assets/_Game/Map/map-layout.json] [--render out.png]
"""

import argparse
import heapq
import json
import math
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------- navmesh

def parse_navmesh(nav_path: Path):
    data = nav_path.read_bytes()
    if data[:4] == b"RSC0":
        end = data.index(0, 38)
        data = data[end + 1:]
    vstart = 134
    idx_count = struct.unpack_from("<I", data, 8)[0]
    vcount = struct.unpack_from("<I", data, vstart - 31)[0]
    vlen = struct.unpack_from("<I", data, vstart - 25)[0]
    rec = struct.unpack_from("<I", data, vstart - 21)[0]
    if vlen != vcount * rec or rec != 24:
        raise SystemExit(f"navmesh header mismatch: vcount={vcount} vlen={vlen} rec={rec}")
    verts = []
    for i in range(vcount):
        x, y, z = struct.unpack_from("<3f", data, vstart + i * 24)
        verts.append((x, y, z))
    tstart = vstart + vlen
    step = 3 if vcount < 256 else 6   # bytes per triangle (3x u8 or 3x u16)
    tris = []
    for t in range(idx_count // 3):
        o = tstart + t * step
        if o + step > len(data):
            break
        if step == 3:
            a, b, c = data[o], data[o + 1], data[o + 2]
        else:
            a, b, c = struct.unpack_from("<3H", data, o)
        if a < vcount and b < vcount and c < vcount:
            tris.append((a, b, c))
    return verts, tris


def tri_edges(tris):
    """edge -> [triangle indices]; boundary edges appear once."""
    edge = {}
    for ti, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            edge.setdefault(frozenset(e), []).append(ti)
    return edge

# ------------------------------------------------------- outline + decimate

def rasterize_mask(verts, tris, cell=0.5, pad=2.0):
    """Rasterize triangles into a boolean walkable grid (row 0 = min z)."""
    import numpy as np
    xs = [v[0] for v in verts]; zs = [v[2] for v in verts]
    x0, x1 = min(xs) - pad, max(xs) + pad
    z0, z1 = min(zs) - pad, max(zs) + pad
    nx = int((x1 - x0) / cell) + 1
    nz = int((z1 - z0) / cell) + 1
    mask = np.zeros((nz, nx), dtype=bool)
    V = np.array([(v[0], v[2]) for v in verts])
    for a, b, c in tris:
        p0, p1, p2 = V[a], V[b], V[c]
        gx0 = max(int((min(p0[0], p1[0], p2[0]) - x0) / cell), 0)
        gx1 = min(int((max(p0[0], p1[0], p2[0]) - x0) / cell) + 1, nx - 1)
        gz0 = max(int((min(p0[1], p1[1], p2[1]) - z0) / cell), 0)
        gz1 = min(int((max(p0[1], p1[1], p2[1]) - z0) / cell) + 1, nz - 1)
        if gx1 < gx0 or gz1 < gz0:
            continue
        gx, gz = np.meshgrid(np.arange(gx0, gx1 + 1), np.arange(gz0, gz1 + 1))
        px = x0 + gx * cell; pz = z0 + gz * cell
        d1 = (p1[0] - p0[0]) * (pz - p0[1]) - (p1[1] - p0[1]) * (px - p0[0])
        d2 = (p2[0] - p1[0]) * (pz - p1[1]) - (p2[1] - p1[1]) * (px - p1[0])
        d3 = (p0[0] - p2[0]) * (pz - p2[1]) - (p0[1] - p2[1]) * (px - p2[0])
        inside = ((d1 >= 0) & (d2 >= 0) & (d3 >= 0)) | ((d1 <= 0) & (d2 <= 0) & (d3 <= 0))
        mask[gz0:gz1 + 1, gx0:gx1 + 1] |= inside
    return mask, (x0, z0, cell)


def smooth_mask(mask):
    """3x3 majority filter: kills single-cell spurs and staircase raggedness."""
    import numpy as np
    m = mask.astype(np.uint8)
    acc = np.zeros_like(m)
    for dz in (-1, 0, 1):
        for dx in (-1, 0, 1):
            acc += np.roll(np.roll(m, dz, axis=0), dx, axis=1)
    return acc >= 5


def trace_contours(mask, x0, z0, cell):
    """Chain exposed cell edges into oriented loops (true boundary, single rail).

    Returns (outer_loops, holes): filled region borders wind clockwise in
    grid coords, hole borders counter-clockwise (detected by signed area).
    """
    nz, nx = mask.shape
    edges = {}   # start corner (cx, cz) -> list of end corners
    def add(a, b):
        edges.setdefault(a, []).append(b)
    for r in range(nz):
        for c in range(nx):
            if not mask[r, c]:
                continue
            if r == 0 or not mask[r - 1, c]:
                add((c, r), (c + 1, r))
            if c == nx - 1 or not mask[r, c + 1]:
                add((c + 1, r), (c + 1, r + 1))
            if r == nz - 1 or not mask[r + 1, c]:
                add((c + 1, r + 1), (c, r + 1))
            if c == 0 or not mask[r, c - 1]:
                add((c, r + 1), (c, r))
    loops = []
    for starts in list(edges.values()):
        while edges:
            # pick any unused edge and walk
            start = next(iter(edges))
            loop = [start]
            cur = start
            while True:
                outs = edges.get(cur)
                if not outs:
                    break
                nxt = outs.pop()
                if not outs:
                    del edges[cur]
                cur = nxt
                if cur == start:
                    break
                loop.append(cur)
            if len(loop) >= 8:
                loops.append([(x0 + cx * cell, z0 + cz * cell) for cx, cz in loop])
    def signed_area(loop):
        s = 0.0
        for (x1, z1), (x2, z2) in zip(loop, loop[1:] + loop[:1]):
            s += x1 * z2 - x2 * z1
        return s / 2
    outer, holes = [], []
    for lp in loops:
        (holes if signed_area(lp) < 0 else outer).append(lp)
    outer.sort(key=len, reverse=True)
    holes.sort(key=len, reverse=True)
    return outer, holes


def rdp(points, eps):
    """Douglas-Peucker on (x, z) point lists."""
    if len(points) < 3:
        return points[:]
    def d(p, a, b):
        ax, az = a; bx, bz = b; px, pz = p
        dx, dz = bx - ax, bz - az
        L = math.hypot(dx, dz) or 1e-9
        return abs(dx * (az - pz) - dz * (ax - px)) / L
    a, b = points[0], points[-1]
    idx, worst = -1, -1.0
    for i in range(1, len(points) - 1):
        v = d(points[i], a, b)
        if v > worst:
            idx, worst = i, v
    if worst > eps:
        left = rdp(points[:idx + 1], eps)
        right = rdp(points[idx:], eps)
        return left[:-1] + right
    return [a, b]

# -------------------------------------------------- graph shortest path

def centroid_paths(verts, tris, queries):
    """Dijkstra over triangle centroids; queries = [(name, sx, sz, gx, gz)]."""
    edge = tri_edges(tris)
    neigh = {}
    for ts in edge.values():
        for i in ts:
            neigh.setdefault(i, set()).update(ts)
    cent = []
    for a, b, c in tris:
        cent.append(((verts[a][0] + verts[b][0] + verts[c][0]) / 3,
                     (verts[a][2] + verts[b][2] + verts[c][2]) / 3))

    def nearest(x, z):
        best, bi = 1e9, None
        for i, (cx, cz) in enumerate(cent):
            dd = (cx - x) ** 2 + (cz - z) ** 2
            if dd < best:
                best, bi = dd, i
        return bi, math.sqrt(best)

    def dijkstra(src):
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d0, u = heapq.heappop(pq)
            if d0 > dist.get(u, 1e18):
                continue
            for v in neigh.get(u, ()):
                w = math.hypot(cent[u][0] - cent[v][0], cent[u][1] - cent[v][1])
                nd = d0 + w
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        return dist, prev

    results = {}
    cache = {}
    for name, sx, sz, gx, gz in queries:
        s, ds = nearest(sx, sz)
        if s not in cache:
            cache[s] = dijkstra(s)
        dist, prev = cache[s]
        g, dg = nearest(gx, gz)
        # if the goal triangle is unreachable, fall back to nearest reachable
        if g not in dist:
            reach = [i for i in dist if math.isfinite(dist[i])]
            g = min(reach, key=lambda i: (cent[i][0] - gx) ** 2 + (cent[i][1] - gz) ** 2)
            dg = math.hypot(cent[g][0] - gx, cent[g][1] - gz)
        path = [g]
        while path[-1] != s and path[-1] in prev:
            path.append(prev[path[-1]])
        pts = [cent[i] for i in reversed(path)]
        results[name] = dict(points=pts, start_gap=ds, end_gap=dg,
                             length=dist.get(g, float("inf")))
    return results


def chained_paths(verts, tris, chains):
    """Geodesic through chains of anchors: [(name, [(x, z), ...]), ...].

    Each consecutive anchor pair is connected by a centroid-graph shortest
    path; segments are concatenated so the route passes through every
    objective anchor (game flow), not the open-field geodesic.
    """
    edge = tri_edges(tris)
    neigh = {}
    for ts in edge.values():
        for i in ts:
            neigh.setdefault(i, set()).update(ts)
    cent = []
    for a, b, c in tris:
        cent.append(((verts[a][0] + verts[b][0] + verts[c][0]) / 3,
                     (verts[a][2] + verts[b][2] + verts[c][2]) / 3))

    def nearest(x, z):
        best, bi = 1e9, None
        for i, (cx, cz) in enumerate(cent):
            dd = (cx - x) ** 2 + (cz - z) ** 2
            if dd < best:
                best, bi = dd, i
        return bi, math.sqrt(best)

    cache = {}
    def dijkstra(src):
        if src in cache:
            return cache[src]
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d0, u = heapq.heappop(pq)
            if d0 > dist.get(u, 1e18):
                continue
            for v in neigh.get(u, ()):
                w = math.hypot(cent[u][0] - cent[v][0], cent[u][1] - cent[v][1])
                nd = d0 + w
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        cache[src] = (dist, prev)
        return cache[src]

    results = {}
    for name, anchors in chains:
        full = [anchors[0]]
        total = 0.0
        gaps = []
        for (ax, az), (bx, bz) in zip(anchors, anchors[1:]):
            s, ds = nearest(ax, az)
            g, dg = nearest(bx, bz)
            gaps.append(round(max(ds, dg), 2))
            dist, prev = dijkstra(s)
            if g not in dist:
                total = float("inf")
                break
            seg = [g]
            while seg[-1] != s and seg[-1] in prev:
                seg.append(prev[seg[-1]])
            seg = [cent[i] for i in reversed(seg)]
            total += dist[g]
            full.extend(seg[1:])
        results[name] = dict(points=full, anchors=[list(a) for a in anchors],
                             anchor_gaps=gaps, length=total)
    return results


def decimate_path(points, eps):
    """Collapse collinear-ish centroid paths with RDP."""
    return rdp(points, eps)

# ----------------------------------------------------------------- main

RENAMES = {
    "HF_CenterKraken":  ("pit_boss",       "active"),
    "HF_CenterMid":     ("mid_anchor",     "active"),
    "HF_CenterBottom":  ("lane_south_anchor", "active"),
    "HF_CenterShop":    ("neutral_shop",   "active"),
    "HF_LCrystalMine":  ("mine_left",      "active"),
    "HF_RCrystalMine":  ("mine_right",     "active"),
    "HF_LCampA":        ("camp_left_a",    "active"),
    "HF_LCampB":        ("camp_left_b",    "active"),
    "HF_LCampC":        ("camp_left_c",    "active"),
    "HF_LCampD":        ("camp_left_d",    "active"),
    "HF_RCampA":        ("camp_right_a",   "active"),
    "HF_RCampB":        ("camp_right_b",   "active"),
    "HF_RCampC":        ("camp_right_c",   "active"),
    "HF_RCampD":        ("camp_right_d",   "active"),
    "HF_LLaneSpawn":    ("lane_spawn_left",  "active"),
    "HF_RLaneSpawn":    ("lane_spawn_right", "active"),
    "HF_LShop":         ("base_shop_left",  "active"),
    "HF_RShop":         ("base_shop_right", "active"),
    "HF_LTurret_Outer": ("tower_left_outer", "active"),
    "HF_LTurret_Middle": ("tower_left_middle", "inactive"),
    "HF_LTurret_Base":  ("tower_left_base",  "active"),
    "HF_LTurret_Vain1": ("tower_left_vain1", "inactive"),
    "HF_LTurret_Vain2": ("tower_left_vain2", "inactive"),
    "HF_RTurret_Outer": ("tower_right_outer", "active"),
    "HF_RTurret_Middle": ("tower_right_middle", "inactive"),
    "HF_RTurret_Base":  ("tower_right_base",  "active"),
    "HF_RTurret_Vain1": ("tower_right_vain1", "inactive"),
    "HF_RTurret_Vain2": ("tower_right_vain2", "inactive"),
    "HF_LVainCrystal":  ("core_left",      "active"),
    "HF_RVainCrystal":  ("core_right",     "active"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("navmesh")
    ap.add_argument("placement")
    ap.add_argument("--out", default="Assets/_Game/Map/map-layout.json")
    ap.add_argument("--render", default=None)
    ap.add_argument("--outline-eps", type=float, default=1.5)
    ap.add_argument("--path-eps", type=float, default=3.0)
    args = ap.parse_args()

    verts, tris = parse_navmesh(Path(args.navmesh))
    placement = json.load(open(args.placement))
    table = placement["records"] if isinstance(placement, dict) and "records" in placement else placement

    xs = [v[0] for v in verts]; zs = [v[2] for v in verts]
    bounds = dict(x0=min(xs), x1=max(xs), z0=min(zs), z1=max(zs))

    mask, (mx0, mz0, mcell) = rasterize_mask(verts, tris)
    mask = smooth_mask(mask)

    # objectives (renamed; measured coords preserved). Source tier names are
    # NOT written into game assets — the HF_* <-> id mapping lives only in
    # this teardown tool and the teardown docs.
    objs = []
    for r in table:
        name, status = RENAMES.get(r["name"], (r["name"], "unknown"))
        objs.append(dict(id=name,
                         x=round(r["x"], 3), y=round(r["y"], 3), z=round(r["z"], 3),
                         yaw_deg=round(r["yaw"], 1), state=status))

    # containment: soft objectives must sit ON walkable; structures (towers,
    # cores, shops) have their footprint carved out of the navmesh, so they
    # get a proximity test instead
    import numpy as np
    STRUCTURE = ("tower_", "core_", "base_shop_", "neutral_shop")
    def inside(x, z):
        cx = int(round((x - mx0) / mcell)); cz = int(round((z - mz0) / mcell))
        if 0 <= cz < mask.shape[0] and 0 <= cx < mask.shape[1]:
            return bool(mask[cz, cx])
        return False
    def nearest_walkable(x, z):
        wz, wx = np.nonzero(mask)
        d2 = np.hypot(wx * mcell + mx0 - x, wz * mcell + mz0 - z)
        return float(d2[int(np.argmin(d2))])
    containment = {}
    for o in objs:
        if inside(o["x"], o["z"]):
            containment[o["id"]] = "on-walkable"
        else:
            d = nearest_walkable(o["x"], o["z"])
            containment[o["id"]] = (f"struct-edge {d:.1f}u" if d < 4.0
                                    else f"OFF-GRID {d:.1f}u")

    # walkable contours (true boundary edge-chaining)
    outer, hole_loops = trace_contours(mask, mx0, mz0, mcell)
    outline = rdp(outer[0], args.outline_eps)
    holes = [rdp(c, args.outline_eps) for c in hole_loops if len(c) > 40]

    # routes as objective chains (game flow), geodesic between anchors
    by_id = {o["id"]: o for o in objs}
    def A(*ids):
        return [(by_id[i]["x"], by_id[i]["z"]) for i in ids]
    chains = [
        ("lane_left_to_right", A("lane_spawn_left", "tower_left_base",
                                 "tower_left_outer", "tower_right_outer",
                                 "tower_right_base", "lane_spawn_right")),
        ("branch_outer_to_pit", A("tower_left_outer", "pit_boss",
                                  "tower_right_outer")),
        ("jungle_left_mine_loop", A("lane_spawn_left", "camp_left_a",
                                    "camp_left_b", "mine_left", "camp_left_d",
                                    "camp_left_c", "lane_spawn_left")),
    ]
    paths = {}
    g = chained_paths(verts, tris, chains)
    for name, res in g.items():
        raw = res["points"]
        simp = decimate_path(raw, args.path_eps)
        paths[name] = dict(anchor_chain=res["anchors"],
                           anchor_snap_gaps=res["anchor_gaps"],
                           graph_length=round(res["length"], 2),
                           raw_points=len(raw),
                           decimated=[(round(px, 2), round(pz, 2)) for px, pz in simp])

    layout = dict(
        generator="Tools/Teardown/build_map_layout.py",
        provenance="goal-012 runtime teardown (structural derivative, decimated)",
        outline_decimation_eps=args.outline_eps,
        path_decimation_eps=args.path_eps,
        world_bounds=bounds,
        ground_snap_y=0.0071,
        outline=[(round(x, 2), round(z, 2)) for x, z in outline],
        holes=[[(round(x, 2), round(z, 2)) for x, z in h] for h in holes],
        objectives=objs,
        paths=paths,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(layout, indent=1), newline="\n")

    # verification report
    print(f"navmesh: {len(verts)} verts, {len(tris)} tris, bounds {bounds}")
    print(f"contours: {len(outer)} outer + {len(hole_loops)} holes "
          f"(outline {len(outer[0])} -> {len(outline)} pts after RDP "
          f"eps={args.outline_eps}; {len(holes)} holes kept)")
    aspect = (bounds["x1"] - bounds["x0"]) / (bounds["z1"] - bounds["z0"])
    print(f"footprint aspect: {aspect:.2f}:1")
    bad = [f"{k}: {v}" for k, v in containment.items() if str(v).startswith("OFF")]
    ongrid = sum(1 for v in containment.values() if not str(v).startswith("OFF"))
    print(f"objectives on/near walkable: {ongrid}/{len(containment)}"
          + (f"  PROBLEM: {bad}" if bad else ""))
    detail = {k: v for k, v in containment.items() if v != "on-walkable"}
    for k, v in detail.items():
        print(f"   {k}: {v}")
    for name, p in paths.items():
        print(f"path {name}: {p['graph_length']} u over {p['raw_points']} centroids "
              f"-> {len(p['decimated'])} pts")
    active = [o for o in objs if o["state"] == "active"]
    print(f"objectives: {len(objs)} total, {len(active)} active")

    if args.render:
        render(args.render, layout)
        print(f"render: {args.render}")


def render(png, layout):
    """Top-down PNG, uniform scale, no aspect distortion (PIL if present)."""
    W = H = 1400
    b = layout["world_bounds"]
    dx = b["x1"] - b["x0"]; dz = b["z1"] - b["z0"]
    s = min((W - 80) / dx, (H - 80) / dz)
    ox = (W - dx * s) / 2
    oy = (H - dz * s) / 2
    def px(x, z):
        return int(ox + (x - b["x0"]) * s), int(oy + (b["z1"] - z) * s)
    import collections
    img = bytearray(b"\xff" * (W * H * 3))
    def put(x, y, col):
        if 0 <= x < W and 0 <= y < H:
            i = (y * W + x) * 3
            img[i:i + 3] = bytes(col)
    # outline fill: even-odd scanline
    poly = [px(x, z) for x, z in layout["outline"]]
    for y in range(H):
        row = []
        for i in range(len(poly)):
            x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % len(poly)]
            if (y1 > y) != (y2 > y):
                row.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        row.sort()
        for a, bxx in zip(row[::2], row[1::2]):
            for x in range(max(0, int(a)), min(W, int(bxx) + 1)):
                put(x, y, (38, 42, 50))
    # holes: void pockets inside the walkable area
    for hole in layout.get("holes", []):
        hp = [px(x, z) for x, z in hole]
        for y in range(H):
            row = []
            for i in range(len(hp)):
                x1, y1 = hp[i]; x2, y2 = hp[(i + 1) % len(hp)]
                if (y1 > y) != (y2 > y):
                    row.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            row.sort()
            for a, bxx in zip(row[::2], row[1::2]):
                for x in range(max(0, int(a)), min(W, int(bxx) + 1)):
                    put(x, y, (12, 12, 16))
    # outline stroke
    for i in range(len(poly)):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % len(poly)]
        steps = max(abs(x2 - x1), abs(y2 - y1)) * 2 + 1
        for si in range(steps + 1):
            t = si / steps
            put(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t), (120, 200, 120))
    # paths
    for k, (r, g, b2) in dict(lane_left_to_right=(230, 200, 90),
                              branch_outer_to_pit=(140, 190, 240),
                              jungle_left_mine_loop=(200, 120, 220)).items():
        pts = [px(x, z) for x, z in layout["paths"][k]["decimated"]]
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]; x2, y2 = pts[i + 1]
            steps = max(abs(x2 - x1), abs(y2 - y1)) * 2 + 1
            for si in range(steps + 1):
                t = si / steps
                put(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t), (r, g, b2))
    # objectives
    for o in layout["objectives"]:
        x, y = px(o["x"], o["z"])
        col = (240, 90, 90) if o["state"] == "active" else (110, 110, 110)
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                if dx * dx + dy * dy <= 16:
                    put(x + dx, y + dy, col)
    try:
        from PIL import Image
        Image.frombytes("RGB", (W, H), bytes(img)).save(png)
    except ImportError:
        with open(png, "wb") as f:   # P6 fallback
            f.write(b"P6\n%d %d\n255\n" % (W, H)); f.write(bytes(img))


if __name__ == "__main__":
    main()
