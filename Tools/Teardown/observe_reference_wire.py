"""Passive adapter: an owned client's existing TCP capture -> scenario JSONL.

Starts no capture, contacts no backend and sends no game packets. Reuses the
production codec and network decoder. Timestamps are CLIENT-interface
observations translated by a measured clock offset, never server receipts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from server import wire, vgdecode


def complete_pcap_prefix(data):
    """Keep whole captured packets; a live writer's unfinished tail is explicit."""
    formats = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>',
               b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}
    if len(data) < 24 or data[:4] not in formats:
        raise ValueError('unsupported/truncated PCAP header')
    offset = 24
    while offset + 16 <= len(data):
        size = struct.unpack_from(formats[data[:4]] + 'I', data, offset + 8)[0]
        if size > 262144:
            raise ValueError('oversized capture record')
        if offset + 16 + size > len(data):
            break
        offset += 16 + size
    return data[:offset], len(data) - offset


def decoded_rows(flows, match_id, server_port, clock_offset):
    """Strict selected-flow walk, no byte resynchronization or inferred owner."""
    cipher = wire.MatchCipher(match_id)
    candidates = [(key, value) for key, value in flows.items()
                  if key[3] == server_port and value[1].startswith(b'\x00\x86\x00\x05')]
    if len(candidates) != 1:
        raise ValueError('expected one selected match route-request flow')
    key, _ = candidates[0]
    reverse = (key[2], key[3], key[0], key[1])
    if reverse not in flows:
        raise ValueError('selected match has no server stream')
    rows, tails = [], {}
    for direction, flow in (('c2s', key), ('s2c', reverse)):
        _, raw, times, _, _ = flows[flow]
        offset = 136 if direction == 'c2s' else 0
        if direction == 's2c':
            if not raw.startswith(b'\x00\x03\x00\x06\x00'):
                raise ValueError('selected server stream lacks the measured gateway acknowledgement')
            offset = 5
        while offset + 2 <= len(raw):
            length = struct.unpack_from('>H', raw, offset)[0]
            end = offset + 2 + length
            if end > len(raw):
                break
            body = raw[offset + 2:end]
            if direction == 'c2s' and length == 6:
                # Existing clear six-byte op-0 variant; not a game intent.
                offset = end
                continue
            if length < 8 or length % 8:
                raise ValueError(f'invalid {direction} frame length at {offset}')
            op, payload = wire.decode_body(cipher, body)
            if op != 0 and not 1000 <= op <= 1168:
                raise ValueError(f'unknown decoded opcode at {direction}:{offset}')
            if op not in (0, 1000):  # Never export the login/session token.
                captured = max(times[offset:end])
                rows.append({'time': captured + clock_offset,
                    'capture_time': captured, 'direction': direction,
                    'connection': key[1], 'opcode': op, 'payload': payload.hex(),
                    'stream_offset': offset,
                    'time_source': 'client-interface capture + measured host offset'})
            offset = end
        tails[direction] = len(raw) - offset
    rows.sort(key=lambda r: (r['time'], r['direction'], r['stream_offset']))
    return rows, {'connection': key[1], 'server_port': server_port,
                  'incomplete_stream_bytes': tails}


class TCPBytes:
    """Append once, retain first-observed byte times, validate retransmissions."""
    def __init__(self, sequence):
        self.base = sequence
        self.data = bytearray()
        self.times = []
        self.pending = []
        self.cursor = None
        self.delivered_at = 0.0

    def add(self, sequence, body, captured):
        offset = ((sequence - self.base + 2**31) % 2**32) - 2**31
        if offset < 0:
            raise ValueError('capture starts after the selected TCP stream')
        self.pending.append((offset, body, captured))
        while True:
            index = next((i for i, (start, _, _) in enumerate(self.pending)
                          if start <= len(self.data)), None)
            if index is None:
                break
            start, body, stamp = self.pending.pop(index)
            overlap = min(len(body), len(self.data) - start)
            if self.data[start:start + overlap] != body[:overlap]:
                raise ValueError('conflicting TCP retransmission')
            self.data.extend(body[overlap:])
            self.times.extend([stamp] * (len(body) - overlap))


class IncrementalReference:
    """Decode each captured packet and complete match frame only once."""
    def __init__(self, match_id, server_port, clock_offset):
        self.cipher = wire.MatchCipher(match_id)
        self.port, self.clock_offset = server_port, clock_offset
        self.packet_offset = 24
        self.streams = {}
        self.connection = None

    def feed(self, data):
        endian = '<' if data[:4] in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1') else '>'
        divisor = 1e9 if data[:4] in (b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d') else 1e6
        linktype = struct.unpack_from(endian + 'I', data, 20)[0] & 255
        while self.packet_offset < len(data):
            seconds, fraction, size, _ = struct.unpack_from(endian + '4I', data, self.packet_offset)
            self.packet_offset += 16
            packet = vgdecode.l3(data[self.packet_offset:self.packet_offset + size], linktype)
            self.packet_offset += size
            if packet is None or not packet[-1] or self.port not in (packet[1], packet[3]):
                continue
            key, sequence, body = packet[:4], packet[4], packet[5]
            self.streams.setdefault(key, TCPBytes(sequence)).add(sequence, body, seconds + fraction / divisor)
        rows, tails, gaps = [], {}, {}
        for key, stream in self.streams.items():
            direction = 'c2s' if key[3] == self.port else 's2c'
            connection = key[1] if direction == 'c2s' else key[3]
            if self.connection is not None and connection != self.connection:
                raise ValueError('ambiguous selected match connections')
            self.connection = connection
            raw = stream.data
            if stream.cursor is None:
                needed = 136 if direction == 'c2s' else 5
                if len(raw) < needed:
                    continue
                expected = b'\x00\x86\x00\x05' if direction == 'c2s' else b'\x00\x03\x00\x06\x00'
                if not raw.startswith(expected):
                    raise ValueError('selected stream lacks route request/gateway acknowledgement')
                stream.cursor = needed
                stream.delivered_at = max(stream.times[:needed])
            while stream.cursor + 2 <= len(raw):
                offset = stream.cursor
                length = struct.unpack_from('>H', raw, offset)[0]
                end = offset + 2 + length
                if end > len(raw):
                    break
                # Later frame bytes may arrive before a preceding TCP gap is
                # filled. They cannot be made available before that gap.
                stream.delivered_at = max(stream.delivered_at, max(stream.times[offset:end]))
                if direction == 'c2s' and length == 6:
                    stream.cursor = end
                    continue
                if length < 8 or length % 8:
                    raise ValueError('invalid selected match frame length')
                op, payload = wire.decode_body(self.cipher, bytes(raw[offset + 2:end]))
                if op != 0 and not 1000 <= op <= 1168:
                    raise ValueError('unknown decoded opcode')
                if op not in (0, 1000):
                    captured = stream.delivered_at
                    rows.append({'time': captured + self.clock_offset, 'capture_time': captured,
                        'direction': direction, 'connection': connection, 'opcode': op,
                        'payload': payload.hex(), 'stream_offset': offset,
                        'time_source': 'client-interface capture + measured host offset'})
                stream.cursor = end
            tails[direction] = len(raw) - stream.cursor
            gaps[direction] = len(stream.pending)
        rows.sort(key=lambda r: (r['time'], r['direction'], r['stream_offset']))
        return rows, {'connection': self.connection, 'server_port': self.port,
                      'incomplete_stream_bytes': tails, 'pending_tcp_segments': gaps}


def clock_brackets(adb):
    measurements = []
    for _ in range(5):
        before = time.time()
        guest = float(subprocess.check_output(adb + ['shell', 'date', '+%s.%N'],
                                             text=True, timeout=10))
        after = time.time()
        measurements.append({'host_before': before, 'host_after': after,
                             'guest_wall': guest,
                             'offset': (before + after) / 2 - guest})
    return measurements


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--remote-pcap', required=True)
    parser.add_argument('--match-id', required=True)
    parser.add_argument('--server-port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=120)
    args = parser.parse_args(argv)
    destination = args.output.resolve()
    if destination.is_relative_to(ROOT) and not destination.is_relative_to(ROOT / 'Local'):
        parser.error('QA evidence must be outside the checkout or under Local/')
    if not args.remote_pcap.startswith('/sdcard/') or any(c not in '/._-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in args.remote_pcap):
        parser.error('expected an explicit owned /sdcard capture file')
    if not 1 <= args.duration <= 600:
        parser.error('duration must be 1..600 seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    adb = [args.adb, '-s', args.serial]
    clocks = [clock_brackets(adb)]
    best = min(clocks[0], key=lambda r: r['host_after'] - r['host_before'])
    offset = best['offset']
    reader = IncrementalReference(args.match_id, args.server_port, offset)
    seen, prefix, errors = set(), b'', []
    deadline = time.monotonic() + args.duration
    metadata = {'match_id': args.match_id, 'clock_brackets': clocks,
                'clock_offset_used': offset, 'errors': errors,
                'limit': 'Client-interface timing, not server receipt/RTT or a complete computation oracle.'}
    source = args.output / 'source.pcap'
    try:
        with source.open('xb') as capture, (args.output / 'wire.jsonl').open('x') as journal:
            while time.monotonic() < deadline:
                poll_started = time.monotonic()
                raw = subprocess.check_output(adb + ['exec-out', 'cat', args.remote_pcap], timeout=10)
                complete, trailing = complete_pcap_prefix(raw)
                if not complete.startswith(prefix):
                    raise ValueError('owned capture changed rather than growing')
                capture.write(complete[len(prefix):]); capture.flush()
                prefix = complete
                rows, identity = reader.feed(complete)
                for row in rows:
                    marker = (row['direction'], row['stream_offset'])
                    if marker not in seen:
                        journal.write(json.dumps(row, separators=(',', ':')) + '\n')
                        seen.add(marker)
                journal.flush()
                metadata.update(identity=identity, exported_frames=len(seen),
                                pending_pcap_bytes=trailing,
                                last_poll_ms=(time.monotonic() - poll_started) * 1000)
                (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
                time.sleep(.5)
    except Exception as exc:
        errors.append(repr(exc))
        raise
    finally:
        clocks.append(clock_brackets(adb))
        metadata['narrowest_offset_drift_s'] = min(clocks[-1], key=lambda r: r['host_after']-r['host_before'])['offset'] - offset
        (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps({'frames': len(seen), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
