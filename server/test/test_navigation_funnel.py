"""Route quality, not just collision freedom, is part of walking correctness."""
import math
import unittest

from server.navigation import DEFAULT_A001_PATH, NavMesh, fixed, load_halcyon_navmesh
from server.hero_movement import HeroMovement
from server.wave import Minion
from server import roster
from server.test.test_navigation_lifecycle import ring_mesh


class FunnelNavigationTests(unittest.TestCase):
    def assert_safe(self, mesh, start, target):
        route = mesh.find_path(start, target)
        self.assertTrue(route, (start, target))
        self.assertEqual(route[-1], target)
        for a, b in zip([start] + route, route):
            self.assertTrue(mesh.segment_walkable(a, b), (a, b))
        return sum(math.dist(a, b) for a, b in zip([start] + route, route))

    def test_taut_route_uses_obstacle_corners_not_triangle_midpoints(self):
        mesh = ring_mesh()
        for start, target in [((1, 5), (9, 5)), ((9, 5), (1, 5)),
                              ((5, 1), (5, 9)), ((5, 9), (5, 1))]:
            with self.subTest(start=start, target=target):
                # Independent analytic shortest route around the 2x2 hole.
                self.assertAlmostEqual(self.assert_safe(mesh, start, target), 2 * math.sqrt(10) + 2)

    def test_collinear_portals_and_boundary_endpoints_remain_reachable(self):
        mesh = ring_mesh()
        points = [(1, 5), (9, 5), (5, 1), (5, 9), (0, 0), (10, 10),
                  (4, 4), (4, 6), (6, 4), (6, 6), (0, 5), (10, 5)]
        for a in points:
            for b in points:
                if a != b:
                    self.assert_safe(mesh, a, b)

    def test_quantized_hero_and_minion_steps_do_not_stick_on_diagonal_wall(self):
        mesh = NavMesh([(0, 0), (10, -.189), (0, -5)], [(0, 1, 2)])
        hero = HeroMovement(x=0, y=0, navigation=mesh, speed=3.9)
        hero.set_target(10, -.189)
        minion = Minion(2500, 1, 0)
        minion.x = minion.y = 0
        minion.navigation, minion.path = mesh, [(10, -.189)]
        for actor, speed in ((hero, 3.9), (minion, roster.MINION_SPEED)):
            with self.subTest(actor=type(actor).__name__):
                for _ in range(100):
                    previous = actor.position_fixed
                    actor.step(.05)
                    self.assertTrue(mesh.contains((actor.x, actor.y)))
                    self.assertLessEqual(sum((b-a)**2 for a, b in zip(previous, actor.position_fixed)), fixed(speed * .05)**2)
                self.assertEqual(actor.position_fixed, (fixed(10), fixed(-.189)))

    def test_quantization_repair_does_not_walk_through_a_real_wall(self):
        mesh = ring_mesh()
        endpoint = mesh.clamp_walk_step((1, 5), (9, 5), (9, 5), fixed(8))
        self.assertLessEqual(endpoint[0], 4)
        self.assertTrue(mesh.segment_walkable((1, 5), endpoint))

    @unittest.skipUnless(DEFAULT_A001_PATH.is_file(), 'operator-owned A001 unavailable')
    def test_measured_return_leg_no_longer_takes_triangle_midpoint_detour(self):
        # This historical length was measured on the authoring surface. The
        # production default now uses qualified baked agent-clearance geometry;
        # its wall contract has a separate regression in test_navigation_detour.
        mesh = load_halcyon_navmesh(DEFAULT_A001_PATH)
        start, target = (-69.671150, 5.680763), (-85.053848, -1.326254)
        length = self.assert_safe(mesh, start, target)
        self.assertLess(length, 17.029)  # measured old route was 19.36597
        self.assertGreaterEqual(length, math.dist(start, target))


if __name__ == '__main__':
    unittest.main()
