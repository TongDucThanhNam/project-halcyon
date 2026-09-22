"""A fresh native hero and the authoritative simulation start in one place."""
import struct
import unittest

from server import roster, wire
from server.test.test_same_hero import SameHeroTests


class SpawnPublicationTests(unittest.TestCase):
    def test_canonical_slot_positions_use_xz_not_xy_height(self):
        expected = {1500: (-78.18, .88), 1515: (-81.81, 1.97),
                    1516: (-77.03, -1.94), 1517: (79.66, -.91),
                    1518: (78.60, -5.06), 1519: (83.22, .72)}
        for eid, point in expected.items():
            with self.subTest(eid=eid):
                for observed, value in zip(roster.HERO_SPAWNS[eid], point):
                    self.assertAlmostEqual(observed, value, places=5)

    def test_mirrored_donor_heroes_do_not_share_the_donor_spawn(self):
        world, frames, _ = SameHeroTests().make_match(True)
        world._begin_lock()
        world._finalize()
        world.tape_frames = []
        world._dump_world()
        blocks = [body for op, body in frames if op == wire.OP.HERO_BLOCK]
        self.assertEqual(len(blocks), 6)
        positions = set()
        for block in blocks:
            eid = struct.unpack_from('>I', block, 8)[0]
            x, height, y = struct.unpack_from('>fff', block, 18)
            sim = world.hero_sims[eid]
            self.assertAlmostEqual(x, sim.x, places=4)
            self.assertAlmostEqual(y, sim.y, places=4)
            self.assertGreater(height, 1)
            self.assertLess(height, 2)
            positions.add((x, y))
        self.assertEqual(len(positions), 6)


if __name__ == '__main__':
    unittest.main()
