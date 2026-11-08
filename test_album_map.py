import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from album_map import build_layout, cached_facet_tags, cached_layout, cached_links, CELL
from plex_client import Item


class AlbumMapTests(unittest.TestCase):
    def setUp(self):
        self.albums = [Item('/library/metadata/1/children', 'One', artist='A'),
                       Item('/library/metadata/2/children', 'Two', artist='B'),
                       Item('/library/metadata/3/children', 'Three', artist='C')]
        self.tracks = [Item('/t/1', 'One', artist='A', album_key='/library/metadata/1', genre='Jazz'),
                       Item('/t/2', 'Two', artist='B', album_key='/library/metadata/2', genre='Rock')]

    def test_groups_by_cached_metadata_and_keeps_unknown_separate(self):
        layout = build_layout(self.albums, self.tracks)
        self.assertEqual({label[0] for label in layout['labels']}, {'Jazz', 'Rock', 'Uncharted'})
        self.assertEqual(set(layout['positions']), {album.key for album in self.albums})
        self.assertEqual(layout, build_layout(list(reversed(self.albums)), list(reversed(self.tracks))))

    def test_untagged_album_uses_tagged_albums_by_same_artist(self):
        import math
        albums = [Item('/a', 'Known', artist='Artist', genre='Jazz'),
                  Item('/b', 'Unknown', artist='Artist'),
                  Item('/c', 'Unrelated', artist='Other', genre='Rock')]
        layout = build_layout(albums, [])
        self.assertNotIn('Uncharted', {label[0] for label in layout['labels']})
        labels = {name: (x, y) for name, x, y in layout['labels']}
        point = layout['positions']['/b']
        self.assertLess(math.dist(point, labels['Jazz']), math.dist(point, labels['Rock']))

    def test_untagged_album_uses_consistent_cached_links_without_propagation(self):
        albums = [Item('/a', 'Known 1', genre='Jazz'), Item('/b', 'Known 2', genre='Jazz'),
                  Item('/c', 'Unknown'), Item('/d', 'Still unknown')]
        layout = build_layout(albums, [], links=[('/a', '/c'), ('/b', '/c'), ('/c', '/d')])
        labels = {label[0] for label in layout['labels']}
        self.assertEqual(labels, {'Jazz', 'Uncharted'})
        self.assertEqual(layout, build_layout(list(reversed(albums)), [],
                                             links=[('/c', '/d'), ('/b', '/c'), ('/a', '/c')]))

    def test_conflicting_or_weak_evidence_stays_uncharted(self):
        albums = [Item('/a', 'Jazz', artist='A', genre='Jazz'),
                  Item('/b', 'Rock', artist='A', genre='Rock'),
                  Item('/c', 'Unknown', artist='A'), Item('/d', 'Other')]
        layout = build_layout(albums, [], links=[('/a', '/d')])
        self.assertIn('Uncharted', {label[0] for label in layout['labels']})
        self.assertEqual(len(layout['positions']), 4)

    def test_untagged_related_community_stays_together(self):
        albums = [Item('/a', 'One', artist='A'), Item('/b', 'Two', artist='B'),
                  Item('/c', 'Three', artist='C'), Item('/d', 'Other', artist='D')]
        layout = build_layout(albums, [], links=[('/a', '/b'), ('/b', '/c')])
        self.assertEqual({label[0] for label in layout['labels']},
                         {'Uncharted · related to A', 'Uncharted'})

    def test_small_unrelated_collection_remains_uncharted(self):
        albums = [Item('/' + str(i), str(i), artist='Artist ' + str(i)) for i in range(4)]
        self.assertEqual([label[0] for label in build_layout(albums, [])['labels']], ['Uncharted'])

    def test_uncharted_groups_are_outside_classified_groups(self):
        albums = [Item('/j', 'Jazz', genre='Jazz'), Item('/r', 'Rock', genre='Rock'),
                  Item('/u', 'Unknown', artist='Unmatched'),
                  Item('/a', 'One', artist='Unknown band'), Item('/b', 'Two', artist='Unknown band'),
                  Item('/c', 'Three', artist='Unknown band')]
        layout = build_layout(albums, [])
        labels = {title: x for title, x, _y in layout['labels']}
        self.assertGreater(labels['Uncharted'], max(labels['Jazz'], labels['Rock']))
        self.assertGreater(labels['Uncharted · Unknown band'], max(labels['Jazz'], labels['Rock']))
        self.assertEqual(layout, build_layout(list(reversed(albums)), []))

    def test_album_art_does_not_overlap_within_or_between_islands(self):
        albums = [Item('/a/' + str(i), str(i), artist='Artist ' + str(i % 11),
                       genre='Jazz' if i % 3 else 'Rock') for i in range(200)]
        positions = list(build_layout(albums, [])['positions'].values())
        for i, (x, y) in enumerate(positions):
            for other_x, other_y in positions[i + 1:]:
                self.assertTrue(abs(x - other_x) >= 160 or abs(y - other_y) >= 160)

    def test_older_index_without_parent_key_matches_unambiguous_album(self):
        album = Item('/album/1', 'Record', artist='Artist')
        track = Item('/track/1', 'Song', artist='Artist', album='Record', genre='Soul')
        self.assertEqual(build_layout([album], [track])['labels'][0][0], 'Soul')

    def test_broad_pop_rock_prefers_specific_tags_and_moods(self):
        albums = [Item('/a', 'A', artist='A', genre='Pop/Rock, Indie Rock'),
                  Item('/b', 'B', artist='B', genre='Pop/Rock', mood='Dreamy')]
        labels = {label[0] for label in build_layout(albums, [])['labels']}
        self.assertEqual(labels, {'Indie Rock', 'Pop/Rock', 'Pop/Rock · Dreamy'})

    def test_pop_rock_uses_mood_even_when_specific_style_exists(self):
        album = Item('/a', 'A', artist='A', genre='Pop/Rock, Indie Rock', mood='Dreamy')
        self.assertIn('Pop/Rock · Dreamy', [label[0] for label in build_layout([album], [])['labels']])

    def test_cached_mood_facet_splits_pop_rock(self):
        album = Item('/library/metadata/1/children', 'A', genre='Pop/Rock')
        facets = {'/library/metadata/1': {'style': ['Indie Rock'], 'mood': ['Energetic']}}
        self.assertIn('Pop/Rock · Energetic',
                      [label[0] for label in build_layout([album], [], facets=facets)['labels']])

    def test_mood_groups_link_to_pop_rock_hub(self):
        albums = [Item('/' + mood, mood, genre='Pop/Rock', mood=mood)
                  for mood in ('Happy', 'Joyful', 'Sad', 'Angry')]
        layout = build_layout(albums, [])
        labels = [label[0] for label in layout['labels']]
        self.assertEqual({(labels[parent], labels[child]) for parent, child in layout['group_links']},
                         {('Pop/Rock', 'Pop/Rock · ' + mood)
                          for mood in ('Happy', 'Joyful', 'Sad', 'Angry')})
        self.assertEqual(layout, build_layout(list(reversed(albums)), []))

    def test_contrasting_moods_occupy_different_regions(self):
        import math
        albums = [Item('/' + mood, mood, genre='Pop/Rock', mood=mood)
                  for mood in ('Happy', 'Joyful', 'Sad', 'Angry')]
        labels = {name: (x, y) for name, x, y in build_layout(albums, [])['labels']}
        distance = lambda a, b: math.dist(labels['Pop/Rock · ' + a], labels['Pop/Rock · ' + b])
        self.assertLess(distance('Happy', 'Joyful'), distance('Happy', 'Sad'))
        self.assertLess(distance('Sad', 'Angry'), distance('Joyful', 'Angry'))

    def test_related_genres_are_placed_near_each_other(self):
        import math
        albums = [Item('/' + genre, genre, genre=genre)
                  for genre in ('Ambient', 'Electronic', 'Folk', 'Country', 'Jazz', 'Classical')]
        labels = {name: (x, y) for name, x, y in build_layout(albums, [])['labels']}
        self.assertLess(math.dist(labels['Ambient'], labels['Electronic']),
                        math.dist(labels['Ambient'], labels['Country']))
        self.assertLess(math.dist(labels['Folk'], labels['Country']),
                        math.dist(labels['Folk'], labels['Electronic']))

    def test_labels_are_centered_with_space_for_text(self):
        albums = [Item('/a/' + str(i), str(i), artist='Artist', genre='Jazz') for i in range(10)]
        layout = build_layout(albums, [])
        _, x, y = layout['labels'][0]
        for left, top in layout['positions'].values():
            self.assertGreater(((left + 80 - x) ** 2 + (top + 80 - y) ** 2) ** .5, CELL)

    def test_shared_artist_albums_have_local_connections(self):
        albums = [Item('/a', 'First', artist='Artist', genre='Jazz'),
                  Item('/b', 'Second', artist='Artist', genre='Rock')]
        self.assertEqual(build_layout(albums, [])['connections'], [['/a', '/b']])

    def test_cached_plex_styles_take_precedence_over_generic_genres(self):
        album = Item('/library/metadata/1/children', 'Record', artist='Artist', genre='Rock')
        layout = build_layout([album], [], facets={'/library/metadata/1': ['Art Rock']})
        self.assertEqual(layout['labels'][0][0], 'Art Rock')

    def test_cache_is_reused_and_invalidated_by_metadata_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            client = object()
            def write(path, data):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            with patch('album_map.LocalCache', return_value=SimpleNamespace(root=Path(temp))), \
                 patch('album_map._write_bytes', side_effect=write), \
                 patch('album_map.build_layout', wraps=build_layout) as build:
                first = cached_layout(client, '1', self.albums, self.tracks, [])
                self.assertEqual(first, cached_layout(client, '1', self.albums, self.tracks, []))
                self.assertEqual(build.call_count, 1)
                facets = Mock(side_effect=AssertionError('cached facets should not be read'))
                self.assertEqual(first, cached_layout(client, '1', self.albums, self.tracks, [], facets=facets))
                facets.assert_not_called()
                self.assertEqual(first, cached_layout(client, '1', self.albums, self.tracks,
                                                      [(self.albums[0].key, self.albums[1].key)]))
                self.assertEqual(build.call_count, 1)
                self.tracks[0].genre = 'Soul'
                self.assertIn('Soul', [x[0] for x in cached_layout(client, '1', self.albums, self.tracks, [])['labels']])
                self.assertEqual(build.call_count, 2)
                cached_layout(client, '1', self.albums, self.tracks, [], refresh=True)
                self.assertEqual(build.call_count, 3)

    def test_only_existing_fresh_album_web_connections_are_used(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'album-web'
            folder.mkdir()
            first, second = self.albums[:2]
            key = hashlib.sha256(('1\0' + first.key).encode()).hexdigest()
            (folder / (key + '.json')).write_text(json.dumps({'version': 2, 'time': time.time(),
                                                              'albums': [second.key, '/outside']}))
            with patch('album_map.LocalCache', return_value=SimpleNamespace(root=Path(temp))):
                self.assertEqual(cached_links(object(), '1', self.albums), [tuple(sorted((first.key, second.key)))])
                (folder / (key + '.json')).write_text('{bad')
                self.assertEqual(cached_links(object(), '1', self.albums), [])

    def test_cached_plex_styles_use_only_existing_facet_indexes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cached.json'
            path.write_text('{}')
            present = SimpleNamespace(field='style', title='Art Rock', cache_key='present')
            mood = SimpleNamespace(field='mood', title='Dreamy', cache_key='present')
            absent = SimpleNamespace(field='style', title='Soul', cache_key='absent')
            cache = SimpleNamespace(read_music_facets=Mock(return_value=[present, mood, absent]),
                                    song_index_path=lambda _section, key: path if key == 'present' else path / 'missing',
                                    read_song_index=Mock(return_value=[self.tracks[0]]))
            with patch('album_map.LocalCache', return_value=cache):
                result = cached_facet_tags(object(), '1')
            self.assertEqual(result, {'/library/metadata/1': {'style': ['Art Rock'], 'mood': ['Dreamy']}})
            self.assertEqual(cache.read_song_index.call_count, 2)


class AlbumMapCanvasTests(unittest.TestCase):
    def test_spatial_culling_and_search_only_return_matching_visible_albums(self):
        from album_map_canvas import AlbumMapCanvas
        player = SimpleNamespace(theme='dark', text_size=18, show_album_details=False,
                                 accent_color='#ff9900', art_accent_enabled=False,
                                 search_escape_pressed=Mock(), shared_background=None,
                                 background_visualizer=None)
        albums = [Item('/a', 'First', artist='Alpha'), Item('/b', 'Second', artist='Beta'),
                  Item('/c', 'Third', artist='Gamma')]
        layout = {'positions': {'/a': [100, 100], '/b': [800, 800], '/c': [120, 120]},
                  'labels': [], 'width': 1500, 'height': 1500}
        with patch('gpu_album_wall.load_gl', return_value=Mock()):
            canvas = AlbumMapCanvas(player, Mock(), Mock())
        try:
            canvas.set_map(None, albums, layout, [])
            canvas.canvas_player.zoom = 1
            self.assertEqual({i for i, _x, _y in canvas.visible_in_rect((0, 0, 400, 400))}, {0, 2})
            canvas.set_filter('gamma')
            self.assertEqual([i for i, _x, _y in canvas.visible_in_rect((0, 0, 400, 400))], [2])
            canvas.set_filter('')
            self.assertEqual([i for i, _x, _y in canvas.visible_in_rect((750, 750, 300, 300))], [1])
            epoch = canvas.epoch
            canvas.set_map(None, albums, layout, [])
            self.assertEqual(canvas.epoch, epoch)
            self.assertEqual(canvas.canvas_player.zoom, 1)
        finally:
            canvas.shutdown()
            canvas.destroy()

    def test_group_links_are_drawn_before_album_art(self):
        import cairo
        from album_map_canvas import AlbumMapCanvas
        player = SimpleNamespace(theme='dark', text_size=18, show_album_details=False,
                                 accent_color='#ff9900', art_accent_enabled=False,
                                 search_escape_pressed=Mock(), shared_background=None,
                                 background_visualizer=None)
        with patch('gpu_album_wall.load_gl', return_value=Mock()):
            canvas = AlbumMapCanvas(player, Mock(), Mock())
        try:
            canvas.canvas_player.zoom = 1
            canvas.map_layout = {'width': 200, 'height': 100,
                                 'labels': [['A', 10, 50], ['B', 100, 50]],
                                 'group_links': [[0, 1]]}
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 100)
            context = cairo.Context(surface)
            def draw_cover(_wall, _area, ctx):
                ctx.set_source_rgb(1, 0, 0)
                ctx.rectangle(40, 40, 20, 20)
                ctx.fill()
                return False
            with patch('gpu_album_wall.GPUAlbumWall.draw_gpu', draw_cover):
                canvas.draw_gpu(canvas.area, context)
            surface.flush()
            pixels = surface.get_data()
            stride = surface.get_stride()
            self.assertGreater(pixels[50 * stride + 20 * 4 + 3], 0)
            self.assertEqual(pixels[50 * stride + 50 * 4 + 3], 255)
        finally:
            canvas.shutdown()
            canvas.destroy()

    def test_map_controls_respect_minimum_zoom(self):
        from album_map_canvas import AlbumMapCanvas, MIN_MAP_ZOOM
        wall = SimpleNamespace(target_zoom=MIN_MAP_ZOOM, minimum_zoom=lambda: MIN_MAP_ZOOM,
                               unflip_for_zoom_out=Mock(), start_animation=Mock())
        AlbumMapCanvas.change_columns(wall, -1)
        self.assertEqual(wall.target_zoom, MIN_MAP_ZOOM)
        wall.unflip_for_zoom_out.assert_called_once()

    def test_minimum_zoom_fits_large_maps_and_reacts_to_resize(self):
        from album_map_canvas import AlbumMapCanvas
        dimensions = {'width': 800, 'height': 600}
        area = SimpleNamespace(get_allocated_width=lambda: dimensions['width'],
                               get_allocated_height=lambda: dimensions['height'])
        wall = SimpleNamespace(area=area, map_layout={'width': 20000, 'height': 15000})
        self.assertAlmostEqual(AlbumMapCanvas.minimum_zoom(wall), .04)
        dimensions['width'] = 400
        self.assertAlmostEqual(AlbumMapCanvas.minimum_zoom(wall), .02)

    def test_map_uses_cached_index_without_fetching_all_songs(self):
        from player import Player
        client = SimpleNamespace(albums=Mock())
        albums = [Item('/a', 'One', artist='A', genre='Jazz')]
        canvas = SimpleNamespace(set_map=Mock(), set_filter=Mock())
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: '1'),
                                 album_map_active=True, album_map_generation=0,
                                 canvas_catalog=albums, canvas_catalog_identity=(client, '1'),
                                 song_catalog=None, song_catalog_source=None, closed=False,
                                 status=SimpleNamespace(set_text=Mock()), album_map_canvas=canvas,
                                 search=SimpleNamespace(get_text=lambda: ''))
        player.async_work = lambda work, done, valid, failed: done(work()) if valid() else None
        cache = SimpleNamespace(read_song_index=Mock(return_value=None))
        with patch('player.LocalCache', return_value=cache), \
             patch('album_map.cached_links', return_value=[]), \
             patch('album_map.cached_facet_tags', return_value={}), \
             patch('album_map.cached_layout', return_value={'positions': {}, 'labels': []}):
            Player.load_album_map(player)
        client.albums.assert_not_called()
        cache.read_song_index.assert_called_once_with('1', max_age=None)
        self.assertEqual(canvas.set_map.call_args.args[1], albums)
        self.assertIn('cache song genres', player.status.set_text.call_args.args[0])

    def test_map_switch_restores_previous_album_wall(self):
        from player import Player
        state = {'active': True}
        button = SimpleNamespace(get_active=lambda: state['active'], get_style_context=Mock())
        canvas = SimpleNamespace()
        stack = SimpleNamespace(get_visible_child_name=lambda: 'canvas', set_visible_child_name=Mock())
        player = SimpleNamespace(client=object(), library=SimpleNamespace(get_active_id=lambda: '1'),
                                 album_map_canvas=canvas, album_map_active=False, album_map_generation=0,
                                 album_wall_stack=stack, artist_filter='Artist', artist_filter_bar=Mock(),
                                 views=Mock(), set_album_frosted_source=Mock(), album_top_allocated=Mock(),
                                 update_queue_bottom_inset=Mock(), load_album_map=Mock(),
                                 album_canvas=object(), gpu_wall=None, wall_scroll=object(), load_albums=Mock())
        Player.album_map_toggled(player, button)
        self.assertTrue(player.album_map_active)
        stack.set_visible_child_name.assert_called_with('map')
        player.load_album_map.assert_called_once()
        state['active'] = False
        Player.album_map_toggled(player, button)
        self.assertFalse(player.album_map_active)
        stack.set_visible_child_name.assert_called_with('canvas')
        player.load_albums.assert_called_once()

    def test_map_album_click_flips_and_context_menu_remains_available(self):
        from player import Player
        album = Item('/a', 'One')
        canvas = SimpleNamespace(selected_album=None, toggle_album=Mock(), labels=Mock())
        player = SimpleNamespace(album_map_canvas=canvas, show_context_menu=Mock())
        Player.album_map_pressed(player, album, SimpleNamespace(button=1), 0, 0)
        canvas.toggle_album.assert_called_once_with(album)
        event = SimpleNamespace(button=3)
        Player.album_map_pressed(player, album, event, 0, 0)
        player.show_context_menu.assert_called_once_with(event, gpu_album=album, gpu_wall=canvas)


if __name__ == '__main__':
    unittest.main()
