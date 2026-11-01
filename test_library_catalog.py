import unittest
from types import SimpleNamespace

from library_catalog import build_song_catalog, filter_sort_songs
from plex_client import Item


class LibraryCatalogTests(unittest.TestCase):
    def test_filter_and_sort_cover_all_song_pages(self):
        songs = [Item('/library/metadata/1', 'Blue Night', artist='Coltrane',
                      album='Alpha', duration=240000),
                 Item('/library/metadata/2', 'Red Day', artist='Miles',
                      album='Beta', duration=180000),
                 Item('/library/metadata/3', 'Blue Train', artist='Coltrane',
                      album='Gamma', duration=120000)]
        requests = []
        def page(section, start, sort):
            requests.append((section, start, sort))
            return songs[start:start + 2], len(songs)
        catalog = build_song_catalog(SimpleNamespace(songs=page), 'music')
        self.assertEqual(requests, [('music', 0, 'addedAt:desc'),
                                    ('music', 2, 'addedAt:desc')])
        self.assertEqual([song.title for song in filter_sort_songs(
            catalog, 'blue coltrane', ('duration', False))],
            ['Blue Train', 'Blue Night'])
        self.assertEqual([song.title for song in filter_sort_songs(
            catalog, sort=('album', True))],
            ['Blue Train', 'Red Day', 'Blue Night'])

    def test_playlist_filter_preserves_order_without_sort(self):
        playlist = Item('/playlists/1/items', 'Favorites')
        songs = [Item('/library/metadata/1', 'Zebra', artist='Artist'),
                 Item('/library/metadata/2', 'Apple', artist='Artist')]
        client = SimpleNamespace(playlist_items=lambda selected, start: (songs[start:], len(songs)))
        catalog = build_song_catalog(client, 'music', playlist)
        self.assertEqual(filter_sort_songs(catalog, 'artist'), songs)
        self.assertEqual([song.title for song in filter_sort_songs(
            catalog, sort=('title', False))], ['Apple', 'Zebra'])

    def test_optional_genre_year_and_added_columns_sort_all_songs(self):
        songs = [Item('/library/metadata/1', 'First', genre='Jazz', year='1999', added_at=10),
                 Item('/library/metadata/2', 'Second', genre='Ambient', year='2024', added_at=30),
                 Item('/library/metadata/3', 'Third', genre='Rock', year='', added_at=20)]
        self.assertEqual([song.title for song in filter_sort_songs(
            songs, sort=('genre', False))], ['Second', 'First', 'Third'])
        self.assertEqual([song.title for song in filter_sort_songs(
            songs, sort=('year', True))], ['Second', 'First', 'Third'])
        self.assertEqual([song.title for song in filter_sort_songs(
            songs, sort=('added_at', True))], ['Second', 'Third', 'First'])

    def test_ratings_play_counts_and_audio_tags_sort_locally(self):
        songs = [Item('/library/metadata/1', 'First', mood='Warm',
                      play_count=8, user_rating=10, bitrate=320),
                 Item('/library/metadata/2', 'Second', mood='Calm',
                      play_count=2, user_rating=4, bitrate=128)]
        for field in ('play_count', 'user_rating', 'bitrate'):
            self.assertEqual([song.title for song in filter_sort_songs(
                songs, sort=(field, True))], ['First', 'Second'])
        self.assertEqual([song.title for song in filter_sort_songs(
            songs, sort=('mood', False))], ['Second', 'First'])


if __name__ == '__main__':
    unittest.main()
