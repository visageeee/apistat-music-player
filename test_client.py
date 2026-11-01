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
        fixtures = {
            '/library/sections': '<MediaContainer><Directory key="1" title="Films" type="movie"/><Directory key="2" title="Music" type="artist"/></MediaContainer>',
            '/library/sections/2/all': '<MediaContainer totalSize="151"><Directory key="/library/metadata/10/children" title="Album &amp; More" parentTitle="Artist" year="2026"/></MediaContainer>',
            '/library/metadata/10/children': '<MediaContainer><Track key="/library/metadata/20" title="Song" index="2" parentIndex="1" duration="125000" grandparentTitle="Artist"/></MediaContainer>',
            '/library/metadata/20': '<MediaContainer><Track><Media><Part key="/library/parts/42/file.flac"/></Media></Track></MediaContainer>',
        }
        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(fixtures.get(path, '<MediaContainer/>').encode())


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
        path, token = Handler.requests[-1]
        query = parse_qs(urlsplit(path).query)
        self.assertEqual(query['X-Plex-Container-Start'], ['100'])
        self.assertEqual(query['title'], ['A & B'])
        self.assertEqual(query['sort'], ['addedAt:desc'])
        self.assertNotIn('test-secret', path)
        self.assertEqual(token, 'test-secret')

    def test_tracks_and_direct_stream(self):
        album = self.client.albums('2')[0][0]
        track = self.client.tracks(album)[0]
        self.assertEqual(track.duration, 125000)
        self.assertEqual(track.number, '1.2')
        self.assertEqual(self.client.stream(track), self.address + '/library/parts/42/file.flac')

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
