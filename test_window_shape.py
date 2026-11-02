import unittest

from window_shape import rounded_region


class WindowShapeTests(unittest.TestCase):
    def test_corners_are_cut_without_clipping_window_edges(self):
        region = rounded_region(100, 60, 14)
        self.assertFalse(region.contains_point(0, 0))
        self.assertFalse(region.contains_point(99, 0))
        self.assertFalse(region.contains_point(0, 59))
        self.assertFalse(region.contains_point(99, 59))
        self.assertTrue(region.contains_point(50, 0))
        self.assertTrue(region.contains_point(0, 30))
        self.assertTrue(region.contains_point(50, 30))

    def test_small_windows_and_square_mask(self):
        region = rounded_region(10, 8, 20)
        self.assertTrue(region.contains_point(5, 4))
        self.assertFalse(region.contains_point(0, 0))
        self.assertTrue(rounded_region(10, 8, 0).contains_point(0, 0))
        with self.assertRaises(ValueError):
            rounded_region(0, 8)


if __name__ == '__main__':
    unittest.main()
