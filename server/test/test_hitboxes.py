"""Geometric boundary and deterministic ordering checks independent of hero kits."""
import math
import unittest

from server.hitboxes import TargetDisk, circle_hits, cone_hits, dash_endpoint, line_hits


class TestAbilityHitboxes(unittest.TestCase):
    def test_line_stops_at_first_contact_not_input_order(self):
        disks = [TargetDisk(2, 8, 0), TargetDisk(1, 3, 0)]
        self.assertEqual(line_hits((0, 0), (1, 0), 10, 0.2, disks), [1])

    def test_line_pierces_in_contact_order(self):
        disks = [TargetDisk(8, 8, 0), TargetDisk(3, 3, 0), TargetDisk(1, 1, 0)]
        self.assertEqual(line_hits((0, 0), (1, 0), 10, 0.2, disks, pierce=True), [1, 3, 8])

    def test_line_disk_radius_changes_first_contact(self):
        disks = [TargetDisk(1, 5, 0, 2), TargetDisk(2, 4, 0, 0.1)]
        self.assertEqual(line_hits((0, 0), (1, 0), 10, 0, disks), [1])

    def test_line_equal_contacts_break_ties_by_eid(self):
        disks = [TargetDisk(9, 3, 0), TargetDisk(1, 3, 0)]
        self.assertEqual(line_hits((0, 0), (1, 0), 10, 0.5, disks, pierce=True), [1, 9])

    def test_line_is_a_finite_segment_with_width(self):
        disks = [TargetDisk(1, 5, 0.5), TargetDisk(2, 5, 0.51),
                 TargetDisk(3, 10.5, 0), TargetDisk(4, 10.51, 0), TargetDisk(5, -1, 0)]
        self.assertEqual(line_hits((0, 0), (1, 0), 10, 0.5, disks, pierce=True), [1, 3])

    def test_line_rotates_with_aim(self):
        disks = [TargetDisk(1, 0, 4), TargetDisk(2, 4, 0)]
        self.assertEqual(line_hits((0, 0), (0, 1), 10, 0.2, disks), [1])

    def test_cone_excludes_targets_behind_and_beyond_range(self):
        disks = [TargetDisk(1, 5, 0), TargetDisk(2, -1, 0), TargetDisk(3, 11, 0)]
        self.assertEqual(cone_hits((0, 0), (1, 0), 10, 60, disks), [1])

    def test_cone_sector_edge_is_inclusive(self):
        edge = 5 * math.tan(math.radians(30))
        disks = [TargetDisk(1, 5, edge), TargetDisk(2, 5, edge + 0.01)]
        self.assertEqual(cone_hits((0, 0), (1, 0), 10, 60, disks), [1])

    def test_cone_target_disk_can_overlap_edge(self):
        disks = [TargetDisk(1, 5, 3.0, 0.5), TargetDisk(2, 5, 4.0, 0.5)]
        self.assertEqual(cone_hits((0, 0), (1, 0), 10, 60, disks), [1])

    def test_cone_checks_arc_radius_in_addition_to_angle(self):
        disks = [TargetDisk(1, 10.2, 0.0, 0.3), TargetDisk(2, 10.4, 0.0, 0.3)]
        self.assertEqual(cone_hits((0, 0), (1, 0), 10, 60, disks), [1])

    def test_cone_rotates_and_supports_reflex_angles(self):
        disks = [TargetDisk(1, 0, 3), TargetDisk(2, -3, 0), TargetDisk(3, 0, -3)]
        self.assertEqual(cone_hits((0, 0), (0, 1), 5, 60, disks), [1])
        self.assertEqual(cone_hits((0, 0), (0, 1), 5, 270, disks), [1, 2])

    def test_circle_includes_touching_disk_and_orders_by_eid(self):
        disks = [TargetDisk(8, 2, 0), TargetDisk(2, 3.5, 0, 0.5), TargetDisk(1, 3.6, 0, 0.5)]
        self.assertEqual(circle_hits((0, 0), 3, disks), [2, 8])

    def test_dash_over_target_and_clamped_range(self):
        self.assertEqual(dash_endpoint((0, 0), (3, 0), 8, behind=1), (4, 0))
        self.assertEqual(dash_endpoint((0, 0), (10, 0), 8, behind=1), (8, 0))

    def test_coincident_dash_uses_facing(self):
        self.assertEqual(dash_endpoint((2, 2), (2, 2), 8, facing=(0, -1)), (2, 1))

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            TargetDisk(1, math.nan, 0)
        with self.assertRaises(ValueError):
            line_hits((0, 0), (1, 0), -1, 0, [])
        with self.assertRaises(ValueError):
            circle_hits((0, 0), math.inf, [])
        with self.assertRaises(ValueError):
            cone_hits((0, 0), (1, 0), 1, 0, [])
        with self.assertRaises(ValueError):
            dash_endpoint((0, 0), (math.inf, 0), 1)


if __name__ == "__main__":
    unittest.main()
