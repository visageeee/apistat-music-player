import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from plex_client import PlexClient, Item


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.requests.append((self.path, self.headers.get('X-Plex-Token')))
        if self.headers.get('X-Plex-Token') != 'test-secret':
            self.send_error(401)
            return
        path = urlsplit(self.path).path
        query = parse_qs(urlsplit(self.path).query)
        fixtures = {
            '/': '<MediaContainer machineIdentifier="test-machine"/>',
            '/library/sections': '<MediaContainer><Directory key="1" title="Films" type="movie"/><Directory key="2" title="Music" type="artist"/></MediaContainer>',
            '/library/sections/2/all': '<MediaContainer totalSize="151"><Directory key="/library/metadata/10/children" title="Album &amp; More" parentTitle="Artist" year="2026" addedAt="1700000000"/></MediaContainer>',
            '/library/metadata/10/children': '<MediaContainer><Track key="/library/metadata/20" title="Song" index="2" parentIndex="1" duration="125000" grandparentTitle="Artist"/></MediaContainer>',
            '/library/metadata/20': '<MediaContainer><Track><Media><Part key="/library/parts/42/file.flac"/></Media></Track></MediaContainer>',
            '/library/metadata/20/nearest': ('<MediaContainer>'
                '<Track key="/library/metadata/21" title="Nearby One" grandparentTitle="Artist" parentTitle="Album" duration="90000"/>'
                '<Metadata type="track" key="/library/metadata/22" title="Nearby Two"/>'
                '<Track key="https://other.example/track" title="Invalid"/>'
                '</MediaContainer>'),
            '/playlists': '<MediaContainer><Playlist key="/playlists/7/items" title="Favorites" playlistType="audio"/></MediaContainer>',
            '/playlists/7/items': '<MediaContainer totalSize="1"><Track key="/library/metadata/20" title="Playlist Song" grandparentTitle="Artist" parentTitle="Album" duration="125000"/></MediaContainer>',
        }
        if path == '/library/sections/2/all' and query.get('type') == ['10']:
            fixtures[path] = '<MediaContainer totalSize="151"><Track key="/library/metadata/20" title="Song" grandparentTitle="Artist" parentTitle="Album" duration="125000" thumb="/art" year="1999" addedAt="1700000000" lastViewedAt="1700000100" viewCount="3" userRating="10" originallyAvailableAt="1999-05-01" parentIndex="2" index="4"><Genre tag="Jazz"/><Mood tag="Calm"/><Label tag="Favorite"/><Media bitrate="320" audioCodec="flac"/></Track></MediaContainer>'
            if query.get('genre') == ['Jazz']:
                fixtures[path] = ('<MediaContainer>'
                    '<Track key="/library/metadata/21" title="Same Artist and Genre" grandparentTitle="Artist"><Genre tag="Jazz"/></Track>'
                    '<Track key="/library/metadata/22" title="Same Genre" grandparentTitle="Other"><Genre tag="Jazz"/></Track>'
                    '</MediaContainer>')
            elif query.get('artist.title') == ['Artist']:
                fixtures[path] = ('<MediaContainer>'
                    '<Track key="/library/metadata/21" title="Same Artist and Genre" grandparentTitle="Artist"><Genre tag="Jazz"/></Track>'
                    '<Track key="/library/metadata/23" title="Same Artist" grandparentTitle="Artist"><Genre tag="Rock"/></Track>'
                    '</MediaContainer>')
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(fixtures.get(path, '<MediaContainer/>').encode())

    def do_POST(self):
        self.requests.append((self.command, self.path, self.headers.get('X-Plex-Token')))
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(b'<MediaContainer><Playlist key="/playlists/9/items" title="Road Trip"/></MediaContainer>')

    def do_PUT(self):
        self.requests.append((self.command, self.path, self.headers.get('X-Plex-Token')))
        self.send_response(200)
        self.end_headers()


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.address = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.client = PlexClient(self.address, 'test-secret')

    def test_library_filter(self):
        self.assertEqual(self.client.sections(), [('2', 'Music')])

    def test_album_pagination_and_search_encoding(self):
        albums, total = self.client.albums('2', 100, 'A & B')
        self.assertEqual(total, 151)
        self.assertEqual(albums[0].title, 'Album & More')
        self.assertEqual(albums[0].added_at, 1700000000)
        path, token = Handler.requests[-1]
        query = parse_qs(urlsplit(path).query)
        self.assertEqual(query['X-Plex-Container-Start'], ['100'])
        self.assertEqual(query['title'], ['A & B'])
        self.assertEqual(query['sort'], ['addedAt:desc'])
        self.assertNotIn('test-secret', path)
        self.assertEqual(token, 'test-secret')

    def test_album_sort_is_forwarded_and_invalid_sort_rejected(self):
        sort = 'artist.titleSort,album.titleSort,album.index,album.id,album.originallyAvailableAt'
        self.client.albums('2', sort=sort)
        path, _token = Handler.requests[-1]
        self.assertEqual(parse_qs(urlsplit(path).query)['sort'],
                         [sort])
        with self.assertRaises(ValueError):
            self.client.albums('2', sort='titleSort:desc&foo=bar')

    def test_tracks_and_direct_stream(self):
        album = self.client.albums('2')[0][0]
        track = self.client.tracks(album)[0]
        self.assertEqual(track.duration, 125000)
        self.assertEqual(track.number, '1.2')
        self.assertEqual(self.client.stream(track), self.address + '/library/parts/42/file.flac')

    def test_nearest_tracks_parse_only_local_track_keys(self):
        seed = Item('/library/metadata/20', 'Seed')
        nearby = self.client.nearest_tracks(seed, limit=12)
        self.assertEqual([song.key for song in nearby],
                         ['/library/metadata/21', '/library/metadata/22'])
        path, _token = Handler.requests[-1]
        self.assertEqual(parse_qs(urlsplit(path).query)['limit'], ['12'])
        with self.assertRaises(ValueError):
            self.client.nearest_tracks(Item('https://other.example/track', 'Unsafe'))
        with self.assertRaises(ValueError):
            self.client.nearest_tracks(seed, limit=101)

    def test_metadata_similarity_uses_plex_genre_and_artist_filters(self):
        seed = Item('/library/metadata/20', 'Seed', artist='Artist', genre='Jazz')
        candidates = self.client.metadata_similar_tracks(seed, '2')
        self.assertEqual([song.key for song in candidates],
                         ['/library/metadata/21', '/library/metadata/22',
                          '/library/metadata/23'])
        request_queries = [parse_qs(urlsplit(path).query) for path, _token in Handler.requests[-2:]]
        self.assertEqual([query['sort'] for query in request_queries],
                         [['random'], ['random']])
        with self.assertRaises(ValueError):
            self.client.metadata_similar_tracks(seed, '../other')

    def test_songs_and_playlists(self):
        songs, total = self.client.songs('2', 100, 'artist.titleSort,titleSort')
        self.assertEqual((songs[0].title, songs[0].artist, songs[0].album, total),
                         ('Song', 'Artist', 'Album', 151))
        self.assertEqual((songs[0].genre, songs[0].year, songs[0].added_at),
                         ('Jazz', '1999', 1700000000))
        self.assertEqual((songs[0].mood, songs[0].label, songs[0].album_artist,
                          songs[0].release_date, songs[0].disc, songs[0].track_number),
                         ('Calm', 'Favorite', 'Artist', '1999-05-01', 2, 4))
        self.assertEqual((songs[0].last_played_at, songs[0].play_count,
                          songs[0].user_rating, songs[0].bitrate, songs[0].codec),
                         (1700000100, 3, 10.0, 320, 'flac'))
        query = parse_qs(urlsplit(Handler.requests[-1][0]).query)
        self.assertEqual(query['type'], ['10'])
        self.assertEqual(query['sort'], ['artist.titleSort,titleSort'])
        self.assertEqual(query['X-Plex-Container-Start'], ['100'])
        playlists = self.client.playlists()
        self.assertEqual([item.title for item in playlists], ['Favorites'])
        items, total = self.client.playlist_items(playlists[0])
        self.assertEqual((items[0].title, total), ('Playlist Song', 1))

    def test_create_playlist_and_add_song(self):
        track = Item('/library/metadata/20', 'Song')
        playlist = self.client.create_playlist('Road Trip', track)
        self.assertEqual(playlist.key, '/playlists/9/items')
        method, path, token = Handler.requests[-1]
        self.assertEqual((method, token), ('POST', 'test-secret'))
        self.assertEqual(parse_qs(urlsplit(path).query)['title'], ['Road Trip'])
        self.assertEqual(parse_qs(urlsplit(path).query)['uri'],
                         ['server://test-machine/com.plexapp.plugins.library/library/metadata/20'])
        self.client.add_playlist_item(playlist, track)
        method, path, token = Handler.requests[-1]
        self.assertEqual((method, urlsplit(path).path, token),
                         ('PUT', '/playlists/9/items', 'test-secret'))
        self.assertEqual(parse_qs(urlsplit(path).query)['uri'],
                         ['server://test-machine/com.plexapp.plugins.library/library/metadata/20'])
        with self.assertRaises(ValueError):
            self.client.add_playlist_item(playlist, Item('http://elsewhere', 'Bad'))

    def test_love_song_sends_plex_user_rating(self):
        track = Item('/library/metadata/20', 'Song')
        self.client.rate_track(track, True)
        method, path, token = Handler.requests[-1]
        self.assertEqual((method, urlsplit(path).path, token),
                         ('PUT', '/:/rate', 'test-secret'))
        self.assertEqual(parse_qs(urlsplit(path).query), {
            'key': ['20'], 'identifier': ['com.plexapp.plugins.library'],
            'rating': ['10']})
        self.client.rate_track(track, False)
        self.assertEqual(parse_qs(urlsplit(Handler.requests[-1][1]).query)['rating'], ['-1'])

    def test_missing_media(self):
        with self.assertRaises(ValueError):
            self.client.stream(Item('/missing', 'Missing'))

    def test_auth_failure(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as caught:
            PlexClient(self.address, 'wrong').sections()
        self.assertEqual(caught.exception.code, 401)

    def test_invalid_addresses_and_paths(self):
        for address in ['file:///tmp/test', 'https://user:pass@example.com', 'https://host/?token=x']:
            with self.assertRaises(ValueError):
                PlexClient(address, 'token')
        with self.assertRaises(ValueError):
            self.client.url('//another-host/file')


if __name__ == '__main__':
    unittest.main()
