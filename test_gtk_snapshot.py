import unittest
from unittest.mock import patch

import cairo
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk

from album_card import FlipCard
from frosted_bar import FrostedBar
from gtk_snapshot import draw_allocated, normalize_surface_origin
from player import Player


class GtkSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.criticals = []
        self.log_handler = GLib.log_set_handler(
            'Gtk', GLib.LogLevelFlags.LEVEL_CRITICAL,
            lambda _domain, _level, message, *_args: self.criticals.append(message))

    def tearDown(self):
        GLib.log_remove_handler('Gtk', self.log_handler)

    @staticmethod
    def show(widget):
        window = Gtk.OffscreenWindow()
        window.add(widget)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        return window

    def assert_no_draw_critical(self):
        self.assertFalse([message for message in self.criticals if 'gtk_widget_draw' in message],
                         self.criticals)

    def test_snapshot_allocates_only_when_gtk_has_a_pending_resize(self):
        label = Gtk.Label(label='Track')
        window = self.show(label)
        allocations = []
        label.connect('size-allocate', lambda *_args: allocations.append(1))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 40)
        try:
            draw_allocated(label, cairo.Context(surface))
            draw_allocated(label, cairo.Context(surface))
            self.assertEqual(allocations, [])
            label.queue_resize()
            draw_allocated(label, cairo.Context(surface))
            self.assertEqual(len(allocations), 1)
            self.assert_no_draw_critical()
        finally:
            window.destroy()

    def test_tree_row_drag_surface_has_zero_origin_for_gtk_image(self):
        model = Gtk.ListStore(str)
        model.append(['Track'])
        view = Gtk.TreeView(model=model)
        view.append_column(Gtk.TreeViewColumn('Title', Gtk.CellRendererText(), text=0))
        window = self.show(view)
        try:
            surface = view.create_row_drag_icon(Gtk.TreePath.new_from_indices([0]))
            self.assertIsNotNone(surface)
            normalized = normalize_surface_origin(surface)
            self.assertIs(normalized, surface)
            self.assertEqual(surface.get_device_offset(), (0.0, 0.0))
            self.assertEqual(cairo.Context(surface).clip_extents()[:2], (0.0, 0.0))
            image = Gtk.Image.new_from_surface(surface)
            image.get_preferred_width()
            image.destroy()
        finally:
            window.destroy()

    def test_album_snapshot_handles_pending_resize(self):
        front = Gtk.Label(label='Front')
        card = FlipCard(front, Gtk.Label(label='Back'), 120)
        window = self.show(card)
        try:
            front.queue_resize()
            self.assertIsNotNone(card.snapshot(front))
            self.assert_no_draw_critical()
        finally:
            window.destroy()

    def test_frosted_capture_handles_pending_content_and_background_resize(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        background = Gtk.DrawingArea()
        background.set_size_request(120, 100)
        content = Gtk.EventBox()
        content.set_size_request(120, 100)
        bar = Gtk.DrawingArea()
        bar.set_size_request(120, 40)
        for widget in (background, content, bar):
            box.pack_start(widget, False, False, 0)
        window = self.show(box)
        glass = FrostedBar(bar, content, background, lambda: 'dark')
        glass.enabled = True
        glass._ready = {id(content): True, id(background): True}
        try:
            background.queue_resize()
            content.queue_resize()
            glass.refresh()
            self.assertIsNotNone(glass.surface)
            self.assert_no_draw_critical()
        finally:
            glass.stop()
            window.destroy()

    def test_album_track_drag_preview_handles_pending_resize(self):
        button = Gtk.Button(label='Track')
        window = self.show(button)
        try:
            button.queue_resize()
            with patch('player.Gtk.drag_set_icon_surface') as set_icon:
                Player.album_track_drag_begin(None, button, object(), 'Track')
            set_icon.assert_called_once()
            self.assert_no_draw_critical()
        finally:
            window.destroy()


if __name__ == '__main__':
    unittest.main()
