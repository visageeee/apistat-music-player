import io
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
from player import Player
from plex_client import Item


class LocalCacheTests(unittest.TestCase):
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
            self.assertEqual(cache.read_song_index('music', '/playlists/7/items'), songs[:1])
            self.assertIsNone(cache.read_song_index('other'))
            self.assertIsNone(local_cache.LocalCache(other).read_song_index('music'))
            self.assertEqual(cache.song_index_path('music').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
