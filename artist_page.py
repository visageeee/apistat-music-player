"""Artist-page data selection and on-demand metadata lookup."""
import re
from html.parser import HTMLParser

from plex_client import Item
from similar_recommendations import _normal


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.skip += 1
        elif tag in ('p', 'br') and not self.skip:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'a' and self.skip:
            self.skip -= 1
        elif tag == 'p' and not self.skip:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def full_description(value):
    parser = _PlainText()
    parser.feed(str(value or ''))
    text = ''.join(parser.parts)
    lines = [' '.join(line.split()) for line in text.splitlines()]
    return '\n\n'.join(line for line in lines if line)


def short_description(value, limit=360):
    text = full_description(value)
    if len(text) > limit:
        text = text[:limit - 1].rsplit(' ', 1)[0] + '…'
    return text


def plex_album_description(client, album):
    key = re.sub(r'/children$', '', album.key or '')
    if not re.fullmatch(r'/library/metadata/\d+', key):
        return ''
    node = client.xml(key).find('Directory')
    return full_description(node.get('summary', '')) if node is not None else ''


def artist_library(artist, albums, tracks):
    name = _normal(artist)
    records = [album for album in albums if _normal(album.artist) == name]
    records.sort(key=lambda album: (-(int(album.year) if str(album.year).isdigit() else -1),
                                    _normal(album.title)))
    songs = [song for song in tracks if _normal(song.artist) == name]
    songs.sort(key=lambda song: (-song.play_count, -song.user_rating, _normal(song.title)))
    return records, songs


def popular_tracks(songs, response, limit=8):
    """Match Last.fm's popularity order to tracks that are playable locally."""
    try:
        entries = response['toptracks']['track']
    except (KeyError, TypeError):
        entries = []
    if not isinstance(entries, list):
        entries = []
    by_name = {}
    for song in songs:
        by_name.setdefault(_normal(song.title), song)
    selected, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            continue
        song = by_name.get(_normal(entry['name']))
        if song and song.key not in seen:
            selected.append(song)
            seen.add(song.key)
            if len(selected) >= limit:
                break
    return selected


def plex_artist_profile(client, track, name):
    """Fetch a Plex artist's summary and artwork through validated Plex paths."""
    if not track or not re.fullmatch(r'/library/metadata/\d+', track.key or ''):
        return '', None
    node = client.xml(track.key).find('Track')
    if node is None or _normal(node.get('grandparentTitle', '')) != _normal(name):
        return '', None
    key = node.get('grandparentKey', '')
    if not re.fullmatch(r'/library/metadata/\d+', key):
        return '', None
    artist = client.xml(key).find('Directory')
    if artist is None:
        return '', None
    thumb = artist.get('thumb', '')
    return artist.get('summary', ''), Item(key, name, artist=name, thumb=thumb) if thumb else None
