"""Small Plex music client. No third-party Python dependencies."""
from dataclasses import dataclass, replace
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
import random
import re
import xml.etree.ElementTree as ET
from id3_tags import read_id3_tags
from music_facets import FACET_SOURCES, MusicFacet, merge_categories


ALBUM_SORT_ARTIST = ('artist.titleSort,album.titleSort,album.index,album.id,'
                     'album.originallyAvailableAt')


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
    album_key: str = ''
    album_thumb: str = ''
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
    playlist_item_id: int = 0
    smart: bool = False


class PlexClient:
    def __init__(self, address, token, identifier='linux-plex-music-prototype',
                 device_name='Apistat', timeout=15):
        address = address.strip().rstrip('/')
        parsed = urlsplit(address)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Enter a server URL such as http://192.168.1.10:32400')
        self.address, self.token = address, token.strip()
        self.identifier = identifier
        self.device_name = device_name
        self.timeout = timeout
        if not self.token:
            raise ValueError('Enter a Plex token.')
        self.opener = build_opener(NoRedirect())

    def url(self, path, **params):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('Invalid Plex resource path')
        return self.address + path + ('?' + urlencode(params) if params else '')

    def request(self, method, path, **params):
        req = Request(self.url(path, **params), headers={
            'X-Plex-Token': self.token, 'X-Plex-Product': 'Apistat',
            'X-Plex-Client-Identifier': self.identifier,
            'X-Plex-Device-Name': self.device_name,
            'Accept': 'application/xml'}, method=method)
        with self.opener.open(req, timeout=self.timeout) as response:
            return response.read()

    def get(self, path, **params):
        return self.request('GET', path, **params)

    def xml(self, path, **params):
        return ET.fromstring(self.get(path, **params))

    def sections(self):
        return [(x.attrib['key'], x.get('title', 'Music'))
                for x in self.xml('/library/sections').findall('Directory')
                if x.get('type') == 'artist']

    def music_facets(self, section):
        """List Plex's server-side Style and Mood categories for a music library."""
        if not re.fullmatch(r'\d+', str(section)):
            raise ValueError('Invalid music library')
        responses = []
        for field, media_type, filter_field in FACET_SOURCES:
            try:
                root = self.xml(f'/library/sections/{section}/{field}', type=media_type)
            except HTTPError as error:
                if error.code in (400, 404):
                    continue
                raise
            responses.append((field, media_type, filter_field, root))
        return merge_categories(responses)

    def music_facet_cover(self, section, facet):
        """Find one local Plex artwork path for a style or mood preview."""
        if not re.fullmatch(r'\d+', str(section)) or not isinstance(facet, MusicFacet):
            raise ValueError('Invalid music category request')
        for filter_field, tag_id in facet.filters:
            try:
                root = self.xml(f'/library/sections/{section}/all', type=10,
                                sort='random', **{filter_field: tag_id,
                                                 'X-Plex-Container-Start': 0,
                                                 'X-Plex-Container-Size': 1})
            except HTTPError as error:
                if error.code in (400, 404):
                    continue
                raise
            for node in root.findall('Track'):
                cover = node.get('parentThumb') or node.get('thumb', '')
                if cover.startswith('/') and not cover.startswith('//'):
                    return cover
        return ''

    def music_facet_random_tracks(self, section, facet, limit=25, exclude_keys=()):
        """Sample tracks from every Plex filter behind a style or mood."""
        if (not re.fullmatch(r'\d+', str(section)) or
                not isinstance(facet, MusicFacet) or
                type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError('Invalid random music category request')
        excluded = set(exclude_keys)
        candidates = {}
        for filter_field, tag_id in facet.filters:
            try:
                root = self.xml(f'/library/sections/{section}/all', type=10,
                                sort='random', **{
                                    filter_field: tag_id,
                                    'X-Plex-Container-Start': 0,
                                    'X-Plex-Container-Size': min(100, max(40, limit * 4))})
            except HTTPError as error:
                if error.code in (400, 404):
                    continue
                raise
            for node in root.findall('Track'):
                key = node.get('key', '')
                if (re.fullmatch(r'/library/metadata/\d+', key) and
                        key not in excluded and key not in candidates):
                    candidates[key] = self.track_item(node)
        songs = list(candidates.values())
        random.shuffle(songs)
        return songs[:limit]

    def music_facet_tracks(self, section, facet, valid=lambda: True):
        """Fetch tracks selected by a Plex category, including parent metadata tags."""
        if not re.fullmatch(r'\d+', str(section)) or not isinstance(facet, MusicFacet):
            raise ValueError('Invalid music category request')
        songs = {}
        for filter_field, tag_id in facet.filters:
            start = 0
            previous_page = None
            while valid():
                try:
                    root = self.xml(f'/library/sections/{section}/all', type=10,
                                    sort='addedAt:desc', **{
                                        filter_field: tag_id,
                                        'X-Plex-Container-Start': start,
                                        'X-Plex-Container-Size': 200})
                except HTTPError as error:
                    if error.code in (400, 404):
                        break
                    raise
                tracks = root.findall('Track')
                if not tracks:
                    break
                page = tuple(node.get('key', '') for node in tracks)
                if page == previous_page:
                    break
                previous_page = page
                for node in tracks:
                    key = node.get('key', '')
                    if re.fullmatch(r'/library/metadata/\d+', key) and key not in songs:
                        songs[key] = self.track_item(node)
                total_text = root.get('totalSize', '')
                total = int(total_text) if total_text.isdigit() else None
                start += len(tracks)
                if (total is not None and start >= total) or (
                        total is None and len(tracks) < 200):
                    break
        return (sorted(songs.values(), key=lambda song: (-song.added_at,
                                                         song.title.casefold()))
                if valid() else None)

    def track_music_tags(self, track):
        """Read Plex mood, style and genre metadata from track and ancestors."""
        if not isinstance(track, Item) or not re.fullmatch(r'/library/metadata/\d+', track.key):
            raise ValueError('Invalid Plex track key')
        root = self.xml(track.key)
        node = root.find('Track')
        if node is None:
            return {'mood': tuple(track.mood.split(', ')) if track.mood else (),
                    'style': (),
                    'genre': tuple(track.genre.split(', ')) if track.genre else ()}
        sources = [node]
        for parent_key in (node.get('parentKey', ''), node.get('grandparentKey', '')):
            if not re.fullmatch(r'/library/metadata/\d+', parent_key):
                continue
            parent_root = self.xml(parent_key)
            parent = next((child for child in parent_root
                           if child.tag in ('Directory', 'Metadata')), None)
            if parent is not None:
                sources.append(parent)
        tags = {}
        for field in ('mood', 'style', 'genre'):
            names = [tag.get('tag', '').strip() for source in sources
                     for tag in source.findall(field.title())]
            fallback = getattr(track, field, '')
            if fallback:
                names.extend(part.strip() for part in fallback.split(','))
            tags[field] = tuple(dict.fromkeys(name for name in names if name))
        return tags

    def track_style_names(self, track):
        return self.track_music_tags(track)['style']

    def more_tracks_same_mood(self, section, track, facets, exclude_keys=(),
                              preferred=None, limit=10):
        """Use Plex mood categories first, then style and metadata tags."""
        if (not re.fullmatch(r'\d+', str(section)) or
                not isinstance(track, Item) or
                not re.fullmatch(r'/library/metadata/\d+', track.key) or
                type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError('Invalid mood continuation request')
        if preferred is not None and not isinstance(preferred, MusicFacet):
            raise ValueError('Invalid mood continuation category')
        tags = self.track_music_tags(track)
        matches = []
        if preferred is not None and preferred.field == 'mood':
            matches.append(preferred)
        for field in ('mood', 'style'):
            names = {name.casefold() for name in tags[field]}
            if field == 'style' and preferred is not None and preferred.field == 'style':
                matches.append(preferred)
            matches.extend(facet for facet in facets if isinstance(facet, MusicFacet)
                           and facet.field == field and facet.title.casefold() in names)
        seen = set()
        for facet in matches:
            if facet in seen:
                continue
            seen.add(facet)
            songs = self.music_facet_random_tracks(section, facet, limit, exclude_keys)
            if songs:
                return facet, songs
        seed = replace(track, mood=', '.join(tags['mood']),
                       genre=', '.join(tags['genre']))
        candidates = self.metadata_similar_tracks(seed, section,
                                                  min(100, max(40, limit * 4)))
        excluded = set(exclude_keys)
        return None, [song for song in candidates if song.key not in excluded][:limit]

    def more_tracks_same_style(self, section, track, facets, exclude_keys=(),
                               preferred=None, limit=10):
        """Pick a small random continuation from a matching Plex style facet."""
        if (not re.fullmatch(r'\d+', str(section)) or
                not isinstance(track, Item) or
                not re.fullmatch(r'/library/metadata/\d+', track.key) or
                type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError('Invalid style continuation request')
        if preferred is not None and (not isinstance(preferred, MusicFacet) or
                                      preferred.field != 'style'):
            raise ValueError('Invalid style continuation category')
        if preferred is not None:
            matches = (preferred,)
        else:
            names = {name.casefold() for name in self.track_style_names(track)}
            matches = tuple(facet for facet in facets if isinstance(facet, MusicFacet)
                            and facet.field == 'style' and facet.title.casefold() in names)
        for facet in matches:
            songs = self.music_facet_random_tracks(section, facet, limit, exclude_keys)
            if songs:
                return facet, songs
        return None, []

    def albums(self, section, start=0, title='', sort='addedAt:desc', artist=''):
        if sort not in ('addedAt:desc', 'year:desc', ALBUM_SORT_ARTIST, 'titleSort'):
            raise ValueError('Unsupported album sort')
        params = {'type': 9, 'sort': sort,
                  'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 100}
        if title:
            params['title'] = title
        if artist:
            params['artist.title'] = artist
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
    def albums_from_tracks(tracks):
        """Make album-wall entries from the parent metadata in Plex track results."""
        albums = {}
        for track in tracks:
            key = track.album_key
            if not re.fullmatch(r'/library/metadata/\d+', key) or key in albums:
                continue
            albums[key] = Item(key, track.album or 'Untitled album',
                               artist=track.album_artist or track.artist,
                               year=track.year, thumb=track.album_thumb or track.thumb,
                               added_at=track.added_at)
        return list(albums.values())

    def nearest_tracks(self, track, limit=50):
        if not re.fullmatch(r'/library/metadata/\d+', track.key):
            raise ValueError('Invalid Plex track key')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid similar-track limit')
        root = self.xml(track.key + '/nearest', limit=limit)
        elements = list(root.findall('Track')) + [
            node for node in root.findall('Metadata') if node.get('type') == 'track']
        return [self.track_item(node) for node in elements
                if re.fullmatch(r'/library/metadata/\d+', node.get('key', ''))]

    def metadata_similar_tracks(self, track, section, limit=50):
        if not re.fullmatch(r'/library/metadata/\d+', track.key):
            raise ValueError('Invalid Plex track key')
        if not re.fullmatch(r'\d+', str(section)) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Invalid similar-track request')
        filters = []
        for genre in [part.strip() for part in track.genre.split(',') if part.strip()][:2]:
            filters.append(('genre', genre))
        for mood in [part.strip() for part in track.mood.split(',') if part.strip()][:2]:
            filters.append(('mood', mood))
        if track.artist:
            filters.append(('artist.title', track.artist))
        candidates = {}
        for field, value in filters:
            try:
                root = self.xml('/library/sections/' + str(section) + '/all',
                                type=10, sort='random', **{
                                    field: value, 'X-Plex-Container-Start': 0,
                                    'X-Plex-Container-Size': 100})
            except HTTPError as error:
                if error.code in (400, 404):
                    continue
                raise
            for node in root.findall('Track'):
                key = node.get('key', '')
                if re.fullmatch(r'/library/metadata/\d+', key) and key != track.key:
                    candidates[key] = self.track_item(node)
        seed_genres = {tag.strip().casefold() for tag in track.genre.split(',') if tag.strip()}
        seed_moods = {tag.strip().casefold() for tag in track.mood.split(',') if tag.strip()}
        def score(candidate):
            genres = {tag.strip().casefold() for tag in candidate.genre.split(',') if tag.strip()}
            moods = {tag.strip().casefold() for tag in candidate.mood.split(',') if tag.strip()}
            tag_score = 6 * len(seed_genres & genres) + 5 * len(seed_moods & moods)
            artist_score = bool(track.artist and
                                candidate.artist.casefold() == track.artist.casefold())
            return tag_score or artist_score
        ranked = [candidate for candidate in candidates.values() if score(candidate)]
        return sorted(ranked, key=lambda candidate: -score(candidate))[:limit]

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
                    album_key=element.get('parentKey', ''),
                    album_thumb=element.get('parentThumb', ''),
                    added_at=integer('addedAt'),
                    genre=', '.join(genres) if genres else element.get('genre', ''),
                    mood=tags('Mood'), label=tags('Label'),
                    album_artist=element.get('grandparentTitle', ''),
                    release_date=element.get('originallyAvailableAt', ''),
                    disc=disc, track_number=track_number,
                    last_played_at=integer('lastViewedAt'),
                    play_count=integer('viewCount'), user_rating=user_rating,
                    bitrate=integer('bitrate', media),
                    codec=media.get('audioCodec', '') if media is not None else '',
                    playlist_item_id=integer('playlistItemID'))

    def songs(self, section, start=0, sort='addedAt:desc'):
        if sort not in ('addedAt:desc', 'titleSort', 'artist.titleSort,titleSort'):
            raise ValueError('Unsupported song sort order')
        root = self.xml('/library/sections/' + section + '/all', type=10, sort=sort,
                        **{'X-Plex-Container-Start': start, 'X-Plex-Container-Size': 100})
        songs = [self.track_item(x) for x in root.findall('Track')]
        return songs, int(root.get('totalSize', start + len(songs)))

    def track_details(self, track):
        if not re.fullmatch(r'/library/metadata/\d+', track.key):
            raise ValueError('Invalid track path')
        root = self.xml(track.key)
        node = root.find('Track')
        if node is None:
            return {}, ''
        media = node.find('Media')
        part = media.find('Part') if media is not None else None
        streams = [stream for stream in part.findall('Stream')
                   if stream.get('streamType') == '2'] if part is not None else []
        stream = next((item for item in streams if item.get('selected') == '1'),
                      streams[0] if streams else None)
        details = {}
        for key, source, attribute in (
                ('codec', media, 'audioCodec'), ('container', media, 'container'),
                ('bitrate', media, 'bitrate'), ('sample_rate', media, 'audioSampleRate'),
                ('bit_depth', media, 'audioBitDepth'), ('channels', media, 'audioChannels'),
                ('size', part, 'size'), ('file', part, 'file')):
            if source is not None and source.get(attribute):
                details[key] = source.get(attribute)
        if stream is not None:
            for key, attribute in (('codec', 'codec'), ('bitrate', 'bitrate'),
                                   ('sample_rate', 'samplingRate'), ('bit_depth', 'bitDepth'),
                                   ('channels', 'channels')):
                if stream.get(attribute):
                    details[key] = stream.get(attribute)
        for key, attribute in (('title', 'title'), ('artist', 'originalTitle'),
                               ('album_artist', 'grandparentTitle'), ('album', 'parentTitle'),
                               ('year', 'parentYear'), ('track', 'index'), ('disc', 'parentIndex'),
                               ('date', 'originallyAvailableAt'), ('rating', 'userRating'),
                               ('play_count', 'viewCount'), ('summary', 'summary')):
            if node.get(attribute):
                details[key] = node.get(attribute)
        for tag in ('Genre', 'Mood', 'Label', 'Writer', 'Director', 'Collection', 'Country'):
            values = [element.get('tag') for element in node.findall(tag) if element.get('tag')]
            if values:
                details[tag.lower()] = ', '.join(values)
        if part is not None and part.get('key'):
            details['id3_tags'], details['id3_status'] = read_id3_tags(
                self, part.get('key'), part.get('size'))
        summary = ''
        artist_key = node.get('grandparentKey', '')
        album_artist = node.get('grandparentTitle', '')
        if (re.fullmatch(r'/library/metadata/\d+', artist_key) and album_artist and
                album_artist.casefold() == track.artist.casefold()):
            try:
                artist = self.xml(artist_key).find('Directory')
                if artist is not None:
                    summary = artist.get('summary', '')
            except (OSError, ValueError, ET.ParseError):
                pass
        return details, summary

    def playlists(self):
        root = self.xml('/playlists', playlistType='audio')
        return [Item(x.attrib['key'], x.get('title', 'Untitled playlist'),
                     smart=x.get('smart') == '1')
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

    def rename_playlist(self, playlist, title):
        match = re.fullmatch(r'/playlists/(\d+)/items', playlist.key)
        if not match or not isinstance(title, str) or not title.strip():
            raise ValueError('Invalid playlist or name.')
        self.request('PUT', f'/playlists/{match.group(1)}',
                     **{'title.value': title.strip(), 'title.locked': 1})

    def delete_playlist(self, playlist):
        match = re.fullmatch(r'/playlists/(\d+)/items', playlist.key)
        if not match:
            raise ValueError('Invalid playlist.')
        self.request('DELETE', f'/playlists/{match.group(1)}')

    def move_playlist_item(self, playlist, item_id, after_id=None):
        match = re.fullmatch(r'/playlists/(\d+)/items', playlist.key)
        if not match or type(item_id) is not int or item_id <= 0 or (
                after_id is not None and (type(after_id) is not int or after_id <= 0
                                          or after_id == item_id)):
            raise ValueError('Invalid playlist move.')
        path = f'/playlists/{match.group(1)}/items/{item_id}/move'
        self.request('PUT', path, **({'after': after_id} if after_id is not None else {}))

    def rate_track(self, track, loved=True):
        self.set_track_rating(track, 10 if loved else -1)

    def set_track_rating(self, track, rating):
        if type(rating) not in (int, float) or rating != -1 and not 0 <= rating <= 10:
            raise ValueError('Invalid track rating.')
        match = re.fullmatch(r'/library/metadata/(\d+)', track.key)
        if not match:
            raise ValueError('Invalid song path.')
        self.request('PUT', '/:/rate', key=match.group(1),
                     identifier='com.plexapp.plugins.library',
                     rating=rating)

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
