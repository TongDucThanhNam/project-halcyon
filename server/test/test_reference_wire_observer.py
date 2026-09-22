"""Passive reference evidence must not invent timing, identity or completeness."""
import struct
import unittest
from unittest.mock import patch
from Tools.Teardown.observe_reference_wire import complete_pcap_prefix, decoded_rows, TCPBytes, IncrementalReference
from server import wire

MATCH = '00000000-1111-4222-8333-444455556666'
KEY = (b'\xac\x10\x01\x0f', 41994, b'\x88B\x94u', 7088)
REVERSE = (KEY[2], KEY[3], KEY[0], KEY[1])


def fixture(server_tail=b''):
    cipher = wire.MatchCipher(MATCH)
    greeting = wire.frame(b'\x00\x05' + bytes(132))
    client = greeting + wire.encode_message(cipher, 1000, b'private-session-token')
    client += wire.encode_message(cipher, 1012, struct.pack('>ff6x', 4, 5))
    server = b'\x00\x03\x00\x06\x00' + wire.encode_message(cipher, 1001, bytes(102)) + server_tail
    def flow(raw):
        return [], raw, [10 + i / 1000 for i in range(len(raw))], 0, {}
    return {KEY: flow(client), REVERSE: flow(server)}


class ReferenceWireObserverTests(unittest.TestCase):
    def test_tcp_wrap_gap_and_duplicate_preserve_first_observation(self):
        stream = TCPBytes(2**32 - 2)
        stream.add(2**32 - 2, b'ab', 1)
        stream.add(2, b'ef', 2)
        self.assertEqual(stream.data, b'ab')
        stream.add(0, b'cd', 3)
        stream.add(0, b'cdef', 4)
        self.assertEqual(stream.data, b'abcdef')
        self.assertEqual(stream.times, [1, 1, 3, 3, 2, 2])
        self.assertEqual(stream.pending, [])
        with self.assertRaisesRegex(ValueError, 'conflicting TCP'):
            stream.add(0, b'XX', 5)

    def test_incremental_frames_complete_once_with_out_of_order_bytes(self):
        flows = fixture()
        client, server = flows[KEY][1], flows[REVERSE][1]
        packets = [(*KEY, 100, client[:-3]), (*REVERSE, 200, server),
                   (*KEY, 100 + len(client) - 1, client[-1:]),
                   (*KEY, 100 + len(client) - 3, client[-3:-1]),
                   (*KEY, 100, client)]
        header = b'\xd4\xc3\xb2\xa1' + bytes(16) + struct.pack('<I', 1)
        records = [struct.pack('<4I', 10 + i, 0, 1, 1) + bytes([i]) for i in range(len(packets))]
        reader = IncrementalReference(MATCH, 7088, -2)
        with patch('Tools.Teardown.observe_reference_wire.vgdecode.l3',
                   side_effect=lambda payload, _: packets[payload[0]]):
            rows, metadata = reader.feed(header + b''.join(records[:3]))
            self.assertEqual([r['opcode'] for r in rows], [1001])
            self.assertEqual(metadata['pending_tcp_segments']['c2s'], 1)
            rows, metadata = reader.feed(header + b''.join(records))
            self.assertEqual([r['opcode'] for r in rows], [1012])
            self.assertEqual(rows[0]['capture_time'], 13)
            self.assertEqual(rows[0]['time'], 11)
            self.assertEqual(metadata['incomplete_stream_bytes'], {'c2s': 0, 's2c': 0})
            self.assertEqual(reader.feed(header + b''.join(records))[0], [])

    def test_client_clock_completion_time_and_private_frame_exclusion(self):
        flows = fixture()
        rows, metadata = decoded_rows(flows, MATCH, 7088, -2)
        self.assertEqual({r['opcode'] for r in rows}, {1001, 1012})
        self.assertNotIn('private-session-token'.encode().hex(), str(rows))
        request = next(r for r in rows if r['opcode'] == 1012)
        self.assertEqual(request['connection'], KEY[1])
        self.assertEqual(request['capture_time'], max(flows[KEY][2]))
        self.assertEqual(request['time'], request['capture_time'] - 2)
        self.assertEqual(metadata['incomplete_stream_bytes'], {'c2s': 0, 's2c': 0})

    def test_later_frame_cannot_precede_tcp_gap_completion(self):
        cipher = wire.MatchCipher(MATCH)
        frame = wire.encode_message(cipher, 1016, struct.pack('>Bff5x', 0, 4, 5))
        reader = IncrementalReference(MATCH, 7088, 0)
        stream = TCPBytes(100)
        stream.add(100, b'\x00\x03\x00\x06\x00', 1)
        stream.add(105 + len(frame), frame, 2)
        stream.add(105, frame, 3)
        reader.streams[REVERSE] = stream
        header = b'\xd4\xc3\xb2\xa1' + bytes(16) + struct.pack('<I', 1)
        rows, _ = reader.feed(header)
        self.assertEqual([r['capture_time'] for r in rows], [3, 3])

    def test_incremental_reader_rejects_corruption_instead_of_resynchronizing(self):
        header = b'\xd4\xc3\xb2\xa1' + bytes(16) + struct.pack('<I', 1)
        cases = [(fixture(b'\x00\x03bad')[REVERSE][1], MATCH, 'frame length'),
                 (b'xxxxx' + fixture()[REVERSE][1][5:], MATCH, 'gateway'),
                 (fixture()[REVERSE][1], 'wrong-match-id', 'opcode')]
        for body, match, error in cases:
            with self.subTest(error=error), patch(
                    'Tools.Teardown.observe_reference_wire.vgdecode.l3',
                    return_value=(*REVERSE, 200, body)):
                reader = IncrementalReference(match, 7088, 0)
                with self.assertRaisesRegex(ValueError, error):
                    reader.feed(header + struct.pack('<4I', 10, 0, 1, 1) + b'x')

    def test_partial_wire_tail_is_reported_not_resynchronized(self):
        rows, metadata = decoded_rows(fixture(b'\x00\x10\x99'), MATCH, 7088, 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(metadata['incomplete_stream_bytes']['s2c'], 3)

    def test_invalid_middle_frame_cannot_be_skipped(self):
        with self.assertRaisesRegex(ValueError, 'invalid s2c frame length'):
            decoded_rows(fixture(b'\x00\x03bad'), MATCH, 7088, 0)

    def test_wrong_key_and_ambiguous_connections_fail(self):
        with self.assertRaisesRegex(ValueError, 'unknown decoded opcode'):
            decoded_rows(fixture(), 'wrong-match-id', 7088, 0)
        flows = fixture()
        flows[(KEY[0], KEY[1] + 1, KEY[2], KEY[3])] = flows[KEY]
        with self.assertRaisesRegex(ValueError, 'one selected match'):
            decoded_rows(flows, MATCH, 7088, 0)

    def test_selected_flow_requires_gateway_acknowledgement(self):
        flows = fixture()
        data = list(flows[REVERSE]); data[1] = b'xxxxx' + data[1][5:]
        flows[REVERSE] = tuple(data)
        with self.assertRaisesRegex(ValueError, 'gateway acknowledgement'):
            decoded_rows(flows, MATCH, 7088, 0)

    def test_live_pcap_keeps_only_complete_packets_and_rejects_bad_length(self):
        header = b'\xd4\xc3\xb2\xa1' + bytes(20)
        packet = struct.pack('<4I', 10, 0, 4, 4) + b'abcd'
        tail = struct.pack('<4I', 11, 0, 4, 4) + b'ab'
        complete, pending = complete_pcap_prefix(header + packet + tail)
        self.assertEqual(complete, header + packet)
        self.assertEqual(pending, len(tail))
        self.assertEqual(complete_pcap_prefix(header + packet), (header + packet, 0))
        with self.assertRaisesRegex(ValueError, 'oversized'):
            complete_pcap_prefix(header + struct.pack('<4I', 0, 0, 262145, 262145))


if __name__ == '__main__':
    unittest.main()
