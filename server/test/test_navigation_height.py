"""Explicit relocation uses the owned surface, independent of pathfinding."""
import unittest
from server.navigation import NavMesh


class HeightTests(unittest.TestCase):
    def test_sloped_plane_with_clockwise_triangle_and_boundary(self):
        # h = 1 + 2*x + 3*y. Reversing winding must preserve corner identity.
        for order in ((0, 1, 2), (0, 2, 1)):
            mesh = NavMesh([(0, 0), (4, 0), (0, 4)], [order], heights=[1, 9, 13])
            self.assertEqual(mesh.height_at((1, 1)), 6)
            self.assertEqual(mesh.height_at((2, 2)), 11)
            self.assertEqual(mesh.height_at((0, 0)), 1)
            with self.assertRaises(ValueError):
                mesh.height_at((3, 3))

    def test_height_data_does_not_change_2d_routes(self):
        vertices = [(0, 0), (4, 0), (4, 4), (0, 4)]
        triangles = [(0, 1, 2), (0, 2, 3)]
        flat = NavMesh(vertices, triangles)
        slope = NavMesh(vertices, triangles, heights=[1, 9, 21, 13])
        self.assertEqual(flat.find_path((.1, .1), (3.9, 3.9)), slope.find_path((.1, .1), (3.9, 3.9)))
        self.assertEqual(flat.height_at((1, 1)), 0)


if __name__ == '__main__':
    unittest.main()
