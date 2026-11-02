import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cairo
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, GLib

import local_cache
from appearance import cached_gradient
from player import Player, ALBUM_SORT_OPTIONS
from plex_client import Item, ALBUM_SORT_ARTIST


class LocalCacheTests(unittest.TestCase):
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
        player = SimpleNamespace(closed=False)
        player.art_workers = SimpleNamespace(submit=lambda work, *args: work(*args))
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

    def test_fresh_song_index_avoids_server_catalog_query(self):
        song = Item('/library/metadata/1', 'Cached song')
        calls = []
        client = object()
        player = SimpleNamespace(
            client=client, song_catalog_source=None, song_catalog=None,
            song_catalog_loading=False, song_catalog_generation=0,
            invalidate_song_catalog=lambda: calls.append('invalidate'),
            load_songs=lambda: calls.append('display'),
            song_count=SimpleNamespace(set_text=lambda value: calls.append(value)),
            async_work=lambda *_args: calls.append('server'))
        with patch('player.LocalCache', return_value=SimpleNamespace(
                read_song_index=lambda _section, _playlist: [song])):
            Player.start_song_catalog(player, client, 'music', None, None)
        self.assertEqual(player.song_catalog, [song])
        self.assertFalse(player.song_catalog_loading)
        self.assertNotIn('server', calls)


if __name__ == '__main__':
    unittest.main()
