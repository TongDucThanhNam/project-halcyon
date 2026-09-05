#!/usr/bin/env python3
"""Locate and render candidate BC1 textures from the Vainglory content store.

The 28-byte size-prefixed header (size, mip count, 1, format flag, width,
height, flags) was solved arithmetically against full BC1 mip-chain lengths.
This tool decodes format-flag-2 payloads (BC1/DXT1, 0.5 bytes per pixel) and
writes PNGs to an output directory for local structural inspection only.

Read-only on the store; nothing is written back into it. No decoded payload
belongs in the repository.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import zlib  # noqa: F401  (used indirectly through png writer)

HEADER = 28


def read_header(data: bytes) -> tuple[int, int, int, int] | None:
    if len(data) < HEADER:
        return None
    size, mips, one, fmt, width, height, flags = struct.unpack_from("<7I", data, 0)
    if size != len(data) or one != 1:
        return None
    return mips, fmt, width, height, flags


def mip_chain_bytes(width: int, height: int, mips: int) -> int:
    total = 0
    w, h = width, height
    for _ in range(mips):
        bw, bh = max(w // 4, 1), max(h // 4, 1)
        total += bw * bh * 8
        w, h = max(w // 2, 1), max(h // 2, 1)
    return total


def color_565(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def decode_bc1_mip(payload: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 3)
    bw, bh = max(width // 4, 1), max(height // 4, 1)
    for by in range(bh):
        for bx in range(bw):
            block = payload[(by * bw + bx) * 8 : (by * bw + bx) * 8 + 8]
            if len(block) < 8:
                continue
            c0, c1, idx = struct.unpack_from("<HHI", block, 0)
            r0, g0, b0 = color_565(c0)
            r1, g1, b1 = color_565(c1)
            if c0 > c1:
                c2 = ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3)
                c3 = ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3)
            else:
                c2 = ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2)
                c3 = (0, 0, 0)
            palette = (  # type: ignore[var-annotated]
                (r0, g0, b0),
                (r1, g1, b1),
                c2,
                c3,
            )
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    break
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        break
                    sel = (idx >> ((py * 4 + px) * 2)) & 0x3
                    r, g, b = palette[sel]
                    o = (y * width + x) * 3
                    out[o] = r
                    out[o + 1] = g
                    out[o + 2] = b
    return bytes(out)


def decode_bc1_thumbnail(payload: bytes, width: int, height: int) -> bytes:
    """One pixel per 4x4 block (block endpoint c0 color) — 16x faster than full decode."""
    bw, bh = max(width // 4, 1), max(height // 4, 1)
    out = bytearray(bw * bh * 3)
    for i in range(bw * bh):
        c0 = struct.unpack_from("<H", payload, i * 8)[0]
        r, g, b = color_565(c0)
        out[i * 3] = r
        out[i * 3 + 1] = g
        out[i * 3 + 2] = b
    return bytes(out), bw, bh


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + rgb[row * width * 3 : (row + 1) * width * 3] for row in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: render_vainglory_bc1.py <Data-dir> <out-dir>", file=sys.stderr)
        return 2
    root, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[int, int, int, Path, bytes]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or len(path.name) != 32:
            continue
        with path.open("rb") as stream:
            head = stream.read(HEADER)
        if len(head) < HEADER:
            continue
        size, mips, one, fmt, width, height, flags = struct.unpack_from("<7I", head, 0)
        file_size = path.stat().st_size
        if size != file_size or one != 1 or fmt != 2:
            continue
        if mip_chain_bytes(width, height, mips) + HEADER != file_size:
            continue
        candidates.append((width * height, mips, flags, path, b""))

    candidates.sort(reverse=True)
    print(f"BC1 candidates: {len(candidates)}")
    for area, mips, flags, path, _ in candidates[: int(sys.argv[0] and 40)][:40]:
        print(f"  {path.name} {path.parent.name} {area ** 0.5:.0f}px² mips={mips} flags={flags}")

    for i, (_, _, _, path, _) in enumerate(candidates[:24]):
        data = path.read_bytes()
        header = read_header(data)
        if header is None:
            continue
        mips, _fmt, width, height, _flags = header
        payload = data[HEADER:]
        top = mip_chain_bytes(width, height, 1)
        rgb, tw, th = decode_bc1_thumbnail(payload[:top], width, height)
        write_png(out_dir / f"bc1_{i:02d}_{width}x{height}_{path.name[:12]}.png", tw, th, rgb)
        print(f"rendered bc1_{i:02d} {width}x{height} (thumb {tw}x{th}) from {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
