import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cairo
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

import appearance


class AppearanceTests(unittest.TestCase):
    def test_theme_gradient_black_is_disabled_and_light_is_readable(self):
        colors = ('#221144', '#334455')
        self.assertEqual(appearance.theme_gradient_colors(colors, 'dark'), colors)
        self.assertIsNone(appearance.theme_gradient_colors(colors, 'black'))
        light = appearance.theme_gradient_colors(colors, 'light')
        self.assertEqual(len(light), 2)
        self.assertTrue(all(min(bytes.fromhex(color[1:])) > 190 for color in light))

    def test_album_age_uses_days_since_plex_added_timestamp(self):
        added = 1700000000
        self.assertEqual(appearance.added_age_label(added, added + 3600), 'Added today')
        self.assertEqual(appearance.added_age_label(added, added + 86400), 'Added 1 day ago')
        self.assertEqual(appearance.added_age_label(added, added + 2 * 86400), 'Added 2 days ago')
        self.assertEqual(appearance.added_age_label(0, added), 'Date added unknown')

    def test_gradient_dither_breaks_up_flat_color_without_large_variation(self):
        surface, _pixels = appearance.render_dithered_gradient(
            256, 128, ('#444444', '#444444'))
        pixels = bytes(surface.get_data())
        shades = set(pixels[0::4])
        self.assertGreater(len(shades), 1)
        self.assertLess(max(shades) - min(shades), 8)
        self.assertNotEqual(pixels[:128 * 4], pixels[128 * 4:256 * 4])

    def test_gradient_uses_artwork_colors_and_stays_dark(self):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 32, 32)
        pixbuf.fill(0xd02020ff)
        pixbuf.new_subpixbuf(16, 0, 16, 32).fill(0x2040d0ff)

        colors = appearance.gradient_colors(pixbuf)

        self.assertEqual(len(colors), 2)
        self.assertNotEqual(*colors)
        self.assertLessEqual(max(bytes.fromhex(colors[0][1:])), 86)
        self.assertLessEqual(max(bytes.fromhex(colors[1][1:])), 42)
        waveform = appearance.waveform_colors(pixbuf)
        self.assertNotEqual(*waveform)
        self.assertGreaterEqual(max(bytes.fromhex(waveform[0][1:])), 180)

    def test_preference_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            with patch.object(appearance, 'SETTINGS_PATH', path):
                self.assertFalse(appearance.load_gradient_enabled())
                self.assertEqual(appearance.load_theme(), 'dark')
                appearance.save_theme('black')
                self.assertEqual(appearance.load_theme(), 'black')
                appearance.save_theme('light')
                self.assertEqual(appearance.load_theme(), 'light')
                with self.assertRaises(ValueError):
                    appearance.save_theme('unknown')
                appearance.save_gradient_enabled(True)
                self.assertTrue(appearance.load_gradient_enabled())
                self.assertFalse(appearance.load_album_details_enabled())
                appearance.save_album_details_enabled(True)
                self.assertTrue(appearance.load_album_details_enabled())
                self.assertEqual(appearance.load_art_sizes(), (160, 360))
                appearance.save_art_sizes(220, 440)
                self.assertEqual(appearance.load_art_sizes(), (220, 440))
                appearance.save_gradient_enabled(False)
                self.assertFalse(appearance.load_gradient_enabled())
                self.assertTrue(appearance.load_album_details_enabled())
                self.assertEqual(appearance.load_art_sizes(), (220, 440))
                self.assertEqual(appearance.load_album_columns(), 5)
                appearance.save_album_columns(16)
                self.assertEqual(appearance.load_album_columns(), 16)
                appearance.save_single_flip_enabled(True)
                appearance.save_title_bar_hidden(True)
                appearance.save_text_size(20)
                self.assertTrue(appearance.load_single_flip_enabled())
                self.assertTrue(appearance.load_title_bar_hidden())
                self.assertEqual(appearance.load_text_size(), 20)
                self.assertFalse(appearance.load_search_index_enabled())
                appearance.save_search_index_enabled(True)
                self.assertTrue(appearance.load_search_index_enabled())
                self.assertEqual(appearance.load_custom_font(), '')
                appearance.save_custom_font('DejaVu Sans')
                self.assertEqual(appearance.load_custom_font(), 'DejaVu Sans')
                appearance.save_custom_font('')
                self.assertEqual(appearance.load_custom_font(), '')
                self.assertFalse(appearance.load_tooltips_hidden())
                appearance.save_tooltips_hidden(True)
                self.assertTrue(appearance.load_tooltips_hidden())
                self.assertEqual(appearance.load_accent_color(), '#e7a641')
                appearance.save_accent_color('#2DA7F0')
                self.assertEqual(appearance.load_accent_color(), '#2da7f0')
                self.assertFalse(appearance.load_art_accent_enabled())
                appearance.save_art_accent_enabled(True)
                self.assertTrue(appearance.load_art_accent_enabled())
                appearance.save_now_art_size(480)
                self.assertEqual(appearance.load_art_sizes(), (220, 480))
                self.assertEqual(appearance.load_album_margins(), (20, 12))
                appearance.save_album_margins(32, 8)
                self.assertEqual(appearance.load_album_margins(), (32, 8))
                self.assertLess(appearance.album_cover_size(1100, 8, 32, 8),
                                appearance.album_cover_size(1100, 8, 0, 8))
                all_songs, playlist = 'a' * 64, 'b' * 64
                appearance.save_library_layout(all_songs, {'visible': ['title', 'artist']})
                appearance.save_library_layout(playlist, {'visible': ['title', 'genre']})
                self.assertEqual(appearance.load_library_layout(all_songs)['visible'],
                                 ['title', 'artist'])
                self.assertEqual(appearance.load_library_layout(playlist)['visible'],
                                 ['title', 'genre'])


if __name__ == '__main__':
    unittest.main()
