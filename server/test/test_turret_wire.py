"""Native turret actions distinguish shots from target release/idle."""
import os
import struct
import unittest

from server import roster
from server.test.test_corpus import VGFULL_PCAP, _cached_frames


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), "external turret corpus unavailable")
class TestNativeTurretActions(unittest.TestCase):
    def test_acquire_shot_then_release_idle_match_native_target_death(self):
        frames, _ = _cached_frames()
        self.assertEqual(frames[6137], (1045, roster.build_target_acquire(3545, 4325, flag=1)))
        self.assertEqual(frames[6152], (1045, roster.build_target_acquire(3545, 4325, flag=0)))
        self.assertEqual(frames[6284][0], 1072)
        self.assertEqual(struct.unpack_from(">II", frames[6284][1]), (4325, 3545))
        self.assertEqual(frames[6299], (1045, roster.build_target_acquire(3545, 3545, flag=2)))
        self.assertEqual(frames[6302], (1045, roster.build_target_acquire(3545, 3545, flag=3)))

    def test_no_native_turret_shot_targets_null(self):
        frames, _ = _cached_frames()
        turrets = {struct.unpack_from(">I", p, 8)[0] for op, p in frames
                   if op == 1010 and len(p) == 126
                   and struct.unpack_from(">I", p)[0] in (369, 370, 371, 372)}
        shots = [(source, target) for op, p in frames if op == 1045
                 for source, target, action in [struct.unpack_from(">IIB", p)]
                 if source in turrets and action == 0]
        self.assertEqual(len(shots), 67)
        self.assertTrue(all(target not in (0, 0xffffffff, source) for source, target in shots))
