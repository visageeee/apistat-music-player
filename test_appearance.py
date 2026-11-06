import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import cairo
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

import appearance


class AppearanceTests(unittest.TestCase):
    def test_info_panel_width_is_saved_and_validated(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertEqual(appearance.load_info_panel_width(), 300)
            appearance.save_info_panel_width(520)
            self.assertEqual(appearance.load_info_panel_width(), 520)
            with self.assertRaises(ValueError):
                appearance.save_info_panel_width(200)

    def test_playlist_order_is_saved_per_server_and_account(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            order = ['/playlists/2/items', '/playlists/1/items']
            appearance.save_playlist_order('http://server', 'token', order)
            self.assertEqual(appearance.load_playlist_order('http://server', 'token'), order)
            self.assertEqual(appearance.load_playlist_order('http://server', 'other'), [])
            self.assertEqual(appearance.load_playlist_order('http://other', 'token'), [])
            with self.assertRaises(ValueError):
                appearance.save_playlist_order('http://server', 'token', ['/other'])

    def test_frosted_player_bar_preference_persists(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertFalse(appearance.load_frosted_player_bar())
            appearance.save_frosted_player_bar(True)
            self.assertTrue(appearance.load_frosted_player_bar())
            appearance.save_frosted_player_bar(False)
            self.assertFalse(appearance.load_frosted_player_bar())

    def test_gradient_render_waits_until_resize_settles(self):
        widget = appearance.DitheredGradient()
        widget.colors = ('#334455', '#112233')
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 32, 24)
        with patch.object(widget, 'get_allocated_width', return_value=32), \
                patch.object(widget, 'get_allocated_height', return_value=24), \
                patch.object(widget, '_start_render') as start, \
                patch('appearance.GLib.timeout_add', return_value=99), \
                patch('appearance.GLib.source_remove'):
            widget.draw_gradient(widget, cairo.Context(canvas))
            start.assert_not_called()
            self.assertEqual(widget._scheduled_key[:2], (32, 24))
            widget.destroy()

    def test_same_style_queue_option_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
                self.assertFalse(appearance.load_keep_style_playing_enabled())
                appearance.save_keep_style_playing_enabled(True)
                self.assertTrue(appearance.load_keep_style_playing_enabled())
                appearance.save_keep_style_playing_enabled(False)
                self.assertFalse(appearance.load_keep_style_playing_enabled())

    def test_background_visualizer_preference_persists(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertFalse(appearance.load_background_visualizer_enabled())
            appearance.save_background_visualizer_enabled(True)
            self.assertTrue(appearance.load_background_visualizer_enabled())
            appearance.save_background_visualizer_enabled(False)
            self.assertFalse(appearance.load_background_visualizer_enabled())

    def test_sidebar_note_animation_preference_persists(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertTrue(appearance.load_sidebar_note_animation_enabled())
            appearance.save_sidebar_note_animation_enabled(False)
            self.assertFalse(appearance.load_sidebar_note_animation_enabled())
            appearance.save_sidebar_note_animation_enabled(True)
            self.assertTrue(appearance.load_sidebar_note_animation_enabled())

    def test_sidebar_labels_preference_persists(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertFalse(appearance.load_sidebar_labels_enabled())
            appearance.save_sidebar_labels_enabled(True)
            self.assertTrue(appearance.load_sidebar_labels_enabled())
            appearance.save_sidebar_labels_enabled(False)
            self.assertFalse(appearance.load_sidebar_labels_enabled())

    def test_sidebar_order_migrates_and_visibility_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            with patch.object(appearance, 'SETTINGS_PATH', path):
                appearance._write_settings({
                    'sidebar_order': ['now', 'albums', 'library', 'queue', 'settings']})
                self.assertEqual(appearance.load_sidebar_order(),
                                 ['now', 'albums', 'library', 'queue', 'styles', 'lyrics', 'time', 'settings'])
                appearance._write_settings({'sidebar_visible': ['albums']})
                self.assertEqual(appearance.load_sidebar_visible(),
                                 {'albums', 'lyrics', 'time', 'settings'})
                appearance.save_sidebar_visible({'albums', 'styles', 'settings'})
                self.assertEqual(appearance.load_sidebar_visible(),
                                 {'albums', 'styles', 'settings'})
                with self.assertRaises(ValueError):
                    appearance.save_sidebar_visible({'albums'})
                appearance._write_settings({'sidebar_visible': [['bad']]})
                self.assertEqual(appearance.load_sidebar_visible(),
                                 set(appearance.DEFAULT_SIDEBAR_ORDER))

    def test_gradient_fades_between_cached_artwork_colors(self):
        widget = appearance.DitheredGradient()
        red = ('#ff0000', '#ff0000')
        blue = ('#0000ff', '#0000ff')
        with patch('appearance.time.monotonic', return_value=100.0):
            widget.set_colors(red)
            future = Future()
            future.set_result(appearance.render_dithered_gradient(1, 1, red))
            widget._finish_render((1, 1, red), future)
            widget._stop_fade()
            widget._previous = None
            widget._fade_started = None
            widget.set_colors(blue)
            future = Future()
            future.set_result(appearance.render_dithered_gradient(1, 1, blue))
            widget._finish_render((1, 1, blue), future)
        self.assertIsNotNone(widget._previous)
        self.assertIsNotNone(widget._fade_started)
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        with patch('appearance.time.monotonic', return_value=100.4):
            widget.draw_gradient(widget, cairo.Context(canvas))
        blue_channel, _green, red_channel, _alpha = bytes(canvas.get_data())[:4]
        self.assertGreater(blue_channel, 70)
        self.assertGreater(red_channel, 70)
        self.assertLess(blue_channel, 190)
        self.assertLess(red_channel, 190)
        widget.destroy()

    def test_preloaded_gradient_is_ready_on_color_change(self):
        colors = ('#194063', '#5a132b')
        appearance._gradient_memory.clear()
        surface, pixels = appearance.cached_gradient(32, 24, colors)
        widget = appearance.DitheredGradient()
        with patch.object(widget, 'get_allocated_width', return_value=32), \
                patch.object(widget, 'get_allocated_height', return_value=24):
            widget.set_colors(colors)
            self.assertIs(widget._cache[1], surface)
            self.assertIs(widget._cache[2], pixels)
            self.assertIsNotNone(widget._fade_started)
        widget.destroy()

    def test_gradient_fade_eases_in_and_out(self):
        fade = appearance.DitheredGradient.fade_alpha
        self.assertEqual(fade(0), 0)
        self.assertEqual(fade(appearance.DitheredGradient.FADE_SECONDS / 2), 0.5)
        self.assertEqual(fade(appearance.DitheredGradient.FADE_SECONDS), 1)
        self.assertLess(fade(0.08), 0.1)
        self.assertGreater(fade(0.72), 0.9)

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
                self.assertTrue(appearance.load_gradient_enabled())
                self.assertTrue(appearance.load_album_details_enabled())
                self.assertEqual(appearance.load_album_columns(), 5)
                self.assertEqual(appearance.load_theme(), 'dark')
                appearance.save_theme('black')
                self.assertEqual(appearance.load_theme(), 'black')
                appearance.save_theme('light')
                self.assertEqual(appearance.load_theme(), 'light')
                with self.assertRaises(ValueError):
                    appearance.save_theme('unknown')
                appearance.save_gradient_enabled(True)
                self.assertTrue(appearance.load_gradient_enabled())
                self.assertFalse(appearance.load_star_ratings_hidden())
                appearance.save_star_ratings_hidden(True)
                self.assertTrue(appearance.load_star_ratings_hidden())
                self.assertTrue(appearance.load_smooth_scrolling_enabled())
                appearance.save_smooth_scrolling_enabled(False)
                self.assertFalse(appearance.load_smooth_scrolling_enabled())
                appearance.save_smooth_scrolling_enabled(True)
                appearance.save_album_details_enabled(False)
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
                self.assertTrue(appearance.load_rounded_corners_enabled())
                self.assertEqual(appearance.load_text_size(), 18)
                appearance.save_single_flip_enabled(True)
                appearance.save_title_bar_hidden(True)
                appearance.save_window_buttons_enabled(True)
                appearance.save_rounded_corners_enabled(True)
                appearance.save_text_size(20)
                self.assertTrue(appearance.load_single_flip_enabled())
                self.assertTrue(appearance.load_title_bar_hidden())
                self.assertTrue(appearance.load_window_buttons_enabled())
                self.assertTrue(appearance.load_rounded_corners_enabled())
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
                self.assertEqual(appearance.load_album_margins(), (40, 30))
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
