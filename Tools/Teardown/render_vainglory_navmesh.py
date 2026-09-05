#!/usr/bin/env python3
"""Parse and render Vainglory navMesh records (walkable layout).

The `RSC0:bin` nav records are plain binary, fully reverse-engineered here:

    u32 version = 1
    u32 0
    u32 index count (3 per triangle)
    6× f32 world bounds, min/max form (x0, y0, z0, x1, y1, z1)
    zero padding to byte 72; `00 03` marker at 72
    bounds repeated; index count repeated; vertex count
    `01 04` marker; u32 vertex-bytes; u32 24 (record size)
    17 bytes of section flags
    vertex array: vertex_count × 24 B (x, y, z, 0, 1, 0 as 6× f32)
    triangle array: index_count × (u8 if vertex_count < 256 else u16)

Every byte of both sample files is accounted for by this layout.
Renders top-down walkable meshes to an output directory. Read-only on the
store; rendered images stay out of the repository.

Usage:
    python render_vainglory_navmesh.py <Data-dir> <out-dir> <A1/B2...hash>...
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

VSTART = 134
PAD = 20


def write_png(path: Path, w: int, h: int, rgb: bytes) -> None:
    def chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + rgb[y * w * 3 : (y + 1) * w * 3] for y in range(h))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def parse_nav(rel: str, root: Path) -> dict:
    data = (root / rel).read_bytes()
    end = data.index(0, 38)
    p = data[end + 1 :]
    idx_count = struct.unpack_from("<I", p, 8)[0]
    x0, _y0, z0, x1, _y1, z1 = struct.unpack_from("<6f", p, 12)
    vcount = struct.unpack_from("<I", p, VSTART - 31)[0]
    vlen = struct.unpack_from("<I", p, VSTART - 25)[0]
    rec = struct.unpack_from("<I", p, VSTART - 21)[0]
    if not (vlen == vcount * rec == vcount * 24):
        raise ValueError(f"header mismatch: vcount={vcount} vlen={vlen} rec={rec}")
    verts = []
    for i in range(vcount):
        x, _y, z = struct.unpack_from("<3f", p, VSTART + i * 24)
        verts.append((x, z))
    tstart = VSTART + vlen
    step = 3 if vcount < 256 else 6
    tris = []
    for t in range(idx_count // 3):
        if tstart + (t + 1) * step > len(p):
            break
        if step == 3:
            a, b, c = p[tstart + t * 3 : tstart + t * 3 + 3]
        else:
            a, b, c = struct.unpack_from("<3H", p, tstart + t * 6)
        if a < vcount and b < vcount and c < vcount:
            tris.append((a, b, c))
    consumed = tstart + len(tris) * step
    print(f"{rel}: verts={vcount} tris={len(tris)}/{idx_count // 3} "
          f"consumed={consumed}/{len(p)} bounds=({x0:.1f},{z0:.1f})-({x1:.1f},{z1:.1f})")
    return dict(bounds=(x0, z0, x1, z1), verts=verts, tris=tris)


def render(r: dict, root: Path, rel: str, out_dir: Path, scale: int) -> None:
    x0, z0, x1, z1 = r["bounds"]
    W = int((x1 - x0) * scale) + PAD * 2
    H = int((z1 - z0) * scale) + PAD * 2
    img = bytearray(W * H * 3)
    for i in range(0, len(img), 3):
        img[i], img[i + 1], img[i + 2] = 13, 15, 20

    def fill_tri(A, B, C) -> None:
        ax, az = A
        bx, bz = B
        cx, cz = C
        minx = max(0, int((min(ax, bx, cx) - x0) * scale) + PAD - 1)
        maxx = min(W - 1, int((max(ax, bx, cx) - x0) * scale) + PAD + 1)
        minz = max(0, int((min(az, bz, cz) - z0) * scale) + PAD - 1)
        maxz = min(H - 1, int((max(az, bz, cz) - z0) * scale) + PAD + 1)
        if minx > maxx or minz > maxz:
            return
        for pz in range(minz, maxz + 1):
            wy = (pz - PAD) / scale + z0
            base = pz * W * 3
            for px in range(minx, maxx + 1):
                wx = (px - PAD) / scale + x0
                s1 = (bx - ax) * (wy - az) - (bz - az) * (wx - ax)
                s2 = (cx - bx) * (wy - bz) - (cz - bz) * (wx - bx)
                s3 = (ax - cx) * (wy - cz) - (az - cz) * (wx - cx)
                if (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0):
                    o = base + px * 3
                    img[o], img[o + 1], img[o + 2] = 52, 208, 128

    for t in r["tris"]:
        fill_tri(r["verts"][t[0]], r["verts"][t[1]], r["verts"][t[2]])
    name = rel.replace("/", "_")
    write_png(out_dir / f"{name}_layout.png", W, H, bytes(img))


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    root, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    for rel in sys.argv[3:]:
        render(parse_nav(rel, root), root, rel, out_dir, 10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
