import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cairo
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, GLib

import local_cache
import appearance
from appearance import cached_gradient
from player import Player, ALBUM_SORT_OPTIONS
from plex_client import Item, ALBUM_SORT_ARTIST
from music_facets import MusicFacet


class LocalCacheTests(unittest.TestCase):
    def test_server_music_categories_are_cached_per_library_and_login(self):
        facet = MusicFacet('mood', 'Calm', (('track.mood', 30),))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)), \
                patch('local_cache.time.time', return_value=100):
            client = SimpleNamespace(address='https://plex.example', token='secret')
            cache = local_cache.LocalCache(client)
            cache.save_music_facets('2', (facet,))
            self.assertEqual(cache.read_music_facets('2'), (facet,))
            self.assertIsNone(cache.read_music_facets('3'))
            other = local_cache.LocalCache(SimpleNamespace(
                address=client.address, token='another-token'))
            self.assertIsNone(other.read_music_facets('2'))
            with patch('local_cache.time.time', return_value=5000):
                self.assertIsNone(cache.read_music_facets('2'))

    def test_category_cover_is_cached_for_the_matching_library_and_facet(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)), \
                patch('local_cache.time.time', return_value=100):
            client = SimpleNamespace(address='https://plex.example', token='secret')
            cache = local_cache.LocalCache(client)
            cache.save_music_facet_cover('2', 'facet:style:a', '/library/metadata/1/thumb')
            self.assertEqual(cache.read_music_facet_cover('2', 'facet:style:a'),
                             '/library/metadata/1/thumb')
            self.assertIsNone(cache.read_music_facet_cover('3', 'facet:style:a'))
            self.assertIsNone(cache.read_music_facet_cover('2', 'facet:style:b'))
            with self.assertRaises(ValueError):
                cache.save_music_facet_cover('2', 'facet:style:b',
                                             'https://outside.example/art')
            other = local_cache.LocalCache(SimpleNamespace(
                address=client.address, token='different'))
            self.assertIsNone(other.read_music_facet_cover('2', 'facet:style:a'))

    def test_other_sort_pages_and_art_are_prefetched(self):
        fetched = []
        saved_art = []
        client = SimpleNamespace(
            albums=lambda section, sort: (
                fetched.append(sort) or [Item('/library/metadata/' + str(len(fetched)),
                                              'Album', thumb='/thumb/' + str(len(fetched)))], 1),
            get=lambda *_args, **_kwargs: b'image',
        )
        cache = SimpleNamespace(
            read_album_page=lambda *_args: None,
            save_album_page=lambda *_args: None,
            read_art=lambda *_args: None,
            save_art=lambda thumb, size, data: saved_art.append((thumb, size, data)),
        )
        player = SimpleNamespace(
            client=client, closed=False, album_prefetch_generation=1,
            library=SimpleNamespace(get_active_id=lambda: '2'),
            album_sort='addedAt:desc', search=SimpleNamespace(get_text=lambda: ''),
        )
        with patch('player.LocalCache', return_value=cache), \
                patch('player.threading.Thread', side_effect=lambda target, daemon:
                      SimpleNamespace(start=target)):
            Player.prefetch_album_sort_pages(player)
        self.assertEqual(fetched, [sort for _label, sort in ALBUM_SORT_OPTIONS[1:]])
        self.assertEqual(len(saved_art), 3)
        self.assertTrue(all(data == b'image' for _thumb, _size, data in saved_art))

    def test_first_album_pages_are_cached_by_section_and_sort(self):
        album = Item('/library/metadata/1', 'Album', 'Artist', '2024', thumb='/art')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            cache = local_cache.LocalCache(SimpleNamespace(address='https://plex.example',
                                                          token='secret'))
            calls = []
            client = SimpleNamespace(albums=lambda section, sort: (
                calls.append((section, sort)) or [album], 42))
            self.assertEqual(local_cache.cached_album_page(cache, client, '2', 'year:desc'),
                             ([album], 42))
            self.assertEqual(local_cache.cached_album_page(cache, client, '2', 'year:desc'),
                             ([album], 42))
            self.assertEqual(calls, [('2', 'year:desc')])
            self.assertEqual(cache.read_album_page('2', 'year:desc'), ([album], 42))
            self.assertIsNone(cache.read_album_page('3', 'year:desc'))
            self.assertIsNone(cache.read_album_page('2', 'titleSort'))
            with patch('local_cache.time.time', return_value=10**12):
                self.assertIsNone(cache.read_album_page('2', 'year:desc'))

    def test_album_sort_orders_entire_catalog_before_pagination(self):
        albums = [Item('/1', 'Zebra', 'Bravo', '2020', added_at=20),
                  Item('/2', 'Alpha', 'Charlie', '2024', added_at=10),
                  Item('/3', 'Delta', 'Alpha', '2019', added_at=30)]
        expected = {'addedAt:desc': ['/3', '/1', '/2'],
                    'year:desc': ['/2', '/1', '/3'],
                    ALBUM_SORT_ARTIST: ['/3', '/1', '/2'],
                    'titleSort': ['/2', '/3', '/1']}
        for sort, keys in expected.items():
            with self.subTest(sort=sort):
                ordered = local_cache.sort_albums(albums, sort)
                self.assertEqual([album.key for album in ordered], keys)
                self.assertEqual(local_cache.search_albums(ordered, '', 1, 1)[0][0].key,
                                 keys[1])

    def test_artwork_is_reused_without_second_server_request(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
        output = io.BytesIO()
        surface.write_to_png(output)
        calls = []
        client = SimpleNamespace(address='https://plex.example', token='secret',
                                 get=lambda *args, **kwargs: (calls.append(True), output.getvalue())[1])
        other_login = SimpleNamespace(address=client.address, token='different')
        album = Item('/library/metadata/1', 'Album', thumb='/library/metadata/1/thumb')
        from concurrent.futures import Future
        player = SimpleNamespace(closed=False, busy=SimpleNamespace(begin=Mock(), end=Mock()))
        def submit(work, *args):
            future = Future()
            future.set_result(work(*args))
            return future
        player.art_workers = SimpleNamespace(submit=submit)
        image = SimpleNamespace(set_from_pixbuf=lambda pixbuf: None)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)), \
                patch('player.GLib.idle_add', lambda callback: callback()):
            Player.load_art(player, client, album, image, 80, lambda: True)
            Player.load_art(player, client, album, image, 80, lambda: True)
            self.assertEqual(len(calls), 1)
            self.assertEqual(image.art_source.get_width(), 80)
            self.assertIsNone(local_cache.LocalCache(other_login).read_art(album.thumb, 80))

    def test_gradient_render_is_loaded_from_disk(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            colors = ('#553344', '#112233')
            first, pixels = cached_gradient(32, 24, colors)
            appearance._gradient_memory.clear()
            second, cached_pixels = cached_gradient(32, 24, colors)
            self.assertIsNotNone(pixels)
            self.assertIsNone(cached_pixels)
            self.assertEqual((first.get_width(), first.get_height()), (32, 24))
            self.assertEqual((second.get_width(), second.get_height()), (32, 24))
            self.assertTrue(local_cache.gradient_path(colors, 32, 24).exists())

    def test_index_build_search_and_private_storage(self):
        albums = [Item('/library/metadata/1', 'Blue Train', artist='Coltrane'),
                  Item('/library/metadata/2', 'Kind of Blue', artist='Miles Davis'),
                  Item('/library/metadata/3', 'Giant Steps', artist='Coltrane')]
        requests = []
        def page(section, start, title=''):
            requests.append((section, start, title))
            return albums[start:start + 2], len(albums)
        client = SimpleNamespace(address='https://plex.example', token='secret', albums=page)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            cache = local_cache.LocalCache(client)
            built = local_cache.build_album_index(client, 'music')
            cache.save_index('music', built)
            self.assertEqual(requests, [('music', 0, ''), ('music', 2, '')])
            self.assertEqual(cache.read_index('music'), albums)
            self.assertIsNone(cache.read_index('other'))
            result, total = local_cache.search_albums(cache.read_index('music'), 'COLTRANE')
            self.assertEqual((result, total), ([albums[0], albums[2]], 2))
            if os.name != 'nt':
                self.assertEqual(cache.index_path('music').stat().st_mode & 0o777, 0o600)
                self.assertEqual(cache.index_path('music').parent.stat().st_mode & 0o777, 0o700)
            cache.clear_indices()
            self.assertIsNone(cache.read_index('music'))

    def test_song_index_is_complete_and_scoped_to_server_and_playlist(self):
        client = SimpleNamespace(address='https://plex.example', token='secret')
        other = SimpleNamespace(address=client.address, token='other')
        songs = [Item('/library/metadata/1', 'First'),
                 Item('/library/metadata/2', 'Second')]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            cache = local_cache.LocalCache(client)
            cache.save_song_index('music', songs)
            cache.save_song_index('music', songs[:1], '/playlists/7/items')
            self.assertEqual(cache.read_song_index('music'), songs)
            self.assertEqual(local_cache.LocalCache(client).read_song_index('music'), songs)
            self.assertEqual(cache.read_song_index('music', '/playlists/7/items'), songs[:1])
            self.assertIsNone(cache.read_song_index('other'))
            self.assertIsNone(local_cache.LocalCache(other).read_song_index('music'))
            if os.name != 'nt':
                self.assertEqual(cache.song_index_path('music').stat().st_mode & 0o777, 0o600)
            with patch('local_cache.time.time', return_value=10**12):
                self.assertIsNone(cache.read_song_index('music'))
                self.assertEqual(cache.read_song_index('music', max_age=None), songs)
            cache.save_song_index('music', songs, built_at=123)
            self.assertEqual(cache.read_song_index_entry('music'), (songs, 123))

    def test_fresh_song_index_avoids_server_catalog_query(self):
        song = Item('/library/metadata/1', 'Cached song')
        calls = []
        jobs = []
        client = object()
        player = SimpleNamespace(
            client=client, song_catalog_source=None, song_catalog=None,
            song_catalog_loading=False, song_catalog_generation=0,
            invalidate_song_catalog=lambda: calls.append('invalidate'),
            load_songs=lambda: calls.append('display'),
            song_count=SimpleNamespace(set_text=lambda value: calls.append(value)),
            async_work=lambda work, done, valid, failed: jobs.append((work, done)))
        with patch('player.LocalCache', return_value=SimpleNamespace(
                read_song_index_entry=lambda _section, _playlist:
                    (calls.append('read') or ([song], time.time())))):
            Player.start_song_catalog(player, client, 'music', None, None)
            self.assertNotIn('read', calls)
            work, done = jobs[0]
            done(work())
        self.assertEqual(player.song_catalog, [song])
        self.assertFalse(player.song_catalog_loading)
        self.assertIn('read', calls)

    def test_cancelled_background_cache_write_preserves_existing_index(self):
        client = SimpleNamespace(address='https://plex.example', token='secret')
        original = [Item('/library/metadata/1', 'Original')]
        replacement = [Item('/library/metadata/2', 'Replacement')]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            cache = local_cache.LocalCache(client)
            cache.save_song_index('music', original)
            saved = cache.save_song_index('music', replacement, still_current=lambda: False,
                                          commit_lock=threading.Lock())
            self.assertFalse(saved)
            self.assertEqual(cache.read_song_index('music'), original)

    def test_stale_song_index_is_displayed_before_background_refresh(self):
        cached = [Item('/library/metadata/1', 'Cached')]
        updated = cached + [Item('/library/metadata/2', 'New')]
        jobs, displayed = [], []
        client = object()
        cache = SimpleNamespace(read_song_index_entry=lambda *_: (cached, time.time() - 7200),
                                save_song_index=Mock())
        player = SimpleNamespace(
            client=client, song_catalog_source=None, song_catalog=None,
            song_catalog_loading=False, song_catalog_generation=0,
            song_view_cache={'old': {}}, invalidate_song_catalog=lambda: None,
            load_songs=lambda: displayed.append(player.song_catalog),
            song_count=SimpleNamespace(set_text=Mock()),
            async_work=lambda work, done, valid, *args: jobs.append((work, done, valid)))
        with patch('player.LocalCache', return_value=cache), \
                patch('player.build_song_catalog', return_value=updated) as fetch:
            Player.start_song_catalog(player, client, 'music', None, None)
            jobs[0][1](jobs[0][0]())
            self.assertEqual(displayed, [cached])
            fetch.assert_not_called()
            jobs[1][1](jobs[1][0]())
        fetch.assert_called_once()
        args, kwargs = cache.save_song_index.call_args
        self.assertEqual(args, ('music', updated, None))
        self.assertTrue(kwargs['still_current']())
        self.assertEqual(displayed, [cached, updated])
        self.assertEqual(player.song_view_cache, {})

    def test_missing_song_index_fetches_and_saves_library(self):
        songs = [Item('/library/metadata/1', 'Fetched')]
        jobs = []
        client = object()
        cache = SimpleNamespace(read_song_index_entry=lambda *_: None, save_song_index=Mock())
        player = SimpleNamespace(
            client=client, song_catalog_source=None, song_catalog=None,
            song_catalog_loading=False, song_catalog_generation=0,
            invalidate_song_catalog=lambda: None, load_songs=Mock(),
            song_count=SimpleNamespace(set_text=Mock()),
            async_work=lambda work, done, valid, *args: jobs.append((work, done, valid)))
        with patch('player.LocalCache', return_value=cache), \
                patch('player.build_song_catalog', return_value=songs) as fetch:
            Player.start_song_catalog(player, client, 'music', None, None)
            jobs[0][1](jobs[0][0]())
        fetch.assert_called_once()
        cache.save_song_index.assert_called_once_with('music', songs, None)
        self.assertEqual(player.song_catalog, songs)
        self.assertEqual(len(jobs), 1)

    def test_stale_song_index_survives_failed_background_refresh(self):
        cached = [Item('/library/metadata/1', 'Cached')]
        jobs = []
        client = object()
        cache = SimpleNamespace(read_song_index_entry=lambda *_: (cached, time.time() - 7200))
        player = SimpleNamespace(
            client=client, song_catalog_source=None, song_catalog=None,
            song_catalog_loading=False, song_catalog_generation=0,
            invalidate_song_catalog=lambda: None, load_songs=Mock(),
            song_count=SimpleNamespace(set_text=Mock()),
            async_work=lambda work, done, valid, *args: jobs.append((work, done, valid)))
        with patch('player.LocalCache', return_value=cache), \
                patch('player.build_song_catalog', side_effect=OSError('offline')):
            Player.start_song_catalog(player, client, 'music', None, None)
            jobs[0][1](jobs[0][0]())
            jobs[1][1](jobs[1][0]())
        self.assertEqual(player.song_catalog, cached)
        player.load_songs.assert_called_once()

    def test_stale_playlist_still_refreshes_before_showing_its_order(self):
        cached = [Item('/library/metadata/1', 'Cached')]
        updated = [Item('/library/metadata/2', 'New')]
        jobs = []
        client = object()
        playlist = SimpleNamespace(key='/playlists/7/items')
        cache = SimpleNamespace(read_song_index_entry=lambda *_: (cached, time.time() - 7200),
                                save_song_index=Mock())
        player = SimpleNamespace(
            client=client, song_catalog_source=None, song_catalog=None,
            song_catalog_loading=False, song_catalog_generation=0,
            invalidate_song_catalog=lambda: None, load_songs=Mock(),
            song_count=SimpleNamespace(set_text=Mock()),
            async_work=lambda work, done, valid, *args: jobs.append((work, done, valid)))
        with patch('player.LocalCache', return_value=cache), \
                patch('player.build_song_catalog', return_value=updated) as fetch:
            Player.start_song_catalog(player, client, 'music', playlist, None)
            result = jobs[0][0]()
            fetch.assert_called_once()
            jobs[0][1](result)
        self.assertEqual(player.song_catalog, updated)
        self.assertEqual(len(jobs), 1)

    def test_stale_refresh_does_not_replace_local_edits_or_unchanged_view(self):
        cached = [Item('/library/metadata/1', 'Cached')]
        jobs = []
        client = object()
        cache = SimpleNamespace(read_song_index_entry=lambda *_: (cached, time.time() - 7200),
                                save_song_index=Mock())
        player = SimpleNamespace(
            client=client, song_catalog_source=None, song_catalog=None,
            song_catalog_loading=False, song_catalog_generation=0,
            invalidate_song_catalog=lambda: None, load_songs=Mock(),
            song_count=SimpleNamespace(set_text=Mock()),
            async_work=lambda work, done, valid, *args: jobs.append((work, done, valid)))
        with patch('player.LocalCache', return_value=cache), \
                patch('player.build_song_catalog', return_value=list(cached)):
            Player.start_song_catalog(player, client, 'music', None, None)
            jobs[0][1](jobs[0][0]())
            jobs[1][1](jobs[1][0]())
            player.load_songs.assert_called_once()
            cache.save_song_index.assert_called_once()
            jobs.clear()
            player.song_catalog_source = None
            Player.start_song_catalog(player, client, 'music', None, None)
            jobs[0][1](jobs[0][0]())
            Player.note_song_cache_edit(player)
            self.assertFalse(jobs[1][2]())
            self.assertIsNone(jobs[1][0]())
            cache.save_song_index.assert_called_once()

    def test_album_index_cache_read_is_deferred_and_stale_result_is_rejected(self):
        jobs = []
        reads = []
        client = object()
        player = SimpleNamespace(
            client=client, search_index_enabled=True, index_section=None,
            indexed_albums=None, index_building=False, index_generation=0,
            library=SimpleNamespace(get_active_id=lambda: 'music'),
            index_refresh=SimpleNamespace(set_sensitive=lambda _value: None),
            index_status=SimpleNamespace(set_text=lambda _value: None),
            search=SimpleNamespace(get_text=lambda: ''),
            start_search_index_build=lambda: self.fail('Unexpected server index build'),
            async_work=lambda work, done, valid, failed: jobs.append((work, done, valid)))
        cache = SimpleNamespace(read_index=lambda section: (reads.append(section) or []))
        with patch('player.LocalCache', return_value=cache):
            Player.ensure_search_index(player)
            self.assertEqual(reads, [])
            work, done, valid = jobs[0]
            result = work()
            self.assertEqual(reads, ['music'])
            self.assertTrue(valid())
            done(result)
            self.assertEqual(player.indexed_albums, [])
            player.index_generation += 1
            self.assertFalse(valid())


if __name__ == '__main__':
    unittest.main()
