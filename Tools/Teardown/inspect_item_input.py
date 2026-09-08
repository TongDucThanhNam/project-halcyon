"""Audit item-instance uses in an operator-owned passive match capture.

Reads existing PCAP bytes only. Reports numeric inventory/use/echo/buff
associations; never exports packet payloads or sends network traffic.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import item_input, vgdecode, wire


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
    for request in frames["c2s"]:
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
                     "instance": intent.instance_id, "item": native_item,
                     "position": intent.target_position,
                     "echo_time": round(echo.time, 6) if echo else None,
                     "following_buffs": [{"time": round(row.time, 6),
                                          "kind": struct.unpack_from(">H", row.payload, 14)[0]} for row in buffs]})
    return uses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", type=Path)
    parser.add_argument("--match", required=True, help="captured match UUID")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--eid", type=int, default=1500)
    args = parser.parse_args()
    print(json.dumps(inspect_uses(read_capture(args.pcap, args.match, args.port), args.eid), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
