import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from player import Player

import cairo

from sidebar_icons import (CUSTOM_SIDEBAR_ICONS, SidebarIcon, draw_sidebar_icon,
                           sidebar_icon_color)


class SidebarIconTests(unittest.TestCase):
    def test_custom_icons_draw_distinct_visible_shapes(self):
        images = []
        for name in ('now', 'albums', 'library', 'styles', 'lyrics', 'queue'):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 28, 28)
            draw_sidebar_icon(cairo.Context(surface), name, 28, 28, '#eeeeee')
            surface.flush()
            data = bytes(surface.get_data())
            self.assertTrue(any(data[3::4]), name)
            images.append(data)
        self.assertEqual(len(set(images)), len(images))
        self.assertEqual(CUSTOM_SIDEBAR_ICONS,
                         {'now', 'albums', 'library', 'styles', 'lyrics', 'queue'})

    def test_active_icon_tracks_accent_and_inactive_icon_tracks_theme(self):
        current = ['albums']
        player = SimpleNamespace(content_views=SimpleNamespace(
            get_visible_child_name=lambda: current[0]), theme='dark',
            accent_color='#ff8000', art_accent_enabled=False, current_art_bright='#aabbcc')
        self.assertEqual(sidebar_icon_color(player, 'albums'), '#ff8000')
        self.assertEqual(sidebar_icon_color(player, 'now'), '#eeeeee')
        player.art_accent_enabled = True
        self.assertEqual(sidebar_icon_color(player, 'albums'), '#aabbcc')
        player.theme = 'light'
        self.assertEqual(sidebar_icon_color(player, 'now'), '#202326')
        current[0] = 'now'
        self.assertEqual(sidebar_icon_color(player, 'now'), '#aabbcc')

    def test_sidebar_label_does_not_replace_icon_and_stays_hidden_on_show_all(self):
        player = SimpleNamespace(sidebar_labels_enabled=False)
        button = Gtk.Button()
        icon = SidebarIcon(player, 'now')
        button.set_image(icon)
        Player.setup_sidebar_label(player, button, 'Now playing')
        button.show_all()
        self.assertIs(button.get_image(), icon)
        self.assertFalse(button.sidebar_label.get_visible())
        button.sidebar_label.set_visible(True)
        self.assertTrue(button.sidebar_label.get_visible())
        button.destroy()

    def test_now_playing_fill_changes_and_animation_stops_on_pause(self):
        surfaces = []
        for fill in (0.2, 0.8):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 28, 28)
            draw_sidebar_icon(cairo.Context(surface), 'now', 28, 28, '#eeeeee', fill)
            surface.flush()
            surfaces.append(bytes(surface.get_data()))
        self.assertNotEqual(*surfaces)
        icon = SidebarIcon(SimpleNamespace(), 'now')
        with patch.object(icon, 'add_tick_callback', return_value=123) as start, \
                patch.object(icon, 'remove_tick_callback') as stop:
            icon.set_playing(True)
            icon.set_playing(True)
            start.assert_called_once()
            icon.set_playing(False)
            stop.assert_called_once_with(123)
            self.assertFalse(icon.playing)
        icon.destroy()

    def test_icons_do_not_own_input_windows(self):
        player = SimpleNamespace()
        for name in CUSTOM_SIDEBAR_ICONS:
            icon = SidebarIcon(player, name)
            self.assertFalse(icon.get_has_window())
            self.assertEqual((icon.get_size_request().width, icon.get_size_request().height), (28, 28))
            icon.destroy()


if __name__ == '__main__':
    unittest.main()
