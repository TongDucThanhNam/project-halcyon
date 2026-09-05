#!/usr/bin/env python3
"""Extract all self-declared embedded paths from a Vainglory content store.

Read-only: prints path strings that are stored in plaintext inside container
headers/surface records. Does not export asset payloads. Structural evidence
only — the same plaintext paths already indexed by inspect_vainglory_store.py,
dumped in full so the environment/map taxonomy can be studied.
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

RSC_HEADER_SIZE = 32
SURFACE_PATH_RE = re.compile(
    rb"Effects(?:/Menu)?"
    rb"(?P<path>/(?:Environment|Characters|UI|Effects)/"
    rb"[A-Za-z0-9_./ -]+\.Surface)\[[0-9]+\]\.shadergraph"
)


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def rsc_self_declared_path(data: bytes, file_size: int) -> str | None:
    if (
        len(data) < RSC_HEADER_SIZE + 7
        or data[:4] != b"RSC0"
        or data[RSC_HEADER_SIZE : RSC_HEADER_SIZE + 4] == b"CFF0"
        or u32(data, RSC_HEADER_SIZE) != file_size
    ):
        return None
    raw_path = data[RSC_HEADER_SIZE + 6 :].split(b"\0", 1)[0]
    if not raw_path.startswith(b"/"):
        return None
    try:
        return raw_path.decode("ascii")
    except UnicodeDecodeError:
        return None


def surface_self_declared_path(data: bytes) -> str | None:
    matches = {
        match.group("path").decode("ascii")
        for match in SURFACE_PATH_RE.finditer(data)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_vainglory_paths.py <Data-dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    seen: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and len(p.name) == 32):
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            head = stream.read(64)
        magic = head[:4]
        if magic not in (b"RSC0", b"CFF0") and file_size > 65536:
            continue
        data = path.read_bytes() if magic == b"RSC0" or file_size <= 65536 else head
        logical = rsc_self_declared_path(data, file_size)
        kind = "RSC0" if logical else None
        if logical is None:
            logical = surface_self_declared_path(data)
            kind = "surface" if logical else None
        if logical and kind:
            seen.setdefault(logical, kind)

    for logical in sorted(seen):
        print(f"{seen[logical]}\t{logical}")
    print(f"# total unique paths: {len(seen)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
