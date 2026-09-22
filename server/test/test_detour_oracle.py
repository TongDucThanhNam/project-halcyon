"""Reference comparison must retain scope, truncation and numeric differences."""
import unittest
from unittest.mock import Mock
from Tools.Teardown.detour_route_oracle import compare_path, point


class ReferenceScopeTests(unittest.TestCase):
    def native(self,points,flags=1,destination=None):
        return {'observed':{'navigation_flags':flags},'count':len(points),'points':points,
                'destination':destination or points[-1]}

    def test_inactive_array_is_not_paired_with_changed_stop_or_respawn_destination(self):
        oracle=Mock()
        for flags in (0,6,34,38):
            with self.subTest(flags=flags),self.assertRaises(ValueError):
                compare_path(self.native([[0,0,0],[4,0,0]],flags,destination=[2,0,0]),oracle)
        oracle.query.assert_not_called()

    def test_cap_is_preserved_even_when_all_retained_points_match(self):
        points=[[i,0,0] for i in range(128)]
        oracle=Mock();oracle.query.return_value={'points':points,'capped':True,'ended':False}
        result=compare_path(self.native(points,destination=[200,0,0]),oracle)
        self.assertTrue(result['exact_float32'])
        self.assertTrue(result['oracle']['capped'])
        self.assertFalse(result['oracle']['ended'])
        self.assertNotEqual(result['native_destination'],result['native_endpoint'])
        oracle.query.assert_called_once_with((0,0,0),(200,0,0))

    def test_height_ulp_difference_is_reported_not_mislabeled_exact(self):
        points=[[0,0,0],[1,.5,0],[2,1,0]]
        oracle=Mock();oracle.query.return_value={'points':[[0,0,0],[1,.5+2**-24,0],[2,1,0]]}
        result=compare_path(self.native(points),oracle)
        self.assertFalse(result['exact_float32'])
        self.assertEqual(result['max_aligned_point_error'],2**-24)
        self.assertEqual(result['endpoint_error'],0)

    def test_different_count_cannot_be_compared_using_a_zip_prefix(self):
        oracle=Mock();oracle.query.return_value={'points':[[0,0,0],[1,0,0]]}
        result=compare_path(self.native([[0,0,0],[1,0,0],[2,0,0]]),oracle)
        self.assertIsNone(result['max_aligned_point_error'])
        self.assertFalse(result['exact_float32'])
        self.assertEqual(result['endpoint_error'],1)

    def test_nonfinite_query_is_not_sent_to_native_library(self):
        for value in ([0,float('inf'),0],[0,float('nan'),0],[0,0],[True,0,0]):
            with self.subTest(value=value),self.assertRaises(ValueError):
                point(value)


if __name__ == '__main__':
    unittest.main()
