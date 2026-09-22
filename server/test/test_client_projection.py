"""Independent analytic camera cases and invalid-input gates."""
import unittest
from Tools.Teardown.client_projection import world_to_screen


class ClientProjectionTests(unittest.TestCase):
    def setUp(self):
        # Unit focal lengths, near1/far10, looking down -Z from (2,0,0).
        self.camera = {'view': [1,0,0,0, 0,1,0,0, 0,0,1,0, -2,0,0,1],
            'projection': [1,0,0,0, 0,1,0,0, 0,0,-11/9,-1, 0,0,-20/9,0],
            'dimensions': [960,540]}

    def test_camera_translation_perspective_and_upper_left_origin(self):
        self.assertEqual(world_to_screen(self.camera, [2,0,-2]), [480,270])
        self.assertEqual(world_to_screen(self.camera, [3,1,-2]), [720,135])
        self.assertEqual(world_to_screen(self.camera, [3,1,-4]), [600,202.5])

    def test_behind_near_far_and_offscreen_points_are_rejected(self):
        for p in ([2,0,2], [2,0,0], [2,0,-.5], [2,0,-11], [10,0,-2]):
            with self.subTest(p=p), self.assertRaises(ValueError):
                world_to_screen(self.camera,p)

    def test_nonfinite_malformed_and_invalid_viewport_are_rejected(self):
        for p in ([1,2], [1,float('nan'),-2], [1,True,-2]):
            with self.subTest(p=p), self.assertRaises(ValueError):
                world_to_screen(self.camera,p)
        for dimensions in ([0,540], [960.5,540], [960,9000]):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                world_to_screen(dict(self.camera,dimensions=dimensions), [2,0,-2])


if __name__ == '__main__':
    unittest.main()
