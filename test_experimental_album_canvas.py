import unittest
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
from experimental_album_canvas import (ExperimentalAlbumCanvas, CanvasPlayer, COLUMNS, WORLD_WIDTH,
                                       zoom_anchor, zoom_row_anchor, sort_progress, grid_slots,
                                       row_offsets, year_font_size, artist_font_size, search_catalog,
                                       heading_accent_range)
from plex_client import Item, ALBUM_SORT_ARTIST
from thumbnail_atlas import ThumbnailAtlas, CELL_BYTES
from gpu_album_wall import GPUAlbumWall
from player import Player
import appearance
import local_cache


class CanvasTests(unittest.TestCase):
    def test_horizontal_scrollbar_only_shows_for_overflow(self):
        scrollbar = Mock()
        player = SimpleNamespace(canvas_hscroll=scrollbar)
        adjustment = SimpleNamespace(get_lower=lambda: 0, get_upper=lambda: 800,
                                     get_page_size=lambda: 800)
        Player.update_canvas_hscroll(player, adjustment)
        scrollbar.set_visible.assert_called_with(False)
        adjustment.get_upper = lambda: 1000
        Player.update_canvas_hscroll(player, adjustment)
        scrollbar.set_visible.assert_called_with(True)

    def test_only_year_or_letter_receives_accent(self):
        self.assertEqual(heading_accent_range('2026', 12), (0, 4))
        self.assertEqual(heading_accent_range('Added 2026', 12), (6, 10))
        self.assertEqual(heading_accent_range('Å', None), (0, 2))
        self.assertIsNone(heading_accent_range('Date added unknown', 3))
        self.assertIsNone(heading_accent_range('Unknown year', 3))

    def test_classic_wall_setting_is_opt_in_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertFalse(appearance.load_classic_album_wall_enabled())
            appearance.save_classic_album_wall_enabled(True)
            self.assertTrue(appearance.load_classic_album_wall_enabled())
            appearance.save_classic_album_wall_enabled(False)
            self.assertFalse(appearance.load_classic_album_wall_enabled())

    def test_embedded_catalog_is_reused_for_search_and_artist_filter(self):
        albums = [Item('/1', 'Autumn', artist='Zebra', year='2002'),
                  Item('/2', 'Blue', artist='Amber', year='2020')]
        client = SimpleNamespace(albums=Mock(return_value=(albums, len(albums))))
        canvas = SimpleNamespace(set_albums=Mock(), reorder=Mock(), sort_order=None)
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: 'music'),
                                 canvas_enabled=True, album_canvas=canvas, generation=0, closed=False,
                                 canvas_catalog=None, canvas_catalog_identity=None,
                                 views=Mock(),
                                 search=SimpleNamespace(get_text=lambda: ''), artist_filter=None,
                                 album_sort='year:desc', artist_filter_bar=Mock(), artist_filter_label=Mock(),
                                 status=Mock(), finish_startup_loading=Mock())
        player.async_work = lambda work, done, valid, failed: done(work()) if valid() else None
        Player.load_canvas_albums(player)
        self.assertEqual([album.title for album in player.albums], ['Blue', 'Autumn'])
        player.views.set_visible_child_name.assert_called_with('wall')
        self.assertEqual(client.albums.call_count, 1)
        player.search.get_text = lambda: 'zeb'
        Player.load_canvas_albums(player)
        self.assertEqual([album.title for album in player.albums], ['Autumn'])
        self.assertEqual(client.albums.call_count, 1)
        self.assertEqual(canvas.set_albums.call_count, 1)
        player.search.get_text = lambda: ''
        player.artist_filter = 'Amber'
        Player.load_canvas_albums(player)
        self.assertEqual([album.title for album in player.albums], ['Blue'])
        self.assertEqual(client.albums.call_count, 1)

    def test_canvas_sort_keeps_live_search(self):
        player = SimpleNamespace(canvas_enabled=True, artist_filter=None, album_sort='year:desc',
                                 client=object(), update_album_sort_buttons=Mock(), load_albums=Mock(),
                                 show_all_albums=Mock())
        Player.change_album_sort(player, None, 'titleSort')
        self.assertEqual(player.album_sort, 'titleSort')
        player.load_albums.assert_called_once()
        player.show_all_albums.assert_not_called()

    def test_zoom_preserves_coordinate_under_pointer(self):
        for offset, pointer, old, new in ((300, 250, .5, 1.2), (0, 25, 1, .5)):
            self.assertAlmostEqual((offset + pointer) / old,
                                   (zoom_anchor(offset, pointer, old, new) + pointer) / new)

    def test_initial_fit_fills_window_without_independent_rounding(self):
        player = SimpleNamespace(text_size=18, show_album_details=False)
        canvas_player = CanvasPlayer(player)
        for width in (640, 1000, 1920):
            canvas_player.zoom = width / WORLD_WIDTH
            actual = (2 * canvas_player.album_margin + COLUMNS * canvas_player.album_art_size +
                      (COLUMNS - 1) * canvas_player.album_spacing)
            self.assertAlmostEqual(actual, width)

    def test_sort_uses_smooth_endpoints(self):
        self.assertEqual(sort_progress(10, 9), 0)
        self.assertEqual(sort_progress(10, 11), 1)
        self.assertAlmostEqual(sort_progress(10, 10.325), .5)

    def test_sort_remaps_texture_slots_and_tracks_interrupted_motion(self):
        albums = [Item('/a', 'B', artist='Z'), Item('/b', 'A', artist='A')]
        wall = SimpleNamespace(albums=albums, sort_start=None, sort_origins=None, sort_order='titleSort',
                               album_slots=[0, 1], columns=COLUMNS,
                               art_revision=0, pending={0}, failed_art={1}, uploads=[(1, b'x')],
                               slots={0: 1, 1: 2}, capacity=4, clear_card=Mock(), refresh_indices=set(),
                               start_animation=Mock(), queue_frame=Mock(), layout_changed=Mock(),
                               geometry=lambda: (800, 100, 10, 0, COLUMNS, 110, 500, 0),
                               get_row_offsets=lambda _height: [i * 110 for i in range(100)])
        ExperimentalAlbumCanvas.reorder(wall, ALBUM_SORT_ARTIST)
        self.assertEqual([a.key for a in wall.albums], ['/b', '/a'])
        self.assertEqual(wall.slots, {1: 1, 0: 2})
        self.assertEqual(wall.slot_keys, [None, 1, 0, None])
        self.assertEqual(wall.sort_origins, [(1, 0), (0, 0)])
        self.assertFalse(wall.pending)
        self.assertEqual(wall.art_revision, 1)
        ExperimentalAlbumCanvas.reorder(wall, 'titleSort')
        self.assertEqual([a.title for a in wall.albums], ['A', 'B'])

    def test_canvas_scale_does_not_change_main_wall(self):
        original = SimpleNamespace(album_art_size=350, album_spacing=30, album_margin=40,
                                   text_size=18, show_album_details=True)
        proxy = CanvasPlayer(original)
        proxy.zoom = 1.5
        self.assertEqual(proxy.album_art_size, 240)
        self.assertEqual(original.album_art_size, 350)
        proxy.dragged_album = 'album'
        self.assertEqual(original.dragged_album, 'album')

    def test_scroll_targets_pointer_and_is_bounded(self):
        wall = SimpleNamespace(target_zoom=2.4, anchor=None, start_animation=Mock(),
                               area=SimpleNamespace(get_allocated_width=lambda: 800))
        event = SimpleNamespace(direction=Gdk.ScrollDirection.UP, x=130, y=270)
        self.assertTrue(ExperimentalAlbumCanvas.scroll(wall, None, event))
        self.assertEqual(wall.anchor, (130, 270))
        self.assertEqual(wall.target_zoom, 2.5)
        wall.start_animation.assert_called_once()

    def test_zoom_can_go_below_fit_width(self):
        wall = SimpleNamespace(target_zoom=800 / WORLD_WIDTH, anchor=None, start_animation=Mock(),
                               unflip_for_zoom_out=Mock(),
                               area=SimpleNamespace(get_allocated_width=lambda: 800))
        for _ in range(8):
            ExperimentalAlbumCanvas.scroll(wall, None,
                SimpleNamespace(direction=Gdk.ScrollDirection.DOWN, x=400, y=300))
        self.assertLess(wall.target_zoom, 800 / WORLD_WIDTH)

    def test_control_scroll_changes_column_count_without_zoom_or_unflip(self):
        wall = SimpleNamespace(target_zoom=.5, anchor=None, start_animation=Mock(),
                               unflip_for_zoom_out=Mock(), ctrl_scroll_remainder=0.,
                               columns=24, sort_order='year:desc', albums=[], reorder=Mock(),
                               canvas_player=SimpleNamespace(zoom=.5),
                               area=SimpleNamespace(get_allocated_width=lambda: 800))
        event = SimpleNamespace(direction=Gdk.ScrollDirection.DOWN, x=120, y=200,
                                state=Gdk.ModifierType.CONTROL_MASK)
        ExperimentalAlbumCanvas.scroll(wall, None, event)
        wall.reorder.assert_called_once_with('year:desc', albums=[], columns=25)
        wall.unflip_for_zoom_out.assert_not_called()
        self.assertEqual(wall.target_zoom, .5)

    def test_zoom_out_starts_flip_back_animation(self):
        flip = Mock(target=1)
        area = SimpleNamespace(get_mapped=lambda: True, add_tick_callback=Mock(return_value=7))
        wall = SimpleNamespace(flips={0: flip}, pending_exclusive_flip=flip, flip_tick_id=0,
                               area=area, animate_flip=Mock(), queue_frame=Mock())
        ExperimentalAlbumCanvas.unflip_for_zoom_out(wall)
        flip.turn.assert_called_once_with(0)
        self.assertIsNone(wall.pending_exclusive_flip)
        self.assertEqual(wall.flip_tick_id, 7)

    def test_detail_change_retains_existing_slots_until_replacements_arrive(self):
        wall = SimpleNamespace(player=SimpleNamespace(album_art_size=150),
                               area=SimpleNamespace(get_scale_factor=lambda: 1),
                               low_detail=True, art_revision=3, slots={2: 1, 4: 2},
                               pending={4}, failed_art={2}, uploads=[(4, b'old')])
        ExperimentalAlbumCanvas.update_detail_tier(wall)
        self.assertEqual(wall.slots, {2: 1, 4: 2})
        self.assertEqual(wall.refresh_indices, {2, 4})
        self.assertEqual(wall.art_revision, 4)
        self.assertTrue(ExperimentalAlbumCanvas.art_needs_refresh(wall, 2))
        ExperimentalAlbumCanvas.art_uploaded(wall, 2)
        self.assertFalse(ExperimentalAlbumCanvas.art_needs_refresh(wall, 2))

    def test_atlas_resize_reuses_pixels_before_requesting_sharper_art(self):
        player = SimpleNamespace(shared_background=None, background_visualizer=None,
                                 search_escape_pressed=Mock())
        with patch('gpu_album_wall.load_gl'):
            wall = ExperimentalAlbumCanvas(player, Mock(), Mock())
        wall.atlas_size = 512
        wall.cell_size = 64
        wall.low_detail = False
        wall.slots = {5: 1}
        wall.slot_pixels = {1: bytes([120]) * (64 * 64 * 4)}
        wall.refresh_indices = {5}
        wall.visible = lambda: iter([(5, 0, 0)])
        wall.upload = Mock()
        def reset_atlas(instance, size):
            instance.slots.clear()
            instance.slot_pixels.clear()
            instance.cell_size = size
            instance.capacity = (instance.atlas_size // size) ** 2
            instance.slot_keys = [None] * instance.capacity
        with patch.object(GPUAlbumWall, 'resize_atlas', reset_atlas):
            wall.resize_atlas(128)
        self.assertEqual(wall.slots, {5: 1})
        self.assertEqual(len(wall.slot_pixels[1]), 128 * 128 * 4)
        self.assertEqual(wall.refresh_indices, {5})
        wall.upload.assert_called_once()
        wall.shutdown()
        wall.destroy()

    def test_static_visibility_culls_rows_and_columns(self):
        adjustment = lambda value: SimpleNamespace(get_value=lambda: value)
        wall = SimpleNamespace(albums=list(range(10000)), grid_items=list(range(10000)),
                               player=SimpleNamespace(album_art_size=100),
                               sort_origins=None, adjustment=adjustment(0), x_adjustment=adjustment(0),
                               get_row_offsets=lambda _height: [i * 110 for i in range(419)],
                               geometry=lambda: (400, 100, 10, 10, COLUMNS, 110, 50000, 10))
        visible = list(ExperimentalAlbumCanvas.visible_in_rect(wall, (0, 0, 400, 300)))
        self.assertTrue(visible)
        self.assertLess(len(visible), 20)
        self.assertTrue(all(x < 400 and y < 300 for _, x, y in visible))

    def test_year_groups_reserve_tiles_and_preserve_album_indices(self):
        albums = [Item('/a', 'A', year='2025', added_at=1735689600),
                  Item('/b', 'B', year='2025', added_at=1735689601),
                  Item('/c', 'C', year='2022', added_at=0)]
        slots, positions, markers = grid_slots(albums, 'year:desc')
        self.assertEqual(slots[:COLUMNS], [None] * COLUMNS)
        self.assertEqual(slots[COLUMNS:COLUMNS + 2], [0, 1])
        self.assertEqual(slots[COLUMNS * 2:COLUMNS * 3], [None] * COLUMNS)
        self.assertEqual(positions, [COLUMNS, COLUMNS + 1, COLUMNS * 3])
        self.assertEqual(markers, [(0, '2025', 2), (COLUMNS * 2, '2022', 1)])
        self.assertEqual(grid_slots(albums, ALBUM_SORT_ARTIST)[2],
                         [(0, '#', None), (COLUMNS, 'Unknown artist', 3)])
        added_markers = grid_slots(albums, 'addedAt:desc')[2]
        self.assertTrue(added_markers[0][1].startswith('Added '))
        self.assertEqual(added_markers[-1][1], 'Date added unknown')

    def test_artist_headers_and_search_follow_selected_sort(self):
        albums = [Item('/a', 'Autumn', artist='Zebra', year='2022'),
                  Item('/b', 'Zebra', artist='Amber', year='1990'),
                  Item('/c', 'Summer', artist='Zebra', year='2020')]
        matches = search_catalog(albums, 'zeb', ALBUM_SORT_ARTIST)
        self.assertEqual([album.key for album in matches], ['/b', '/a', '/c'])
        slots, positions, markers = grid_slots(matches, ALBUM_SORT_ARTIST, 8)
        self.assertEqual(positions, [9, 25, 26])
        self.assertEqual([(label, count) for _, label, count in markers],
                         [('A', None), ('Amber', 1), ('Z', None), ('Zebra', 2)])
        self.assertEqual([album.key for album in search_catalog(albums, 'zeb', 'year:desc')],
                         ['/a', '/c', '/b'])

    def test_artist_label_uses_one_cell_and_artists_share_a_row(self):
        albums = [Item('/a', 'One', artist='Aardvark'), Item('/b', 'Two', artist='Amber')]
        slots, positions, markers = grid_slots(albums, ALBUM_SORT_ARTIST, 4)
        self.assertEqual(slots, [None, None, None, None, None, 0, None, 1])
        self.assertEqual(positions, [5, 7])
        self.assertEqual([slot for slot, _label, _count in markers], [0, 4, 6])

    def test_album_letters_have_full_width_rows(self):
        albums = [Item('/1', '123'), Item('/a', 'Alpha'), Item('/b', 'Apple'), Item('/c', 'Blue')]
        slots, positions, markers = grid_slots(albums, 'titleSort', 4)
        self.assertEqual([(label, count) for _, label, count in markers],
                         [('#', None), ('A', None), ('B', None)])
        self.assertEqual(positions, [4, 12, 13, 20])
        self.assertTrue(all(slots[slot:slot + 4] == [None] * 4 for slot, _, _ in markers))

    def test_pinch_zooms_around_gesture_center_and_unflips_on_shrink(self):
        wall = SimpleNamespace(canvas_player=SimpleNamespace(zoom=.4), target_zoom=.4,
                               pinch_start_zoom=None, pinch_last_target=None,
                               unflip_for_zoom_out=Mock(), start_animation=Mock(),
                               area=SimpleNamespace(get_allocated_width=lambda: 800,
                                                    get_allocated_height=lambda: 600))
        gesture = SimpleNamespace(get_bounding_box_center=lambda: (True, 300, 200))
        ExperimentalAlbumCanvas.pinch_begin(wall, gesture, None)
        ExperimentalAlbumCanvas.pinch_scale_changed(wall, gesture, 1.5)
        self.assertAlmostEqual(wall.target_zoom, .6)
        self.assertEqual(wall.anchor, (300, 200))
        ExperimentalAlbumCanvas.pinch_scale_changed(wall, gesture, .75)
        self.assertAlmostEqual(wall.target_zoom, .3)
        wall.unflip_for_zoom_out.assert_called_once()
        ExperimentalAlbumCanvas.pinch_end(wall, gesture, None)
        self.assertIsNone(wall.pinch_start_zoom)

    def test_release_year_groups_are_independent_of_date_added(self):
        albums = [Item('/a', 'A', year='2020', added_at=1794000000),
                  Item('/b', 'B', year='1997', added_at=1794000000)]
        release_markers = grid_slots(albums, 'year:desc')[2]
        added_markers = grid_slots(albums, 'addedAt:desc')[2]
        self.assertEqual([(label, count) for _, label, count in release_markers],
                         [('2020', 1), ('1997', 1)])
        self.assertEqual([(label, count) for _, label, count in added_markers],
                         [('Added 2026', 2)])

    def test_thumbnail_atlas_persists_is_scoped_and_tracks_cover_identity(self):
        albums = [Item('/a', 'A', thumb='/art/a'), Item('/b', 'B', thumb='/art/b')]
        first = SimpleNamespace(address='local:one', token='')
        second = SimpleNamespace(address='local:two', token='')
        pixels = bytes([7]) * CELL_BYTES
        with tempfile.TemporaryDirectory() as directory, patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            with ExitStack() as stack:
                atlas = stack.enter_context(ThumbnailAtlas(first, albums))
                self.assertIsNone(atlas.read('/art/a'))
                atlas.write('/art/a', pixels)
                reopened = stack.enter_context(ThumbnailAtlas(first, list(reversed(albums))))
                self.assertEqual(reopened.read('/art/a'), pixels)
                self.assertIsNone(reopened.read('/art/b'))
                other = stack.enter_context(ThumbnailAtlas(second, albums))
                self.assertIsNone(other.read('/art/a'))
                changed = [albums[0], Item('/b', 'B', thumb='/art/new')]
                updated = stack.enter_context(ThumbnailAtlas(first, changed))
                self.assertEqual(updated.read('/art/a'), pixels)
                self.assertIsNone(updated.read('/art/new'))

    def test_thumbnail_atlas_close_releases_database_and_stays_closed(self):
        albums = [Item('/a', 'A', thumb='/art/a')]
        client = SimpleNamespace(address='local:close', token='')
        pixels = bytes([9]) * CELL_BYTES
        with tempfile.TemporaryDirectory() as directory, patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            atlas = ThumbnailAtlas(client, albums)
            atlas.write('/art/a', pixels)
            connection = atlas.connection
            atlas.close()
            with self.assertRaises(Exception):
                connection.execute('SELECT 1')
            self.assertIsNone(atlas.read('/art/a'))
            atlas.write('/art/a', pixels)
            self.assertIsNone(atlas.connection)
            atlas.close()

    def test_short_year_rows_and_larger_labels_preserve_zoom_anchor(self):
        self.assertGreaterEqual(year_font_size(.1), 18)
        self.assertGreater(year_font_size(1.), year_font_size(.5))
        old = row_offsets(4, [0, 2], 100, 30)
        new = row_offsets(4, [0, 2], 50, 24)
        self.assertEqual(old, [0, 30, 130, 160, 260])
        # Halfway through the second album row stays halfway through it.
        offset = zoom_row_anchor(0, 210, 0, old, 0, new)
        self.assertAlmostEqual(offset + 210, 24 + 50 + 24 + 25)

    def test_canvas_labels_follow_user_text_size(self):
        for zoom, cover in ((.17, 27), (.8, 128)):
            self.assertLess(year_font_size(zoom, 10), year_font_size(zoom, 24))
            self.assertLess(artist_font_size(zoom, cover, 10), artist_font_size(zoom, cover, 24))
            self.assertLessEqual(artist_font_size(zoom, cover, 24), cover * .48)

    def test_legacy_thumbnail_atlas_is_migrated(self):
        albums = [Item('/a', 'A', thumb='/art/a')]
        client = SimpleNamespace(address='local:legacy', token='')
        pixels = bytes([17]) * CELL_BYTES
        with tempfile.TemporaryDirectory() as directory, patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            with ThumbnailAtlas(client, albums) as atlas:
                path, cell = atlas.legacy_entries['/art/a']
                path.parent.mkdir(parents=True)
                with path.open('wb') as file:
                    file.write(bytes([1]) + bytes(63))
                    file.write(pixels)
                self.assertEqual(atlas.read('/art/a'), pixels)
                path.unlink()
            with ThumbnailAtlas(client, albums) as reopened:
                self.assertEqual(reopened.read('/art/a'), pixels)


if __name__ == '__main__':
    unittest.main()
