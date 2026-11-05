"""Match Last.fm listening history to tracks in the active music library."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import unicodedata

from plex_client import Item


def timestamps(start, end):
    """Inclusive local calendar days, converted to Last.fm's UTC seconds."""
    if not isinstance(start, date) or not isinstance(end, date) or end < start:
        raise ValueError('Choose a valid date range with the end after the start.')
    first = int(datetime.combine(start, time.min).astimezone().timestamp())
    after = int(datetime.combine(end + timedelta(days=1), time.min).astimezone().timestamp())
    return first, after


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def partition_history(history, catalog):
    """Return matched songs and the original listens that could not be matched."""
    by_track = defaultdict(list)
    for song in catalog:
        by_track[(normalized(song.artist), normalized(song.title))].append(song)
    matched, missing = [], []
    for listen in history:
        candidates = by_track.get((normalized(listen['artist']), normalized(listen['title'])), [])
        album = normalized(listen.get('album', ''))
        exact = [song for song in candidates if normalized(song.album) == album] if album else []
        options = exact or (candidates if not album else [])
        if len(options) == 1:
            matched.append(options[0])
        else:
            missing.append(listen)
    return matched, missing


def match_history(history, catalog):
    """Avoid guessing if an artist/title maps to multiple distinct recordings."""
    matched, missing = partition_history(history, catalog)
    return matched, len(missing)


def albums_for_history(tracks):
    albums, counts = {}, Counter()
    for track in tracks:
        key = track.album_key
        if not key:
            continue
        counts[key] += 1
        if key not in albums:
            albums[key] = Item(key, track.album or 'Untitled album',
                               artist=track.album_artist or track.artist,
                               thumb=track.album_thumb or track.thumb,
                               year=track.year, added_at=track.added_at)
    return [albums[key] for key in sorted(albums, key=lambda key: -counts[key])]
