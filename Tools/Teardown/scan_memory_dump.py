#!/usr/bin/env python3
"""Scan raw process-memory dumps of a running Vainglory client for map data.

The dump files must each begin at a 4-byte-aligned virtual address (per-region
`dd if=/proc/<pid>/mem` dumps satisfy this). Three things are reported:

1. Navmesh anchor — exact f32 triples of the A001 navmesh vertices. Finding
   them proves the dump contains live level data and locates it.
2. Static coordinates — (x,y,z) float triples inside the known 3v3 bounds
   that appear bit-identically in BOTH of two dumps taken minutes apart.
   Objectives (turrets/mines/kraken/shops) are static; heroes and minions are
   not, so the intersection isolates level placement from actor state.
3. A full sorted list of unique static coordinates for manual symmetry check.

Pure research tool: reads local artifacts and memory the user owns.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

X0, X1 = -92.2, 94.7
Z0, Z1 = -15.2, 45.8
Y0, Y1 = -6.0, 6.0
MIN_INT_FLOATS = 64  # region must hold >= this many floats to bother


def navmesh_vertices(nav_path: Path) -> np.ndarray:
    """Parse the (x,y,z) float triples from an RSC0 navmesh payload.

    Layout per render_vainglory_navmesh.py: after the RSC0 header comes a
    NUL-terminated asset name; the nav binary starts after that NUL. Vertex
    array begins at byte 134 of the nav binary, 24 B per vertex.
    """
    data = nav_path.read_bytes()
    if data[:4] == b"RSC0":
        end = data.index(0, 38)
        data = data[end + 1 :]
    vstart = 134
    vcount = struct.unpack_from("<I", data, vstart - 31)[0]
    vlen = struct.unpack_from("<I", data, vstart - 25)[0]
    rec = struct.unpack_from("<I", data, vstart - 21)[0]
    if vlen != vcount * rec or rec != 24:
        raise SystemExit(f"nav layout check failed: vcount={vcount} vlen={vlen} rec={rec}")
    verts = np.frombuffer(data, dtype="<f4", count=vcount * 6, offset=vstart)
    return verts.reshape(vcount, 6)[:, :3].copy()


def find_anchor(dump: np.ndarray, verts: np.ndarray, max_hits: int = 8) -> list[int]:
    """Locate exact navmesh vertex triples in a dump. Returns offsets."""
    hits: list[int] = []
    first = verts[0]
    target = first.tobytes()
    pos = 0
    raw = dump.tobytes()
    while len(hits) < max_hits:
        idx = raw.find(target, pos)
        if idx < 0 or idx % 4:
            if idx < 0:
                break
            pos = idx + 1
            continue
        off = idx // 4
        block = dump[off : off + len(verts) * 3]
        if len(block) == len(verts) * 3 and np.array_equal(
            block.reshape(-1, 3), verts
        ):
            hits.append(idx)
            pos = idx + 4
        else:
            pos = idx + 1
    return hits


def in_bounds_triples(dump: np.ndarray) -> np.ndarray:
    """All 4-aligned (x,y,z) triples within the map bounds, all coords nonzero."""
    n = len(dump) // 4
    if n < 3:
        return np.empty((0, 3), dtype="<f4")
    floats = dump[: n * 4].view("<f4")
    x, y, z = floats[:-2], floats[1:-1], floats[2:]
    with np.errstate(invalid="ignore"):
        mask = (
            (floats[:-2] != 0.0)
            & (floats[1:-1] != 0.0)
            & (floats[2:] != 0.0)
            & (x >= X0) & (x <= X1)
            & (y >= Y0) & (y <= Y1)
            & (z >= Z0) & (z <= Z1)
        )
    stack = np.stack([x[mask], y[mask], z[mask]], axis=1)
    return stack.astype("<f4")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path, help="Vainglory store Data dir")
    parser.add_argument("dump_dir", type=Path, help="Directory of region dumps")
    parser.add_argument("out_report", type=Path)
    args = parser.parse_args()

    verts = navmesh_vertices(
        args.data_dir / "4B" / "4BD271EAAC785AEB0C2BCED99515D401"
    )

    total_anchor_hits = 0
    static: dict[bytes, int] = {}
    seen_first: set[bytes] = set()
    dumps = sorted(p for p in args.dump_dir.iterdir() if p.suffix == ".bin")
    half = len(dumps) // 2  # dumps 0..half-1 = pass A, half.. = pass B
    for i, path in enumerate(dumps):
        raw = path.read_bytes()
        arr = np.frombuffer(raw, dtype=np.uint8)
        floats = arr.view("<f4")
        anchor = find_anchor(arr, verts)
        total_anchor_hits += len(anchor)
        if anchor:
            print(f"{path.name}: NAVMESH ANCHOR at byte {anchor}", file=sys.stderr)
        triples = in_bounds_triples(arr)
        # accumulate per-pass sets of exact triple bytes
        pass_a = i < half
        target = seen_first if pass_a else None
        uniq = {row.tobytes() for row in triples}
        if pass_a:
            seen_first |= uniq
        else:
            for key in uniq:
                if key in seen_first:
                    static[key] = static.get(key, 0) + 1

    with open(args.out_report, "w", encoding="utf-8") as out:
        out.write(f"dumps: {len(dumps)} (pass A: {half}, pass B: {len(dumps) - half})\n")
        out.write(f"navmesh anchor total hits: {total_anchor_hits}\n")
        rows = []
        for key in static:
            x, y, z = struct.unpack("<3f", key)
            rows.append((x, y, z))
        rows.sort()
        out.write(f"static in-bounds triples (in both passes): {len(rows)}\n")
        for x, y, z in rows:
            out.write(f"  ({x:10.4f}, {y:8.4f}, {z:10.4f})\n")
    print(f"report -> {args.out_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
