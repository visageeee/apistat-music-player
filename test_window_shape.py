import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from window_shape import rounded_region
from player import Player


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

    def test_resize_temporarily_clears_shape_and_restores_after_settling(self):
        window = SimpleNamespace(shape_combine_region=Mock(), input_shape_combine_region=Mock())
        player = SimpleNamespace(get_window=lambda: window, _window_shape_suspended=False,
                                 _window_shape_resume_source=0, _window_shape_state=(800, 600, True),
                                 resume_window_shape=Mock(), refresh_window_shape=Mock(), closed=False)
        with patch('player.GLib.timeout_add', side_effect=[11, 12]) as timer, \
                patch('player.GLib.source_remove') as remove:
            Player.defer_window_shape(player)
            Player.defer_window_shape(player)
            self.assertTrue(player._window_shape_suspended)
            window.shape_combine_region.assert_called_once_with(None, 0, 0)
            window.input_shape_combine_region.assert_called_once()
            self.assertTrue(window.input_shape_combine_region.call_args.args[0].contains_point(2000, 1000))
            remove.assert_called_once_with(11)
            self.assertEqual(timer.call_count, 2)
            self.assertFalse(Player.resume_window_shape(player))
        self.assertFalse(player._window_shape_suspended)
        self.assertEqual(player._window_shape_resume_source, 0)
        player.refresh_window_shape.assert_called_once_with()

    @unittest.skipIf(os.name == 'nt', 'Windows uses the native frame')
    def test_square_window_does_not_reapply_shape_for_each_size(self):
        allocation = SimpleNamespace(width=800, height=600)
        window = SimpleNamespace(get_state=lambda: 0, shape_combine_region=Mock(),
                                 input_shape_combine_region=Mock())
        player = SimpleNamespace(get_window=lambda: window, get_allocation=lambda: allocation,
                                 rounded_corners_enabled=False, _window_shape_state=None,
                                 _window_shape_suspended=False)
        Player.refresh_window_shape(player)
        allocation.width = 700
        Player.refresh_window_shape(player)
        window.shape_combine_region.assert_called_once_with(None, 0, 0)
        window.input_shape_combine_region.assert_called_once()
        self.assertTrue(window.input_shape_combine_region.call_args.args[0].contains_point(2000, 1000))

    @unittest.skipIf(os.name == 'nt', 'Windows uses the native frame')
    def test_square_input_shape_works_with_real_gtk_binding(self):
        if not Gtk.init_check()[0]:
            self.skipTest('GTK display unavailable')
        window = Gtk.Window()
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        player = SimpleNamespace(get_window=window.get_window, get_allocation=window.get_allocation,
                                 rounded_corners_enabled=False, _window_shape_state=None,
                                 _window_shape_suspended=False)
        try:
            self.assertFalse(Player.refresh_window_shape(player))
        finally:
            window.destroy()


if __name__ == '__main__':
    unittest.main()
