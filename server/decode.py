"""Project Halcyon — corpus decoder (acceptance criteria 2 & 3, phase0.md).

Two readers over the canonical corpus (read-only, never copied into repo):

  pcap mode  reassemble TCP streams from a capture, walk the encrypted
             match stream with the §15.3 grammar + §15.4 crypto, resync-
             validated (an offset is accepted only when the first Blowfish
             block decrypts to a dispatch-range opcode) — the vgdecode.py
             walk, now on top of wire.MatchCipher.
  vgr mode   walk the client's own decoded auto-recording with the §15.6
             grammar ``[u32 token][u32 BE len, includes opcode][u16 opcode]
             [payload len-2]``.

CLI:
  python -m server.decode pcap <capture.pcap> <match-uuid>
  python -m server.decode vgr  <dir-with-.vgr-chunks>
  (direct script form ``python server/decode.py …`` also works)
"""
from __future__ import annotations

import glob
import json
import os
import struct
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import vgdecode
    import wire
else:
    from . import vgdecode
    from . import wire


# --------------------------------------------------------------------------
# Encrypted pcap stream walk (acceptance 2)
# --------------------------------------------------------------------------

def _opcode_ok(cipher, stream: bytes, j: int, length: int) -> bool:
    """Resync rule: candidate frame must decrypt to a dispatch-range opcode."""
    if not (16 <= length <= 3000 and length % 8 == 0 and j + 2 + length <= len(stream)):
        return False
    head = cipher.decrypt(stream[j + 2:j + 10])
    (op,) = struct.unpack(">H", head[:2])
    return wire.DISPATCH_MIN <= op <= wire.DISPATCH_MAX


def walk_stream(stream: bytes, cipher: wire.MatchCipher, start: int = 0):
    """Walk [u16 BE len][body] from `start`; returns (frames, consumed, total, missed).

    frames: list of (opcode, payload). Small 8-aligned bodies are decrypted
    too and named when they decode to a catalogue opcode — c2s actions
    (1123/1119/1137…) and s2c echoes carry 6–8 B payloads. Only frames that
    fail decryption stay raw as (0, body) — pre-key control frames.
    """
    frames, i, missed = [], start, 0
    n = len(stream)
    while i + 2 <= n:
        (length,) = struct.unpack_from(">H", stream, i)
        if length >= 8 and length % 8 == 0 and i + 2 + length <= n:
            try:
                op, payload = wire.decode_body(cipher, stream[i + 2:i + 2 + length])
            except wire.WireError:
                op = -1
            if wire.DISPATCH_MIN <= op <= wire.DISPATCH_MAX:
                frames.append((op, payload))
                i += 2 + length
                continue
        if 2 <= length < 16 and i + 2 + length <= n:
            frames.append((0, stream[i + 2:i + 2 + length]))
            i += 2 + length
            continue
        missed += 1
        i += 1
    return frames, i - start, n - start, missed


def decode_pcap(path: str, match_uuid: str):
    """Decode the match stream from a pcap. Returns (frames, info) like vgdecode."""
    cipher = wire.MatchCipher(match_uuid)
    linktype, flows = vgdecode.reassemble(path)
    candidates = sorted(flows.items(), key=lambda kv: -len(kv[1]))
    best = None
    for key, stream in candidates:
        if len(stream) < 256:
            continue
        for start in range(0, 64):
            result = walk_stream(stream, cipher, start)
            coverage = result[1] / max(1, result[2])
            if result[0] and (best is None or coverage > best[0]):
                best = (coverage, key, result, stream, start)
            if result[0] and coverage > 0.95:
                break
        if best and best[0] > 0.95:
            break
    if not best or best[0] < 0.5:
        return None, dict(linktype=linktype,
                          flows={str(k): len(v) for k, v in flows.items()},
                          best_cov=best[0] if best else 0.0)
    coverage, key, (frames, consumed, total, missed), stream, start = best
    info = dict(linktype=linktype, flow=str(key), consumed=consumed, total=total,
                start=start, missed=missed, cov=round(coverage, 4), nframes=len(frames))
    return frames, info


# --------------------------------------------------------------------------
# .vgr frame-log walk (acceptance 3, §15.6)
# --------------------------------------------------------------------------

VGR_HEADER_SIZE = 8  # [u32 token][u32 BE len] — len includes the u16 opcode


def walk_vgr(path: str):
    """Walk one .vgr chunk. Returns (frames, stats).

    frames: list of (token, opcode, payload). stats counts walk failures —
    a record whose declared length overruns the file, or trailing bytes.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    frames, failures, tokens = [], 0, {}
    i, n = 0, len(data)
    while i + VGR_HEADER_SIZE <= n:
        token, length = struct.unpack_from(">II", data, i)
        if length < 2 or i + VGR_HEADER_SIZE + length > n:
            failures += 1
            break
        (opcode,) = struct.unpack_from(">H", data, i + 8)
        frames.append((token, opcode, data[i + 10:i + 8 + length]))
        tokens[token] = tokens.get(token, 0) + 1
        i += VGR_HEADER_SIZE + length
    trailing = n - i
    if trailing:
        failures += 1
    stats = dict(path=os.path.basename(path), size=n, frames=len(frames),
                 failures=failures, trailing=trailing,
                 top_tokens=sorted(tokens.items(), key=lambda kv: -kv[1])[:4])
    return frames, stats


def walk_vgr_dir(directory: str):
    """Walk every .vgr chunk in a directory. Returns (frames, per_file_stats)."""
    all_frames, per_file = [], []
    for path in sorted(glob.glob(os.path.join(directory, "*.vgr"))):
        frames, stats = walk_vgr(path)
        all_frames.extend(frames)
        per_file.append(stats)
    return all_frames, per_file


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _main(argv):
    if len(argv) < 3 or argv[1] not in ("pcap", "vgr"):
        print(__doc__)
        return 2
    import collections
    if argv[1] == "pcap":
        if len(argv) != 4:
            print("usage: decode.py pcap <capture.pcap> <match-uuid>")
            return 2
        frames, info = decode_pcap(argv[2], argv[3])
        if frames is None:
            print(json.dumps({"ok": False, **info}, indent=1, default=str))
            return 1
        hist = collections.Counter(op for op, _ in frames)
        print(json.dumps({"ok": True, **info,
                          "top_ops": [(op, cnt) for op, cnt in hist.most_common(20)]},
                         default=str))
        return 0
    frames, per_file = walk_vgr_dir(argv[2])
    hist = collections.Counter(op for _, op, _ in frames)
    total_failures = sum(s["failures"] for s in per_file)
    print(json.dumps({
        "ok": total_failures == 0,
        "files": len(per_file),
        "frames": len(frames),
        "failures": total_failures,
        "top_ops": [(op, cnt) for op, cnt in hist.most_common(20)],
        "per_file": per_file,
    }, indent=1, default=str))
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
