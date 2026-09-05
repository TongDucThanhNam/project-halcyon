#!/usr/bin/env python3
"""Try bounded standard decompression probes against one CFF0 INST payload."""

from __future__ import annotations

import argparse
import bz2
import hashlib
import io
import json
import lzma
import sys
import zlib
from pathlib import Path
from typing import Callable

import lz4.block
import lz4.frame
import zstandard

from inspect_vainglory_store import parse_cff_chunks


MAX_OUTPUT = 64 * 1024 * 1024
OFFSETS = (0, 4, 8, 12, 16)


def zlib_bounded(data: bytes, window_bits: int) -> bytes:
    decoder = zlib.decompressobj(window_bits)
    output = decoder.decompress(data, MAX_OUTPUT)
    if len(output) >= MAX_OUTPUT or not decoder.eof:
        raise ValueError("stream did not terminate within output bound")
    output += decoder.flush(MAX_OUTPUT - len(output))
    if len(output) >= MAX_OUTPUT:
        raise ValueError("stream reached output bound")
    return output


def lzma_bounded(data: bytes) -> bytes:
    decoder = lzma.LZMADecompressor()
    output = decoder.decompress(data, max_length=MAX_OUTPUT)
    if len(output) >= MAX_OUTPUT or not decoder.eof:
        raise ValueError("stream did not terminate within output bound")
    return output


def bz2_bounded(data: bytes) -> bytes:
    decoder = bz2.BZ2Decompressor()
    output = decoder.decompress(data, max_length=MAX_OUTPUT)
    if len(output) >= MAX_OUTPUT or not decoder.eof:
        raise ValueError("stream did not terminate within output bound")
    return output


def zstd_bounded(data: bytes) -> bytes:
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as reader:
        output = reader.read(MAX_OUTPUT + 1)
    if len(output) > MAX_OUTPUT:
        raise ValueError("stream exceeded output bound")
    return output


def lz4_frame_bounded(data: bytes) -> bytes:
    decoder = lz4.frame.LZ4FrameDecompressor()
    output = decoder.decompress(data, max_length=MAX_OUTPUT)
    if len(output) >= MAX_OUTPUT or not decoder.eof:
        raise ValueError("frame did not terminate within output bound")
    return output


def probes() -> dict[str, Callable[[bytes], bytes]]:
    return {
        "zlib": lambda data: zlib_bounded(data, zlib.MAX_WBITS),
        "raw-deflate": lambda data: zlib_bounded(data, -zlib.MAX_WBITS),
        "lzma-auto": lzma_bounded,
        "bzip2": bz2_bounded,
        "lz4-block-64KiB": lambda data: lz4.block.decompress(
            data, uncompressed_size=64 * 1024
        ),
        "lz4-block-1MiB": lambda data: lz4.block.decompress(
            data, uncompressed_size=1024 * 1024
        ),
        "lz4-block-16MiB": lambda data: lz4.block.decompress(
            data, uncompressed_size=16 * 1024 * 1024
        ),
        "lz4-frame": lz4_frame_bounded,
        "zstandard": zstd_bounded,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("container", type=Path)
    args = parser.parse_args()
    data = args.container.read_bytes()
    cff = parse_cff_chunks(data)
    if cff is None or not cff["valid"]:
        parser.error("input is not a complete supported CFF0 container")
    inst = next((chunk for chunk in cff["chunks"] if chunk["tag"] == "INST"), None)
    if inst is None:
        parser.error("container has no INST chunk")

    start = int(inst["offset"]) + 8
    end = int(inst["offset"]) + int(inst["size_including_header"])
    payload = data[start:end]
    attempts: list[dict[str, object]] = []
    for name, probe in probes().items():
        for offset in OFFSETS:
            try:
                output = probe(payload[offset:])
                attempts.append(
                    {
                        "codec": name,
                        "offset": offset,
                        "success": True,
                        "output_bytes": len(output),
                        "output_sha256": hashlib.sha256(output).hexdigest(),
                    }
                )
            except Exception as error:  # Decoder APIs use different exception types.
                attempts.append(
                    {
                        "codec": name,
                        "offset": offset,
                        "success": False,
                        "error_type": type(error).__name__,
                    }
                )

    result = {
        "container": str(args.container.resolve()),
        "container_sha256": hashlib.sha256(data).hexdigest(),
        "inst_payload_bytes": len(payload),
        "inst_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "offsets": OFFSETS,
        "probes": list(probes()),
        "attempt_count": len(attempts),
        "success_count": sum(1 for attempt in attempts if attempt["success"]),
        "attempts": attempts,
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
