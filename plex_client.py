"""Small Plex music client. No third-party Python dependencies."""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
import re
import xml.etree.ElementTree as ET


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward authentication to another host.
        return None


@dataclass
class Item:
    key: str
    title: str
    artist: str = ''
    year: str = ''
    album: str = ''
    duration: int = 0
    number: str = ''
    thumb: str = ''
    added_at: int = 0
    genre: str = ''
    mood: str = ''
    label: str = ''
    album_artist: str = ''
    release_date: str = ''
    disc: int = 0
    track_number: int = 0
    last_played_at: int = 0
    play_count: int = 0
    user_rating: float = 0.0
    bitrate: int = 0
    codec: str = ''


class PlexClient:
    def __init__(self, address, token):
        address = address.strip().rstrip('/')
        parsed = urlsplit(address)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Enter a server URL such as http://192.168.1.10:32400')
        self.address, self.token = address, token.strip()
        if not self.token:
            raise ValueError('Enter a Plex token.')
        self.opener = build_opener(NoRedirect())

    def url(self, path, **params):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('Invalid Plex resource path')
        return self.address + path + ('?' + urlencode(params) if params else '')

    def request(self, method, path, **params):
        req = Request(self.url(path, **params), headers={
            'X-Plex-Token': self.token, 'X-Plex-Product': 'Plex Music Prototype',
            'X-Plex-Client-Identifier': 'linux-plex-music-prototype',
            'Accept': 'application/xml'}, method=method)
        with self.opener.open(req, timeout=15) as response:
            return response.read()

    def get(self, path, **params):
        return self.request('GET', path, **params)

    def xml(self, path, **params):
        return ET.fromstring(self.get(path, **params))

    def sections(self):
        return [(x.attrib['key'], x.get('title', 'Music'))
                for x in self.xml('/library/sections').findall('Directory')
                if x.get('type') == 'artist']

    def albums(self, section, start=0, title=''):
        params = {'type': 9, 'sort': 'addedAt:desc',
                  'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 100}
        if title:
            params['title'] = title
        root = self.xml('/library/sections/' + section + '/all', **params)
        items = [Item(x.attrib['key'], x.get('title', 'Untitled'),
                      x.get('parentTitle', ''), x.get('year', ''), thumb=x.get('thumb', ''),
                      added_at=int(x.get('addedAt', '0')) if x.get('addedAt', '0').isdigit() else 0)
                 for x in root.findall('Directory')]
        total = int(root.get('totalSize', start + len(items)))
        return items, total

    def tracks(self, album):
        path = album.key if album.key.endswith('/children') else album.key + '/children'
        return [self.track_item(x, album.artist) for x in self.xml(path).findall('Track')]

    @staticmethod
    def track_item(element, fallback_artist=''):
        def integer(name, source=element):
            value = source.get(name, '0') if source is not None else '0'
            return int(value) if value.isdigit() else 0
        def tags(name):
            return ', '.join(item.get('tag') for item in element.findall(name) if item.get('tag'))
        genres = [item.get('tag') for item in element.findall('Genre') if item.get('tag')]
        media = element.find('Media')
        try:
            user_rating = float(element.get('userRating', '0'))
        except ValueError:
            user_rating = 0.0
        if not 0 <= user_rating <= 10:
            user_rating = 0.0
        disc = integer('parentIndex')
        track_number = integer('index')
        return Item(element.attrib['key'], element.get('title', 'Untitled'),
                    element.get('originalTitle') or element.get('grandparentTitle', fallback_artist),
                    year=element.get('year') or element.get('parentYear', ''),
                    album=element.get('parentTitle', ''),
                    duration=integer('duration'),
                    number=f"{disc or 1}.{track_number}",
                    thumb=element.get('thumb') or element.get('parentThumb', ''),
                    added_at=integer('addedAt'),
                    genre=', '.join(genres) if genres else element.get('genre', ''),
                    mood=tags('Mood'), label=tags('Label'),
                    album_artist=element.get('grandparentTitle', ''),
                    release_date=element.get('originallyAvailableAt', ''),
                    disc=disc, track_number=track_number,
                    last_played_at=integer('lastViewedAt'),
                    play_count=integer('viewCount'), user_rating=user_rating,
                    bitrate=integer('bitrate', media),
                    codec=media.get('audioCodec', '') if media is not None else '')

    def songs(self, section, start=0, sort='addedAt:desc'):
        if sort not in ('addedAt:desc', 'titleSort', 'artist.titleSort,titleSort'):
            raise ValueError('Unsupported song sort order')
        root = self.xml('/library/sections/' + section + '/all', type=10, sort=sort,
                        **{'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 100})
        songs = [self.track_item(x) for x in root.findall('Track')]
        return songs, int(root.get('totalSize', start + len(songs)))

    def playlists(self):
        root = self.xml('/playlists', playlistType='audio')
        return [Item(x.attrib['key'], x.get('title', 'Untitled playlist'))
                for x in root.findall('Playlist') if x.get('key', '').startswith('/playlists/')]

    def track_uri(self, track):
        if not re.fullmatch(r'/library/metadata/\d+', track.key):
            raise ValueError('Invalid song path.')
        machine = self.xml('/').get('machineIdentifier', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', machine):
            raise ValueError('Plex did not provide a server identifier.')
        return f'server://{machine}/com.plexapp.plugins.library{track.key}'

    def create_playlist(self, title, first_track):
        title = title.strip()
        if not title:
            raise ValueError('Enter a playlist name.')
        uri = self.track_uri(first_track)
        root = ET.fromstring(self.request('POST', '/playlists', type='audio',
                                          title=title, smart=0, uri=uri))
        element = root.find('Playlist')
        if element is None:
            element = root.find('Metadata')
        if element is None or not re.fullmatch(r'/playlists/\d+/items', element.get('key', '')):
            raise ValueError('Plex did not return the new playlist.')
        return Item(element.attrib['key'], element.get('title', title))

    def add_playlist_item(self, playlist, track):
        match = re.fullmatch(r'/playlists/(\d+)/items', playlist.key)
        if not match:
            raise ValueError('Invalid playlist or song.')
        uri = self.track_uri(track)
        self.request('PUT', f'/playlists/{match.group(1)}/items', uri=uri)

    def rate_track(self, track, loved=True):
        match = re.fullmatch(r'/library/metadata/(\d+)', track.key)
        if not match:
            raise ValueError('Invalid song path.')
        self.request('PUT', '/:/rate', key=match.group(1),
                     identifier='com.plexapp.plugins.library',
                     rating=10 if loved else -1)

    def playlist_items(self, playlist, start=0):
        if not playlist.key.startswith('/playlists/') or not playlist.key.endswith('/items'):
            raise ValueError('Invalid playlist path')
        root = self.xml(playlist.key, **{'X-Plex-Container-Start': start,
                                         'X-Plex-Container-Size': 100})
        songs = [self.track_item(x) for x in root.findall('Track')]
        return songs, int(root.get('totalSize', start + len(songs)))

    def stream(self, track):
        part = self.xml(track.key).find('.//Media/Part')
        if part is None or not part.get('key'):
            raise ValueError('This track has no playable file.')
        return self.url(part.attrib['key'])
