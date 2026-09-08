"""Skill-button acknowledgements must reach only the requesting client."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from server import abilities, cooldown_wire, match_server, roster, wire
from server.navigation import NavMesh


class TestSkillHandshake(unittest.TestCase):
    def test_network_routes_both_skill_buttons_to_session_writer(self):
        conn = object()
        stream = Mock()
        server = match_server.MatchServer(log=Mock())
        server._streams_by_conn[conn] = stream
        for opcode in (wire.OP.LEVELUP_A, wire.OP.LEVELUP_B):
            with self.subTest(opcode=opcode):
                match_server.MatchServer._dispatch(server, conn, opcode, bytes(6))
                stream.submit.assert_called_with(opcode, bytes(6), conn=conn)

    def make_stream(self):
        conn = object()
        players = roster.default_solo_bots("skills", "skills")[:2]
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        stream = match_server.SnapshotStream(None, players, "skills", None,
                                            log=Mock(), navigation_mesh=mesh)
        stream.clients[conn] = (players[1], Mock())
        stream.hero_kits[1515] = abilities.create_hero_kit(stream.hero_sims[1515], 243)
        stream.hero_kits[1515].cast_ability = Mock()
        stream._send_to, stream._broadcast = Mock(), Mock()
        stream.economy.upgrade_ability = Mock(return_value=True)
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
                    self.assert_learned_frames(stream, 0)
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
        self.assert_learned_frames(stream, 1)

    def assert_learned_frames(self, stream, slot):
        calls = stream._broadcast.call_args_list
        self.assertEqual([call.args[0] for call in calls], [1082, 1162])
        self.assertEqual(calls[0].args[1], roster.build_inventory_slot(1515, slot))
        timer = cooldown_wire.parse_timer_tick(calls[1].args[1])
        self.assertEqual(timer.eid, 1515)
        self.assertEqual(timer.remaining, 0)
        self.assertEqual(timer.tag, cooldown_wire.native_ability_tag(
            f"Ability__Ringo__{'ABC'[slot]}"))

    def test_no_points_does_not_publish_success(self):
        stream, conn = self.make_stream()
        stream.economy.upgrade_ability.return_value = False
        match_server.SnapshotStream._apply_event(stream, 1078, bytes(6), conn=conn)
        stream._send_to.assert_not_called()
        stream._broadcast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
