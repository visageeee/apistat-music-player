import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from album_chart import ChartLookupError, cached_charts, chart_album, chart_artist
from album_map import build_layout
from plex_client import Item


class AlbumChartTests(unittest.TestCase):
    def setUp(self):
        self.album = Item('/library/metadata/1/children', 'Record', artist='Artist', genre='Pop/Rock')
        self.client = SimpleNamespace(is_local=False)

    def test_uses_plex_style_and_cached_chart_changes_group(self):
        self.client.xml = Mock(return_value=ET.fromstring(
            '<MediaContainer><Directory><Style tag="Dream Pop"/><Mood tag="Dreamy"/></Directory></MediaContainer>'))
        with tempfile.TemporaryDirectory() as temp, patch('album_chart.LocalCache', return_value=SimpleNamespace(root=Path(temp))), \
             patch('local_cache.CACHE_ROOT', Path(temp)):
            result = chart_album(self.client, '1', self.album, None)
            self.assertEqual(result['sources'], ['Plex'])
            cached = cached_charts(self.client, '1', [self.album])
            self.assertEqual(cached['/library/metadata/1']['chart_style'], ['Dream Pop'])
            layout = build_layout([self.album], [], facets=cached)
            self.assertIn('Dream Pop', [label[0] for label in layout['labels']])

    def test_album_listing_plex_style_improves_map_without_charting(self):
        album = Item('/a', 'Album', genre='Pop/Rock', style='Art Rock')
        self.assertEqual(build_layout([album], [])['labels'][0][0], 'Art Rock')

    def test_lastfm_rejects_nonmusical_tags_and_falls_back_to_artist(self):
        self.client.is_local = True
        api = SimpleNamespace(request=Mock(side_effect=[{'toptags': {'tag': [{'name': 'seen live'}, {'name': '2005'}]}},
                                                      {'toptags': {'tag': [{'name': 'shoegaze'}, {'name': 'dreamy'}]}}]))
        with tempfile.TemporaryDirectory() as temp, patch('album_chart.LocalCache', return_value=SimpleNamespace(root=Path(temp))), \
             patch('local_cache.CACHE_ROOT', Path(temp)):
            result = chart_album(self.client, '1', self.album, api)
        self.assertEqual((result['styles'], result['moods']), (['shoegaze'], ['dreamy']))
        self.assertEqual([call.args[0] for call in api.request.call_args_list],
                         ['album.getTopTags', 'artist.getTopTags'])

    def test_artist_chart_applies_to_all_albums_and_last_chart_wins(self):
        albums = [self.album, Item('/library/metadata/2/children', 'Second', artist=' artist ', genre='Jazz'),
                  Item('/library/metadata/3/children', 'Other', artist='Another', genre='Jazz')]
        self.client.is_local = True
        album_api = SimpleNamespace(request=Mock(return_value={'toptags': {'tag': [{'name': 'jazz'}]}}))
        artist_api = SimpleNamespace(request=Mock(return_value={'toptags': {'tag': [{'name': 'shoegaze'}]}}))
        with tempfile.TemporaryDirectory() as temp, patch('album_chart.LocalCache', return_value=SimpleNamespace(root=Path(temp))), \
             patch('local_cache.CACHE_ROOT', Path(temp)), patch('album_chart.time.time_ns', side_effect=[1, 2, 3]):
            chart_album(self.client, '1', self.album, album_api)
            chart_artist(self.client, '1', self.album, artist_api)
            cached = cached_charts(self.client, '1', albums)
            self.assertEqual(cached['/library/metadata/1']['chart_style'], ['shoegaze'])
            self.assertEqual(cached['/library/metadata/2']['chart_style'], ['shoegaze'])
            self.assertNotIn('/library/metadata/3', cached)
            layout = build_layout(albums, [], facets=cached)
            self.assertIn('shoegaze', [label[0] for label in layout['labels']])
            artist_api.request.assert_called_once_with('artist.getTopTags', {'artist': 'Artist', 'autocorrect': 1})
            chart_album(self.client, '1', self.album, album_api)
            cached = cached_charts(self.client, '1', albums)
            self.assertEqual(cached['/library/metadata/1']['chart_style'], ['jazz'])
            self.assertEqual(cached['/library/metadata/2']['chart_style'], ['shoegaze'])

    def test_mood_only_artist_chart_overrides_existing_genre(self):
        albums = [Item('/library/metadata/1', 'Album', artist='Artist', genre='Jazz'),
                  Item('/library/metadata/2', 'Other', artist='Artist', genre='Pop/Rock')]
        facets = {album.key: {'chart_mood': ['dreamy']} for album in albums}
        layout = build_layout(albums, [], facets=facets)
        self.assertEqual([label[0] for label in layout['labels']], ['dreamy'])

    def test_artist_chart_uses_validated_plex_artist_metadata(self):
        self.client.xml = Mock(side_effect=[
            ET.fromstring('<MediaContainer><Directory parentKey="/library/metadata/7"/></MediaContainer>'),
            ET.fromstring('<MediaContainer><Directory title="Artist"><Style tag="Art Rock"/></Directory></MediaContainer>')])
        with tempfile.TemporaryDirectory() as temp, patch('album_chart.LocalCache', return_value=SimpleNamespace(root=Path(temp))), \
             patch('local_cache.CACHE_ROOT', Path(temp)):
            result = chart_artist(self.client, '1', self.album, None)
        self.assertEqual(result['styles'], ['Art Rock'])
        self.assertEqual([call.args[0] for call in self.client.xml.call_args_list],
                         ['/library/metadata/1', '/library/metadata/7'])

    def test_does_not_fetch_other_plex_paths_and_reports_failure(self):
        self.album.key = 'https://example.com/elsewhere'
        self.client.xml = Mock()
        api = SimpleNamespace(request=Mock(side_effect=RuntimeError('unavailable')))
        with self.assertRaises(ChartLookupError):
            chart_album(self.client, '1', self.album, api)
        self.client.xml.assert_not_called()

    def test_does_not_cache_empty_results_and_isolates_libraries(self):
        self.client.is_local = True
        with tempfile.TemporaryDirectory() as temp, patch('album_chart.LocalCache', return_value=SimpleNamespace(root=Path(temp))), \
             patch('local_cache.CACHE_ROOT', Path(temp)):
            self.assertIsNone(chart_album(self.client, '1', self.album, None))
            api = SimpleNamespace(request=Mock(return_value={'toptags': {'tag': [{'name': 'ambient'}]}}))
            chart_album(self.client, '1', self.album, api)
            self.assertEqual(cached_charts(self.client, '2', [self.album]), {})
            self.assertEqual(cached_charts(self.client, '1', []), {})


if __name__ == '__main__':
    unittest.main()
