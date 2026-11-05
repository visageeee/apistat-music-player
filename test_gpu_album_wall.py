import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import appearance
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk
from gpu_album_wall import GPUAlbumWall, atlas_cell_size, DRAG_GRACE_SECONDS
from gpu_flip import GPUFlip, card_layout
from player import Player


class GPUAlbumWallTests(unittest.TestCase):
    def make_wall(self, width=800, height=600, offset=0):
        player = SimpleNamespace(album_art_size=100, album_spacing=10, album_margin=10,
                                 show_album_details=False, text_size=18)
        area = SimpleNamespace(get_allocated_width=lambda: width,
                               get_allocated_height=lambda: height)
        wall = SimpleNamespace(player=player, area=area, albums=list(range(1000)),
                               adjustment=SimpleNamespace(get_value=lambda: offset))
        wall.geometry = lambda: GPUAlbumWall.geometry(wall)
        return wall

    def test_only_visible_rows_are_generated(self):
        wall = self.make_wall(offset=550)
        visible = list(GPUAlbumWall.visible(wall))
        self.assertLess(len(visible), 60)
        self.assertGreater(visible[0][0], 0)
        self.assertTrue(all(0 <= row[0] < 1000 for row in visible))

    def test_grid_reflows_without_changing_cover_size(self):
        wide = self.make_wall(width=800)
        narrow = self.make_wall(width=420)
        self.assertGreater(wide.geometry()[4], narrow.geometry()[4])
        self.assertEqual(wide.geometry()[1], narrow.geometry()[1])
        self.assertGreater(narrow.geometry()[6], wide.geometry()[6])

    def test_prefetch_region_includes_rows_above_and_below_viewport(self):
        wall = self.make_wall(offset=550)
        onscreen = list(GPUAlbumWall.visible(wall))
        row_height = wall.geometry()[5]
        nearby = list(GPUAlbumWall.visible_in_rect(
            wall, (0, -row_height * 2, 800, 600 + row_height * 4)))
        self.assertLess(nearby[0][0], onscreen[0][0])
        self.assertGreater(nearby[-1][0], onscreen[-1][0])

    def test_gpu_pagination_requires_near_end_and_correct_panel(self):
        adjustment = SimpleNamespace(get_value=lambda: 0, get_page_size=lambda: 500,
                                     get_upper=lambda: 5000)
        player = SimpleNamespace(gpu_wall_enabled=True, gpu_wall=SimpleNamespace(adjustment=adjustment),
                                 loading_albums=False, albums=[1], total=200,
                                 content_views=SimpleNamespace(get_visible_child_name=lambda: 'albums'),
                                 views=SimpleNamespace(get_visible_child_name=lambda: 'wall'),
                                 load_albums=Mock())
        Player.gpu_load_more_albums(player)
        player.load_albums.assert_not_called()
        adjustment.get_value = lambda: 4400
        Player.gpu_load_more_albums(player)
        player.load_albums.assert_called_once_with(True)
        player.loading_albums = True
        Player.gpu_load_more_albums(player)
        self.assertEqual(player.load_albums.call_count, 1)

    def test_gpu_setting_defaults_off_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(appearance, 'SETTINGS_PATH', Path(tmp) / 'settings.json'):
            self.assertFalse(appearance.load_gpu_album_wall_enabled())
            appearance.save_gpu_album_wall_enabled(True)
            self.assertTrue(appearance.load_gpu_album_wall_enabled())
            appearance.save_gpu_album_wall_enabled(False)
            self.assertFalse(appearance.load_gpu_album_wall_enabled())

    def test_click_and_drag_use_the_album_under_the_pointer(self):
        album = SimpleNamespace(key='/library/metadata/1', artist='Artist')
        player = SimpleNamespace(album_art_size=100, show_album_details=False,
                                 gpu_album_pressed=Mock(), client=object())
        wall = SimpleNamespace(player=player, albums=[album],
                               visible=lambda: [(0, 10, 20)], drag_album=None,
                               dragging=False, flip=None, flips={}, pressed_hit=None,
                               drag_track=None, drag_exceeded=False,
                               background_scroller=SimpleNamespace(release=lambda _event: False))
        press = SimpleNamespace(button=1, x=15, y=25)
        self.assertFalse(GPUAlbumWall.pressed(wall, None, press))
        selection = Mock()
        selection.get_target.return_value = 'target'
        GPUAlbumWall.drag_data_get(wall, None, None, selection, 0, 0)
        selection.set.assert_called_once_with('target', 8, b'/library/metadata/1')
        self.assertTrue(GPUAlbumWall.released(wall, None, press))
        player.gpu_album_pressed.assert_called_once_with(album, press, 10, 20)

    def test_input_surface_receives_click_and_scroll_signals(self):
        album = SimpleNamespace(key='/library/metadata/1', artist='Artist')
        player = SimpleNamespace(album_art_size=100, album_spacing=10, album_margin=10,
                                 show_album_details=False, text_size=18,
                                 search_escape_pressed=Mock(), gpu_album_pressed=Mock(),
                                 gpu_load_more_albums=Mock(return_value=False),
                                 client=object())
        with patch('gpu_album_wall.load_gl', return_value=Mock()):
            wall = GPUAlbumWall(player, Mock())
        try:
            self.assertIsInstance(wall.area, Gtk.DrawingArea)
            self.assertNotIsInstance(wall.area, Gtk.GLArea)
            self.assertIsInstance(wall.input_surface, Gtk.EventBox)
            wall.albums = [album]
            wall.visible = lambda: [(0, 10, 20)]
            press = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
            press.button, press.x, press.y = 1, 15, 25
            release = Gdk.Event.new(Gdk.EventType.BUTTON_RELEASE)
            release.button, release.x, release.y = 1, 15, 25
            wall.input_surface.emit('button-press-event', press)
            wall.input_surface.emit('button-release-event', release)
            player.gpu_album_pressed.assert_called_once()
            wall.adjustment.configure(0, 0, 1000, 20, 200, 200)
            scroll = Gdk.Event.new(Gdk.EventType.SCROLL)
            scroll.direction = Gdk.ScrollDirection.DOWN
            scroll.state = 0
            self.assertTrue(wall.input_surface.emit('scroll-event', scroll))
            self.assertEqual(wall.adjustment.get_value(), 90)
        finally:
            wall.shutdown()
            wall.destroy()

    def test_gpu_track_row_can_be_clicked_and_dragged(self):
        album = SimpleNamespace(key='/library/metadata/1', title='Album', artist='Artist')
        track = SimpleNamespace(key='/library/metadata/2', title='Track', duration=180000)
        player = SimpleNamespace(album_art_size=300, album_spacing=10, album_margin=10,
                                 show_album_details=False, text_size=18,
                                 search_escape_pressed=Mock(), gpu_album_pressed=Mock(),
                                 gpu_load_more_albums=Mock(return_value=False),
                                 play_card_track=Mock(), client=object())
        with patch('gpu_album_wall.load_gl', return_value=Mock()):
            wall = GPUAlbumWall(player, Mock())
        try:
            wall.albums = [album]
            wall.visible = lambda: [(0, 10, 20)]
            wall.flip = GPUFlip(album, 0, tracks=[track], progress=1)
            wall.flips[0] = wall.flip
            wall.flip.layout = card_layout(300, 18, 1, 0)
            row_y = 20 + (wall.flip.layout['start'] + wall.flip.layout['row_height'] / 2) * 300 / 512
            press = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
            press.button, press.x, press.y = 1, 30, row_y
            release = Gdk.Event.new(Gdk.EventType.BUTTON_RELEASE)
            release.button, release.x, release.y = 1, 30, row_y
            wall.input_surface.emit('button-press-event', press)
            selection = Mock()
            selection.get_target.return_value = 'song'
            wall.drag_data_get(None, None, selection, 0, 0)
            selection.set.assert_called_once_with('song', 8, b'/library/metadata/2')
            with patch('gpu_album_wall.Gtk.drag_set_icon_widget'):
                wall.drag_begin(None, object())
            self.assertEqual(Player.resolve_loaded_tracks(player, [track.key]), [track])
            wall.dragging = False
            wall.input_surface.emit('button-release-event', release)
            self.assertEqual(player.play_card_track.call_args.args[1], 0)
            self.assertEqual(player.play_card_track.call_args.args[0].album, album)
        finally:
            wall.shutdown()
            wall.destroy()

    def test_gpu_frame_only_queues_its_own_widget(self):
        area = SimpleNamespace(get_mapped=lambda: True, queue_draw=Mock(), get_toplevel=Mock())
        wall = SimpleNamespace(area=area, closed=False, frame_source=1)
        GPUAlbumWall.flush_frame(wall)
        area.queue_draw.assert_called_once()
        area.get_toplevel.assert_not_called()

    def test_repeated_art_updates_share_one_queued_frame(self):
        area = SimpleNamespace(get_mapped=lambda: True)
        wall = SimpleNamespace(area=area, closed=False, frame_source=0, flush_frame=Mock())
        with patch('gpu_album_wall.GLib.timeout_add', return_value=42) as idle:
            GPUAlbumWall.queue_frame(wall)
            GPUAlbumWall.queue_frame(wall)
        idle.assert_called_once_with(0, wall.flush_frame, priority=GLib.PRIORITY_HIGH)
        self.assertEqual(wall.frame_source, 42)

    def test_closed_gpu_wall_does_not_queue_another_frame(self):
        area = SimpleNamespace(get_mapped=Mock(), queue_render=Mock())
        GPUAlbumWall.queue_frame(SimpleNamespace(area=area, closed=True))
        area.get_mapped.assert_not_called()
        area.queue_render.assert_not_called()

    def test_hidden_gpu_wall_does_not_damage_other_panels(self):
        area = SimpleNamespace(get_mapped=lambda: False, get_toplevel=Mock(), queue_render=Mock())
        GPUAlbumWall.queue_frame(SimpleNamespace(area=area, closed=False))
        area.get_toplevel.assert_not_called()
        area.queue_render.assert_not_called()

    def test_unmapping_cancels_pending_frame_without_destroying_surface(self):
        surface = SimpleNamespace(unrealize=Mock())
        wall = SimpleNamespace(frame_source=42, render_surface=surface)
        with patch('gpu_album_wall.GLib.source_remove') as remove:
            GPUAlbumWall.area_unmapped(wall, None)
        remove.assert_called_once_with(42)
        surface.unrealize.assert_not_called()
        self.assertEqual(wall.frame_source, 0)

    def test_texture_tier_balances_zoom_and_visible_capacity(self):
        self.assertEqual(atlas_cell_size(400, 4096, 30), 512)
        self.assertEqual(atlas_cell_size(400, 4096, 100), 256)
        self.assertEqual(atlas_cell_size(100, 2048, 200), 128)

    def test_stale_artwork_buffer_cannot_be_uploaded_at_a_new_tier(self):
        gl = Mock()
        wall = SimpleNamespace(cell_size=512, atlas_columns=8, gl=gl)
        with self.assertRaises(ValueError):
            GPUAlbumWall.upload(wall, 1, bytes(256 * 256 * 4))
        gl.glTexSubImage2D.assert_not_called()

    def test_drag_waits_for_both_distance_and_grace_period(self):
        widget = SimpleNamespace(drag_begin_with_coordinates=Mock())
        wall = SimpleNamespace(drag_album=(object(), 0, 0), dragging=False,
                               drag_origin=(10, 10), drag_started_at=1.0,
                               drag_exceeded=False, drag_targets=object(),
                               background_scroller=SimpleNamespace(motion=lambda _event: False))
        event = SimpleNamespace(x=30, y=30, state=Gdk.ModifierType.BUTTON1_MASK)
        with patch('gpu_album_wall.time.monotonic', return_value=1.05):
            self.assertFalse(GPUAlbumWall.drag_motion(wall, widget, event))
        widget.drag_begin_with_coordinates.assert_not_called()
        with patch('gpu_album_wall.time.monotonic', return_value=1 + DRAG_GRACE_SECONDS + .01):
            self.assertTrue(GPUAlbumWall.drag_motion(wall, widget, event))
        widget.drag_begin_with_coordinates.assert_called_once()

    def test_single_flip_closes_previous_only_after_new_flip_finishes(self):
        first, second = object(), object()
        wall = SimpleNamespace(player=SimpleNamespace(single_flip_enabled=True),
                               albums=[first, second], flips={}, flip=None,
                               pending_exclusive_flip=None, client=None, epoch=0,
                               flip_scroll_remainder=0, flip_tick_id=1,
                               retired_textures=[], closed=False, queue_frame=Mock(),
                               area=SimpleNamespace(add_tick_callback=lambda _callback: 1))
        wall.animate_flip = lambda area, clock: GPUAlbumWall.animate_flip(wall, area, clock)
        with patch('gpu_album_wall.time.monotonic', return_value=10):
            GPUAlbumWall.toggle_album(wall, first)
            wall.flips[0].started = 10
        with patch('gpu_album_wall.time.monotonic', return_value=10.5):
            GPUAlbumWall.animate_flip(wall, None, None)
            GPUAlbumWall.toggle_album(wall, second)
            wall.flips[1].started = 10.5
        self.assertEqual(wall.flips[0].target, 1)
        with patch('gpu_album_wall.time.monotonic', return_value=11):
            self.assertTrue(GPUAlbumWall.animate_flip(wall, None, None))
        self.assertEqual(wall.flips[0].target, 0)
        self.assertEqual(wall.flips[1].target, 1)
        with patch('gpu_album_wall.time.monotonic', return_value=11.5):
            GPUAlbumWall.animate_flip(wall, None, None)
        self.assertEqual(list(wall.flips), [1])

    def test_multiple_flips_stay_open_when_single_flip_is_disabled(self):
        first, second = object(), object()
        wall = SimpleNamespace(player=SimpleNamespace(single_flip_enabled=False),
                               albums=[first, second], flips={}, flip=None,
                               pending_exclusive_flip=None, client=None, epoch=0,
                               flip_scroll_remainder=0, flip_tick_id=1,
                               retired_textures=[], closed=False, queue_frame=Mock(),
                               area=SimpleNamespace(add_tick_callback=lambda _callback: 1))
        wall.animate_flip = lambda area, clock: GPUAlbumWall.animate_flip(wall, area, clock)
        with patch('gpu_album_wall.time.monotonic', return_value=10):
            GPUAlbumWall.toggle_album(wall, first)
            wall.flips[0].started = 10
            GPUAlbumWall.toggle_album(wall, second)
            wall.flips[1].started = 10
        with patch('gpu_album_wall.time.monotonic', return_value=10.5):
            GPUAlbumWall.animate_flip(wall, None, None)
        self.assertEqual([(index, flip.target) for index, flip in wall.flips.items()],
                         [(0, 1), (1, 1)])

    def test_gpu_surface_uses_a_dedicated_native_window(self):
        player = SimpleNamespace(album_art_size=100, album_spacing=10, album_margin=10,
                                 show_album_details=False, text_size=18,
                                 search_escape_pressed=Mock(), gpu_album_pressed=Mock(),
                                 gpu_load_more_albums=Mock(return_value=False))
        with patch('gpu_album_wall.load_gl', return_value=Mock()), \
                patch.object(GPUAlbumWall, 'realize_gl', return_value=False):
            wall = GPUAlbumWall(player, Mock())
            window = Gtk.Window()
            try:
                window.add(wall)
                window.show_all()
                self.assertTrue(wall.render_surface.get_has_window())
                self.assertFalse(wall.labels.get_has_window())
                self.assertIsNotNone(wall.render_surface.get_window())
                self.assertNotEqual(wall.render_surface.get_window(), window.get_window())
                self.assertEqual(wall.area.get_window(), wall.render_surface.get_window())
            finally:
                wall.shutdown()
                window.destroy()


if __name__ == '__main__':
    unittest.main()
