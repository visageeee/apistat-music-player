"""Find related library albums from Last.fm track recommendations."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import time

import lastfm
from local_cache import LocalCache, _write_bytes
from similar_recommendations import _normal, _recommendations, library_catalog

CACHE_AGE = 24 * 60 * 60
MAX_RESULTS = 10
MAX_SEEDS = 4


def representative_tracks(tracks, limit=MAX_SEEDS):
    tracks = [track for track in tracks if track.artist and track.title]
    if len(tracks) <= limit:
        return tracks
    return [tracks[round(i * (len(tracks) - 1) / (limit - 1))] for i in range(limit)]


def canonical_album_key(key):
    """Plex albums use /children; track parentKey names the same metadata item."""
    if re.fullmatch(r'/library/metadata/\d+/children', key or ''):
        return key[:-len('/children')]
    return key


def rank_albums(seed_album, album_catalog, library_tracks, recommendation_lists, limit=MAX_RESULTS):
    """Score distinct seed-track matches, retaining Last.fm's result ordering."""
    seed_artist = _normal(seed_album.artist)
    seed_key = canonical_album_key(seed_album.key)
    albums = {album.key: album for album in album_catalog
              if canonical_album_key(album.key) != seed_key and
              _normal(album.artist) != seed_artist and album.artist}
    by_parent = {canonical_album_key(key): key for key in albums}
    by_name = defaultdict(list)
    for key, album in albums.items():
        by_name[(_normal(album.artist), _normal(album.title))].append(key)
    index = defaultdict(list)
    for track in library_tracks:
        album_key = by_parent.get(canonical_album_key(track.album_key))
        if not album_key:
            candidates = by_name.get((_normal(track.album_artist or track.artist),
                                      _normal(track.album)), ())
            # Avoid assigning tracks to the wrong edition when names are ambiguous.
            if len(candidates) == 1:
                album_key = candidates[0]
        if album_key and track.artist and track.title and _normal(track.artist) != seed_artist:
            index[(_normal(track.artist), _normal(track.title))].append(album_key)
    scores, hits = defaultdict(float), defaultdict(int)
    for names in recommendation_lists:
        best = {}
        for rank, name in enumerate(names):
            for album_key in index.get(name, ()):
                score = 1.0 / (1.0 + rank / 20.0)
                best[album_key] = max(best.get(album_key, 0), score)
        for album_key, score in best.items():
            scores[album_key] += score
            hits[album_key] += 1
    ordered = sorted(scores, key=lambda key: (-hits[key], -scores[key],
                                               _normal(albums[key].artist), _normal(albums[key].title)))
    selected, artists = [], defaultdict(int)
    for key in ordered:
        album = albums[key]
        artist = _normal(album.artist)
        if artists[artist] >= 2:
            continue
        artists[artist] += 1
        selected.append(album)
        if len(selected) >= limit:
            break
    return selected


def artist_fallback(api, seed_album, album_catalog, limit=MAX_RESULTS):
    """Use Last.fm's similar artists when no recommended tracks match locally."""
    result = api.request('artist.getSimilar', {'artist': seed_album.artist,
                                              'autocorrect': 1, 'limit': 200})
    try:
        artists = result['similarartists']['artist']
    except (KeyError, TypeError):
        return []
    if not isinstance(artists, list):
        return []
    seed_artist = _normal(seed_album.artist)
    by_artist = defaultdict(list)
    for album in album_catalog:
        name = _normal(album.artist)
        if name and name != seed_artist and canonical_album_key(album.key) != canonical_album_key(seed_album.key):
            by_artist[name].append(album)
    selected, seen = [], set()
    for artist in artists:
        name = _normal(artist.get('name', '')) if isinstance(artist, dict) else ''
        if not name or name in seen:
            continue
        seen.add(name)
        # Keep the web varied and prefer recently added albums for the same artist.
        candidates = sorted(by_artist.get(name, ()), key=lambda album: (-album.added_at, _normal(album.title)))
        selected.extend(candidates[:2])
        if len(selected) >= limit:
            break
    return selected[:limit]


def cache_path(client, section, album):
    name = hashlib.sha256((str(section) + '\0' + album.key).encode('utf-8')).hexdigest()
    return LocalCache(client).root / 'album-web' / (name + '.json')


def read_cache(client, section, album, catalog):
    try:
        path = cache_path(client, section, album)
        if path.stat().st_size > 16384:
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        if (data.get('version') != 2 or type(data.get('time')) not in (int, float) or
                not 0 <= time.time() - data['time'] < CACHE_AGE or
                not isinstance(data.get('albums'), list) or not data['albums'] or len(data['albums']) > MAX_RESULTS or
                not all(isinstance(key, str) for key in data['albums'])):
            return None
        index = {candidate.key: candidate for candidate in catalog
                 if canonical_album_key(candidate.key) != canonical_album_key(album.key) and candidate.artist and
                 _normal(candidate.artist) != _normal(album.artist)}
        # An outdated index may omit an album; rebuild rather than serve stale references.
        if any(key not in index for key in data['albums']):
            return None
        return [index[key] for key in data['albums']]
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def related_albums(client, section, album, album_catalog, credentials, refresh=False):
    if not refresh:
        cached = read_cache(client, section, album, album_catalog)
        if cached is not None:
            return cached
    if not credentials:
        raise lastfm.LastFMError('Last.fm application credentials are not available in this build.')
    if not album.artist:
        return []
    seeds = representative_tracks(client.tracks(album))
    if not seeds:
        return []
    def lookup(track):
        return _recommendations(lastfm.LastFM(*credentials), track, refresh=refresh)
    with ThreadPoolExecutor(max_workers=len(seeds), thread_name_prefix='album-web') as pool:
        futures = [pool.submit(lookup, track) for track in seeds]
        results, errors = [], []
        for future in futures:
            try:
                results.append(future.result())
            except lastfm.LastFMError as error:
                errors.append(error)
    if errors and not results:
        raise lastfm.LastFMError('Could not load Last.fm recommendations. Try again.')
    library_tracks = library_catalog(client, section) if any(results) else []
    albums = rank_albums(album, album_catalog, library_tracks, results)
    if not albums:
        albums = artist_fallback(lastfm.LastFM(*credentials), album, album_catalog)
    # Avoid persisting incomplete results when a subset of the requests failed.
    if not errors and albums:
        try:
            _write_bytes(cache_path(client, section, album), json.dumps(
                {'version': 2, 'time': time.time(), 'albums': [item.key for item in albums]}).encode('utf-8'))
        except OSError:
            pass
    return albums
