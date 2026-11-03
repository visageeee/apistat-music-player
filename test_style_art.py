import unittest

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

from style_art import square_preview


class StyleArtTests(unittest.TestCase):
    def test_preview_crops_to_square_without_blurring_artwork(self):
        source = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 40, 20)
        source.fill(0xff0000ff)
        blue = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 20, 20)
        blue.fill(0x0000ffff)
        blue.copy_area(0, 0, 20, 20, source, 20, 0)
        preview = square_preview(source)
        self.assertEqual((preview.get_width(), preview.get_height()), (224, 224))
        pixels = preview.get_pixels()
        left = 112 * preview.get_rowstride() + 30 * preview.get_n_channels()
        right = 112 * preview.get_rowstride() + 190 * preview.get_n_channels()
        self.assertEqual(tuple(pixels[left:left + 3]), (255, 0, 0))
        self.assertEqual(tuple(pixels[right:right + 3]), (0, 0, 255))


if __name__ == '__main__':
    unittest.main()
