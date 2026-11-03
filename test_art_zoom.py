import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

from appearance import album_cover_size
from player import Player, create_content_stack, now_art_fit


class ArtZoomTests(unittest.TestCase):
    def test_hidden_panels_do_not_force_content_width(self):
        if not Gtk.init_check()[0]:
            self.skipTest('GTK display unavailable')
        stack = create_content_stack()
        narrow = Gtk.DrawingArea()
        wide = Gtk.DrawingArea()
        narrow.set_size_request(100, 20)
        wide.set_size_request(900, 20)
        stack.add_named(narrow, 'narrow')
        stack.add_named(wide, 'wide')
        stack.show_all()
        stack.set_visible_child_name('narrow')
        self.assertEqual(stack.get_preferred_width().minimum_width, 100)
        stack.set_visible_child_name('wide')
        self.assertEqual(stack.get_preferred_width().minimum_width, 900)
        stack.destroy()

    def test_now_playing_art_follows_selected_size(self):
        sizes = []
        player = SimpleNamespace(now_art_size=220,
                                 hero_cover=SimpleNamespace(art_display_size=None),
                                 set_art_size=lambda _image, size: sizes.append(size))
        Player.update_now_art_slot(player)
        player.now_art_size = 480
        Player.update_now_art_slot(player)
        self.assertEqual(sizes, [220, 480])

    def test_clicking_art_shows_waveform_and_clicking_waveform_restores_art(self):
        visible = ['art']
        background = Mock()
        player = SimpleNamespace(
            now_visual_stack=SimpleNamespace(
                get_visible_child_name=lambda: visible[0],
                set_visible_child_name=lambda name: visible.__setitem__(0, name)),
            now_visual_background=background,
            live_waveform_tap=object(), refresh_live_waveform=Mock(),
            apply_now_view_resize=Mock(),
            now_panel=SimpleNamespace(queue_resize=Mock()))
        click = SimpleNamespace(button=1)
        self.assertFalse(Player.toggle_now_waveform(player, None,
                                                     SimpleNamespace(button=3)))
        self.assertTrue(Player.toggle_now_waveform(player, None, click))
        self.assertEqual(visible[0], 'waveform')
        background.set_visible_child_name.assert_called_with('waveform')
        self.assertTrue(player.hero_waveform_active)
        self.assertTrue(Player.toggle_now_waveform(player, None, click))
        self.assertEqual(visible[0], 'art')
        background.set_visible_child_name.assert_called_with('art')
        self.assertFalse(player.hero_waveform_active)
        self.assertEqual(player.refresh_live_waveform.call_count, 2)

    def test_visualizer_background_click_preserves_song_info_controls(self):
        group = object()
        info = object()
        info_child = SimpleNamespace(get_parent=lambda: info)
        player = SimpleNamespace(hero_waveform_active=True, now_group=group, now_info=info,
                                 toggle_now_waveform=Mock(return_value=True))
        event = SimpleNamespace(button=1)
        with patch('player.Gtk.get_event_widget', return_value=info_child):
            self.assertFalse(Player.now_group_pressed(player, None, event))
        player.toggle_now_waveform.assert_not_called()
        with patch('player.Gtk.get_event_widget', return_value=group):
            self.assertTrue(Player.now_group_pressed(player, None, event))
        player.toggle_now_waveform.assert_called_once_with(None, event)

    def test_now_playing_art_fits_resize_immediately(self):
        self.assertEqual(now_art_fit(500, 640, 500, 140), 260)
        self.assertEqual(now_art_fit(500, 1000, 800, 140), 500)
        artwork = SimpleNamespace(art_display_size=500)
        art_sizes = []
        player = SimpleNamespace(
            now_art_size=500, _now_view_dimensions=(640, 500, 140),
            hero_cover=artwork,
            set_art_size=lambda _image, size: (art_sizes.append(size),
                                               setattr(artwork, 'art_display_size', size)))
        Player.update_now_art_slot(player)
        self.assertEqual(art_sizes, [260])
        Player.update_now_art_slot(player)
        self.assertEqual(len(art_sizes), 1)
        player._now_view_dimensions = (1000, 800, 140)
        Player.update_now_art_slot(player)
        self.assertEqual(art_sizes, [260, 500])

    def test_now_view_resize_applies_layout_during_allocation(self):
        player = SimpleNamespace(
            now_info=SimpleNamespace(get_preferred_height_for_width=lambda _width: (120, 140)),
            hero_title=SimpleNamespace(set_max_width_chars=Mock()),
            hero_artist=SimpleNamespace(set_max_width_chars=Mock()),
            hero_album=SimpleNamespace(set_max_width_chars=Mock()),
            update_now_art_slot=Mock(), now_panel=SimpleNamespace(queue_resize=Mock()),
            request_now_layout_flush=Mock(),
            closed=False)
        player.apply_now_view_resize = lambda: Player.apply_now_view_resize(player)
        allocation = SimpleNamespace(width=640, height=500)
        Player.now_view_allocated(player, None, allocation)
        Player.now_view_allocated(player, None, allocation)
        self.assertEqual(player._now_view_dimensions, (640, 500, 140))
        player.update_now_art_slot.assert_called_once_with()
        player.request_now_layout_flush.assert_not_called()
        player.now_panel.queue_resize.assert_not_called()

    def test_now_view_reflows_if_initial_group_allocation_is_stale(self):
        group = SimpleNamespace(get_allocated_width=lambda: 1000,
                                get_allocated_height=lambda: 262,
                                get_preferred_height_for_width=lambda _width: (580, 580))
        player = SimpleNamespace(
            now_info=SimpleNamespace(get_preferred_height_for_width=lambda _width: (140, 140)),
            now_group=group, hero_waveform_active=False,
            apply_now_view_resize=Mock(), request_now_layout_flush=Mock())
        Player.now_view_allocated(player, None, SimpleNamespace(width=1000, height=666))
        player.request_now_layout_flush.assert_called_once_with()

    def test_visualizer_keeps_artwork_slot_size_for_stationary_song_info(self):
        stack = SimpleNamespace(set_size_request=Mock())
        panel = SimpleNamespace(queue_resize=Mock())
        player = SimpleNamespace(now_art_size=360, _now_view_dimensions=(1000, 600, 160),
                                 hero_waveform_active=True, now_visual_stack=stack,
                                 now_panel=panel,
                                 request_now_layout_flush=Mock())
        Player.update_now_art_slot(player)
        stack.set_size_request.assert_called_once_with(340, 340)
        player._now_view_dimensions = (800, 400, 160)
        Player.update_now_art_slot(player)
        stack.set_size_request.assert_called_with(176, 176)
        self.assertEqual(panel.queue_resize.call_count, 2)

    def test_visualizer_keeps_the_same_compact_layout_as_artwork(self):
        group = SimpleNamespace(get_orientation=lambda: Gtk.Orientation.HORIZONTAL,
                                get_spacing=lambda: 24, set_orientation=Mock(),
                                set_halign=Mock(), set_hexpand=Mock(), set_valign=Mock(),
                                set_vexpand=Mock(), set_spacing=Mock(), set_margin_top=Mock())
        info = SimpleNamespace(get_margin_top=lambda: 6, get_spacing=lambda: 4,
                               set_margin_top=Mock(), set_spacing=Mock(),
                               get_preferred_height_for_width=lambda _width: (100, 100))
        title = SimpleNamespace(get_lines=lambda: 2, set_lines=Mock(), set_max_width_chars=Mock())
        player = SimpleNamespace(
            closed=False, now_panel=SimpleNamespace(get_allocated_width=lambda: 1100,
                                                    get_allocated_height=lambda: 324),
            now_group=group, now_info=info, hero_title=title,
            hero_artist=SimpleNamespace(set_max_width_chars=Mock()),
            hero_album=SimpleNamespace(set_max_width_chars=Mock()),
            now_top_spacer=SimpleNamespace(set_visible=Mock()),
            now_bottom_spacer=SimpleNamespace(set_visible=Mock()),
            now_display_art_size=250, hero_waveform_active=False,
            update_now_art_slot=Mock(), request_now_layout_flush=Mock())
        Player.apply_now_view_resize(player)
        self.assertTrue(player._now_horizontal)
        player.hero_waveform_active = True
        Player.apply_now_view_resize(player)
        self.assertTrue(player._now_horizontal)
        self.assertEqual(group.set_valign.call_args_list,
                         [unittest.mock.call(Gtk.Align.CENTER),
                          unittest.mock.call(Gtk.Align.CENTER)])

    def test_window_resize_records_normal_size_without_forcing_child_layout(self):
        player = SimpleNamespace(
            is_maximized=lambda: False, normal_size=(900, 700),
            now_info=object(), content_views=object(),
            schedule_now_view_resize=Mock())
        first = SimpleNamespace(width=900, height=700)
        second = SimpleNamespace(width=800, height=600)
        Player.window_allocated(player, None, first)
        Player.window_allocated(player, None, first)
        Player.window_allocated(player, None, second)
        player.schedule_now_view_resize.assert_not_called()
        self.assertEqual(player.normal_size, (800, 600))

    def test_window_resize_changes_columns_without_changing_cover_pixels(self):
        widths = [1200, 800]
        columns = []
        grid = SimpleNamespace(set_min_children_per_line=lambda value: columns.append(value),
                               set_max_children_per_line=lambda _value: None)
        player = SimpleNamespace(_album_layout_pending=True, album_art_size=120,
                                 album_margin=20, album_spacing=12,
                                 wall_scroll=SimpleNamespace(get_allocated_width=lambda: widths[0]),
                                 grid=grid)
        Player.apply_album_grid_columns(player)
        widths[0] = 800
        Player.apply_album_grid_columns(player)
        self.assertEqual(player.album_art_size, 120)
        self.assertEqual(columns, [8, 5])

    def test_ctrl_wheel_changes_each_view_independently(self):
        layouts = []
        slots = []
        slider_values = []
        subject = SimpleNamespace(
            album_columns=8, now_art_size=360,
            album_grid_scale=SimpleNamespace(set_value=slider_values.append),
            zoom_remainder={'albums': 0.0, 'now': 0.0},
            apply_album_grid_layout=lambda: layouts.append(True),
            update_now_art_slot=lambda: slots.append(True),
            status=SimpleNamespace(set_text=lambda _message: None),
        )
        up = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                             direction=Gdk.ScrollDirection.UP)
        down = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                               direction=Gdk.ScrollDirection.DOWN)
        plain = SimpleNamespace(state=0, direction=Gdk.ScrollDirection.UP)

        with patch('player.save_album_columns') as save_columns, \
                patch('player.save_now_art_size') as save_now:
            self.assertFalse(Player.zoom_art(subject, None, plain, 'albums'))
            self.assertTrue(Player.zoom_art(subject, None, up, 'albums'))
            self.assertTrue(Player.zoom_art(subject, None, up, 'now'))
            self.assertTrue(Player.zoom_art(subject, None, down, 'albums'))

        self.assertEqual((subject.album_columns, subject.now_art_size), (8, 400))
        self.assertEqual(len(layouts), 2)
        self.assertEqual(slider_values, [7, 8])
        self.assertEqual(slots, [True])
        self.assertEqual(save_columns.call_args.args, (8,))
        self.assertEqual(save_now.call_args.args, (400,))

    def test_grid_slider_changes_same_column_count_as_ctrl_scroll(self):
        layouts = []
        subject = SimpleNamespace(
            album_columns=8,
            apply_album_grid_layout=lambda: layouts.append(True),
            status=SimpleNamespace(set_text=lambda _message: None))
        with patch('player.save_album_columns') as save:
            Player.album_grid_scale_changed(subject,
                                            SimpleNamespace(get_value=lambda: 5.0))
            Player.album_grid_scale_changed(subject,
                                            SimpleNamespace(get_value=lambda: 5.0))
        self.assertEqual(subject.album_columns, 5)
        self.assertEqual(layouts, [True])
        save.assert_called_once_with(5)

    def test_zoom_limits_are_four_to_sixteen_columns(self):
        subject = SimpleNamespace(
            album_columns=4, zoom_remainder={'albums': 0.0, 'now': 0.0},
            apply_album_grid_layout=lambda: None,
            status=SimpleNamespace(set_text=lambda _message: None),
        )
        up = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                             direction=Gdk.ScrollDirection.UP)
        down = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                               direction=Gdk.ScrollDirection.DOWN)
        with patch('player.save_album_columns'):
            Player.zoom_art(subject, None, up, 'albums')
            self.assertEqual(subject.album_columns, 4)
            for _ in range(20):
                Player.zoom_art(subject, None, down, 'albums')
            self.assertEqual(subject.album_columns, 16)
        self.assertGreater(album_cover_size(1100, 4), album_cover_size(1100, 16))


if __name__ == '__main__':
    unittest.main()
