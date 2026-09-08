"""Independent exhaustive clipping oracle for the optimized geometry queries."""
from fractions import Fraction
import unittest

from server.navigation import DEFAULT_A001_PATH, NavMesh, SCALE, fixed, load_halcyon_navmesh
from server.test.test_navigation_lifecycle import ring_mesh


def exhaustive_intervals(mesh, start, end):
    """Clip every triangle using Fraction arithmetic, without grid/bounds skips."""
    intervals = []
    for triangle in mesh.triangles:
        low, high = Fraction(0), Fraction(1)
        for a, b in zip(triangle, triangle[1:] + triangle[:1]):
            initial = (b[0] - a[0]) * (start[1] - a[1]) - (b[1] - a[1]) * (start[0] - a[0])
            final = (b[0] - a[0]) * (end[1] - a[1]) - (b[1] - a[1]) * (end[0] - a[0])
            if initial < 0 and final < 0:
                break
            if initial < 0:
                low = max(low, Fraction(-initial, final - initial))
            elif final < 0:
                high = min(high, Fraction(initial, initial - final))
            if low > high:
                break
        else:
            intervals.append((low, high))
    merged = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(merged[-1][1], high)
        else:
            merged.append((low, high))
    return merged


class TestExactClipping(unittest.TestCase):
    def assert_matches_exhaustive(self, mesh, start, end):
        expected = exhaustive_intervals(mesh, start, end)
        self.assertEqual(mesh._intervals(start, end), expected, (start, end))
        world_start = tuple(value / SCALE for value in start)
        world_end = tuple(value / SCALE for value in end)
        self.assertEqual(mesh.segment_walkable(world_start, world_end),
                         bool(expected and expected[0] == (0, 1)), (start, end))

    def test_holes_edges_corners_and_zero_length_segments(self):
        mesh = ring_mesh()
        points = [tuple(map(fixed, point)) for point in (
            (-1, -1), (0, 0), (0, 10), (1, 5), (4, 4), (4, 6),
            (5, 5), (6, 4), (6, 6), (8, 8), (9, 5), (10, 0), (11, 11),
            (4 - 1 / SCALE, 5), (4 + 1 / SCALE, 5),
        )]
        for start in points:
            for end in points:
                self.assert_matches_exhaustive(mesh, start, end)

    def test_negative_cells_and_clockwise_input_triangles(self):
        vertices = [(-16, -16), (0, -16), (-16, 0), (0, 0),
                    (8, 0), (0, 8), (8, 8)]
        mesh = NavMesh(vertices, [(0, 2, 1), (1, 2, 3), (3, 5, 4), (4, 5, 6)])
        points = [tuple(map(fixed, point)) for point in (
            (-16, -16), (-8, -8), (-8, 0), (0, -8), (0, 0),
            (0, 8), (8, 0), (8, 8), (-8, 8), (8, -8),
        )]
        for start in points:
            for end in points:
                self.assert_matches_exhaustive(mesh, start, end)

    @unittest.skipUnless(DEFAULT_A001_PATH.is_file(), 'operator-owned external A001 unavailable')
    def test_external_mesh_long_routes_and_microunit_edge_crossings(self):
        mesh = load_halcyon_navmesh()
        centers = mesh.centers[::23]
        for index, start in enumerate(centers):
            self.assert_matches_exhaustive(mesh, start, centers[(index * 13 + 7) % len(centers)])
        for triangle in mesh.triangles[::29]:
            a, b = triangle[:2]
            middle = tuple((a[k] + b[k]) // 2 for k in (0, 1))
            for offset in ((1, 0), (0, 1), (1, 1)):
                start = tuple(middle[k] - offset[k] for k in (0, 1))
                end = tuple(middle[k] + offset[k] for k in (0, 1))
                self.assert_matches_exhaustive(mesh, start, end)


if __name__ == '__main__':
    unittest.main()
