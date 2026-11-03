"""Look up a track's plain or synchronized lyrics from LRCLIB."""

from dataclasses import dataclass
import json
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Lyrics:
    text: str = ''
    lines: tuple = ()  # (seconds, text), sorted by timestamp
    instrumental: bool = False
    source: str = 'LRCLIB'


class LyricsLookupError(Exception):
    pass


def lyrics_error_message(error):
    """Describe lookup failures without exposing URLs or request metadata."""
    if isinstance(error, LyricsLookupError):
        return str(error)
    if isinstance(error, HTTPError):
        if error.code == 429:
            return 'LRCLIB is receiving too many requests. Wait a moment, then refresh.'
        if error.code == 503:
            return 'LRCLIB is temporarily unavailable (HTTP 503). Try refreshing later.'
        if error.code in (401, 403):
            return f'LRCLIB refused the request (HTTP {error.code}). Try again later.'
        return f'LRCLIB returned HTTP {error.code}. Try refreshing later.'
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'The connection to LRCLIB timed out. Check your connection and refresh.'
    if isinstance(reason, ssl.SSLError):
        return 'A secure connection to LRCLIB could not be established. Check your network and certificates.'
    if isinstance(error, (URLError, OSError)):
        return 'Could not connect to LRCLIB. Check your internet connection and refresh.'
    if isinstance(error, (ValueError, UnicodeError)):
        return 'LRCLIB returned an invalid response. Try refreshing later.'
    return 'The lyrics lookup failed unexpectedly. Try refreshing later.'


_STAMP = re.compile(r'\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]')


def parse_lrc(text):
    lines = []
    for raw in text.splitlines():
        stamps = list(_STAMP.finditer(raw))
        if not stamps:
            continue
        words = _STAMP.sub('', raw).strip()
        for stamp in stamps:
            minutes, seconds, fraction = stamp.groups()
            if int(seconds) >= 60:
                continue
            fraction = (fraction or '').ljust(3, '0')
            lines.append((int(minutes) * 60 + int(seconds) + int(fraction or '0') / 1000,
                          words))
    return tuple(sorted(lines, key=lambda line: line[0]))


def lookup_lyrics(title, artist, album='', duration_ms=0, opener=urlopen):
    if not title.strip() or not artist.strip():
        return None
    params = {'track_name': title.strip(), 'artist_name': artist.strip()}
    if album.strip():
        params['album_name'] = album.strip()
    if 1000 <= duration_ms <= 3600000:
        params['duration'] = round(duration_ms / 1000)
    request = Request('https://lrclib.net/api/get?' + urlencode(params),
                      headers={'User-Agent': 'Apistat/1.0 (https://github.com/visageeee/plex-music-prototype)',
                               'Accept': 'application/json'})
    try:
        with opener(request, timeout=8) as response:
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ValueError('Lyrics response is too large')
        data = json.loads(payload)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not isinstance(data, dict):
        raise ValueError('Invalid lyrics response')
    if data.get('instrumental') is True:
        return Lyrics(instrumental=True)
    synced = data.get('syncedLyrics')
    plain = data.get('plainLyrics')
    lines = parse_lrc(synced) if isinstance(synced, str) else ()
    text = '\n'.join(line for _time, line in lines) if lines else (
        plain.strip() if isinstance(plain, str) else '')
    return Lyrics(text=text, lines=lines) if text else None


def lookup_lyrics_ovh(title, artist, opener=urlopen):
    if not title.strip() or not artist.strip():
        return None
    path = '/'.join(quote(value.strip(), safe='') for value in (artist, title))
    request = Request('https://api.lyrics.ovh/v1/' + path,
                      headers={'User-Agent': 'Apistat/1.0 (https://github.com/visageeee/plex-music-prototype)',
                               'Accept': 'application/json'})
    try:
        with opener(request, timeout=8) as response:
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ValueError('Lyrics response is too large')
        data = json.loads(payload)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not isinstance(data, dict):
        raise ValueError('Invalid lyrics response')
    text = data.get('lyrics')
    return Lyrics(text=text.strip(), source='lyrics.ovh') if isinstance(text, str) and text.strip() else None


def retry_after_seconds(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 1.0


class LyricsClient:
    """Serialize requests and respect LRCLIB's retry and throttling guidance."""

    def __init__(self):
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._not_before = 0.0
        self._retry_until = 0.0

    def lookup(self, title, artist, album='', duration_ms=0, valid=lambda: True):
        with self._lock:
            while not self._closed.is_set() and valid():
                remaining = self._not_before - time.monotonic()
                if remaining <= 0:
                    break
                self._closed.wait(min(remaining, 0.25))
            if self._closed.is_set() or not valid():
                return None
            primary_error = None
            result = None
            if time.monotonic() < self._retry_until:
                primary_error = 'LRCLIB is temporarily rate limited.'
            else:
                try:
                    result = lookup_lyrics(title, artist, album, duration_ms)
                except Exception as error:
                    primary_error = lyrics_error_message(error)
                    if isinstance(error, HTTPError) and error.code in (429, 503):
                        delay = retry_after_seconds(error.headers.get('Retry-After')
                                                    if error.headers else None)
                        self._retry_until = max(self._retry_until, time.monotonic() + delay)
                finally:
                    self._not_before = max(self._not_before, time.monotonic() + 0.3)
            if result is not None or self._closed.is_set() or not valid():
                return result
            try:
                result = lookup_lyrics_ovh(title, artist)
            except Exception as error:
                detail = lyrics_error_message(error).replace('LRCLIB', 'lyrics.ovh')
                raise LyricsLookupError((primary_error + '\n' if primary_error else '') + detail) from error
            if result is None and primary_error:
                raise LyricsLookupError(primary_error + '\nNo matching lyrics found on lyrics.ovh.')
            return result

    def close(self):
        self._closed.set()
