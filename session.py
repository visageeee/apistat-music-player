"""Persist the window and playback session without storing credentials."""

import json
import os
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

import gi
from gi.repository import GLib

from plex_client import Item


SESSION_PATH = Path(GLib.get_user_config_dir()) / 'apistat' / 'session.json'
PANELS = {'now', 'albums', 'library', 'styles', 'queue', 'lyrics', 'time', 'settings'}
SORTS = {'addedAt:desc', 'titleSort', 'artist.titleSort,titleSort'}


def item_to_data(item):
    return asdict(item)


def serialize_snapshot(snapshot):
    """Convert captured track objects away from the GTK thread."""
    data = dict(snapshot)
    if 'history' in data:
        data['history'] = [item_to_data(item) if isinstance(item, Item) else item
                           for item in data['history']]
    if isinstance(data.get('album_detail'), Item):
        data['album_detail'] = item_to_data(data['album_detail'])
    if 'playback' in data:
        playback = dict(data['playback'])
        playback['queue'] = [item_to_data(item) if isinstance(item, Item) else item
                             for item in playback['queue']]
        if isinstance(playback.get('album'), Item):
            playback['album'] = item_to_data(playback['album'])
        data['playback'] = playback
    return data


def item_from_data(data):
    if not isinstance(data, dict) or not isinstance(data.get('key'), str):
        return None
    if not data['key'].startswith('/') or not isinstance(data.get('title'), str):
        return None
    fields = {}
    for name in ('artist', 'year', 'album', 'number', 'thumb', 'album_key', 'album_thumb', 'genre', 'mood',
                 'label', 'album_artist', 'release_date', 'codec'):
        value = data.get(name, '')
        if not isinstance(value, str):
            return None
        fields[name] = value
    duration = data.get('duration', 0)
    if type(duration) is not int or duration < 0:
        return None
    added_at = data.get('added_at', 0)
    if type(added_at) is not int or added_at < 0:
        return None
    numbers = {}
    for name in ('disc', 'track_number', 'last_played_at', 'play_count', 'bitrate'):
        value = data.get(name, 0)
        if type(value) is not int or value < 0:
            return None
        numbers[name] = value
    user_rating = data.get('user_rating', 0.0)
    if type(user_rating) not in (int, float) or not 0 <= user_rating <= 10:
        return None
    return Item(data['key'], data['title'], duration=duration, added_at=added_at,
                user_rating=float(user_rating), **fields, **numbers)


def load_session():
    try:
        data = json.loads(SESSION_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        return {}
    window = data.get('window')
    if not isinstance(window, dict):
        window = {}
    width, height = window.get('width'), window.get('height')
    if type(width) is not int or not 640 <= width <= 8192:
        width = 1080
    if type(height) is not int or not 480 <= height <= 8192:
        height = 720
    panel = data.get('panel')
    result = {'window': {'width': width, 'height': height,
                         'maximized': window.get('maximized') is True},
              'panel': panel if isinstance(panel, str) and panel in PANELS else 'albums'}
    dates = data.get('time_machine_dates')
    if isinstance(dates, dict):
        try:
            start = date.fromisoformat(dates['from'])
            end = date.fromisoformat(dates['to'])
            if 1970 <= start.year <= 9998 and 1970 <= end.year <= 9998:
                result['time_machine_dates'] = {'from': start, 'to': end}
        except (KeyError, TypeError, ValueError):
            pass
    if data.get('settings_page') in ('main', 'shortcuts'):
        result['settings_page'] = data['settings_page']
    if type(data.get('settings_tab')) is int and 0 <= data['settings_tab'] <= 4:
        result['settings_tab'] = data['settings_tab']
    for name in ('server', 'section', 'playlist'):
        if isinstance(data.get(name), str):
            result[name] = data[name]
    history = data.get('history')
    if isinstance(history, list) and len(history) <= 200:
        tracks = [item_from_data(item) for item in history]
        if all(tracks):
            result['history'] = tracks
    sort = data.get('song_sort')
    if isinstance(sort, str) and sort in SORTS:
        result['song_sort'] = sort
    album = item_from_data(data.get('album_detail'))
    if album:
        result['album_detail'] = album
    playback = data.get('playback')
    if isinstance(playback, dict) and isinstance(result.get('server'), str):
        queue = playback.get('queue')
        index = playback.get('index')
        position = playback.get('position_ms', 0)
        if (isinstance(queue, list) and queue and len(queue) <= 20000
                and type(index) is int and 0 <= index < len(queue)
                and type(position) is int and 0 <= position <= 86400000):
            tracks = [item_from_data(item) for item in queue]
            if all(tracks):
                result['playback'] = {
                    'queue': tracks, 'index': index, 'position_ms': position,
                    'album': item_from_data(playback.get('album')),
                    'shuffle': playback.get('shuffle') is True,
                    'repeat': playback.get('repeat') is True,
                }
    return result


def save_session(data):
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.session-', dir=SESSION_PATH.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output)
        os.replace(temporary, SESSION_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
