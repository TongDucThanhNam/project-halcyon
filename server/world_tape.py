"""World-init tape loader — replay bootstrap for the entity layer.

The entity world the client waits for after 1134/1137 (1087 allocations,
1053/1086/1067/1164/1045 deltas, 1010 full updates) is measured, not yet
simulated: T3 owns the real simulation. Until then the WORLD phase streams
a *tape* — every s2c frame the corpus server sent between the client's
1137 and its first movement (vgfull.pcap match 1, 0..12.5 s) — paced in
real time. The tape file lives OUTSIDE the repo (payload rule, AGENTS.md
boundary 2). The known truncated bootstrap is completed in memory; the
operator's tape file is never rewritten.

Tape record: [u32 t_ms][u16 body_len][body], body = [u16 BE opcode][payload]
exactly as wire.encode_message consumes it. Times are relative to the tape
start, monotonically non-decreasing.
"""
from __future__ import annotations

import hashlib
import struct

RECORD_HEAD = struct.Struct(">IH")

# vgfull match 1 after skip_until_op=1087: 1,458 records, ending at 12.478s.
# Pin the entire prefix, including timestamps, rather than treating buff type
# 255 as a general movement lock or cancelling instances in unrelated tapes.
# Evidence: Docs/Teardown/vainglory-locomotion-handoff.md.
_TRUNCATED_BOOTSTRAP_SHA256 = "20c553224e5523ff354536fc4594230ebec76e1ea72755de8c855b8cead1d341"
STARTUP_CANCEL_MS = 16672
STARTUP_CANCEL_INSTANCES = (
    (1500, 2024), (1515, 2021), (1516, 2018),
    (1517, 2015), (1518, 2012), (1519, 2009),
)


def complete_corpus_bootstrap(frames):
    """Complete only the measured, trimmed vgfull bootstrap, without mutation.

    The original ends before six explicit ActionCancelBuff records. Recreate
    those from protocol constants at their original timestamp. Already extended
    candidates, longer captures, synthetic tapes and other corpora pass through
    unchanged; matching the whole input makes this operation idempotent.
    Call after load_tape(..., skip_until_op=1087).
    """
    digest = hashlib.sha256()
    for t_ms, body in frames:
        digest.update(RECORD_HEAD.pack(t_ms, len(body)))
        digest.update(body)
    if digest.hexdigest() != _TRUNCATED_BOOTSTRAP_SHA256:
        return frames
    return frames + [
        (STARTUP_CANCEL_MS, struct.pack(">HII", 1093, eid, instance) + bytes(6))
        for eid, instance in STARTUP_CANCEL_INSTANCES
    ]


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
