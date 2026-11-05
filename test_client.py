import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch
from xml.etree import ElementTree as ET
from plex_client import PlexClient, Item
from music_facets import MusicFacet


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
            '/playlists/7/items': '<MediaContainer totalSize="1"><Track key="/library/metadata/20" title="Playlist Song" grandparentTitle="Artist" parentTitle="Album" duration="125000" playlistItemID="81"/></MediaContainer>',
            '/library/sections/2/style': '<MediaContainer><Directory key="12" title="Dream Pop"/></MediaContainer>',
            '/library/sections/2/mood': '<MediaContainer><Directory key="30" title="Calm"/></MediaContainer>',
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
            elif query.get('artist.style') == ['12'] or query.get('album.style') == ['12']:
                fixtures[path] = ('<MediaContainer totalSize="1">'
                    '<Track key="/library/metadata/21" title="Dreamy Song" '
                    'parentKey="/library/metadata/101" parentTitle="Dream Album" '
                    'parentThumb="/album-art" grandparentTitle="Dream Artist"/>'
                    '</MediaContainer>')
            elif query.get('track.mood') == ['30'] or query.get('album.mood') == ['30']:
                fixtures[path] = ('<MediaContainer totalSize="1">'
                    '<Track key="/library/metadata/22" title="Calm Song"/></MediaContainer>')
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

    def do_DELETE(self):
        self.requests.append((self.command, self.path, self.headers.get('X-Plex-Token')))
        self.send_response(204)
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

    def test_album_artist_filter_is_forwarded_to_plex(self):
        self.client.albums('2', 100, sort='titleSort', artist='Artist & Band')
        path, token = Handler.requests[-1]
        query = parse_qs(urlsplit(path).query)
        self.assertEqual(query['type'], ['9'])
        self.assertEqual(query['artist.title'], ['Artist & Band'])
        self.assertEqual(query['X-Plex-Container-Start'], ['100'])
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

    def test_server_music_facets_filter_tracks_through_parent_tags(self):
        facets = self.client.music_facets('2')
        self.assertEqual([(facet.field, facet.title) for facet in facets],
                         [('mood', 'Calm'), ('style', 'Dream Pop')])
        style = facets[1]
        self.assertEqual(style.filters, (('album.style', 12), ('artist.style', 12)))
        self.assertEqual(self.client.music_facet_cover('2', style), '/album-art')
        self.assertEqual([song.key for song in self.client.music_facet_tracks('2', style)],
                         ['/library/metadata/21'])
        albums = self.client.albums_from_tracks(self.client.music_facet_tracks('2', style))
        self.assertEqual([(album.key, album.title, album.thumb) for album in albums],
                         [('/library/metadata/101', 'Dream Album', '/album-art')])
        self.assertEqual([song.key for song in self.client.music_facet_tracks('2', facets[0])],
                         ['/library/metadata/22'])
        query = parse_qs(urlsplit(Handler.requests[-1][0]).query)
        self.assertEqual(query['track.mood'], ['30'])
        self.assertEqual(query['type'], ['10'])
        with self.assertRaises(ValueError):
            self.client.music_facets('../other')

    def test_category_pagination_continues_after_overlapping_filter_page(self):
        facet = MusicFacet('style', 'Dream Pop',
                           (('artist.style', 12), ('album.style', 12)))
        def page(_path, **params):
            start = params['X-Plex-Container-Start']
            field = 'artist.style' if 'artist.style' in params else 'album.style'
            root = ET.Element('MediaContainer', totalSize='201')
            if start == 0:
                keys = range(1, 201)
            elif field == 'artist.style':
                keys = (201,)
            else:
                keys = (202,)
            for key in keys:
                ET.SubElement(root, 'Track', key=f'/library/metadata/{key}',
                              title=f'Song {key}')
            return root
        with patch.object(self.client, 'xml', side_effect=page) as request:
            songs = self.client.music_facet_tracks('2', facet)
        self.assertEqual(len(songs), 202)
        self.assertEqual(request.call_count, 4)
        self.assertIn('/library/metadata/202', {song.key for song in songs})

    def test_random_mood_queue_samples_25_unique_filtered_tracks(self):
        facet = MusicFacet('mood', 'Calm',
                           (('album.mood', 30), ('track.mood', 31)))
        def sample(_path, **params):
            first = 1 if 'album.mood' in params else 31
            root = ET.Element('MediaContainer')
            for number in range(first, first + 60):
                ET.SubElement(root, 'Track', key=f'/library/metadata/{number}',
                              title=f'Song {number}')
            return root
        with patch.object(self.client, 'xml', side_effect=sample) as request:
            songs = self.client.music_facet_random_tracks(
                '2', facet, 25, {'/library/metadata/1'})
        keys = [song.key for song in songs]
        self.assertEqual(len(keys), 25)
        self.assertEqual(len(set(keys)), 25)
        self.assertNotIn('/library/metadata/1', keys)
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertEqual(call.kwargs['sort'], 'random')
            self.assertEqual(call.kwargs['type'], 10)
        with self.assertRaises(ValueError):
            self.client.music_facet_random_tracks('../other', facet)

    def test_same_style_continuation_uses_parent_plex_tags_and_filters(self):
        track = Item('/library/metadata/20', 'Current')
        facet = MusicFacet('style', 'Dream Pop', (('album.style', 12),))
        queries = []
        def response(path, **params):
            queries.append((path, params))
            if path == track.key:
                return ET.fromstring('<MediaContainer><Track parentKey="/library/metadata/50" '
                                      'grandparentKey="/library/metadata/60"/></MediaContainer>')
            if path == '/library/metadata/50':
                return ET.fromstring('<MediaContainer><Directory><Style tag="Dream Pop"/>'
                                      '</Directory></MediaContainer>')
            if path == '/library/metadata/60':
                return ET.fromstring('<MediaContainer><Directory><Style tag="Indie Rock"/>'
                                      '</Directory></MediaContainer>')
            return ET.fromstring('<MediaContainer>'
                                  '<Track key="/library/metadata/20" title="Current"/>'
                                  '<Track key="/library/metadata/21" title="Next"/>'
                                  '<Track key="https://invalid.example/track" title="Unsafe"/>'
                                  '</MediaContainer>')
        with patch.object(self.client, 'xml', side_effect=response):
            selected, songs = self.client.more_tracks_same_style(
                '2', track, (facet,), {track.key})
        self.assertEqual(selected, facet)
        self.assertEqual([song.key for song in songs], ['/library/metadata/21'])
        self.assertEqual(queries[-1][1]['album.style'], 12)
        self.assertEqual(queries[-1][1]['sort'], 'random')
        with self.assertRaises(ValueError):
            self.client.more_tracks_same_style('2', Item('https://other.example', 'Bad'),
                                               (facet,))

    def test_mood_continuation_prefers_plex_moods_then_tag_fallback(self):
        seed = Item('/library/metadata/20', 'Current', artist='Artist', genre='Rock')
        mood = MusicFacet('mood', 'Calm', (('album.mood', 30),))
        style = MusicFacet('style', 'Dream Pop', (('artist.style', 12),))
        next_song = Item('/library/metadata/21', 'Next')
        tags = {'mood': ('Calm',), 'style': ('Dream Pop',), 'genre': ('Rock',)}
        sampled = []
        with patch.object(self.client, 'track_music_tags', return_value=tags), \
                patch.object(self.client, 'music_facet_random_tracks',
                             side_effect=lambda _section, facet, *_args:
                             sampled.append(facet.field) or [next_song]):
            chosen, songs = self.client.more_tracks_same_mood(
                '2', seed, (style, mood), {seed.key})
        self.assertEqual((chosen, songs), (mood, [next_song]))
        self.assertEqual(sampled, ['mood'])
        sampled.clear()
        with patch.object(self.client, 'track_music_tags', return_value=tags), \
                patch.object(self.client, 'music_facet_random_tracks',
                             side_effect=lambda _section, facet, *_args:
                             sampled.append(facet.field) or
                             ([next_song] if facet.field == 'style' else [])):
            chosen, songs = self.client.more_tracks_same_mood(
                '2', seed, (style, mood), {seed.key})
        self.assertEqual((chosen, songs), (style, [next_song]))
        self.assertEqual(sampled, ['mood', 'style'])
        with patch.object(self.client, 'track_music_tags', return_value=tags), \
                patch.object(self.client, 'music_facet_random_tracks', return_value=[]), \
                patch.object(self.client, 'metadata_similar_tracks',
                             return_value=[seed, next_song]) as fallback:
            chosen, songs = self.client.more_tracks_same_mood(
                '2', seed, (mood, style), {seed.key})
        self.assertIsNone(chosen)
        self.assertEqual(songs, [next_song])
        self.assertEqual(fallback.call_args.args[1], '2')

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
        self.assertEqual(items[0].playlist_item_id, 81)

    def test_move_playlist_entry_uses_plex_entry_ids(self):
        playlist = Item('/playlists/7/items', 'Favorites')
        self.client.move_playlist_item(playlist, 81, 80)
        method, path, token = Handler.requests[-1]
        self.assertEqual((method, urlsplit(path).path, token),
                         ('PUT', '/playlists/7/items/81/move', 'test-secret'))
        self.assertEqual(parse_qs(urlsplit(path).query), {'after': ['80']})
        self.client.move_playlist_item(playlist, 81)
        self.assertEqual(parse_qs(urlsplit(Handler.requests[-1][1]).query), {})
        for item_id, after_id in ((0, None), (81, 81), (81, -1)):
            with self.assertRaises(ValueError):
                self.client.move_playlist_item(playlist, item_id, after_id)

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

    def test_rename_and_delete_playlist(self):
        playlist = Item('/playlists/7/items', 'Favorites')
        self.client.rename_playlist(playlist, '  Rock & Soul  ')
        method, path, token = Handler.requests[-1]
        self.assertEqual((method, urlsplit(path).path, token),
                         ('PUT', '/playlists/7', 'test-secret'))
        self.assertEqual(parse_qs(urlsplit(path).query),
                         {'title.value': ['Rock & Soul'], 'title.locked': ['1']})
        self.client.delete_playlist(playlist)
        self.assertEqual(Handler.requests[-1], ('DELETE', '/playlists/7', 'test-secret'))
        for invalid in ('/playlists/7', '/playlists/7/items/extra', 'https://other/playlists/7/items'):
            with self.assertRaises(ValueError):
                self.client.delete_playlist(Item(invalid, 'Bad'))
            with self.assertRaises(ValueError):
                self.client.rename_playlist(Item(invalid, 'Bad'), 'Name')
        with self.assertRaises(ValueError):
            self.client.rename_playlist(playlist, '  ')

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

    def test_five_star_rating_and_clear_are_sent_to_plex(self):
        track = Item('/library/metadata/20', 'Song')
        self.client.set_track_rating(track, 6)
        self.assertEqual(parse_qs(urlsplit(Handler.requests[-1][1]).query)['rating'], ['6'])
        self.client.set_track_rating(track, -1)
        self.assertEqual(parse_qs(urlsplit(Handler.requests[-1][1]).query)['rating'], ['-1'])
        for invalid in (-2, 11, float('nan')):
            with self.assertRaises(ValueError):
                self.client.set_track_rating(track, invalid)

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
