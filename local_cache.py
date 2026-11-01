"""Private, server-scoped disk caches for artwork, gradients, and album search."""

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import cairo
from gi.repository import GLib

from plex_client import Item


CACHE_ROOT = Path(GLib.get_user_cache_dir()) / 'plex-music-prototype'
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _hash(*parts):
    return hashlib.sha256('\0'.join(map(str, parts)).encode('utf-8')).hexdigest()


def _write_bytes(path, data):
    _private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.cache-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        os.replace(temporary, path)
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

    def song_index_path(self, section, playlist_key=None):
        return self.root / 'songs' / (_hash(section, playlist_key or '') + '.json')

    def read_song_index(self, section, playlist_key=None):
        try:
            data = json.loads(self.song_index_path(section, playlist_key).read_text(encoding='utf-8'))
            if (data.get('version') != 3 or data.get('section') != section or
                    data.get('playlist') != playlist_key):
                return None
            songs = []
            for value in data['songs']:
                if (not isinstance(value, dict) or
                        not isinstance(value.get('key'), str) or
                        not value['key'].startswith('/library/metadata/') or
                        not isinstance(value.get('title'), str)):
                    return None
                songs.append(Item(**value))
            return songs
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    def save_song_index(self, section, songs, playlist_key=None):
        data = {'version': 3, 'section': section, 'playlist': playlist_key,
                'built_at': int(time.time()), 'songs': [asdict(song) for song in songs]}
        _write_bytes(self.song_index_path(section, playlist_key),
                     json.dumps(data, separators=(',', ':')).encode('utf-8'))

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
