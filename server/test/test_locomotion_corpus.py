"""Optional external-corpus gate for the recovered hero movement contract."""
import os
from pathlib import Path
import struct
import unittest

from server import decode, wire, world_tape


CORPUS_DIR = Path(os.environ.get("TEMP", ".")) / "vg_max"
PCAP = CORPUS_DIR / "vgfull.pcap"
C2S = CORPUS_DIR / "c2s.bin"
MATCH_ID = "b9f511e0-11cd-4cfa-ad62-dc8612b8d270"
STACK_DIR = Path(os.environ.get("TEMP", ".")) / "halcyon_stack"
ORIGINAL_TAPE = STACK_DIR / "world_tape_pre_cancel_20260907-142422.bin"
CANDIDATE_TAPE = STACK_DIR / "world_tape_cancel_only_candidate.bin"


@unittest.skipUnless(ORIGINAL_TAPE.is_file() and CANDIDATE_TAPE.is_file(),
                     "external bootstrap comparison tapes unavailable")
class TestBootstrapCorpus(unittest.TestCase):
    def test_original_repair_equals_accepted_candidate_byte_for_byte(self):
        original = world_tape.load_tape(str(ORIGINAL_TAPE), skip_until_op=1087)
        candidate = world_tape.load_tape(str(CANDIDATE_TAPE), skip_until_op=1087)
        self.assertEqual(len(original), 1458)
        self.assertEqual(len(candidate), 1464)
        repaired = world_tape.complete_corpus_bootstrap(original)
        self.assertEqual(repaired, candidate)  # timestamps and every body byte
        self.assertEqual(world_tape.complete_corpus_bootstrap(candidate), candidate)


@unittest.skipUnless(PCAP.is_file() and C2S.is_file(), "external locomotion corpus unavailable")
class TestLocomotionCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames, cls.info = decode.decode_pcap(str(PCAP), MATCH_ID)

    def test_targets_match_inputs_without_searching_for_an_eid_in_1016(self):
        data = C2S.read_bytes()
        # Skip the length-prefixed plaintext route request, then walk every
        # frame in order. Unlike the historical resync scanner, retain 1000.
        off = 2 + struct.unpack_from(">H", data)[0]
        cipher = wire.MatchCipher(MATCH_ID)
        inputs = []
        while off < len(data):
            self.assertLessEqual(off + 2, len(data))
            length = struct.unpack_from(">H", data, off)[0]
            off += 2
            self.assertLessEqual(off + length, len(data))
            body = data[off:off + length]
            off += length
            if length >= 8 and length % 8 == 0:
                op, payload = wire.decode_body(cipher, body)
                if op == wire.OP.MOVE_CAST:
                    inputs.append(payload[:8])
        self.assertEqual(off, len(data))
        targets = [p[1:9] for op, p in self.frames if op == wire.OP.MOVE_TO and p[0] == 0]
        self.assertEqual(len(inputs), 21)
        self.assertEqual(len(targets), 18)
        self.assertEqual(targets, inputs[-18:])

    def test_target_precedes_correction_and_local_movement_does_not_modify_visibility(self):
        self.assertEqual(self.info["missed"], 0)
        self.assertEqual(sum(op == 1070 and struct.unpack_from(">I", p)[0] == 1500
                             for op, p in self.frames), 39)
        for i, (op, payload) in enumerate(self.frames):
            if op == 1016 and payload[0] == 0:
                following = self.frames[i + 1:i + 3]
                self.assertTrue(any(o == 1070 and struct.unpack_from(">I", p)[0] == 1500
                                    for o, p in following))
            if op == 1067 and struct.unpack_from(">I", payload)[0] == 1500:
                self.assertNotEqual(payload[4], 1, "Local hero has no channel-1 movement visibility stream")


if __name__ == "__main__":
    unittest.main()
