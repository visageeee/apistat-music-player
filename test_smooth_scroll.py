import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

from smooth_scroll import SmoothScroller
from player import LIBRARY_COLUMNS, Player


class SmoothScrollTests(unittest.TestCase):
    def test_library_scrollbar_stays_visible_when_list_overflows(self):
        model = Gtk.ListStore(str)
        for index in range(100):
            model.append([f'Track {index}'])
        view = Gtk.TreeView(model=model)
        view.append_column(Gtk.TreeViewColumn('Track', Gtk.CellRendererText(), text=0))
        player = SimpleNamespace(attach_smooth_scroll=lambda scroll: scroll)
        scroll = Player.scroll(player, view, overlay_scrolling=False)
        window = Gtk.OffscreenWindow()
        window.set_size_request(240, 150)
        window.add(scroll)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        try:
            self.assertFalse(scroll.get_overlay_scrolling())
            self.assertEqual(scroll.get_policy().vscrollbar_policy, Gtk.PolicyType.AUTOMATIC)
            self.assertTrue(scroll.get_vscrollbar().get_visible())
        finally:
            window.destroy()

    def test_playlist_scrollbar_stays_in_place_while_scrolling(self):
        playlist_list = Gtk.ListBox()
        for index in range(60):
            playlist_list.add(Gtk.Label(label=f'Playlist {index}'))
        player = SimpleNamespace(attach_smooth_scroll=lambda scroll: scroll)
        scroll = Player.scroll(player, playlist_list, overlay_scrolling=False)
        window = Gtk.OffscreenWindow()
        window.set_size_request(240, 150)
        window.add(scroll)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        try:
            bar = scroll.get_vscrollbar()
            self.assertTrue(bar.get_visible())
            before = bar.get_allocation()
            adjustment = scroll.get_vadjustment()
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            while Gtk.events_pending():
                Gtk.main_iteration()
            after = bar.get_allocation()
            self.assertEqual((before.x, before.width), (after.x, after.width))
            self.assertFalse(scroll.get_overlay_scrolling())
        finally:
            window.destroy()

    def test_library_scrollbar_stays_fixed_while_list_changes_and_scrolls(self):
        model = Gtk.ListStore(str)
        for index in range(60):
            model.append([f'Track {index}'])
        view = Gtk.TreeView(model=model)
        view.append_column(Gtk.TreeViewColumn('Track', Gtk.CellRendererText(), text=0))
        player = SimpleNamespace(attach_smooth_scroll=lambda scroll: scroll)
        scroll = Player.scroll(player, view, overlay_scrolling=False)
        row = Player.stable_library_scrollbar(scroll)
        window = Gtk.OffscreenWindow()
        window.set_size_request(300, 150)
        window.add(row)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        try:
            scrollbar = row.get_children()[1]
            self.assertIs(scrollbar.get_adjustment(), scroll.get_vadjustment())
            self.assertEqual(scroll.get_policy().vscrollbar_policy, Gtk.PolicyType.EXTERNAL)
            before = scrollbar.get_allocation()
            for index in range(60, 100):
                model.append([f'A considerably longer track title {index}'])
            adjustment = scrollbar.get_adjustment()
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            scrollbar.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
            while Gtk.events_pending():
                Gtk.main_iteration()
            after = scrollbar.get_allocation()
            self.assertGreater(adjustment.get_value(), 0)
            self.assertEqual((before.x, before.width), (after.x, after.width))
        finally:
            window.destroy()

    def test_library_row_colors_switch_themes_without_per_cell_callbacks(self):
        model = Gtk.ListStore(*([str] * (len(LIBRARY_COLUMNS) + 4)))
        values = [''] * (len(LIBRARY_COLUMNS) + 4)
        values[0] = 'Track'
        values[len(LIBRARY_COLUMNS) + 1:] = ['#181818', '#f3f3f1', '#000000']
        row = model.append(values)
        cell = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn('Track', cell, text=0)
        player = SimpleNamespace(theme='dark', song_cell_attributes=[(column, cell, 0)])
        for theme, expected in (('dark', 24), ('light', 243), ('black', 0)):
            player.theme = theme
            Player.bind_song_cell_backgrounds(player)
            column.cell_set_cell_data(model, row, False, False)
            self.assertEqual(cell.get_property('text'), 'Track')
            self.assertAlmostEqual(cell.get_property('cell-background-rgba').red,
                                   expected / 255, places=3)

    @staticmethod
    def clock(seconds):
        return SimpleNamespace(get_frame_time=lambda: round(seconds * 1_000_000))

    def test_setting_updates_existing_scrollable_panels(self):
        changes = []
        scrollers = [SimpleNamespace(set_enabled=lambda enabled: changes.append(enabled))
                     for _ in range(3)]
        player = SimpleNamespace(smooth_scrollers=scrollers,
                                 status=SimpleNamespace(set_text=lambda _message: None))
        with patch('player.save_smooth_scrolling_enabled') as save:
            Player.smooth_scrolling_changed(
                player, SimpleNamespace(get_active=lambda: True))
        self.assertTrue(player.smooth_scrolling_enabled)
        self.assertEqual(changes, [True, True, True])
        save.assert_called_once_with(True)

    def test_wheel_animates_but_ctrl_zoom_keeps_its_handler(self):
        adjustment = Gtk.Adjustment(value=200, lower=0, upper=1000,
                                    step_increment=20, page_increment=100, page_size=100)
        window = Gtk.ScrolledWindow()
        window.set_vadjustment(adjustment)
        scroller = SmoothScroller(window, False)
        down = SimpleNamespace(direction=Gdk.ScrollDirection.DOWN, state=0)
        self.assertFalse(scroller.scroll_event(window, down))
        scroller.set_enabled(True)
        self.assertFalse(window.get_kinetic_scrolling())
        self.assertFalse(scroller.scroll_event(window, SimpleNamespace(
            direction=Gdk.ScrollDirection.DOWN, state=Gdk.ModifierType.CONTROL_MASK)))
        self.assertFalse(scroller.scroll_event(window, SimpleNamespace(
            direction=Gdk.ScrollDirection.SMOOTH, state=0)))
        with patch.object(window, 'get_frame_clock', return_value=self.clock(10.0)), \
                patch.object(window, 'add_tick_callback', return_value=42) as add_tick:
            self.assertTrue(scroller.scroll_event(window, down))
            add_tick.assert_called_once()
            self.assertEqual(scroller.target, 260)
            self.assertTrue(scroller.tick(window, self.clock(10.006)))
            self.assertGreater(adjustment.get_value(), 200)
            self.assertTrue(scroller.tick(window, self.clock(10.1)))
            self.assertGreater(adjustment.get_value(), 255)
            first_position = adjustment.get_value()
            self.assertTrue(scroller.scroll_event(window, down))
            self.assertEqual(scroller.target, 320)
            self.assertEqual(adjustment.get_value(), first_position)
            self.assertTrue(scroller.tick(window, self.clock(10.2)))
            self.assertGreater(adjustment.get_value(), first_position)
            self.assertFalse(scroller.tick(window, self.clock(11.0)))
            self.assertEqual(adjustment.get_value(), 320)
            scroller.set_enabled(False)
            self.assertFalse(scroller.scroll_event(window, down))
        window.destroy()

    def test_animation_tracks_time_at_60_and_144_hz(self):
        positions = []
        for frequency in (60, 144):
            adjustment = Gtk.Adjustment(value=100, lower=0, upper=1000,
                                        step_increment=20, page_increment=100, page_size=100)
            window = Gtk.ScrolledWindow()
            window.set_vadjustment(adjustment)
            scroller = SmoothScroller(window, True)
            with patch.object(window, 'get_frame_clock', return_value=self.clock(10.0)), \
                    patch.object(window, 'add_tick_callback', return_value=42), \
                    patch.object(window, 'remove_tick_callback'):
                event = SimpleNamespace(direction=Gdk.ScrollDirection.DOWN, state=0)
                self.assertTrue(scroller.scroll_event(window, event))
                for frame in range(1, frequency // 4 + 1):
                    scroller.tick(window, self.clock(10.0 + frame / frequency))
                positions.append(adjustment.get_value())
                scroller.cancel()
            window.destroy()
        self.assertAlmostEqual(positions[0], positions[1], places=4)
        self.assertGreater(positions[0], 159)

    def test_smooth_scroll_keeps_fractional_position_between_frames(self):
        adjustment = Gtk.Adjustment(value=200, lower=0, upper=1000,
                                    step_increment=20, page_increment=100, page_size=100)
        window = Gtk.ScrolledWindow()
        window.set_vadjustment(adjustment)
        scroller = SmoothScroller(window, True)
        with patch.object(window, 'get_frame_clock', return_value=self.clock(10.0)), \
                patch.object(window, 'add_tick_callback', return_value=42), \
                patch.object(window, 'remove_tick_callback'):
            scroller.scroll_event(window, SimpleNamespace(direction=Gdk.ScrollDirection.DOWN, state=0))
            self.assertTrue(scroller.tick(window, self.clock(10.0 + 1 / 144)))
            position = adjustment.get_value()
            self.assertGreater(position, 200)
            self.assertNotEqual(position, round(position))
            scroller.cancel()
        window.destroy()

    def test_opposite_wheel_input_can_cancel_a_pending_glide(self):
        adjustment = Gtk.Adjustment(value=200, lower=0, upper=1000,
                                    step_increment=20, page_increment=100, page_size=100)
        window = Gtk.ScrolledWindow()
        window.set_vadjustment(adjustment)
        scroller = SmoothScroller(window, True)
        with patch.object(window, 'get_frame_clock', return_value=self.clock(10.0)), \
                patch.object(window, 'add_tick_callback', return_value=42), \
                patch.object(window, 'remove_tick_callback') as remove:
            self.assertTrue(scroller.scroll_event(window, SimpleNamespace(
                direction=Gdk.ScrollDirection.DOWN, state=0)))
            self.assertTrue(scroller.scroll_event(window, SimpleNamespace(
                direction=Gdk.ScrollDirection.UP, state=0)))
            self.assertEqual(adjustment.get_value(), 200)
            self.assertEqual(scroller.source, 0)
            remove.assert_called_once_with(42)
        window.destroy()

    def test_wheel_distance_scales_with_visible_page(self):
        adjustment = Gtk.Adjustment(value=200, lower=0, upper=3000,
                                    step_increment=20, page_increment=100,
                                    page_size=1200)
        window = Gtk.ScrolledWindow()
        window.set_vadjustment(adjustment)
        scroller = SmoothScroller(window, True)
        down = SimpleNamespace(direction=Gdk.ScrollDirection.DOWN, state=0)
        with patch.object(window, 'get_frame_clock', return_value=self.clock(10.0)), \
                patch.object(window, 'add_tick_callback', return_value=42), \
                patch.object(window, 'remove_tick_callback'):
            self.assertTrue(scroller.scroll_event(window, down))
            self.assertAlmostEqual(scroller.target, 200 + 1200 ** (2.0 / 3.0))
            self.assertGreater(scroller.target - 200, 96)
            scroller.cancel()
        window.destroy()

    def test_smooth_deltas_join_the_glide_without_counting_duplicate_notches(self):
        adjustment = Gtk.Adjustment(value=100, lower=0, upper=1000,
                                    step_increment=60, page_increment=100, page_size=100)
        window = Gtk.ScrolledWindow()
        window.set_vadjustment(adjustment)
        scroller = SmoothScroller(window, True)
        wheel = SimpleNamespace(direction=Gdk.ScrollDirection.DOWN, state=0, time=1000)
        def smooth(time, dx, dy):
            return SimpleNamespace(direction=Gdk.ScrollDirection.SMOOTH, state=0,
                                   time=time,
                                   get_scroll_deltas=lambda: (True, dx, dy))
        with patch.object(window, 'get_frame_clock', return_value=self.clock(10.0)), \
                patch.object(window, 'add_tick_callback', return_value=42), \
                patch.object(window, 'remove_tick_callback') as remove_tick:
            self.assertTrue(scroller.scroll_event(window, wheel))
            self.assertAlmostEqual(scroller.target, 160)
            self.assertTrue(scroller.scroll_event(window, smooth(1000, 0, 1)))
            self.assertAlmostEqual(scroller.target, 160)
            self.assertTrue(scroller.scroll_event(window, smooth(1040, 0, 0.5)))
            self.assertAlmostEqual(scroller.target, 190)
            self.assertFalse(scroller.scroll_event(window, smooth(1050, 1, 0.1)))
            scroller.set_enabled(False)
            remove_tick.assert_called_once_with(42)
        window.destroy()


if __name__ == '__main__':
    unittest.main()
