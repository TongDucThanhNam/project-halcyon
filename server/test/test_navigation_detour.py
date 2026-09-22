"""The live client's baked walkable surface is not the authoring mesh."""
import math
from pathlib import Path
import struct
import tempfile
import unittest

from server.navigation import NavMesh, load_halcyon_navmesh, DEFAULT_A001_PATH
from server.paths import pc_data_dir

BAKED = pc_data_dir() / '4D/4D562D63B9D0796F7FCC5EC61ADB111B'


def square_tile():
    # Independent tiny Detour-v7 fixture: one quad, two detail triangles.
    header = struct.pack('<15I10f', 0x444e4156, 7, 0, 0, 0, 0,
                         1, 4, 0, 1, 0, 2, 0, 0, 1,
                         2, .5, 1, 0, 0, 0, 4, 2, 4, 1)
    vertices = struct.pack('<12f', 0, 0, 0, 4, 0, 0, 4, 2, 4, 0, 2, 4)
    polygon = struct.pack('<I6H6HHBB', 0xffffffff, 0, 1, 2, 3, 0, 0,
                          0, 0, 0, 0, 0, 0, 2, 4, 1)
    detail = struct.pack('<IIBB2x', 0, 0, 0, 2)
    return header + vertices + polygon + detail + bytes((0, 1, 2, 0, 0, 2, 3, 0))


def store(tile):
    return struct.pack('<I5f2I2I', 1, 0, 0, 0, 4, 4, 1, 1, 1, len(tile)) + tile


class DetourStoreTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'fixture.bin'
            path.write_bytes(data)
            return NavMesh.from_file(path)

    def test_baked_quad_detail_height_and_route(self):
        mesh = self.load(store(square_tile()))
        self.assertEqual(len(mesh.triangles), 2)
        self.assertEqual(mesh.find_path((1, 1), (3, 3)), [(3, 3)])
        self.assertEqual(mesh.height_at((2, 2)), 1)
        self.assertFalse(mesh.contains((5, 2)))
        self.assertEqual(mesh.source_metadata['agent_radius'], .5)

    def test_reject_truncation_and_trailing_bytes(self):
        data = store(square_tile())
        for bad in (data[:-1], data + b'x', data[:45]):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                self.load(bad)

    def test_reject_unsupported_tile_version(self):
        tile = bytearray(square_tile())
        struct.pack_into('<I', tile, 4, 99)
        with self.assertRaises(ValueError):
            self.load(store(tile))

    def test_reject_out_of_range_triangle_vertex(self):
        tile = bytearray(square_tile())
        tile[-8] = 9
        with self.assertRaises(ValueError):
            self.load(store(tile))


@unittest.skipUnless(BAKED.is_file() and DEFAULT_A001_PATH.is_file(), 'owned Classic inputs absent')
class QualifiedClassicGeometryTests(unittest.TestCase):
    def test_production_default_excludes_the_measured_native_wall(self):
        # Read-only native tiles exactly match this store's geometry; its
        # authoring waypoint was observed to lie inside the baked wall.
        mesh = load_halcyon_navmesh()
        self.assertFalse(mesh.contains((-72.740685, 12.202225)))
        start = (-73.935333, 9.342721)
        requested = (-73.786499, 13.805074)
        route = mesh.find_path(start, requested)
        self.assertGreater(len(route), 1)
        self.assertLess(math.dist(route[-1], requested), .00001)
        for a, b in zip([start] + route, route):
            self.assertTrue(mesh.segment_walkable(a, b))

    def test_owned_baked_geometry_is_connected_and_spawn_reachable(self):
        mesh = NavMesh.from_file(BAKED)
        self.assertEqual(mesh.source_metadata['tiles'], 870)
        self.assertEqual(mesh.source_metadata['polygons'], 1361)
        self.assertEqual(len(mesh.triangles), 2530)
        reached, pending = set(), [0]
        while pending:
            node = pending.pop()
            if node not in reached:
                reached.add(node)
                pending.extend(mesh.adjacency[node])
        self.assertEqual(len(reached), len(mesh.triangles))
        from server import roster
        for spawn in roster.HERO_SPAWNS.values():
            self.assertTrue(mesh.contains(spawn), spawn)
            self.assertTrue(mesh.find_path(spawn, (0, 0)), spawn)


if __name__ == '__main__':
    unittest.main()
