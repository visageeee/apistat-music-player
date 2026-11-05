"""Last.fm desktop authorization and scrobbling, without third-party dependencies."""
import hashlib
import json
import os
import sys
import time
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from plex_client import NoRedirect

if os.name == 'nt':
    from windows_vault import read_secret, write_secret, delete_secret
    Secret = None
elif sys.platform == 'darwin':
    from macos_vault import read_secret, write_secret, delete_secret
    Secret = None
else:
    import gi
    gi.require_version('Secret', '1')
    from gi.repository import Secret

SCHEMA = (Secret.Schema.new('org.apistat.lastfm', Secret.SchemaFlags.NONE,
                           {'application': Secret.SchemaAttributeType.STRING})
          if Secret is not None else None)
ATTRIBUTES = {'application': 'Apistat'}
TARGET = 'Apistat/LastFM'
API_URL = 'https://ws.audioscrobbler.com/2.0/'


try:
    from lastfm_build_credentials import API_KEY as BUILD_API_KEY, API_SECRET as BUILD_API_SECRET
except ImportError:
    BUILD_API_KEY = BUILD_API_SECRET = ''


def application_credentials():
    """Use Apistat's build credentials, with an optional developer override."""
    if 'APISTAT_LASTFM_API_KEY' in os.environ or 'APISTAT_LASTFM_API_SECRET' in os.environ:
        key = os.environ.get('APISTAT_LASTFM_API_KEY', '').strip()
        secret = os.environ.get('APISTAT_LASTFM_API_SECRET', '').strip()
    else:
        key, secret = BUILD_API_KEY.strip(), BUILD_API_SECRET.strip()
    return (key, secret) if key and secret else None


class LastFMError(Exception):
    pass


def load_session():
    raw = (read_secret(TARGET) if Secret is None else
           Secret.password_lookup_sync(SCHEMA, ATTRIBUTES, None))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if all(isinstance(data.get(key), str) and data[key] for key in
               ('api_key', 'secret', 'session', 'username')):
            return data
    except (ValueError, TypeError, AttributeError):
        pass
    raise LastFMError('Invalid saved Last.fm credentials.')


def save_session(data):
    raw = json.dumps(data)
    if Secret is None:
        write_secret(TARGET, raw)
    elif not Secret.password_store_sync(SCHEMA, ATTRIBUTES, Secret.COLLECTION_DEFAULT,
                                        'Apistat Last.fm', raw, None):
        raise LastFMError('Could not save Last.fm credentials in the keyring.')


def clear_session():
    if Secret is None:
        delete_secret(TARGET)
    else:
        Secret.password_clear_sync(SCHEMA, ATTRIBUTES, None)


class LastFM:
    def __init__(self, api_key, secret, opener=None):
        self.api_key, self.secret = api_key, secret
        self.opener = opener or build_opener(NoRedirect())

    def request(self, method, params=None, post=False):
        args = {'method': method, 'api_key': self.api_key, **(params or {})}
        signature = ''.join(f'{key}{args[key]}' for key in sorted(args)) + self.secret
        args['api_sig'] = hashlib.md5(signature.encode('utf-8')).hexdigest()
        args['format'] = 'json'
        data = urlencode(args).encode('utf-8')
        request = Request(API_URL if post else API_URL + '?' + data.decode('ascii'),
                          data=data if post else None, method='POST' if post else 'GET')
        try:
            with self.opener.open(request, timeout=12) as response:
                result = json.loads(response.read())
        except HTTPError as error:
            try:
                result = json.loads(error.read())
            except (ValueError, OSError):
                raise LastFMError(f'Last.fm returned HTTP {error.code}.') from None
        except Exception:
            raise LastFMError('Could not reach Last.fm. Try again.') from None
        if not isinstance(result, dict):
            raise LastFMError('Last.fm returned an invalid response.')
        if 'error' in result:
            code = result.get('error')
            if code == 14:
                raise LastFMError('Approve Apistat on Last.fm before finishing the link.')
            if code == 9:
                raise LastFMError('Your Last.fm session expired. Link your account again.')
            if type(code) is not int:
                raise LastFMError('Last.fm rejected the request.')
            raise LastFMError(f'Last.fm request failed (error {code}).')
        return result

    def get_token(self):
        token = self.request('auth.getToken').get('token')
        if not isinstance(token, str) or not token:
            raise LastFMError('Last.fm did not provide an authorization token.')
        return token

    def authorization_url(self, token):
        return 'https://www.last.fm/api/auth/?' + urlencode({'api_key': self.api_key, 'token': token})

    def get_session(self, token):
        result = self.request('auth.getSession', {'token': token}).get('session')
        if not isinstance(result, dict) or not result.get('key') or not result.get('name'):
            raise LastFMError('Last.fm did not provide a session.')
        return {'api_key': self.api_key, 'secret': self.secret,
                'session': result['key'], 'username': result['name']}

    def listening_history_count(self, username, start, end, session=None):
        """Ask Last.fm for the total without downloading all history pages."""
        if not username or type(start) is not int or type(end) is not int or end <= start:
            raise ValueError('Invalid listening-history range.')
        params = {'user': username, 'from': start - 1, 'to': end, 'limit': 1, 'page': 1}
        if session:
            params['sk'] = session
        result = self.request('user.getRecentTracks', params).get('recenttracks')
        try:
            total = int(result['@attr']['total'])
        except (TypeError, KeyError, ValueError):
            raise LastFMError('Last.fm did not provide a listening-history count.') from None
        if total < 0:
            raise LastFMError('Last.fm returned an invalid listening-history count.')
        return total

    def listening_history(self, username, start, end, session=None, valid=lambda: True, progress=None):
        """Fetch every completed scrobble in [start, end), newest first."""
        if not username or type(start) is not int or type(end) is not int or end <= start:
            raise ValueError('Invalid listening-history range.')
        history, page = [], 1
        while valid():
            params = {'user': username, 'from': start - 1, 'to': end,
                      'limit': 200, 'page': page}
            if session:
                params['sk'] = session
            result = self.request('user.getRecentTracks', params).get('recenttracks')
            if not isinstance(result, dict):
                raise LastFMError('Last.fm returned invalid listening history.')
            records = result.get('track', [])
            if isinstance(records, dict):
                records = [records]
            if not isinstance(records, list):
                raise LastFMError('Last.fm returned invalid listening history.')
            for record in records:
                if not isinstance(record, dict):
                    continue
                stamp = record.get('date', {})
                stamp = stamp.get('uts') if isinstance(stamp, dict) else None
                try:
                    timestamp = int(stamp)
                except (TypeError, ValueError):
                    continue  # Includes Last.fm's undated now-playing entry.
                if not start <= timestamp < end:
                    continue
                def text_value(value):
                    return value.get('#text', '') if isinstance(value, dict) else value
                artist = text_value(record.get('artist'))
                album = text_value(record.get('album', '')) or ''
                title = record.get('name')
                if all(isinstance(value, str) for value in (artist, album, title)) and artist and title:
                    history.append({'artist': artist, 'album': album, 'title': title, 'timestamp': timestamp})
            attrs = result.get('@attr', {})
            try:
                pages = int(attrs.get('totalPages', 1))
            except (AttributeError, TypeError, ValueError):
                raise LastFMError('Last.fm returned invalid history pagination.') from None
            if progress:
                progress(page, max(1, pages), len(history))
            if not records or page >= pages:
                return history
            page += 1
        return None

    def now_playing(self, session, track):
        self.request('track.updateNowPlaying', {'sk': session, **track}, post=True)

    def scrobble(self, session, track, timestamp):
        result = self.request('track.scrobble', {'sk': session, 'timestamp': timestamp, **track}, post=True)
        scrobbles = result.get('scrobbles', {})
        if int(scrobbles.get('@attr', {}).get('accepted', 0)) != 1:
            raise LastFMError('Last.fm did not accept the scrobble.')


def metadata(track):
    data = {'artist': track.artist.strip(), 'track': track.title.strip()}
    if not all(data.values()):
        return None
    if track.album:
        data['album'] = track.album
    if track.album_artist:
        data['albumArtist'] = track.album_artist
    if track.duration:
        data['duration'] = max(1, int(track.duration / 1000))
    if track.track_number:
        data['trackNumber'] = track.track_number
    return data


class PlaybackTracker:
    """Accumulate media time actually played, excluding pauses, buffering and seeks."""
    def __init__(self, track):
        self.track = metadata(track)
        self.duration = track.duration / 1000
        self.previous = None
        self.listened = 0.0
        self.started = None
        self.announced = False
        self.submitted = False

    def update(self, position, playing, now=None):
        now = time.time() if now is None else now
        events = []
        if not playing or position is None:
            self.previous = None
            return events
        if self.previous is not None:
            delta = position - self.previous
            if 0 < delta <= 2.0:
                self.listened += delta
                if self.started is None:
                    self.started = int(now - delta)
                if self.track and not self.announced:
                    self.announced = True
                    events.append('now_playing')
                if (self.track and not self.submitted and self.duration > 30 and
                        self.listened >= min(self.duration / 2, 240)):
                    self.submitted = True
                    events.append('scrobble')
        self.previous = position
        return events
