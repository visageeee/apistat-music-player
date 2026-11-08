"""On-demand album map enrichment using Plex metadata and Last.fm tags."""
import hashlib
import json
import re
import time

from album_web import canonical_album_key
from local_cache import LocalCache, _write_bytes

# Community tags include years, countries and personal labels. Accept only
# recognizable musical styles/moods, rather than turning arbitrary text into
# map categories.
# Keep multiword tags as whole values rather than splitting on spaces.
STYLES = frozenset(x.strip() for x in '''ambient|electronic|electronica|downtempo|trip-hop|techno|house|trance|disco|folk|country|americana|bluegrass|jazz|blues|soul|funk|gospel|reggae|ska|dub|classical|orchestral|opera|soundtrack|instrumental|experimental|indie|alternative|post-rock|shoegaze|dream-pop|synthpop|electropop|new-wave|punk|grunge|metal|hip-hop|hip hop|rap|r&b|pop-rock|art-rock|psychedelic|indie rock|alternative rock|art rock|post rock|progressive rock|hard rock|folk rock|indie pop|dream pop|synth pop|world music'''.split('|'))
MOODS = frozenset('happy|joyful|cheerful|upbeat|optimistic|playful|uplifting|celebratory|sad|melancholy|melancholic|somber|mournful|angry|aggressive|brooding|dark|calm|peaceful|relaxed|dreamy|soothing|mellow|meditative'.split('|'))
BROAD = frozenset(('rock', 'pop', 'pop/rock', 'pop rock', 'music'))


class ChartLookupError(Exception):
    pass


def _path(client, section, key):
    value = str(section) + '\0' + canonical_album_key(key)
    return LocalCache(client).root / 'album-chart' / (hashlib.sha256(value.encode()).hexdigest() + '.json')


def _plex_tags(client, album):
    key = canonical_album_key(album.key)
    if getattr(client, 'is_local', False) or not re.fullmatch(r'/library/metadata/\d+', key):
        return [], []
    node = client.xml(key).find('Directory')
    if node is None:
        return [], []
    def read(element, kind):
        return [x.get('tag', '').strip() for x in element.findall(kind) if x.get('tag', '').strip()]
    styles = read(node, 'Style') or [v for v in read(node, 'Genre') if v.casefold() not in BROAD]
    moods = read(node, 'Mood')
    parent = node.get('parentKey', '')
    if not styles and re.fullmatch(r'/library/metadata/\d+', parent):
        artist = client.xml(parent).find('Directory')
        if artist is not None:
            styles = read(artist, 'Style') or [v for v in read(artist, 'Genre') if v.casefold() not in BROAD]
    return styles[:5], moods[:5]


def _select_tags(response):
    tags = response.get('toptags', {}).get('tag', [])
    tags = [tags] if isinstance(tags, dict) else tags if isinstance(tags, list) else []
    styles, moods = [], []
    for entry in tags[:50]:
        name = entry.get('name', '') if isinstance(entry, dict) else ''
        name = name.strip().casefold() if isinstance(name, str) else ''
        if name in STYLES and name not in styles:
            styles.append(name)
        elif name in MOODS and name not in moods:
            moods.append(name)
    return styles[:5], moods[:5]


def _lastfm_tags(api, album):
    if not api or not album.artist.strip() or not album.title.strip():
        return [], []
    styles, moods = _select_tags(api.request('album.getTopTags',
        {'artist': album.artist, 'album': album.title, 'autocorrect': 1}))
    if not styles and not moods:
        styles, moods = _select_tags(api.request('artist.getTopTags',
            {'artist': album.artist, 'autocorrect': 1}))
    return styles, moods


def _artist_path(client, section, artist):
    value = str(section) + '\0' + artist.strip().casefold()
    return LocalCache(client).root / 'artist-chart' / (hashlib.sha256(value.encode()).hexdigest() + '.json')


def _plex_artist_tags(client, album):
    key = canonical_album_key(album.key)
    if getattr(client, 'is_local', False) or not re.fullmatch(r'/library/metadata/\d+', key):
        return [], []
    node = client.xml(key).find('Directory')
    if node is None:
        return [], []
    parent = node.get('parentKey', '')
    if not re.fullmatch(r'/library/metadata/\d+', parent):
        return [], []
    artist = client.xml(parent).find('Directory')
    if artist is None:
        return [], []
    title = artist.get('title', '').strip()
    if title and title.casefold() != album.artist.strip().casefold():
        return [], []
    def read(kind):
        return [x.get('tag', '').strip() for x in artist.findall(kind) if x.get('tag', '').strip()]
    styles = read('Style') or [v for v in read('Genre') if v.casefold() not in BROAD]
    return styles[:5], read('Mood')[:5]


def _invalidate_map(client, section):
    path = LocalCache(client).root / 'album-map' / (hashlib.sha256(str(section).encode()).hexdigest() + '.json')
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def chart_artist(client, section, album, api):
    """Chart the album artist once, for all current and future matching albums."""
    artist = (album.artist or '').strip()
    if artist.casefold() in ('', 'unknown artist', 'various artists'):
        return None
    styles, moods, sources, failures = [], [], [], 0
    try:
        styles, moods = _plex_artist_tags(client, album)
        if styles or moods:
            sources.append('Plex')
    except Exception:
        failures += 1
    if api:
        try:
            remote_styles, remote_moods = _select_tags(api.request(
                'artist.getTopTags', {'artist': artist, 'autocorrect': 1}))
            if remote_styles or remote_moods:
                sources.append('Last.fm')
                styles, moods = remote_styles or styles, remote_moods or moods
        except Exception:
            failures += 1
    if not styles and not moods:
        if failures:
            raise ChartLookupError('Could not retrieve artist metadata. Check your connection and try again.')
        return None
    result = {'version': 1, 'artist': artist.casefold(), 'styles': styles[:5], 'moods': moods[:5],
              'sources': sources, 'updated_ns': time.time_ns()}
    _write_bytes(_artist_path(client, section, artist), json.dumps(result, ensure_ascii=False).encode())
    _invalidate_map(client, section)
    return result


def chart_album(client, section, album, api):
    """Fetch just this album on demand; never write tags to Plex or music files."""
    styles, moods, sources = [], [], []
    failures = 0
    try:
        styles, moods = _plex_tags(client, album)
        if styles or moods:
            sources.append('Plex')
    except Exception:
        failures += 1
    try:
        remote_styles, remote_moods = _lastfm_tags(api, album)
        if remote_styles or remote_moods:
            sources.append('Last.fm')
            styles = remote_styles or styles
            moods = remote_moods or moods
    except Exception:
        failures += 1
    if not styles and not moods:
        if failures:
            raise ChartLookupError('Could not retrieve album metadata. Check your connection and try again.')
        return None
    result = {'version': 1, 'key': canonical_album_key(album.key), 'styles': styles[:5],
              'moods': moods[:5], 'sources': sources, 'updated_ns': time.time_ns()}
    _write_bytes(_path(client, section, album.key), json.dumps(result, ensure_ascii=False).encode())
    _invalidate_map(client, section)
    return result


def cached_charts(client, section, albums):
    """Use the latest artist or album chart, scoped to this library."""
    albums = list(albums)
    root = LocalCache(client).root
    expected = {_path(client, section, album.key).name: canonical_album_key(album.key) for album in albums}
    artists = {(album.artist or '').strip().casefold() for album in albums}
    artists.discard('')
    expected_artists = {_artist_path(client, section, name).name: name for name in artists}
    by_album, by_artist = {}, {}
    def read(folder, expected_names, identity, destination):
        if not folder.is_dir():
            return
        for path in folder.glob('*.json'):
            key = expected_names.get(path.name)
            if not key:
                continue
            try:
                if path.stat().st_size > 16384:
                    continue
                value = json.loads(path.read_text(encoding='utf-8'))
                styles, moods, updated = value['styles'], value['moods'], value.get('updated_ns', 0)
                if (value.get('version') != 1 or value.get(identity) != key or
                    type(updated) is not int or updated < 0 or
                    not all(isinstance(items, list) and len(items) <= 5 and
                            all(isinstance(item, str) and 0 < len(item) <= 100 for item in items)
                            for items in (styles, moods))):
                    continue
                destination[key] = (updated, {'chart_style': styles, 'chart_mood': moods})
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
    read(root / 'album-chart', expected, 'key', by_album)
    read(root / 'artist-chart', expected_artists, 'artist', by_artist)
    result = {}
    for album in albums:
        key = canonical_album_key(album.key)
        artist = (album.artist or '').strip().casefold()
        choices = [chart for chart in (by_album.get(key), by_artist.get(artist)) if chart is not None]
        if choices:
            result[key] = max(choices, key=lambda chart: chart[0])[1]
    return result
