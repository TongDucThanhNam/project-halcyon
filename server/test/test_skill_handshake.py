"""Skill-button acknowledgements must reach only the requesting client."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from server import match_server, wire


class TestSkillHandshake(unittest.TestCase):
    def test_network_routes_both_skill_buttons_to_session_writer(self):
        conn = object()
        stream = Mock()
        server = SimpleNamespace(_streams_by_conn={conn: stream}, log=Mock())
        for opcode in (wire.OP.LEVELUP_A, wire.OP.LEVELUP_B):
            with self.subTest(opcode=opcode):
                match_server.MatchServer._dispatch(server, conn, opcode, bytes(6))
                stream.submit.assert_called_with(opcode, bytes(6), conn=conn)

    def make_stream(self):
        conn = object()
        first = SimpleNamespace(eid=1500)
        second = SimpleNamespace(eid=1515)
        stream = SimpleNamespace(
            players=[first, second], clients={conn: (second, Mock())},
            hero_sims={}, hero_kits={1515: Mock()}, log=Mock(),
            _send_to=Mock(), _broadcast=Mock(),
            economy=SimpleNamespace(upgrade_ability=Mock(return_value=True)),
        )
        return stream, conn

    def test_ack_targets_requesting_player_without_casting_or_broadcasting(self):
        for opcode in (wire.OP.LEVELUP_A, wire.OP.LEVELUP_B):
            with self.subTest(opcode=opcode):
                stream, conn = self.make_stream()
                match_server.SnapshotStream._apply_event(stream, opcode, bytes(6), conn=conn)
                stream._send_to.assert_any_call(conn, opcode, bytes(6))
                if opcode == wire.OP.LEVELUP_A:
                    stream._send_to.assert_any_call(conn, 1160, b"\x00\x00\x05\xeb\x00\x00")
                    stream.economy.upgrade_ability.assert_not_called()
                    stream._broadcast.assert_not_called()
                else:
                    stream._broadcast.assert_called_once_with(1082, b"\x00\x00\x05\xeb" + bytes(10))
                stream.hero_kits[1515].cast_ability.assert_not_called()

    def test_unmeasured_payloads_are_rejected_without_ack_or_cast(self):
        for opcode in (wire.OP.LEVELUP_A, wire.OP.LEVELUP_B):
            for payload in (b"", bytes(5), bytes(7), b"\x03" + bytes(5), bytes(5) + b"\x01"):
                with self.subTest(opcode=opcode, payload=payload):
                    stream, conn = self.make_stream()
                    match_server.SnapshotStream._apply_event(stream, opcode, payload, conn=conn)
                    stream._send_to.assert_not_called()
                    stream.economy.upgrade_ability.assert_not_called()
                    stream.hero_kits[1515].cast_ability.assert_not_called()

    def test_slot_b_upgrade_uses_requesting_eid_and_publishes_skill_state(self):
        stream, conn = self.make_stream()
        payload = b"\x01" + bytes(5)
        match_server.SnapshotStream._apply_event(stream, 1078, payload, conn=conn)
        stream.economy.upgrade_ability.assert_called_once_with(1515, 1, stream.hero_kits[1515])
        stream._send_to.assert_called_once_with(conn, 1078, payload)
        stream._broadcast.assert_called_once_with(1082, b"\x00\x00\x05\xeb\x00\x00\x00\x01" + bytes(6))

    def test_no_points_does_not_publish_success(self):
        stream, conn = self.make_stream()
        stream.economy.upgrade_ability.return_value = False
        match_server.SnapshotStream._apply_event(stream, 1078, bytes(6), conn=conn)
        stream._send_to.assert_not_called()
        stream._broadcast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
