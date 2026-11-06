import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from player import Player
from plex_client import Item
from busy_indicator import BusyIndicator


class LoadingResponsivenessTests(unittest.TestCase):
    def test_artwork_decoding_runs_before_the_gtk_callback(self):
        callbacks, decode_threads = [], []
        pixbuf = object()
        class Loader:
            def set_size(self, *_args):
                pass
            def write(self, _data):
                decode_threads.append(threading.get_ident())
            def close(self):
                pass
            def get_pixbuf(self):
                return pixbuf
        client = SimpleNamespace(address='http://plex', token='token', get=Mock(return_value=b'art'))
        cache = SimpleNamespace(read_art=Mock(return_value=None), save_art=Mock())
        image = SimpleNamespace(set_from_pixbuf=Mock())
        with ThreadPoolExecutor(max_workers=1) as workers:
            player = SimpleNamespace(closed=False, busy=SimpleNamespace(begin=Mock(), end=Mock()),
                                     art_workers=workers)
            with patch('player.LocalCache', return_value=cache), \
                    patch('player.GdkPixbuf.PixbufLoader', Loader), \
                    patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)):
                Player.load_art(player, client, Item('/1', 'Album', thumb='/art'), image, 80, lambda: True)
                workers.submit(lambda: None).result(timeout=2)
                self.assertNotEqual(decode_threads, [threading.get_ident()])
                self.assertEqual(len(decode_threads), 1)
                image.set_from_pixbuf.assert_not_called()
                for callback in callbacks:
                    callback()
        image.set_from_pixbuf.assert_called_once_with(pixbuf)

    def test_large_queue_render_is_chunked_and_cancelled_on_refresh(self):
        callbacks = []
        rows = []
        busy = SimpleNamespace(begin=Mock(), end=Mock())
        class Store:
            def clear(self):
                rows.clear()
            def append(self, row):
                rows.append(row)
        player = SimpleNamespace(queue_store=Store(), play_history=[],
                                 queue=[Item(f'/track/{i}', f'Track {i}') for i in range(500)],
                                 index=0, theme='dark', playing=True, stream_open=True,
                                 remote_opening=False, closed=False, busy=busy,
                                 content_views=SimpleNamespace(get_visible_child_name=lambda: 'queue'),
                                 queue_count=SimpleNamespace(set_text=Mock()))
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback) or 42), \
                patch('player.GLib.source_remove') as remove:
            Player.refresh_queue_view(player)
            self.assertLess(len(rows), 500)
            self.assertEqual(player.queue_render_source, 42)
            busy.begin.assert_called_once()
            Player.refresh_queue_view(player)
            remove.assert_called_once_with(42)
            self.assertEqual(busy.end.call_count, 1)
            self.assertFalse(callbacks[0]())
            while callbacks[1]():
                pass
            self.assertEqual(len(rows), 500)
            self.assertEqual(busy.end.call_count, 2)

    def test_chained_background_work_keeps_the_spinner_visible(self):
        callbacks = []
        spinner = Mock()
        busy = BusyIndicator(spinner)
        player = SimpleNamespace(busy=busy, closed=False, status=Mock())

        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        with patch('player.threading.Thread', ImmediateThread), \
                patch('player.GLib.idle_add', side_effect=lambda callback, **_kwargs: callbacks.append(callback)), \
                patch('busy_indicator.GLib.timeout_add', return_value=17), \
                patch('busy_indicator.GLib.source_remove'):
            Player.async_work(player, lambda: 'loaded', lambda _result: busy.begin())
            busy._reveal()
            callbacks.pop()()
            self.assertEqual(busy.pending, 1)
            spinner.hide.assert_not_called()
            busy.end()
            spinner.hide.assert_called_once_with()

    def test_library_build_keeps_spinner_busy_until_all_rows_finish(self):
        callbacks = []
        spinner = Mock()
        busy = BusyIndicator(spinner)
        songs = [Item(f'/library/metadata/{index}', 'Song') for index in range(250)]
        player = SimpleNamespace(
            song_generation=1, closed=False, songs=[], song_total=0, busy=busy,
            song_store=SimpleNamespace(append=Mock()),
            song_column_value=lambda song, _field: song.title,
            song_count=SimpleNamespace(set_text=Mock()),
            mpris=SimpleNamespace(changed=Mock()), player_bar=Mock(), library_header=Mock(),
            effective_library_sort=lambda: None)
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)), \
                patch('busy_indicator.GLib.timeout_add', return_value=17), \
                patch('busy_indicator.GLib.source_remove'):
            Player.display_song_page(player, songs, len(songs), None, None, '')
            self.assertEqual(busy.pending, 1)
            self.assertEqual(player._song_row_builds, 1)
            busy._reveal()
            spinner.show.assert_called_once_with()
            while callbacks[0]():
                self.assertEqual(busy.pending, 1)
            self.assertEqual(busy.pending, 0)
            self.assertEqual(player._song_row_builds, 0)
            spinner.hide.assert_called_once_with()
            player.player_bar.queue_draw.assert_called_once_with()
            player.library_header.queue_draw.assert_called_once_with()

    def test_cancelled_and_overlapping_library_builds_release_busy_counts(self):
        callbacks = []
        busy = SimpleNamespace(begin=Mock(), end=Mock())
        player = SimpleNamespace(
            song_generation=1, closed=False, songs=[], song_total=0, busy=busy,
            song_store=SimpleNamespace(append=Mock()),
            song_column_value=lambda song, _field: song.title,
            song_count=SimpleNamespace(set_text=Mock()), mpris=SimpleNamespace(changed=Mock()),
            effective_library_sort=lambda: None)
        songs = [Item(str(index), 'Song') for index in range(201)]
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)):
            Player.display_song_page(player, songs, len(songs), None, None, '')
            player.song_generation += 1
            Player.display_song_page(player, songs, len(songs), None, None, '')
            self.assertEqual(player._song_row_builds, 2)
            self.assertFalse(callbacks[0]())
            self.assertEqual(player._song_row_builds, 1)
            while callbacks[1]():
                pass
        self.assertEqual(player._song_row_builds, 0)
        self.assertEqual(busy.begin.call_count, 2)
        self.assertEqual(busy.end.call_count, 2)

    def test_library_build_and_spinner_continue_after_switching_panels(self):
        callbacks = []
        visible = ['library']
        nav = SimpleNamespace(get_style_context=lambda: SimpleNamespace(
            add_class=Mock(), remove_class=Mock()),
            get_image=lambda: SimpleNamespace(queue_draw=Mock()))
        spinner = Mock()
        busy = BusyIndicator(spinner)
        songs = [Item(f'/library/metadata/{index}', 'Song') for index in range(250)]
        player = SimpleNamespace(
            content_views=SimpleNamespace(get_visible_child_name=lambda: visible[0],
                                          set_visible_child_name=lambda name: visible.__setitem__(0, name)),
            invalidate_frosted_backdrops=Mock(), previous_panel='library',
            song_generation=1, song_load_pending=False, song_results=songs, songs=[],
            song_total=0, closed=False, busy=busy, nav_buttons={'styles': nav},
            song_store=SimpleNamespace(append=Mock()),
            song_column_value=lambda song, _field: song.title,
            song_count=SimpleNamespace(set_text=Mock()), mpris=SimpleNamespace(changed=Mock()),
            load_current_lyrics=Mock(), effective_library_sort=lambda: None)
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)), \
                patch('busy_indicator.GLib.timeout_add', return_value=17), \
                patch('busy_indicator.GLib.source_remove'):
            Player.display_song_page(player, songs, len(songs), None, None, '')
            busy._reveal()
            self.assertFalse(Player.library_frosted_capture_allowed(player))
            Player.show_view(player, 'lyrics')
            self.assertTrue(Player.library_frosted_capture_allowed(player))
            self.assertEqual(busy.pending, 1)
            spinner.hide.assert_not_called()
            while callbacks[0]():
                self.assertEqual(busy.pending, 1)
            self.assertEqual(len(player.songs), len(songs))
            self.assertEqual(busy.pending, 0)
            spinner.hide.assert_called_once_with()

    def test_category_song_batches_are_tracked_until_finished_or_cancelled(self):
        callbacks = []
        rows = []
        busy = SimpleNamespace(begin=Mock(), end=Mock())
        player = SimpleNamespace(
            style_album_filter=None, style_result_source='mood', style_song_sort=('title', False),
            style_song_render_source=None, style_render_generation=0, closed=False, busy=busy,
            style_result_songs=[Item(str(index), str(index)) for index in range(201)],
            style_song_store=SimpleNamespace(clear=Mock(), append=rows.append),
            style_result_status=SimpleNamespace(set_text=Mock()),
            song_column_value=lambda song, _field: song.title)
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)):
            Player.render_style_song_list(player)
            busy.begin.assert_called_once_with()
            self.assertTrue(callbacks[0]())
            self.assertEqual(len(rows), 150)
            busy.end.assert_not_called()
            self.assertFalse(callbacks[0]())
        busy.end.assert_called_once_with()

    def test_album_and_category_artwork_remain_busy_until_workers_finish(self):
        from concurrent.futures import Future
        from music_facets import MusicFacet
        callbacks = []
        album_future, category_future = Future(), Future()
        busy = SimpleNamespace(begin=Mock(), end=Mock())
        client = SimpleNamespace(address='http://plex', token='token')
        player = SimpleNamespace(
            client=client, closed=False, busy=busy,
            library=SimpleNamespace(get_active_id=lambda: '1'),
            art_workers=SimpleNamespace(submit=lambda *_args: album_future),
            style_tile_art_workers=SimpleNamespace(submit=lambda *_args: category_future))
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)):
            Player.load_art(player, client, Item('/library/metadata/1', 'Album', thumb='/art'),
                            object(), 224, lambda: True)
            Player.load_style_tile_art(player, object(), MusicFacet('mood', 'Calm', (('track.mood', 1),)))
            self.assertEqual(busy.begin.call_count, 2)
            busy.end.assert_not_called()
            album_future.set_result(None)
            category_future.set_result(None)
            self.assertEqual(len(callbacks), 2)
            for callback in callbacks:
                callback()
        self.assertEqual(busy.end.call_count, 2)

    def test_library_count_is_above_the_frosted_player_bar(self):
        from gi.repository import Gtk
        count = Gtk.Label()
        count.set_margin_bottom(8)
        player = SimpleNamespace(
            song_count=count, frosted_player_bar=True,
            player_bar=SimpleNamespace(get_allocated_height=lambda: 120, get_visible=lambda: True))
        Player.update_queue_bottom_inset(player)
        self.assertEqual(count.get_margin_bottom(), 128)
        player.frosted_player_bar = False
        Player.update_queue_bottom_inset(player)
        self.assertEqual(count.get_margin_bottom(), 8)

    def test_settings_scroll_clearance_follows_player_bar(self):
        from gi.repository import Gtk
        pages = [Gtk.Box(), Gtk.Box()]
        height = [120]
        visible = [True]
        player = SimpleNamespace(
            settings_pages=pages, frosted_player_bar=True,
            player_bar=SimpleNamespace(get_allocated_height=lambda: height[0],
                                       get_visible=lambda: visible[0]))
        Player.update_queue_bottom_inset(player)
        self.assertEqual([page.get_margin_bottom() for page in pages], [120, 120])
        height[0] = 160
        Player.update_queue_bottom_inset(player)
        self.assertEqual([page.get_margin_bottom() for page in pages], [160, 160])
        visible[0] = False
        Player.update_queue_bottom_inset(player)
        self.assertEqual([page.get_margin_bottom() for page in pages], [0, 0])
        visible[0] = True
        player.frosted_player_bar = False
        Player.update_queue_bottom_inset(player)
        self.assertEqual([page.get_margin_bottom() for page in pages], [0, 0])

    def test_library_load_is_deferred_until_library_is_visible(self):
        player = SimpleNamespace(content_views=SimpleNamespace(get_visible_child_name=lambda: 'now'),
                                 song_load_pending=False, update_song_drag_mode=Mock())
        Player.load_songs(player)
        self.assertTrue(player.song_load_pending)
        player.update_song_drag_mode.assert_not_called()

    def test_leaving_a_partially_built_library_keeps_its_build_running(self):
        visible = ['library']
        nav = SimpleNamespace(get_style_context=lambda: SimpleNamespace(
            add_class=Mock(), remove_class=Mock()),
            get_image=lambda: SimpleNamespace(queue_draw=Mock()))
        player = SimpleNamespace(
            content_views=SimpleNamespace(get_visible_child_name=lambda: visible[0],
                                          set_visible_child_name=lambda name: visible.__setitem__(0, name)),
            invalidate_frosted_backdrops=Mock(), previous_panel='library',
            song_results=[object()] * 10, songs=[object()] * 2, song_total=10,
            song_generation=3, song_load_pending=False, nav_buttons={'styles': nav},
            load_current_lyrics=Mock(), load_songs=Mock())
        Player.show_view(player, 'lyrics')
        self.assertEqual(player.song_generation, 3)
        self.assertFalse(player.song_load_pending)
        Player.show_view(player, 'library')
        player.load_songs.assert_not_called()

    def test_leaving_library_keeps_in_flight_filtering(self):
        visible = ['library']
        nav = SimpleNamespace(get_style_context=lambda: SimpleNamespace(
            add_class=Mock(), remove_class=Mock()),
            get_image=lambda: SimpleNamespace(queue_draw=Mock()))
        player = SimpleNamespace(
            content_views=SimpleNamespace(get_visible_child_name=lambda: visible[0],
                                          set_visible_child_name=lambda name: visible.__setitem__(0, name)),
            invalidate_frosted_backdrops=Mock(), previous_panel='library',
            song_results=None, songs=[], song_total=0, song_generation=5,
            song_load_pending=False, nav_buttons={'styles': nav}, load_current_lyrics=Mock())
        Player.show_view(player, 'lyrics')
        self.assertEqual(player.song_generation, 5)
        self.assertFalse(player.song_load_pending)

    def test_browsing_does_not_cancel_a_pending_server_connection(self):
        requests = []
        player = SimpleNamespace(
            remote_config={'identifier': 'test', 'name': 'Apistat'},
            generation=0, connection_generation=0, loading_albums=True,
            stop=Mock(), status=SimpleNamespace(set_text=Mock()),
            async_work=lambda work, done, valid, failed: requests.append(valid))
        with patch('player.PlexClient', return_value=object()):
            Player.connect_to_server(player, 'http://example.test', 'token')
            player.generation += 1  # Browsing starts an album request.
            self.assertTrue(requests[0]())
            Player.connect_to_server(player, 'http://other.test', 'token')
        self.assertFalse(requests[0]())
        self.assertTrue(requests[1]())

    def test_song_insertion_yields_when_the_time_budget_expires(self):
        callbacks = []
        rows = []
        songs = [Item(f'/library/metadata/{index}', 'Song') for index in range(250)]
        player = SimpleNamespace(
            song_generation=1, closed=False, songs=[], song_total=0,
            song_store=SimpleNamespace(append=rows.append),
            song_column_value=lambda song, _field: song.title,
            song_count=SimpleNamespace(set_text=Mock()),
            mpris=SimpleNamespace(changed=Mock()), effective_library_sort=lambda: None)
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)), \
                patch('player.time.monotonic', side_effect=[0.0, 1.0]):
            Player.display_song_page(player, songs, len(songs), None, None, '')
            self.assertTrue(callbacks[0]())
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(player.songs), 1)

    def test_song_insertion_pauses_during_resize_and_resumes_afterwards(self):
        idle, timers, rows = [], [], []
        now = [100.1]
        songs = [Item(f'/library/metadata/{index}', 'Song') for index in range(201)]
        player = SimpleNamespace(
            song_generation=1, closed=False, songs=[], song_total=0,
            _last_window_resize_at=100.0,
            song_store=SimpleNamespace(append=rows.append),
            song_column_value=lambda song, _field: song.title,
            song_count=SimpleNamespace(set_text=Mock()),
            mpris=SimpleNamespace(changed=Mock()), effective_library_sort=lambda: None)
        with patch('player.GLib.idle_add', side_effect=lambda callback: idle.append(callback)), \
                patch('player.GLib.timeout_add', side_effect=lambda _ms, callback: timers.append(callback)), \
                patch('player.time.monotonic', side_effect=lambda: now[0]):
            Player.display_song_page(player, songs, len(songs), None, None, '')
            self.assertFalse(idle.pop()())
            self.assertEqual(rows, [])
            self.assertTrue(timers[0]())
            now[0] = 100.3
            self.assertFalse(timers[0]())
            self.assertTrue(idle.pop()())
            self.assertEqual(len(rows), 200)

    def test_pending_resize_batch_stops_when_list_changes(self):
        idle, timers = [], []
        player = SimpleNamespace(
            song_generation=1, closed=False, songs=[], song_total=0,
            _last_window_resize_at=100.0, song_store=SimpleNamespace(append=Mock()),
            song_column_value=lambda song, _field: song.title,
            song_count=SimpleNamespace(set_text=Mock()),
            mpris=SimpleNamespace(changed=Mock()), effective_library_sort=lambda: None)
        songs = [Item(str(index), 'Song') for index in range(201)]
        with patch('player.GLib.idle_add', side_effect=lambda callback: idle.append(callback)), \
                patch('player.GLib.timeout_add', side_effect=lambda _ms, callback: timers.append(callback)), \
                patch('player.time.monotonic', return_value=100.1):
            Player.display_song_page(player, songs, len(songs), None, None, '')
            idle.pop()()
            player.song_generation += 1
            self.assertFalse(timers[0]())
        self.assertEqual(idle, [])

    def test_window_move_does_not_extend_resize_pause(self):
        player = SimpleNamespace(_last_configure_size=(800, 600), _last_window_resize_at=None)
        with patch('player.time.monotonic', return_value=10.0):
            Player.window_configured(player, None, SimpleNamespace(width=800, height=600))
            self.assertIsNone(player._last_window_resize_at)
            Player.window_configured(player, None, SimpleNamespace(width=700, height=600))
        self.assertEqual(player._last_window_resize_at, 10.0)

    def test_album_cards_yield_between_batches_and_stop_when_superseded(self):
        callbacks = []
        albums = [object(), object(), object()]
        label = SimpleNamespace(set_text=Mock())
        player = SimpleNamespace(
            library=SimpleNamespace(get_active_id=lambda: 'music'), client=object(),
            loading_albums=False, generation=0, album_generation=0,
            albums=[], tracks=[], search=SimpleNamespace(get_text=lambda: ''),
            artist_filter=None, artist_filter_bar=SimpleNamespace(hide=Mock()),
            clear_wall=Mock(), track_store=SimpleNamespace(clear=Mock()),
            album_label=label, album_artist=label, album_year=label, cover=object(),
            set_placeholder_art=Mock(), status=label, search_index_enabled=False,
            index_section=None, album_sort='addedAt:desc',
            async_work=lambda _work, done, _valid, _failed: done((albums, 3, None)),
            busy=SimpleNamespace(begin=Mock(), end=Mock()), closed=False,
            add_album_tile=Mock(), album_prefetch_pending=False,
            credential_warning='', finish_startup_loading=Mock())
        with patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)), \
                patch('player.time.monotonic', side_effect=[0.0, 1.0]):
            Player.load_albums(player)
            player.add_album_tile.assert_not_called()
            self.assertTrue(callbacks[0]())
            self.assertEqual(player.add_album_tile.call_count, 1)
            player.generation += 1
            self.assertFalse(callbacks[0]())
        self.assertEqual(player.add_album_tile.call_count, 1)
        player.busy.end.assert_called_once()

    def test_artist_albums_use_fresh_paginated_server_results(self):
        matching = [Item(f'/library/metadata/{i}', f'Album {i:03}', artist='Artist')
                    for i in range(105)]
        source = [*matching[:100], Item('/other', 'Other', artist='Artist Tribute'),
                  *matching[100:]]
        client = SimpleNamespace(albums=Mock(side_effect=lambda section, start, **kwargs:
                                             (source[start:start + 100], len(source))))
        label = SimpleNamespace(set_text=Mock())
        player = SimpleNamespace(
            library=SimpleNamespace(get_active_id=lambda: 'music'), client=client,
            loading_albums=False, generation=0, album_generation=0,
            albums=[], tracks=[], search=SimpleNamespace(get_text=lambda: ''),
            artist_filter='Artist', artist_catalog=None, artist_filter_label=label,
            artist_filter_bar=SimpleNamespace(set_no_show_all=Mock(), show_all=Mock()),
            clear_wall=Mock(), track_store=SimpleNamespace(clear=Mock()),
            album_label=label, album_artist=label, album_year=label, cover=object(),
            set_placeholder_art=Mock(), status=label, search_index_enabled=True,
            indexed_albums=matching[:1], index_section='music', album_sort='titleSort',
            async_work=lambda work, done, valid, failed: done(work()) if valid() else None,
            busy=SimpleNamespace(begin=Mock(), end=Mock()), closed=False,
            add_album_tile=Mock(), album_prefetch_pending=False,
            credential_warning='', finish_startup_loading=Mock())
        def run_idle(callback, **_kwargs):
            while callback():
                pass
        with patch('player.GLib.idle_add', side_effect=run_idle):
            Player.load_albums(player)
            self.assertEqual((len(player.albums), player.total), (100, 105))
            Player.load_albums(player, more=True)
        self.assertEqual(player.albums, matching)
        self.assertEqual(client.albums.call_count, 2)
        self.assertEqual(client.albums.call_args_list[1].args, ('music', 100))
        self.assertEqual(client.albums.call_args_list[0].kwargs['artist'], 'Artist')

    def test_album_sort_buttons_return_from_filtered_results(self):
        for selected_sort in ('addedAt:desc', 'titleSort'):
            with self.subTest(sort=selected_sort):
                player = SimpleNamespace(artist_filter='Artist',
                                         search=SimpleNamespace(get_text=lambda: ''),
                                         album_sort='addedAt:desc', client=object(),
                                         update_album_sort_buttons=Mock(),
                                         show_all_albums=Mock(), load_albums=Mock())
                Player.change_album_sort(player, None, selected_sort)
                self.assertEqual(player.album_sort, selected_sort)
                player.show_all_albums.assert_called_once()
                player.load_albums.assert_not_called()

    def test_reloaded_search_pages_use_fresh_results_not_stale_index(self):
        albums = [Item(f'/library/metadata/{i}', f'Fresh {i:03}', artist='Artist')
                  for i in range(105)]
        client = object()
        label = SimpleNamespace(set_text=Mock())
        player = SimpleNamespace(
            library=SimpleNamespace(get_active_id=lambda: 'music'), client=client,
            loading_albums=False, generation=0, album_generation=0,
            albums=[], tracks=[], search=SimpleNamespace(get_text=lambda: 'Fresh'),
            artist_filter=None, artist_filter_label=label,
            artist_filter_bar=SimpleNamespace(set_no_show_all=Mock(), show_all=Mock()),
            clear_wall=Mock(), track_store=SimpleNamespace(clear=Mock()),
            album_label=label, album_artist=label, album_year=label, cover=object(),
            set_placeholder_art=Mock(), status=label, search_index_enabled=True,
            indexed_albums=albums[:1], index_section='music', album_sort='titleSort',
            async_work=lambda work, done, valid, failed: done(work()) if valid() else None,
            busy=SimpleNamespace(begin=Mock(), end=Mock()), closed=False,
            add_album_tile=Mock(), album_prefetch_pending=False,
            credential_warning='', finish_startup_loading=Mock())
        def run_idle(callback, **_kwargs):
            while callback():
                pass
        with patch('player.build_album_index', return_value=albums), \
                patch('player.GLib.idle_add', side_effect=run_idle):
            Player.load_albums(player, force_refresh=True)
            self.assertEqual(len(player.albums), 100)
            Player.load_albums(player, more=True)
        self.assertEqual(player.albums, albums)

    def test_uncached_album_search_finds_titles_and_artists_across_pages(self):
        title_match = Item('/library/metadata/1', 'Blue album', artist='Someone')
        artist_matches = [Item(f'/library/metadata/{index + 2}', f'Record {index:03}',
                               artist='Blue artist') for index in range(100)]
        source = [title_match, *artist_matches]
        client = object()
        label = SimpleNamespace(set_text=Mock())
        player = SimpleNamespace(
            library=SimpleNamespace(get_active_id=lambda: 'music'), client=client,
            loading_albums=False, generation=0, album_generation=0,
            albums=[], tracks=[], search=SimpleNamespace(get_text=lambda: 'blue'),
            artist_filter=None, artist_filter_label=label,
            artist_filter_bar=SimpleNamespace(set_no_show_all=Mock(), show_all=Mock()),
            clear_wall=Mock(), track_store=SimpleNamespace(clear=Mock()),
            album_label=label, album_artist=label, album_year=label, cover=object(),
            set_placeholder_art=Mock(), status=label, search_index_enabled=False,
            index_section=None, album_sort='titleSort',
            async_work=lambda work, done, valid, failed: done(work()) if valid() else None,
            busy=SimpleNamespace(begin=Mock(), end=Mock()), closed=False,
            add_album_tile=Mock(), album_prefetch_pending=False,
            credential_warning='', finish_startup_loading=Mock())
        def run_idle(callback, **_kwargs):
            while callback():
                pass
        with patch('player.build_album_index', return_value=source) as build, \
                patch('player.GLib.idle_add', side_effect=run_idle):
            Player.load_albums(player)
            self.assertEqual((len(player.albums), player.total), (100, 101))
            Player.load_albums(player, more=True)
        self.assertEqual(player.albums, source)
        build.assert_called_once()


if __name__ == '__main__':
    unittest.main()
