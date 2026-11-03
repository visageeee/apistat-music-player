"""Private, server-scoped disk caches for artwork, gradients, and album search."""

import hashlib
import json
import os
import re
import struct
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import cairo
from gi.repository import GLib

from plex_client import Item, ALBUM_SORT_ARTIST
from music_facets import MusicFacet


CACHE_ROOT = Path(GLib.get_user_cache_dir()) / 'plex-music-prototype'
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _hash(*parts):
    return hashlib.sha256('\0'.join(map(str, parts)).encode('utf-8')).hexdigest()


def _write_bytes(path, data, still_current=None, commit_lock=None):
    _private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.cache-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        def commit():
            if still_current is not None and not still_current():
                return False
            os.replace(temporary, path)
            return True
        if commit_lock is None:
            return commit()
        with commit_lock:
            return commit()
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _private_dir(directory):
    CACHE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CACHE_ROOT, 0o700)
    current = CACHE_ROOT
    for part in directory.relative_to(CACHE_ROOT).parts:
        current = current / part
        current.mkdir(exist_ok=True, mode=0o700)
        os.chmod(current, 0o700)


class LocalCache:
    def __init__(self, client):
        self.root = CACHE_ROOT / _hash(client.address, client.token)[:24]

    def art_path(self, thumb, size):
        return self.root / 'art' / (_hash(thumb, size) + '.img')

    def read_art(self, thumb, size):
        try:
            return self.art_path(thumb, size).read_bytes()
        except OSError:
            return None

    def save_art(self, thumb, size, data):
        _write_bytes(self.art_path(thumb, size), data)

    def palette_path(self, thumb):
        return self.root / 'palette' / (_hash(thumb) + '.json')

    def read_palette(self, thumb):
        try:
            data = json.loads(self.palette_path(thumb).read_text(encoding='utf-8'))
            if (all(isinstance(data.get(name), list) and len(data[name]) == 2 and
                    all(isinstance(color, str) and COLOR_RE.fullmatch(color)
                        for color in data[name]) for name in ('gradient', 'waveform'))):
                return tuple(data['gradient']), tuple(data['waveform'])
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def save_palette(self, thumb, gradient, waveform):
        data = json.dumps({'gradient': gradient, 'waveform': waveform}).encode('utf-8')
        _write_bytes(self.palette_path(thumb), data)

    def waveform_path(self, key, duration):
        return self.root / 'waveforms' / (_hash(key, duration) + '.peaks')

    def read_waveform(self, key, duration):
        try:
            data = self.waveform_path(key, duration).read_bytes()
            if len(data) != 512 * 4:
                return None
            peaks = struct.unpack('!512f', data)
            return list(peaks) if all(0 <= peak <= 1 for peak in peaks) else None
        except (OSError, ValueError, struct.error):
            return None

    def save_waveform(self, key, duration, peaks):
        if len(peaks) != 512 or not all(0 <= peak <= 1 for peak in peaks):
            raise ValueError('Invalid waveform peaks')
        _write_bytes(self.waveform_path(key, duration), struct.pack('!512f', *peaks))

    def index_path(self, section):
        return self.root / 'index' / (_hash(section) + '.json')

    def read_index(self, section):
        try:
            data = json.loads(self.index_path(section).read_text(encoding='utf-8'))
            if data.get('version') != 1 or data.get('section') != section:
                return None
            albums = []
            for value in data['albums']:
                if (not isinstance(value, dict) or not isinstance(value.get('key'), str)
                        or not value['key'].startswith('/') or
                        not isinstance(value.get('title'), str)):
                    return None
                albums.append(Item(**value))
            return albums
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def save_index(self, section, albums):
        data = {'version': 1, 'section': section, 'built_at': int(time.time()),
                'albums': [asdict(album) for album in albums]}
        _write_bytes(self.index_path(section), json.dumps(data).encode('utf-8'))

    def album_page_path(self, section, sort):
        return self.root / 'album-pages' / (_hash(section, sort) + '.json')

    def read_album_page(self, section, sort, max_age=3600):
        try:
            data = json.loads(self.album_page_path(section, sort).read_text(encoding='utf-8'))
            if (data.get('version') != 1 or data.get('section') != section or
                    data.get('sort') != sort or
                    time.time() - data.get('built_at', 0) > max_age or
                    type(data.get('total')) is not int or data['total'] < 0 or
                    not isinstance(data.get('albums'), list)):
                return None
            albums = []
            for value in data['albums']:
                if (not isinstance(value, dict) or
                        not isinstance(value.get('key'), str) or
                        not value['key'].startswith('/library/metadata/') or
                        not isinstance(value.get('title'), str)):
                    return None
                albums.append(Item(**value))
            return albums, data['total']
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def save_album_page(self, section, sort, albums, total):
        data = {'version': 1, 'section': section, 'sort': sort,
                'built_at': int(time.time()), 'total': total,
                'albums': [asdict(album) for album in albums]}
        _write_bytes(self.album_page_path(section, sort),
                     json.dumps(data, separators=(',', ':')).encode('utf-8'))

    def song_index_path(self, section, playlist_key=None):
        return self.root / 'songs' / (_hash(section, playlist_key or '') + '.json')

    def music_facets_path(self, section):
        return self.root / 'facets' / (_hash(section) + '.json')

    def music_facet_cover_path(self, section, facet_key):
        return self.root / 'facet-covers' / (_hash(section, facet_key) + '.json')

    def read_music_facet_cover(self, section, facet_key, max_age=604800):
        try:
            data = json.loads(self.music_facet_cover_path(
                section, facet_key).read_text(encoding='utf-8'))
            cover = data.get('cover')
            if (data.get('version') == 1 and data.get('section') == section and
                    data.get('facet') == facet_key and
                    time.time() - data.get('built_at', 0) <= max_age and
                    isinstance(cover, str) and
                    (not cover or cover.startswith('/') and not cover.startswith('//'))):
                return cover
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def save_music_facet_cover(self, section, facet_key, cover):
        if not isinstance(cover, str) or (cover and
                (not cover.startswith('/') or cover.startswith('//'))):
            raise ValueError('Invalid Plex artwork path')
        _write_bytes(self.music_facet_cover_path(section, facet_key),
                     json.dumps({'version': 1, 'section': section, 'facet': facet_key,
                                 'built_at': int(time.time()), 'cover': cover}).encode('utf-8'))

    def read_music_facets(self, section, max_age=3600):
        try:
            data = json.loads(self.music_facets_path(section).read_text(encoding='utf-8'))
            if (data.get('version') != 1 or data.get('section') != section or
                    time.time() - data.get('built_at', 0) > max_age):
                return None
            return tuple(MusicFacet(value['field'], value['title'],
                                    tuple(tuple(pair) for pair in value['filters']))
                         for value in data['facets'])
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def save_music_facets(self, section, facets):
        data = {'version': 1, 'section': section, 'built_at': int(time.time()),
                'facets': [asdict(facet) for facet in facets]}
        _write_bytes(self.music_facets_path(section),
                     json.dumps(data, separators=(',', ':')).encode('utf-8'))

    def read_song_index_entry(self, section, playlist_key=None):
        try:
            data = json.loads(self.song_index_path(section, playlist_key).read_text(encoding='utf-8'))
            version = 4 if isinstance(playlist_key, str) and playlist_key.startswith('facet:') else 3
            if (data.get('version') != version or data.get('section') != section or
                    data.get('playlist') != playlist_key or
                    not isinstance(data.get('built_at'), (int, float))):
                return None
            songs = []
            for value in data['songs']:
                if (not isinstance(value, dict) or
                        not isinstance(value.get('key'), str) or
                        not value['key'].startswith('/library/metadata/') or
                        not isinstance(value.get('title'), str)):
                    return None
                songs.append(Item(**value))
            return songs, data['built_at']
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def read_song_index(self, section, playlist_key=None, max_age=3600):
        entry = self.read_song_index_entry(section, playlist_key)
        if entry is None:
            return None
        songs, built_at = entry
        if max_age is not None and time.time() - built_at > max_age:
            return None
        return songs

    def save_song_index(self, section, songs, playlist_key=None, built_at=None,
                        still_current=None, commit_lock=None):
        version = 4 if isinstance(playlist_key, str) and playlist_key.startswith('facet:') else 3
        data = {'version': version, 'section': section, 'playlist': playlist_key,
                'built_at': int(time.time()) if built_at is None else built_at,
                'songs': [asdict(song) for song in songs]}
        return _write_bytes(self.song_index_path(section, playlist_key),
                            json.dumps(data, separators=(',', ':')).encode('utf-8'),
                            still_current, commit_lock)

    def clear_indices(self):
        directory = self.root / 'index'
        if directory.is_dir():
            for path in directory.glob('*.json'):
                path.unlink(missing_ok=True)


def search_albums(albums, query, start=0, page_size=100):
    needle = query.casefold().strip()
    matching = [album for album in albums if needle in album.title.casefold() or
                needle in album.artist.casefold()]
    return matching[start:start + page_size], len(matching)


def sort_albums(albums, sort):
    if sort == 'addedAt:desc':
        return sorted(albums, key=lambda album: (-album.added_at, album.title.casefold()))
    if sort == 'year:desc':
        return sorted(albums, key=lambda album: (
            -(int(album.year) if str(album.year).isdigit() else 0),
            album.artist.casefold(), album.title.casefold()))
    if sort == ALBUM_SORT_ARTIST:
        return sorted(albums, key=lambda album: (album.artist.casefold(), album.title.casefold()))
    if sort == 'titleSort':
        return sorted(albums, key=lambda album: (album.title.casefold(), album.artist.casefold()))
    raise ValueError('Unsupported album sort')


def cached_album_page(cache, client, section, sort):
    page = cache.read_album_page(section, sort)
    if page is not None:
        return page
    page = client.albums(section, sort=sort)
    try:
        cache.save_album_page(section, sort, *page)
    except OSError:
        pass
    return page


def build_album_index(client, section, valid=lambda: True):
    albums = []
    start = 0
    while valid():
        page, total = client.albums(section, start)
        albums.extend(page)
        start += len(page)
        if not page or start >= total:
            return albums
    return None


def gradient_path(colors, width, height):
    return CACHE_ROOT / 'gradients' / (_hash(*colors, width, height) + '.png')


def read_gradient(colors, width, height):
    try:
        return cairo.ImageSurface.create_from_png(str(gradient_path(colors, width, height)))
    except (OSError, cairo.Error):
        return None


def save_gradient(colors, width, height, surface):
    path = gradient_path(colors, width, height)
    _private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.gradient-', dir=path.parent)
    os.close(fd)
    try:
        surface.write_to_png(temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
