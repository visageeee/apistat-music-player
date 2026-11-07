import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import lastfm
from plex_client import Item
import album_web
from album_web_wall import AlbumWebWall, radial_positions
from gi.repository import Gdk
from player import Player


class AlbumWebTests(unittest.TestCase):
    def setUp(self):
        self.seed = Item('/album/1', 'Source', artist='Seed')
        self.albums = [self.seed, Item('/album/2', 'Best', artist='Other'),
                       Item('/album/3', 'Other record', artist='Other'),
                       Item('/album/4', 'Third record', artist='Other'),
                       Item('/album/5', 'Different', artist='Third'),
                       Item('/album/6', 'Same artist', artist='SEED')]
        self.tracks = [Item('/t/1', 'One', artist='Other', album_key='/album/2'),
                       Item('/t/2', 'Two', artist='Other', album_key='/album/3'),
                       Item('/t/3', 'Three', artist='Other', album_key='/album/4'),
                       Item('/t/4', 'Four', artist='Third', album_key='/album/5'),
                       Item('/t/5', 'Forbidden', artist='Seed', album_key='/album/6')]

    def test_album_rank_uses_multiple_seed_tracks_and_excludes_same_artist(self):
        lists = [[('other', 'two'), ('other', 'one'), ('seed', 'forbidden'), ('third', 'four')],
                 [('other', 'one'), ('other', 'three')]]
        found = album_web.rank_albums(self.seed, self.albums, self.tracks, lists)
        self.assertEqual([album.key for album in found], ['/album/2', '/album/3', '/album/5'])

    def test_plex_album_children_keys_match_track_parent_keys(self):
        seed = Item('/library/metadata/1/children', 'Seed', artist='Seed')
        other = Item('/library/metadata/2/children', 'Neighbor', artist='Other')
        forbidden = Item('/library/metadata/3/children', 'Same artist', artist='Seed')
        tracks = [Item('/library/metadata/11', 'Related', artist='Other',
                       album_key='/library/metadata/2'),
                  Item('/library/metadata/12', 'Same', artist='Seed',
                       album_key='/library/metadata/3')]
        result = album_web.rank_albums(seed, [seed, other, forbidden], tracks,
                                       [[('other', 'related'), ('seed', 'same')]])
        self.assertEqual(result, [other])
        self.assertEqual(album_web.canonical_album_key('/local/album/123/children'),
                         '/local/album/123/children')

    def test_legacy_empty_cache_is_ignored_and_empty_results_are_not_saved(self):
        import json, time
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'related.json'
            cache.write_text(json.dumps({'version': 1, 'time': time.time(), 'albums': []}))
            client = SimpleNamespace(tracks=lambda _: [Item('seedtrack', 'S', artist='Seed')])
            with patch.object(album_web, 'cache_path', return_value=cache), \
                 patch.object(album_web, '_recommendations', return_value=[]), \
                 patch.object(album_web, 'library_catalog') as catalog, \
                 patch.object(album_web, '_write_bytes') as save, \
                 patch.object(album_web.lastfm, 'LastFM'):
                self.assertIsNone(album_web.read_cache(client, '1', self.seed, self.albums))
                self.assertEqual(album_web.related_albums(client, '1', self.seed, self.albums,
                                                          ('key', 'secret')), [])
                catalog.assert_not_called()
                save.assert_not_called()

    def test_empty_current_cache_is_ignored(self):
        import json, time
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'related.json'
            cache.write_text(json.dumps({'version': 2, 'time': time.time(), 'albums': []}))
            with patch.object(album_web, 'cache_path', return_value=cache):
                self.assertIsNone(album_web.read_cache(None, '1', self.seed, self.albums))

    def test_missing_parent_key_matches_unambiguous_album_name(self):
        track = Item('/t/1', 'One', artist='Other', album='Best')
        result = album_web.rank_albums(self.seed, self.albums, [track], [[('other', 'one')]])
        self.assertEqual(result, [self.albums[1]])

    def test_similar_artist_fallback_when_tracks_do_not_match(self):
        client = SimpleNamespace(tracks=Mock(return_value=[Item('s', 'Song', artist='Seed')]))
        api = Mock()
        api.request.return_value = {'similarartists': {'artist': [
            {'name': 'SEED'}, {'name': 'Third'}, {'name': 'Other'}]}}
        with patch.object(album_web, 'read_cache', return_value=None), \
             patch.object(album_web, 'cache_path', return_value=Path('/tmp/album-web-test.json')), \
             patch.object(album_web, '_recommendations', return_value=[('unknown', 'song')]), \
             patch.object(album_web, 'library_catalog', return_value=self.tracks), \
             patch.object(album_web, '_write_bytes'), \
             patch.object(album_web.lastfm, 'LastFM', return_value=api):
            found = album_web.related_albums(client, '1', self.seed, self.albums, ('key', 'secret'))
        self.assertEqual([album.key for album in found], ['/album/5', '/album/2', '/album/3'])
        api.request.assert_called_once_with('artist.getSimilar',
                                            {'artist': 'Seed', 'autocorrect': 1, 'limit': 200})

    def test_seed_sampling_spans_album(self):
        tracks = [Item(str(i), f'Track {i}', artist='A') for i in range(10)]
        self.assertEqual([x.key for x in album_web.representative_tracks(tracks)], ['0', '3', '6', '9'])

    def test_results_are_cached_and_refresh_bypasses_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'related.json'
            client = SimpleNamespace(tracks=Mock(return_value=[Item('seedtrack', 'S', artist='Seed')]))
            def write(path, data):
                path.write_bytes(data)
            with patch.object(album_web, 'cache_path', return_value=cache), \
                 patch.object(album_web, '_write_bytes', side_effect=write), \
                 patch.object(album_web, '_recommendations', return_value=[('other', 'one')]) as recommend, \
                 patch.object(album_web, 'library_catalog', return_value=self.tracks), \
                 patch.object(album_web.lastfm, 'LastFM'):
                args = (client, '1', self.seed, self.albums, ('key', 'secret'))
                self.assertEqual(album_web.related_albums(*args)[0].key, '/album/2')
                self.assertEqual(album_web.related_albums(*args)[0].key, '/album/2')
                self.assertEqual(recommend.call_count, 1)
                album_web.related_albums(*args, refresh=True)
                self.assertTrue(recommend.call_args.kwargs['refresh'])
                self.assertEqual(recommend.call_count, 2)

    def test_errors_are_not_cached_and_missing_credentials_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'related.json'
            client = SimpleNamespace(tracks=lambda _: [Item('s', 'S', artist='Seed')])
            with patch.object(album_web, 'cache_path', return_value=cache):
                with self.assertRaises(lastfm.LastFMError):
                    album_web.related_albums(client, '1', self.seed, self.albums, None)
                with patch.object(album_web, '_recommendations', side_effect=lastfm.LastFMError('offline')), \
                     patch.object(album_web.lastfm, 'LastFM'):
                    with self.assertRaises(lastfm.LastFMError):
                        album_web.related_albums(client, '1', self.seed, self.albums, ('key', 'secret'))
                self.assertFalse(cache.exists())

    def test_web_navigation_and_back_use_one_hop_results(self):
        seed, neighbor = self.albums[0], self.albums[1]
        state = {'view': 'wall'}
        views = SimpleNamespace(set_visible_child_name=lambda value: state.__setitem__('view', value),
                                get_visible_child_name=lambda: state['view'])
        client = SimpleNamespace()
        wall = SimpleNamespace(set_graph=Mock())
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: '1'),
                                 ensure_album_web=lambda: True, album_web_identity=None,
                                 album_web_history=[], album_web_generation=0,
                                 album_web_wall=wall,
                                 album_web_title=SimpleNamespace(set_text=Mock()),
                                 album_web_message=SimpleNamespace(set_text=Mock()),
                                 views=views, closed=False, canvas_catalog=self.albums,
                                 canvas_catalog_identity=(client, '1'))
        player.async_work = lambda work, done, valid: done(work()) if valid() else None
        player.open_album_web = lambda album, **kw: Player.open_album_web(player, album, **kw)
        player.close_album_web = Mock()
        with patch.object(lastfm, 'application_credentials', return_value=('key', 'secret')), \
             patch.object(album_web, 'related_albums', side_effect=[[neighbor], [seed], [neighbor]]):
            Player.open_album_web(player, seed)
            Player.open_album_web(player, neighbor)
            Player.album_web_back(player)
        self.assertEqual([item.key for item in player.album_web_history], [seed.key])
        self.assertEqual(player.album_web_album.key, seed.key)
        self.assertEqual(wall.set_graph.call_args.args[1:], (seed, [neighbor]))
        self.assertEqual(state['view'], 'web')

    def test_gpu_web_cover_click_is_navigable(self):
        player = SimpleNamespace(theme='dark', show_album_details=False, text_size=18,
                                 search_escape_pressed=Mock(), single_flip_enabled=True,
                                 shared_background=None, background_visualizer=None)
        pressed = Mock()
        with patch('gpu_album_wall.load_gl', return_value=Mock()):
            wall = AlbumWebWall(player, Mock(), pressed)
        try:
            wall.albums = [self.seed]
            wall.visible = lambda: [(0, 10, 20)]
            event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
            event.button, event.x, event.y = 1, 15, 25
            release = Gdk.Event.new(Gdk.EventType.BUTTON_RELEASE)
            release.button, release.x, release.y = 1, 15, 25
            wall.input_surface.emit('button-press-event', event)
            wall.input_surface.emit('button-release-event', release)
            pressed.assert_called_once()
            self.assertEqual(pressed.call_args.args[0], self.seed)
        finally:
            wall.shutdown()
            wall.destroy()

    def test_center_cover_flips_and_neighbor_opens_a_new_web(self):
        wall = SimpleNamespace(toggle_album=Mock())
        player = SimpleNamespace(album_web_album=self.seed, album_web_wall=wall,
                                 open_album_web=Mock(), show_context_menu=Mock())
        left = SimpleNamespace(button=1)
        Player.album_web_pressed(player, self.seed, left, 0, 0)
        wall.toggle_album.assert_called_once_with(self.seed)
        Player.album_web_pressed(player, self.albums[1], left, 0, 0)
        player.open_album_web.assert_called_once_with(self.albums[1])

    def test_radial_layout_center_and_pan(self):
        positions = radial_positions(9, 1000, 800, 100)
        self.assertEqual(positions[0], (450, 350))
        self.assertEqual(len(set(positions)), 9)
        moved = radial_positions(9, 1000, 800, 100, 20, -10)
        self.assertEqual(moved[0], (430, 360))


if __name__ == '__main__':
    unittest.main()
