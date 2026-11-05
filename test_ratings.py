import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from ratings import star_text, stars_from_click
from player import LIBRARY_COLUMNS, PAUSE_MARKER, Player
from plex_client import Item


class RatingsTests(unittest.TestCase):
    def test_rating_text_and_click_to_clear(self):
        self.assertEqual(star_text(0), '☆☆☆☆☆')
        self.assertEqual(star_text(1), '★☆☆☆☆')
        self.assertEqual(star_text(6), '★★★☆☆')
        self.assertEqual(star_text(10), '★★★★★')
        self.assertEqual(stars_from_click(44, 0), 3)
        self.assertEqual(stars_from_click(44, 6), 0)
        self.assertEqual(stars_from_click(200, 0), 5)

    def test_clicking_library_rating_does_not_start_drag_or_playback(self):
        column = Gtk.TreeViewColumn('Rating')
        song = Item('/library/metadata/7', 'Rated song', user_rating=0)
        rated = []
        path = Gtk.TreePath.new_from_indices([0])
        view = SimpleNamespace(get_path_at_pos=lambda *_: (path, column, 44, 0))
        player = SimpleNamespace(song_columns={'user_rating': column}, songs=[song],
                                 set_song_rating=lambda item, stars: rated.append((item, stars)))
        event = SimpleNamespace(button=1, x=44, y=10)
        self.assertTrue(Player.library_artist_pressed(player, view, event))
        self.assertEqual(rated, [(song, 3)])

    def test_clicking_queue_rating_updates_selected_track(self):
        song = Item('/library/metadata/8', 'Queued', user_rating=8)
        store = Gtk.ListStore(int)
        store.append([0])
        path = Gtk.TreePath.new_from_indices([0])
        column = Gtk.TreeViewColumn('Rating')
        view = SimpleNamespace(get_path_at_pos=lambda *_: (path, column, 44, 0))
        rated = []
        player = SimpleNamespace(queue_store=store, queue=[song], play_history=[],
                                 set_song_rating=lambda item, stars: rated.append((item, stars)))
        self.assertTrue(Player.queue_song_pressed(
            player, view, SimpleNamespace(button=1, x=44, y=10)))
        self.assertEqual(rated, [(song, 3)])

    def test_flipped_album_marks_the_current_track(self):
        track = Item('/library/metadata/9', 'Playing')
        tile = Gtk.Box()
        tile.tracks = [track]
        button = Gtk.Button()
        button.play_marker = Gtk.Label()
        tile.track_buttons = [button]
        grid = Gtk.FlowBox()
        grid.add(tile)
        player = SimpleNamespace(grid=grid, queue=[track], index=0,
                                 stream_open=True)
        Player.refresh_playing_highlight(player)
        self.assertEqual(button.play_marker.get_text(), '▶')
        self.assertTrue(button.get_style_context().has_class('playing-track'))
        player.playing = False
        Player.refresh_playing_highlight(player)
        self.assertEqual(button.play_marker.get_text(), PAUSE_MARKER)
        player.stream_open = False
        Player.refresh_playing_highlight(player)
        self.assertEqual(button.play_marker.get_text(), '')

    def test_library_play_triangle_uses_accent_color(self):
        song = Item('/library/metadata/9', 'Playing')
        model = Gtk.ListStore(str)
        row = model.append([song.title])
        cell = Gtk.CellRendererText()
        player = SimpleNamespace(
            song_row_background=lambda *_args: None,
            queue=[song], index=0, stream_open=True, remote_opening=False,
            songs=[song], art_accent_enabled=False, current_art_bright=None,
            accent_color='#c06020')
        Player.library_playing_marker(player, None, cell, model, row)
        self.assertEqual(cell.get_property('text'), '▶')
        self.assertAlmostEqual(cell.get_property('foreground-rgba').red, 0xc0 / 255)
        player.playing = False
        Player.library_playing_marker(player, None, cell, model, row)
        self.assertEqual(cell.get_property('text'), PAUSE_MARKER)
        self.assertLess(cell.get_property('scale'), 1)

    def test_library_marker_reuses_style_for_unchanged_rows(self):
        model = Gtk.ListStore(str)
        row = model.append(['Track'])
        cell = Gtk.CellRendererText()
        player = SimpleNamespace(queue=[], index=-1, songs=[Item('/track/1', 'Track')],
                                 art_accent_enabled=False, current_art_bright=None,
                                 accent_color='#c06020')
        with patch.object(Player, 'style_playback_cell', wraps=Player.style_playback_cell) as style:
            Player.library_playing_marker(player, None, cell, model, row)
            Player.library_playing_marker(player, None, cell, model, row)
            style.assert_called_once_with(cell, '')
        self.assertEqual(cell.get_property('text'), '')

    def test_hide_star_rating_controls_preserves_library_column_preference(self):
        rating = Gtk.Box()
        rating.set_no_show_all(True)
        buttons = [Gtk.Button(label='☆') for _ in range(5)]
        for button in buttons:
            rating.pack_start(button, False, False, 0)
        player = SimpleNamespace(
            star_ratings_hidden=True, rating_column_preferred=True,
            now_rating=rating, detail_rating_column=Gtk.TreeViewColumn('Rating'),
            queue_rating_column=Gtk.TreeViewColumn('Rating'),
            song_columns={'user_rating': Gtk.TreeViewColumn('Rating')})
        Player.apply_star_rating_visibility(player)
        self.assertFalse(player.now_rating.get_visible())
        self.assertFalse(player.song_columns['user_rating'].get_visible())
        player.star_ratings_hidden = False
        Player.apply_star_rating_visibility(player)
        self.assertTrue(player.now_rating.get_visible())
        self.assertTrue(all(button.get_visible() for button in buttons))
        self.assertTrue(player.song_columns['user_rating'].get_visible())
        player.rating_column_preferred = False
        Player.apply_star_rating_visibility(player)
        self.assertFalse(player.song_columns['user_rating'].get_visible())

    def test_album_detail_rating_cell_sets_stars_without_playing(self):
        song = Item('/library/metadata/9', 'Album track', user_rating=0)
        columns = [Gtk.TreeViewColumn(title) for title in ('#', 'Track', 'Time', 'Rating')]
        path = Gtk.TreePath.new_from_indices([0])
        view = SimpleNamespace(get_path_at_pos=lambda *_: (path, columns[3], 84, 0),
                               get_columns=lambda: columns)
        rated = []
        player = SimpleNamespace(tracks=[song],
                                 set_song_rating=lambda item, stars: rated.append((item, stars)))
        self.assertTrue(Player.album_track_pressed(
            player, view, SimpleNamespace(button=1, x=84, y=10)))
        self.assertEqual(rated, [(song, 5)])

    def test_rating_updates_playback_and_cached_library(self):
        song = Item('/library/metadata/10', 'Cached song', user_rating=0)
        cached = Item(song.key, song.title, user_rating=0)
        calls = []
        client = SimpleNamespace(set_track_rating=lambda item, rating:
                                 calls.append((item.key, rating)))
        cache = SimpleNamespace(read_song_index_entry=lambda *_: ([cached], 123),
                                save_song_index=lambda *_args, **kwargs:
                                    calls.append(('saved', kwargs['built_at'])))
        with ThreadPoolExecutor(max_workers=1) as executor, patch('player.LocalCache',
                                                                   return_value=cache):
            player = SimpleNamespace(
                client=client, library=SimpleNamespace(get_active_id=lambda: '2'),
                playlists=[], active_playlist=None, rating_executor=executor,
                song_catalog=[song], songs=[song], queue=[song], play_history=[],
                tracks=[], grid=SimpleNamespace(get_children=lambda: []),
                song_view_cache={}, load_songs=lambda: None,
                refresh_queue_view=lambda: None, refresh_now_rating=lambda: None,
                track_store=Gtk.ListStore(str, str, str, str),
                status=SimpleNamespace(set_text=lambda _text: None),
                async_work=lambda work, done, *_: done(work()))
            Player.set_song_rating(player, song, 3)
        self.assertEqual(calls, [(song.key, 6), ('saved', 123)])
        self.assertEqual(song.user_rating, 6)
        self.assertEqual(cached.user_rating, 6)

    def test_rating_graphics_update_before_server_and_revert_on_failure(self):
        song = Item('/library/metadata/11', 'Immediate', user_rating=0)
        store = Gtk.ListStore(*([str] * (len(LIBRARY_COLUMNS) + 1)))
        store.append([''] * (len(LIBRARY_COLUMNS) + 1))
        pending = []
        calls = []
        def rate(_song, value):
            calls.append(value)
            if value == 10:
                raise OSError('Rejected')
        client = SimpleNamespace(set_track_rating=rate)
        cache = SimpleNamespace(read_song_index_entry=lambda *_: None)
        with ThreadPoolExecutor(max_workers=1) as executor, patch('player.LocalCache',
                                                                   return_value=cache):
            player = SimpleNamespace(
                client=client, library=SimpleNamespace(get_active_id=lambda: '2'),
                playlists=[], active_playlist=None, rating_executor=executor,
                song_catalog=[song], songs=[song], song_results=None,
                song_store=store, queue=[], play_history=[], tracks=[],
                grid=SimpleNamespace(get_children=lambda: []), song_view_cache={},
                refresh_queue_view=lambda: None, refresh_now_rating=lambda: None,
                track_store=Gtk.ListStore(str, str, str, str),
                status=SimpleNamespace(set_text=lambda _text: None),
                async_work=lambda work, done, _valid, failed:
                    pending.append((work, done, failed)))
            Player.set_song_rating(player, song, 3)
            rating_column = next(i for i, (_label, field) in enumerate(LIBRARY_COLUMNS)
                                 if field == 'user_rating')
            self.assertEqual(song.user_rating, 6)
            self.assertEqual(store[0][rating_column], '★★★☆☆')
            Player.set_song_rating(player, song, 5)
            self.assertEqual(store[0][rating_column], '★★★★★')
            pending[0][1](pending[0][0]())
            with self.assertRaises(OSError):
                pending[1][0]()
            pending[1][2]()
        self.assertEqual(calls, [6, 10])
        self.assertEqual(song.user_rating, 6)
        self.assertEqual(store[0][rating_column], '★★★☆☆')


if __name__ == '__main__':
    unittest.main()
