"""Audit item-instance uses in an operator-owned passive match capture.

Reads existing PCAP bytes only. Reports numeric inventory/use/echo/buff
associations; never exports packet payloads or sends network traffic.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import cooldown_wire, item_input, vgdecode, wire


@dataclass(frozen=True)
class CapturedFrame:
    time: float
    opcode: int
    payload: bytes


def read_capture(path: Path, match_uuid: str, port: int) -> dict[str, list[CapturedFrame]]:
    """First-transmission TCP bytes, framed/decrypted independently per direction."""
    data = path.read_bytes()
    formats = {b"\xd4\xc3\xb2\xa1": ("<", 1_000_000), b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
               b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000), b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000)}
    if len(data) < 24 or data[:4] not in formats:
        raise ValueError("unsupported PCAP header")
    endian, divisor = formats[data[:4]]
    linktype = struct.unpack_from(endian + "I", data, 20)[0] & 255
    flows = {}
    offset = 24
    while offset < len(data):
        if offset + 16 > len(data):
            raise ValueError("truncated PCAP record header")
        seconds, fraction, length, _ = struct.unpack_from(endian + "4I", data, offset)
        offset += 16
        if offset + length > len(data):
            raise ValueError("truncated PCAP packet")
        packet = vgdecode.l3(data[offset:offset + length], linktype)
        offset += length
        if packet is not None and packet[-1] and port in (packet[1], packet[3]):
            flows.setdefault(packet[:4], []).append((packet[4], packet[5], seconds + fraction / divisor))
    cipher = wire.MatchCipher(match_uuid)
    result = {}
    for direction, port_index in (("c2s", 3), ("s2c", 1)):
        candidates = [key for key in flows if key[port_index] == port]
        if not candidates:
            raise ValueError(f"no {direction} match stream on port {port}")
        selected = max(candidates, key=lambda key: sum(len(body) for _, body, _ in flows[key]))
        segments = flows[selected]
        base = min(seq for seq, _, _ in segments)
        octets, received = {}, {}
        for seq, body, time in segments:
            for pos, octet in enumerate(body, seq - base):
                octets.setdefault(pos, octet)
                received.setdefault(pos, time)
        total = max(octets) + 1
        if len(octets) != total:
            raise ValueError("capture has a gap in the selected TCP stream")
        stream = bytes(octets[pos] for pos in range(total))
        frames, offset = [], 0
        while offset + 2 <= total:
            size = struct.unpack_from(">H", stream, offset)[0]
            if size >= 8 and size % 8 == 0 and offset + size + 2 <= total:
                opcode, payload = wire.decode_body(cipher, stream[offset + 2:offset + 2 + size])
                if wire.DISPATCH_MIN <= opcode <= wire.DISPATCH_MAX:
                    frames.append(CapturedFrame(received[offset], opcode, payload))
                    offset += 2 + size
                    continue
            offset += 1
        result[direction] = frames
    origin = result["c2s"][0].time
    return {direction: [CapturedFrame(frame.time - origin, frame.opcode, frame.payload)
                        for frame in frames] for direction, frames in result.items()}


def inspect_uses(frames: dict[str, list[CapturedFrame]], eid: int) -> list[dict]:
    uses = []
    used_echoes = set()
    for request_index, request in enumerate(frames["c2s"]):
        if request.opcode not in (item_input.ITEM_USE, item_input.GROUND_ITEM_USE):
            continue
        intent = item_input.parse_item_input(request.opcode, request.payload)
        creations = [row for row in frames["s2c"] if row.time <= request.time and row.opcode == 1085
                     and struct.unpack_from(">III", row.payload)[::2] == (eid, intent.instance_id)]
        native_item = struct.unpack_from(">I", creations[-1].payload, 4)[0] if creations else None
        echoes = [(index, row) for index, row in enumerate(frames["s2c"])
                  if index not in used_echoes and request.time <= row.time <= request.time + 1.0
                  and row.opcode == request.opcode and row.payload == request.payload]
        echo = echoes[0][1] if echoes else None
        if echoes:
            used_echoes.add(echoes[0][0])
        buffs = [row for row in frames["s2c"] if (echo.time if echo else request.time) <= row.time <= request.time + 0.6
                 and row.opcode == 1086 and len(row.payload) == 22
                 and struct.unpack_from(">I", row.payload)[0] == eid
                 and struct.unpack_from(">H", row.payload, 14)[0] in (259, 268, 270, 278, 279, 280, 281)]
        uses.append({"time": round(request.time, 6), "opcode": request.opcode,
                     "c2s_index": request_index,
                     "echo_s2c_index": echoes[0][0] if echoes else None,
                     "instance": intent.instance_id, "item": native_item,
                     "position": intent.target_position,
                     "echo_time": round(echo.time, 6) if echo else None,
                     "following_buffs": [{"time": round(row.time, 6),
                                          "kind": struct.unpack_from(">H", row.payload, 14)[0]} for row in buffs]})
    return uses


def inspect_contract(frames: dict[str, list[CapturedFrame]], eid: int,
                     item_id: int = 457, window: float = 6.0) -> dict:
    """Numeric observations, not a causal rule oracle or a visual verdict.

    Keep TCP frame order even when capture timestamps are equal or reordered.
    Include the one-second baseline and all target buffs/damage as confounders.
    Acknowledgements alone never qualify an operation as mechanically accepted.
    """
    if not math.isfinite(window) or window <= 0:
        raise ValueError("contract window must be finite and positive")
    attempts = []
    for use in inspect_uses(frames, eid):
        if use["item"] != item_id:
            continue
        start = frames["c2s"][use["c2s_index"]].time
        events = []
        for index, row in enumerate(frames["s2c"]):
            if not start - 1 <= row.time <= start + window:
                continue
            p = row.payload
            if len(p) < 4 or struct.unpack_from(">I", p)[0] != eid:
                continue
            event = {"s2c_index": index, "time": round(row.time, 6),
                     "relative_time": round(row.time - start, 6), "opcode": row.opcode}
            if row.opcode == 1053 and len(p) == 14:
                event.update(kind="resource_delta", resource_type=p[8],
                             amount=struct.unpack_from(">f", p, 4)[0])
            elif row.opcode == 1054 and len(p) >= 12:
                event.update(kind="combat_delta", source_eid=struct.unpack_from(">I", p, 4)[0],
                             amount=struct.unpack_from(">f", p, 8)[0])
            elif row.opcode in (1086, 1087) and len(p) == (22 if row.opcode == 1086 else 38):
                _, source, duration, instance, kind = struct.unpack_from(">IIeIH", p)
                event.update(kind="buff_add" if row.opcode == 1086 else "buff_state",
                             source_eid=source, duration=duration, instance=instance, buff_kind=kind)
            elif row.opcode == 1093 and len(p) == 14:
                event.update(kind="buff_cancel", instance=struct.unpack_from(">I", p, 4)[0])
            elif row.opcode == 1162 and len(p) == 22:
                timer = cooldown_wire.parse_timer_tick(p)
                event.update(kind="timer", tag=timer.tag, remaining=timer.remaining,
                             duration=timer.duration)
            else:
                continue
            events.append(event)
        after = [event for event in events if event["relative_time"] >= 0]
        heals = [event for event in after if event["kind"] == "combat_delta"
                 and event["source_eid"] == eid and event["amount"] > 0]
        resources = {}
        for event in after:
            if event["kind"] == "resource_delta":
                resources.setdefault(str(event["resource_type"]), []).append(event["amount"])
        attempts.append({**use, "input_stage": "OBSERVED",
                         "acknowledgement_stage": "OBSERVED" if use["echo_time"] is not None
                         else "UNACKNOWLEDGED_REASON_UNKNOWN",
                         "mechanical_acceptance": "NOT_ESTABLISHED_BY_CORRELATION",
                         "events": events,
                         "observed_summary": {
                             "positive_self_combat_count": len(heals),
                             "positive_self_combat_sum": sum(event["amount"] for event in heals),
                             "positive_self_combat_values": sorted(set(event["amount"] for event in heals)),
                             "positive_self_combat_intervals": [round(b["time"] - a["time"], 6)
                                                                for a, b in zip(heals, heals[1:])],
                             "resource_delta_values": resources}})
    return {"schema": "halcyon.item-contract.v1", "eid": eid, "item_id": item_id,
            "window_seconds": {"before": 1.0, "after": window},
            "attempts": attempts, "visual_acceptance": "UNVERIFIED",
            "simulation_fidelity": "UNVERIFIED",
            "limitations": [
                "Times are packet-capture arrival times, not authoritative simulation ticks.",
                "Largest TCP flow per direction is selected; decoder resynchronizes on unrecognized frames.",
                "Nearby buffs and deltas are observations, not exclusive causal attribution to this input.",
                "Initial HP, energy, level, build version, caps and other active rules are not reconstructed.",
                "No replay is emitted: these selected events omit spawn and other renderer dependencies.",
                "Resource type 4 is retained numerically; shield behavior needs independent validation."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", type=Path)
    parser.add_argument("--match", required=True, help="captured match UUID")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--eid", type=int, default=1500)
    parser.add_argument("--contract", action="store_true", help="report ordered mechanic observations")
    parser.add_argument("--item", type=int, default=457, help="native item ID for contract mode")
    parser.add_argument("--window", type=float, default=6.0, help="seconds after input in contract mode")
    parser.add_argument("--output", type=Path, help="new JSON evidence file outside the checkout")
    args = parser.parse_args()
    if args.output and args.output.resolve().is_relative_to(ROOT):
        parser.error("new QA evidence must be outside the checkout")
    frames = read_capture(args.pcap, args.match, args.port)
    report = (inspect_contract(frames, args.eid, args.item, args.window) if args.contract
              else inspect_uses(frames, args.eid))
    if args.contract:
        report["provenance"] = {
            "capture_path": str(args.pcap.resolve()),
            "capture_sha256": hashlib.sha256(args.pcap.read_bytes()).hexdigest(),
            "inspector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "match_uuid": args.match, "port": args.port,
            "client_version": "UNKNOWN_FROM_THIS_CAPTURE",
            "frame_counts": {direction: len(rows) for direction, rows in frames.items()}}
    rendered = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(rendered + "\n")
        print(args.output.resolve())
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
