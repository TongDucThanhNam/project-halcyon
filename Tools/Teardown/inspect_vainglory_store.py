#!/usr/bin/env python3
"""Measure a Vainglory 4.13 PC content store without extracting payloads.

The script records container structure, embedded asset-path metadata and a
small manifest/chunk sample. It deliberately does not export asset payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from collections import Counter
from pathlib import Path


RSC_HEADER_SIZE = 32
FOURCC_RE = re.compile(rb"^[A-Z0-9]{4}$")
SURFACE_PATH_RE = re.compile(
    rb"Effects(?:/Menu)?"
    rb"(?P<path>/(?:Environment|Characters|UI|Effects)/"
    rb"[A-Za-z0-9_./ -]+\.Surface)\[[0-9]+\]\.shadergraph"
)


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    length = len(data)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in Counter(data).values()
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def parse_cff_chunks(data: bytes) -> dict[str, object] | None:
    if len(data) < 24:
        return None
    if data[:4] == b"CFF0":
        cff_offset = 0
    elif len(data) >= RSC_HEADER_SIZE + 24 and data[RSC_HEADER_SIZE : RSC_HEADER_SIZE + 4] == b"CFF0":
        cff_offset = RSC_HEADER_SIZE
    else:
        return None

    declared_size = u32(data, cff_offset + 4)
    header_size = u32(data, cff_offset + 20)
    if header_size < 24 or cff_offset + header_size > len(data):
        return {
            "offset": cff_offset,
            "declared_size": declared_size,
            "header_size": header_size,
            "valid": False,
            "chunks": [],
        }

    chunks: list[dict[str, object]] = []
    position = cff_offset + header_size
    while position + 8 <= len(data):
        tag_bytes = data[position : position + 4]
        size = u32(data, position + 4)
        if not FOURCC_RE.match(tag_bytes) or size < 8 or position + size > len(data):
            break
        chunks.append(
            {
                "tag": tag_bytes.decode("ascii"),
                "offset": position,
                "size_including_header": size,
                "payload_size": size - 8,
            }
        )
        position += size

    return {
        "offset": cff_offset,
        "declared_size": declared_size,
        "header_size": header_size,
        "valid": bool(chunks) and position == len(data),
        "parsed_end": position,
        "chunks": chunks,
    }


def scan_store(root: Path, include_ui_paths: bool) -> dict[str, object]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    hashed_files = [path for path in files if len(path.name) == 32]

    rsc_count = 0
    exact_rsc_size_count = 0
    cff_count = 0
    cff_declared_file_size_count = 0
    valid_chunk_walk_count = 0
    chunk_tags: Counter[str] = Counter()
    magic_counts: Counter[str] = Counter()
    self_declared_paths: set[str] = set()
    self_declared_kinds: Counter[str] = Counter()
    self_declared_roots: Counter[str] = Counter()
    ui_entries: list[dict[str, str]] = []
    manifest_samples: list[dict[str, object]] = []
    total_bytes = 0

    for path in hashed_files:
        file_size = path.stat().st_size
        total_bytes += file_size
        with path.open("rb") as stream:
            head = stream.read(64)
        magic = head[:4]
        magic_label = (
            magic.decode("ascii")
            if len(magic) == 4 and all(0x20 <= byte <= 0x7E for byte in magic)
            else magic.hex()
        )
        magic_counts[magic_label] += 1

        is_container = magic in (b"RSC0", b"CFF0")
        should_scan_surface = not is_container and file_size <= 65536
        data = path.read_bytes() if is_container or should_scan_surface else head

        logical_path = rsc_self_declared_path(data, file_size)
        path_kind = "RSC0:bin" if logical_path is not None else None
        if logical_path is None and should_scan_surface:
            logical_path = surface_self_declared_path(data)
            path_kind = "surface" if logical_path is not None else None
        if logical_path is not None and path_kind is not None:
            self_declared_paths.add(logical_path)
            self_declared_kinds[path_kind] += 1
            parts = logical_path.split("/")
            root_name = parts[1] if len(parts) > 1 else ""
            self_declared_roots[root_name] += 1
            if root_name == "UI":
                ui_entries.append(
                    {
                        "kind": path_kind,
                        "path": logical_path,
                        "file": path.relative_to(root).as_posix(),
                    }
                )

        if is_container and b"HeroManifest" in data and len(manifest_samples) < 4:
            manifest_samples.append(
                {
                    "file": path.relative_to(root).as_posix(),
                    "bytes": len(data),
                    "sha256": sha256(data),
                    "magic": magic_label,
                    "cff": None,
                }
            )

        cff = parse_cff_chunks(data)
        if cff is not None:
            cff_count += 1
            if cff["declared_size"] == len(data):
                cff_declared_file_size_count += 1
            if cff["valid"]:
                valid_chunk_walk_count += 1
            for chunk in cff["chunks"]:
                chunk_tags[str(chunk["tag"])] += 1

        if b"HeroManifest" in data:
            sample = next(
                (
                    candidate
                    for candidate in manifest_samples
                    if candidate["file"] == path.relative_to(root).as_posix()
                ),
                None,
            )
            if sample is not None:
                sample["cff"] = cff
                if cff is not None:
                    for chunk in sample["cff"]["chunks"]:
                        start = int(chunk["offset"]) + 8
                        end = int(chunk["offset"]) + int(chunk["size_including_header"])
                        chunk["payload_entropy"] = round(entropy(data[start:end]), 5)

        if magic != b"RSC0" or len(data) < RSC_HEADER_SIZE:
            continue

        rsc_count += 1
        payload_size_a = u32(data, 4)
        payload_size_b = u32(data, 8)
        if payload_size_a == payload_size_b == len(data) - RSC_HEADER_SIZE:
            exact_rsc_size_count += 1

    ui_paths = sorted(entry["path"] for entry in ui_entries)
    ui_shadergraph_paths = sorted(
        entry["path"]
        for entry in ui_entries
        if entry["kind"] == "RSC0:bin" and entry["path"].endswith(".shadergraph")
    )
    pretarget_paths = sorted(path for path in ui_shadergraph_paths if "PreTarget" in path)
    legacy_roots = {"Environment", "Characters", "UI", "Effects"}
    legacy_selected_count = sum(
        count for name, count in self_declared_roots.items() if name in legacy_roots
    )
    result: dict[str, object] = {
        "root": str(root.resolve()),
        "all_files": len(files),
        "hashed_name_files": len(hashed_files),
        "total_bytes": total_bytes
        + sum(path.stat().st_size for path in files if len(path.name) != 32),
        "rsc0_files": rsc_count,
        "rsc0_exact_payload_size_files": exact_rsc_size_count,
        "cff0_files": cff_count,
        "cff0_declares_whole_file_size": cff_declared_file_size_count,
        "valid_chunk_walks_when_size_includes_header": valid_chunk_walk_count,
        "magic_counts_top_20": dict(magic_counts.most_common(20)),
        "other_magic_files": sum(magic_counts.values())
        - sum(count for _, count in magic_counts.most_common(20)),
        "self_declared_paths": len(self_declared_paths),
        "self_declared_path_kinds": dict(self_declared_kinds),
        "self_declared_path_roots": dict(
            sorted(self_declared_roots.items(), key=lambda item: (-item[1], item[0]))
        ),
        "legacy_four_root_path_count": legacy_selected_count,
        "ui_self_declared_paths": len(ui_paths),
        "ui_rsc0_shadergraph_paths": len(ui_shadergraph_paths),
        "ui_surface_records": len(ui_paths) - len(ui_shadergraph_paths),
        "pretarget_paths": pretarget_paths,
        "chunk_tags": dict(sorted(chunk_tags.items())),
        "hero_manifest_samples": manifest_samples,
    }
    if include_ui_paths:
        result["ui_path_values"] = ui_entries
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="Path to the extracted Data directory")
    parser.add_argument(
        "--include-ui-paths",
        action="store_true",
        help="Include UI path strings in JSON output",
    )
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error(f"not a directory: {args.root}")
    print(json.dumps(scan_store(args.root, args.include_ui_paths), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
