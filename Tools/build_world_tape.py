"""Rebuild the operator-held world-init tape from the owned corpus capture.

The live WORLD phase replays a measured bootstrap tape — every s2c frame the
corpus server sent after the client's c2s 1137 (world request). The original
53,632-byte ``world_tape.bin`` is an operator-held external input (payload
rule, AGENTS.md boundary 2); this command reproduces it reproducibly using
the repository's own decoders (``server.vgdecode`` link layers,
``server.wire.MatchCipher`` crypto) — no TEMP-side helper is a runtime
dependency, and the external capture path is an explicit argument.

Measured recipe (validated against the digest the production loader pins in
``server/world_tape.py`` — a byte-faithful rebuild must match it exactly):

- reassemble each TCP flow, keeping per-byte capture timestamps and the ack
  carried by every c2s segment (ACK causality: the ack of the segment
  carrying c2s 1137 says how many s2c bytes the client had received);
- decrypt both directions with the corpus match UUID; the c2s stream starts
  with the plaintext 134-byte route greeting;
- keep the s2c frames the client had NOT fully received when it sent 1137;
- the tape file starts at the FIRST 1087 allocation record (the loader's
  skip-until-1087 then is a no-op), keeps frames within the window, and
  floors each frame's milliseconds relative to that first 1087.

Safety: the output must stay outside this repository; an existing file is
never overwritten (the destination is opened exclusively); on validation
failure a ``*.candidate-unvalidated.bin`` sibling is written instead and the
process fails loudly. A caller-supplied ``--expect-sha256`` that differs
from the production pin is reported as a custom expectation, never as
production-pin validation.

Usage:
  python Tools/build_world_tape.py --pcap <vgfull.pcap> \
      --match-uuid b9f511e0-11cd-4cfa-ad62-dc8612b8d270 \
      --output <external tape path> [--window-seconds 12.5]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WINDOW_SECONDS = 12.5
ENTITY_DATA_OPCODE = 1087
_GREETING_LEN = 134


class MalformedCapture(ValueError):
    """Structured parse failure: bad magic, oversized packet, bad frames."""


class TruncatedCapture(ValueError):
    """Structured truncation failure: header or packet cut short."""


def _parse_pcap_with_acks(path: Path):
    """(flows) — per flow: (segments, stream, tsmap, base).

    segments: sorted [(seq, ack, body, ts)]; stream/tsmap reconstruct the
    contiguous TCP byte stream with each byte's capture time (first
    transmission wins). Reuses ``server.vgdecode`` for link/network decode.
    """
    from server import vgdecode

    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 24:
        raise TruncatedCapture(
            f"pcap shorter than its 24-byte header: {len(data)} B")
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4"):
        endian = "<" if magic == b"\xd4\xc3\xb2\xa1" else ">"
        ts_div = 1e6                       # microsecond resolution
    elif magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        # nanosecond-resolution pcap: handled explicitly, never misread
        endian = "<" if magic == b"\x4d\x3c\xb2\xa1" else ">"
        ts_div = 1e9
    else:
        raise MalformedCapture(f"bad pcap magic {magic!r} in {path}")
    linktype = struct.unpack(endian + "I", data[20:24])[0] & 0xFF
    pkts, off = [], 24
    n = len(data)
    while off + 16 <= n:
        ts, tus, incl, _orig = struct.unpack(endian + "IIII", data[off:off + 16])
        off += 16
        if incl > 262144:
            raise MalformedCapture(
                f"oversized captured packet ({incl} B) at offset {off - 16}")
        if off + incl > n:
            raise TruncatedCapture(
                f"final packet header declares {incl} B but only {n - off} B remain")
        pkts.append((ts + tus / ts_div, data[off:off + incl]))
        off += incl

    segs: dict[tuple, list] = {}
    for ts, pkt in pkts:
        decoded = vgdecode.l3(pkt, linktype)
        if not decoded:
            continue
        src, sport, dst, dport, seq, body = decoded
        if not body:
            continue
        ip_off = 14 if linktype == 1 else (16 if linktype == 113 else None)
        if ip_off is None:
            ip_off = 0 if (pkt[0] >> 4) == 4 else 14
        ihl = (pkt[ip_off] & 0xF) * 4
        tcp = pkt[ip_off + ihl:]
        if len(tcp) < 20:
            continue
        ack = struct.unpack(">I", tcp[8:12])[0]
        segs.setdefault((src, sport, dst, dport), []).append((seq, ack, body, ts))

    flows = {}
    for key, lst in segs.items():
        lst = sorted(lst, key=lambda item: item[0])
        base = min(s[0] for s in lst)
        buf, tsmap = {}, {}
        for seq, _ack, body, ts in lst:
            row = seq - base
            for j, ch in enumerate(body):
                idx = row + j
                if idx not in buf:
                    buf[idx] = ch
                    tsmap[idx] = ts
        total = max(buf) + 1
        missing = total - len(buf)
        if missing:
            raise MalformedCapture(
                f"TCP stream gap in flow {key}: {missing} bytes never captured")
        stream = bytes(buf[i] for i in range(total))
        segdict = {}
        for seq, ack, body, ts in lst:      # first transmission wins
            segdict.setdefault(seq, (ack, body, ts))
        flows[key] = (lst, stream, [tsmap[i] for i in range(total)], base, segdict)
    return flows


def collect_post_1137_frames(pcap_path: Path, match_uuid: str):
    """ACK-causal s2c frames after c2s 1137, with real capture times.

    Returns (records, report): records are (t_rel_seconds, opcode, payload)
    in stream order, relative to the first post-ACK frame.
    """
    from server import wire as server_wire

    flows = _parse_pcap_with_acks(pcap_path)
    match_flows = [k for k in flows if 7034 in (k[1], k[3])]
    if not match_flows:
        raise SystemExit("no TCP flow on match port 7034 in the capture")
    s2c_key = next(k for k in match_flows if k[1] == 7034)
    c2s_key = next(k for k in match_flows if k[3] == 7034)
    _s2c_segs, s2c_stream, s2c_tsmap, s2c_base, _ = flows[s2c_key]
    _c2s_segs, c2s_stream, c2s_tsmap, c2s_base, c2s_segdict = flows[c2s_key]

    cipher = server_wire.MatchCipher(match_uuid)
    s2c = _walk(s2c_stream, cipher, 0)
    (greeting_len,) = struct.unpack_from(">H", c2s_stream, 0)
    c2s = _walk(c2s_stream, cipher, 2 + greeting_len)

    def off_ts(tsmap, offset):
        return tsmap[min(offset, len(tsmap) - 1)]

    def ack_at(entry):
        offset, length = entry[0], entry[1]
        last_byte = offset + 2 + length - 1
        acks = [a for _seq, (a, _body, _ts) in c2s_segdict.items()
                if _seq - c2s_base <= last_byte < _seq - c2s_base + len(_body)]
        return max(acks) - s2c_base if acks else None

    if not any(e[2] == 1137 for e in c2s):
        raise MalformedCapture(
            "no c2s 1137 (world request) in the stream — wrong match UUID or "
            "capture without a world entry")
    i1137 = next(i for i, e in enumerate(c2s) if e[2] == 1137)
    ack1137 = ack_at(c2s[i1137])
    if ack1137 is None:
        raise MalformedCapture("no TCP ack observed for the c2s 1137 frame")

    post = [s for s in s2c if s[0] + 2 + s[1] > ack1137]
    if not post:
        raise MalformedCapture("no s2c frames after the 1137 acknowledgement")
    t_first = off_ts(s2c_tsmap, post[0][0])
    t_first1087 = None
    records = []
    for offset, length, op, payload in post:
        t_rel = max(0.0, off_ts(s2c_tsmap, offset) - t_first)
        if op == ENTITY_DATA_OPCODE and t_first1087 is None:
            t_first1087 = t_rel
        records.append((t_rel - (t_first1087 or 0.0), op, payload))
    report = {
        "pcap": str(pcap_path),
        "pcap_sha256": hashlib.sha256(pcap_path.read_bytes()).hexdigest(),
        "match_uuid": match_uuid,
        "s2c_frames_total": len(s2c),
        "post_1137_frames": len(post),
    }
    return records, report


def _walk(stream: bytes, cipher, start: int):
    """Resync-validated frame walk (repository semantics, mirror of the
    external helper: small c2s frames decrypt too)."""
    from server import wire as server_wire

    frames, i, n = [], start, len(stream)
    while i + 2 <= n:
        (length,) = struct.unpack_from(">H", stream, i)
        if length >= 8 and length % 8 == 0 and i + 2 + length <= n:
            raw = stream[i + 2:i + 2 + length]
            if length >= 16:
                head = cipher.decrypt(raw[:8])
                (op,) = struct.unpack(">H", head[:2])
                if server_wire.DISPATCH_MIN <= op <= server_wire.DISPATCH_MAX:
                    op, payload = server_wire.decode_body(cipher, raw)
                    frames.append((i, length, op, payload))
                    i += 2 + length
                    continue
            else:
                # small frames (c2s actions 1123/1119/1134/1137) decrypt too
                clear = cipher.decrypt(raw)
                (op,) = struct.unpack(">H", clear[:2])
                if 1000 <= op <= 1168:
                    frames.append((i, length, op, clear[2:]))
                    i += 2 + length
                    continue
        i += 1
    return frames


def build_candidate_records(records, window_seconds):
    """The measured original recipe: start at the first 1087 allocation,
    keep frames within the window, floor the relative milliseconds."""
    started = False
    kept = []
    for t, op, payload in records:
        if not started:
            if op != ENTITY_DATA_OPCODE:
                continue
            started = True
        if t > window_seconds:
            break
        kept.append((int(t * 1000.0), op, payload))
    return kept


def loader_digest(records_ms):
    """Digest exactly as server.world_tape.complete_corpus_bootstrap computes
    it over the loader's post-skip records."""
    digest = hashlib.sha256()
    started = False
    count = 0
    for t_ms, op, payload in records_ms:
        if not started:
            if op != ENTITY_DATA_OPCODE:
                continue
            started = True
        body = struct.pack(">H", op) + payload
        digest.update(struct.pack(">IH", t_ms, len(body)))
        digest.update(body)
        count += 1
    return digest.hexdigest(), count


def _pinned_loader_digest() -> str:
    source = (ROOT / "server" / "world_tape.py").read_text(encoding="utf-8")
    marker = '_TRUNCATED_BOOTSTRAP_SHA256 = "'
    i = source.index(marker) + len(marker)
    return source[i:i + 64]


def _serialize(records_ms):
    out = bytearray()
    for t_ms, op, payload in records_ms:
        body = struct.pack(">H", op) + payload
        out += struct.pack(">IH", t_ms, len(body)) + body
    return bytes(out)


def _exclusive_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", required=True,
                        help="owned corpus capture (outside the repository)")
    parser.add_argument("--match-uuid", required=True,
                        help="corpus match identity for the stream key")
    parser.add_argument("--output", required=True,
                        help="external world_tape.bin destination (never inside the repo)")
    parser.add_argument("--window-seconds", type=float, default=WINDOW_SECONDS)
    parser.add_argument("--expect-sha256", default=None,
                        help="custom expectation; reported as custom, never "
                             "as production-pin validation")
    args = parser.parse_args(argv)

    pcap_path = Path(args.pcap)
    out_path = Path(args.output).resolve()
    repository = ROOT.resolve()
    # The base report carries the input identity and parameters through every
    # outcome; extraction results are MERGED in, never replacing it.
    report: dict = {
        "pcap": str(pcap_path),
        "pcap_sha256": None,
        "match_uuid": args.match_uuid,
        "window_seconds": args.window_seconds,
        "output": str(out_path),
    }
    if not math.isfinite(args.window_seconds) or args.window_seconds < 0:
        report["error"] = "window_seconds must be finite and nonnegative"
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 2
    if out_path == repository or repository in out_path.parents:
        report["error"] = "repo destination refused (payload rule)"
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 2
    if out_path.exists():
        report["error"] = "output already exists; never overwrite"
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 2
    if not pcap_path.is_file():
        report["error"] = "pcap not found"
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 2
    report["pcap_sha256"] = hashlib.sha256(pcap_path.read_bytes()).hexdigest()

    try:
        records, extraction = collect_post_1137_frames(pcap_path,
                                                       args.match_uuid)
    except (MalformedCapture, TruncatedCapture) as exc:
        report["error"] = f"malformed capture: {exc}"
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 2
    except SystemExit as exc:
        report["error"] = f"extraction failed: {exc}"
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 2
    report["extraction"] = extraction
    report["match_uuid_used"] = args.match_uuid

    records_ms = build_candidate_records(records, args.window_seconds)
    digest, alloc_count = loader_digest(records_ms)
    payload = _serialize(records_ms)
    expected = args.expect_sha256 or _pinned_loader_digest()
    is_production_pin = (args.expect_sha256 is None
                         and digest == _pinned_loader_digest())
    report.update({
        "records_in_window": len(records_ms),
        "bytes_in_window": len(payload),
        "alloc_1087_records": sum(1 for _t, op, _p in records_ms
                                  if op == ENTITY_DATA_OPCODE),
        "first_record": {"t_ms": records_ms[0][0], "op": records_ms[0][1]}
        if records_ms else None,
        "last_record": {"t_ms": records_ms[-1][0], "op": records_ms[-1][1]}
        if records_ms else None,
        "tape_sha256": hashlib.sha256(payload).hexdigest(),
        "loader_window_sha256": digest,
        "expected_sha256": expected,
        "validation": ("production-pin" if is_production_pin else
                       "custom-expectation" if digest == expected else
                       "MISMATCH"),
        "byte_faithful": digest == expected,
    })

    if digest != expected:
        candidate = out_path.with_name(
            out_path.stem + ".candidate-unvalidated.bin")
        if candidate.exists():
            report["error"] = "candidate already exists; never overwrite"
            print(json.dumps(report, indent=1), file=sys.stderr)
            return 2
        try:
            _exclusive_write(candidate, payload)
        except OSError as exc:
            report["error"] = f"candidate write failed: {exc}"
            print(json.dumps(report, indent=1), file=sys.stderr)
            return 2
        report["candidate_path"] = str(candidate)
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 3
    try:
        _exclusive_write(out_path, payload)
    except OSError as exc:
        report["error"] = f"output write failed: {exc}"
        print(json.dumps(report, indent=1), file=sys.stderr)
        return 2
    report["output_bytes"] = out_path.stat().st_size
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
