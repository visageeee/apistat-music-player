import hashlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.error import HTTPError

import lastfm
from plex_client import Item


class Response:
    def __init__(self, result):
        self.result = result
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        pass
    def read(self):
        return json.dumps(self.result).encode()


class LastFMTests(unittest.TestCase):
    def test_signed_scrobble_post_contains_metadata_and_start_time(self):
        class Opener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response({'scrobbles': {'@attr': {'accepted': '1'}}})
        opener = Opener()
        api = lastfm.LastFM('key', 'secret', opener)
        api.scrobble('session', {'artist': 'Björk', 'track': 'Song'}, 12345)
        self.assertEqual(opener.request.get_method(), 'POST')
        params = {k: v[0] for k, v in parse_qs(opener.request.data.decode()).items()}
        signature = params.pop('api_sig')
        params.pop('format')
        expected = ''.join(k + params[k] for k in sorted(params)) + 'secret'
        self.assertEqual(signature, hashlib.md5(expected.encode()).hexdigest())
        self.assertEqual(params['artist'], 'Björk')
        self.assertEqual(params['timestamp'], '12345')
        self.assertEqual(params['sk'], 'session')
        self.assertNotIn('session', opener.request.full_url)

    def test_lastfm_ignored_scrobble_is_an_error(self):
        opener = SimpleNamespace(open=lambda *_args, **_kwargs: Response(
            {'scrobbles': {'@attr': {'accepted': '0', 'ignored': '1'}}}))
        with self.assertRaises(lastfm.LastFMError):
            lastfm.LastFM('key', 'secret', opener).scrobble('s', {'artist': 'A', 'track': 'T'}, 1)

    def test_authentication_failure_explains_browser_approval(self):
        def fail(*_args, **_kwargs):
            raise HTTPError('https://example.test', 403, 'Forbidden', {},
                            io.BytesIO(b'{"error":14}'))
        api = lastfm.LastFM('key', 'secret', SimpleNamespace(open=fail))
        with self.assertRaisesRegex(lastfm.LastFMError, 'Approve Apistat'):
            api.get_session('token')

    def test_tracker_counts_listening_not_pause_or_seek_and_submits_once(self):
        tracker = lastfm.PlaybackTracker(Item('/1', 'Track', artist='Artist', duration=60000))
        events = []
        for second in range(11):
            events += tracker.update(second, True, now=1000 + second)
        tracker.update(10, False)
        tracker.update(50, True, now=1100)
        for second in range(51, 71):
            events += tracker.update(second, True, now=1100 + second)
        events += tracker.update(71, True)
        self.assertEqual(events, ['now_playing', 'scrobble'])
        self.assertEqual(tracker.started, 1000)
        self.assertEqual(tracker.listened, 31)

    def test_short_track_and_missing_metadata_are_never_scrobbled(self):
        for track in (Item('/1', 'Track', artist='Artist', duration=30000),
                      Item('/2', 'Track', duration=60000)):
            tracker = lastfm.PlaybackTracker(track)
            events = [event for second in range(65)
                      for event in tracker.update(second, True, now=1000 + second)]
            self.assertNotIn('scrobble', events)

    def test_unavailable_playback_and_large_jumps_do_not_count(self):
        tracker = lastfm.PlaybackTracker(Item('/1', 'Track', artist='Artist', duration=60000))
        tracker.update(1, True)
        tracker.update(20, True)
        tracker.update(None, False)
        tracker.update(30, True)
        self.assertEqual(tracker.listened, 0)

    def test_long_track_scrobbles_after_four_minutes(self):
        tracker = lastfm.PlaybackTracker(Item('/1', 'Track', artist='Artist', duration=900000))
        events = [event for second in range(241)
                  for event in tracker.update(second, True, now=1000 + second)]
        self.assertEqual(events, ['now_playing', 'scrobble'])

    def test_credentials_are_stored_as_keyring_secret(self):
        saved = {'api_key': 'key', 'secret': 'secret', 'session': 'token', 'username': 'user'}
        with patch.object(lastfm.Secret, 'password_store_sync', return_value=True) as store, \
                patch.object(lastfm.Secret, 'password_lookup_sync', return_value=json.dumps(saved)):
            lastfm.save_session(saved)
            self.assertEqual(lastfm.load_session(), saved)
            self.assertIn('token', store.call_args.args[4])


if __name__ == '__main__':
    unittest.main()
