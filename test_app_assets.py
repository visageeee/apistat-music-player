import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import app_assets
from player import Player


class AppAssetTests(unittest.TestCase):
    def test_logo_loads_from_source_and_frozen_bundle_path(self):
        self.assertTrue(app_assets.icon_path().is_file())
        self.assertTrue(app_assets.app_icon().get_has_alpha())
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app_assets.sys, '_MEIPASS', directory, create=True):
                self.assertEqual(app_assets.icon_path(), Path(directory) / 'apistat.png')

    def test_placeholder_resizes_and_does_not_masquerade_as_plex_art(self):
        image = Gtk.Image()
        player = SimpleNamespace()
        Player.set_placeholder_art(player, image, 80,
                                   app_assets.SMALL_PLACEHOLDER_LOGO_RATIO)
        self.assertIsNone(image.art_source)
        self.assertTrue(image.placeholder_art)
        self.assertEqual((image.get_pixbuf().get_width(),
                          image.get_pixbuf().get_height()), (80, 80))
        Player.set_art_size(player, image, 160)
        self.assertEqual((image.get_pixbuf().get_width(),
                          image.get_pixbuf().get_height()), (160, 160))
        pixbuf = image.get_pixbuf()
        self.assertTrue(pixbuf.get_has_alpha())
        pixels = pixbuf.get_pixels()
        stride = pixbuf.get_rowstride()
        bounds = [(x, y) for y in range(160) for x in range(160)
                  if pixels[y * stride + x * 4 + 3]]
        self.assertGreaterEqual(min(x for x, _y in bounds), 30)
        self.assertLessEqual(max(x for x, _y in bounds), 129)
        self.assertGreaterEqual(min(y for _x, y in bounds), 30)
        self.assertLessEqual(max(y for _x, y in bounds), 129)


if __name__ == '__main__':
    unittest.main()
