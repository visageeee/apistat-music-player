"""Resolve Last.fm track recommendations to tracks in the active library."""
from collections import OrderedDict
import threading
import time
import unicodedata

import lastfm
from local_cache import LocalCache
from play_queue import select_similar_tracks

_CACHE = OrderedDict()
_LOCK = threading.Lock()
_TTL = 86400


def _normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def _recommendations(api, seed, refresh=False):
    key = (_normal(seed.artist), _normal(seed.title))
    if not all(key):
        return []
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if not refresh and cached and now - cached[0] < _TTL:
            _CACHE.move_to_end(key)
            return cached[1]
    result = api.request('track.getSimilar', {'artist': seed.artist, 'track': seed.title,
                                               'autocorrect': 1, 'limit': 200})
    try:
        entries = result['similartracks']['track']
    except (KeyError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    matches = []
    for track in entries:
        if not isinstance(track, dict) or not isinstance(track.get('artist'), dict):
            continue
        artist, title = track['artist'].get('name'), track.get('name')
        if isinstance(artist, str) and isinstance(title, str) and artist.strip() and title.strip():
            matches.append((_normal(artist), _normal(title)))
    with _LOCK:
        _CACHE[key] = (now, matches)
        _CACHE.move_to_end(key)
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    return matches


def library_catalog(client, section):
    if getattr(client, 'is_local', False):
        return client.recommendation_catalog()
    cache = LocalCache(client)
    cached = cache.read_song_index(section, max_age=None)
    if cached is not None:
        return cached
    tracks = []
    while True:
        page, total = client.songs(section, start=len(tracks))
        if not page:
            break
        tracks.extend(page)
        if len(tracks) >= total:
            break
    return tracks


def similar_tracks(client, section, seed, credentials, excluded=(), limit=10):
    if not credentials or not section or not seed.artist or not seed.title:
        return []
    api = lastfm.LastFM(*credentials)
    names = _recommendations(api, seed)
    if not names:
        return []
    index = {}
    excluded = set(excluded)
    excluded.add(seed.key)
    for track in library_catalog(client, section):
        if track.key not in excluded and track.artist and track.title:
            index.setdefault((_normal(track.artist), _normal(track.title)), track)
    candidates = [index[name] for name in names if name in index]
    return select_similar_tracks(seed, candidates, limit=limit)
