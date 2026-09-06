"""World-init tape loader — replay bootstrap for the entity layer.

The entity world the client waits for after 1134/1137 (1087 allocations,
1053/1086/1067/1164/1045 deltas, 1010 full updates) is measured, not yet
simulated: T3 owns the real simulation. Until then the WORLD phase streams
a *tape* — every s2c frame the corpus server sent between the client's
1137 and its first movement (vgfull.pcap match 1, 0..12.5 s) — paced in
real time. The tape file lives OUTSIDE the repo (payload rule, AGENTS.md
boundary 2); this module only reads and validates the format.

Tape record: [u32 t_ms][u16 body_len][body], body = [u16 BE opcode][payload]
exactly as wire.encode_message consumes it. Times are relative to the tape
start, monotonically non-decreasing.
"""
from __future__ import annotations

import struct

RECORD_HEAD = struct.Struct(">IH")


def load_tape(path: str, skip_until_op: int | None = None):
    """Return [(t_ms, body)] or None when the file is absent.

    skip_until_op drops every frame before the first body whose opcode
    matches — used to skip the init block the match server already emits
    live from the roster (1135/1006/1105/1011/1162/1055/echoes).
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return None
    frames, off, last_ms = [], 0, -1
    while off < len(data):
        if off + RECORD_HEAD.size > len(data):
            raise ValueError(f"truncated tape record head at {off}")
        t_ms, blen = RECORD_HEAD.unpack_from(data, off)
        off += RECORD_HEAD.size
        if off + blen > len(data):
            raise ValueError(f"truncated tape body at {off}")
        body = data[off:off + blen]
        off += blen
        if blen < 2:
            raise ValueError(f"tape body shorter than an opcode at {off}")
        if t_ms < last_ms:
            raise ValueError(f"tape time went backwards at {t_ms} ms")
        last_ms = t_ms
        frames.append((t_ms, body))
    if skip_until_op is not None:
        for k, (_t, body) in enumerate(frames):
            if struct.unpack_from(">H", body)[0] == skip_until_op:
                frames = frames[k:]
                break
        else:
            frames = []
    return frames
