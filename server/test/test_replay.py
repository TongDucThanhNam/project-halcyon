"""Unit tests for Project Halcyon replay determinism and byte-for-byte stream verification."""
import unittest

from server import replay, roster, wire


class TestReplayDeterminism(unittest.TestCase):
    def test_replay_produces_identical_event_stream(self):
        # 1. Run primary simulation
        sim_a = replay.ReplaySimulation(dt=0.05)

        # Feed intents at predetermined ticks
        for tick in range(100):
            if tick == 5:
                sim_a.feed_intent(wire.OP.MOVE_CAST, roster.build_move(-60.0, 0.88))
            elif tick == 40:
                sim_a.feed_intent(wire.OP.MOVE_CAST, roster.build_move(-40.0, 5.0))
            elif tick == 70:
                sim_a.feed_intent(wire.OP.MOVE_CAST, roster.build_move(-20.0, 0.0))
            sim_a.step()

        frames_a = sim_a.recorder.frames
        hash_a = sim_a.recorder.get_event_stream_hash()
        self.assertGreater(len(frames_a), 20)

        # 2. Run second simulation with exact same input trace
        sim_b = replay.ReplaySimulation(dt=0.05)
        intents_to_replay = sim_a.recorder.intents

        intent_idx = 0
        for tick in range(100):
            while intent_idx < len(intents_to_replay) and intents_to_replay[intent_idx].tick == tick:
                it = intents_to_replay[intent_idx]
                sim_b.feed_intent(it.opcode, it.payload)
                intent_idx += 1
            sim_b.step()

        frames_b = sim_b.recorder.frames
        hash_b = sim_b.recorder.get_event_stream_hash()

        # 3. Verify byte-for-byte identity
        ok, msg = replay.DeterminismVerifier.verify(frames_a, frames_b)
        self.assertTrue(ok, msg)
        self.assertEqual(hash_a, hash_b)

    def test_divergence_detection(self):
        sim_a = replay.ReplaySimulation(dt=0.05)
        sim_b = replay.ReplaySimulation(dt=0.05)

        for tick in range(30):
            if tick == 5:
                sim_a.feed_intent(wire.OP.MOVE_CAST, roster.build_move(-60.0, 0.88))
                sim_b.feed_intent(wire.OP.MOVE_CAST, roster.build_move(-60.0, 15.0))  # divergent direction!
            sim_a.step()
            sim_b.step()

        ok, msg = replay.DeterminismVerifier.verify(sim_a.recorder.frames, sim_b.recorder.frames)
        self.assertFalse(ok)
        self.assertIn("Divergence", msg)


if __name__ == "__main__":
    unittest.main()
