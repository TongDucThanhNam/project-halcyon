"""ActionMoveTo is required before hero position corrections.

The old no-1016 premise searched for an eid in a compact-id payload. These
checks cover the actual session wire output, including retargets and arrival.
"""
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from server import hero_movement, match_server, roster, wire, jungle, structures


class TestLocomotionTarget(unittest.TestCase):
    def make_stream(self, slot=0, eid=1500):
        conn = object()
        player = SimpleNamespace(slot=slot, eid=eid)
        hero = hero_movement.HeroMovement(eid=eid, x=-70.0, y=1.0)
        frames = []
        players = roster.default_solo_bots("test", "test")
        stream = match_server.SnapshotStream(None, players, "test", None, log=Mock())
        stream.players = [player]
        stream.clients = {conn: (player, None)}
        stream.hero_sims = {eid: hero}
        stream.hero_kits = {}
        stream.hero_sim = hero
        stream.jungle = jungle.JungleManager(open_time=1000000)
        for structure in stream.structures.structures.values():
            structure.is_alive = False
        stream._broadcast = lambda op, body: frames.append((op, body))
        return stream, conn, hero, frames

    def move(self, stream, conn, x, y):
        match_server.SnapshotStream._apply_event(
            stream, wire.OP.MOVE_CAST, struct.pack(">ff", x, y) + bytes(6), conn=conn)

    def test_each_hero_uses_compact_slot_before_current_position(self):
        for slot, eid in enumerate((1500, 1515, 1516, 1517, 1518, 1519)):
            with self.subTest(slot=slot, eid=eid):
                stream, conn, hero, frames = self.make_stream(slot, eid)
                self.move(stream, conn, -60.5, 3.25)
                self.assertEqual([op for op, _ in frames], [1016, 1070])
                self.assertEqual(frames[0][1], struct.pack(">Bff", slot, -60.5, 3.25) + bytes(5))
                self.assertEqual(struct.unpack(">IffH", frames[1][1]), (eid, -70.0, 1.0, 0))

    def test_retarget_replaces_path_without_rewinding_anchor(self):
        stream, conn, hero, frames = self.make_stream()
        self.move(stream, conn, -60.0, 1.0)
        hero.step(1.0)
        frames.clear()
        self.move(stream, conn, -65.0, 6.0)
        self.assertEqual([op for op, _ in frames], [1016, 1070])
        self.assertEqual(struct.unpack(">IffH", frames[1][1]), (1500, -65.0, 1.0, 0))
        self.assertEqual(hero.move_target, (-65.0, 6.0))
        updates = hero.step(1.0)
        self.assertTrue(all(op == 1070 for op, _ in updates))
        self.assertEqual((hero.x, hero.y), (-65.0, 6.0))
        self.assertFalse(hero.is_moving)
        self.assertEqual(hero.step(0.2), [])

    def test_dead_hero_does_not_receive_move_activation(self):
        stream, conn, hero, frames = self.make_stream()
        hero.is_alive = False
        self.move(stream, conn, -60.0, 1.0)
        self.assertEqual(frames, [])

    def test_periodic_1070_suppression_and_resumption(self):
        import time
        stream, conn, hero, frames = self.make_stream()
        stream.suppress_periodic_1070_sec = 2.0
        # Target is 20 units away: (-50, 1) from (-70, 1) at 5 u/s takes 4.0s
        t0 = stream.sim_time
        self.move(stream, conn, -50.0, 1.0)
        # Order broadcasts 1016 and initial anchor 1070
        self.assertEqual([op for op, _ in frames], [1016, 1070])
        frames.clear()

        # Step at +0.2s: periodic 1070 suppressed
        match_server.SnapshotStream._step_heroes(stream, 0.2, now=t0 + 0.2)
        self.assertEqual(frames, [
            (1067, struct.pack(">IBBBB6x", 1500, 1, 1, 15, 0)),
            (1067, struct.pack(">IBBBB6x", 1500, 2, 1, 0, 0)),
        ])
        frames.clear()
        self.assertEqual(stream.suppressed_1070_count, 1)

        # Step at +1.0s: still suppressed
        match_server.SnapshotStream._step_heroes(stream, 0.8, now=t0 + 1.0)
        self.assertEqual(frames, [])
        self.assertEqual(stream.suppressed_1070_count, 2)

        # Step at +2.1s: suppression expired -> resumes and broadcasts 1070
        match_server.SnapshotStream._step_heroes(stream, 1.1, now=t0 + 2.1)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0], 1070)
        eid, x, y, _ = struct.unpack(">IffH", frames[0][1])
        self.assertEqual(eid, 1500)
        self.assertGreater(x, -70.0)
        self.assertFalse(stream.suppress_active)


if __name__ == "__main__":
    unittest.main()
