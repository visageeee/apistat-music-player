import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs
from urllib.error import HTTPError

import lastfm
from player import Player
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
    def test_runtime_application_credentials_require_both_values(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(lastfm.application_credentials())
        with patch.dict('os.environ', {'APISTAT_LASTFM_API_KEY': ' app-key ',
                                       'APISTAT_LASTFM_API_SECRET': ' app-secret '}, clear=True):
            self.assertEqual(lastfm.application_credentials(), ('app-key', 'app-secret'))
        with patch.dict('os.environ', {'APISTAT_LASTFM_API_KEY': 'app-key'}, clear=True):
            self.assertIsNone(lastfm.application_credentials())

    def test_build_credentials_are_used_without_runtime_override(self):
        with patch.dict('os.environ', {}, clear=True), \
                patch.object(lastfm, 'BUILD_API_KEY', 'build-key'), \
                patch.object(lastfm, 'BUILD_API_SECRET', 'build-secret'):
            self.assertEqual(lastfm.application_credentials(), ('build-key', 'build-secret'))

    def test_build_script_writes_no_secrets_to_output_and_removes_stale_file(self):
        script = Path(__file__).parent / 'scripts' / 'embed_lastfm_credentials.py'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            copy = root / 'scripts' / 'embed_lastfm_credentials.py'
            copy.write_text(script.read_text(encoding='utf-8'), encoding='utf-8')
            env = dict(os.environ, LASTFM_API_KEY='test-app-key', LASTFM_API_SECRET='test-app-secret')
            result = subprocess.run([sys.executable, str(copy)], env=env, capture_output=True,
                                    text=True, check=True)
            target = root / 'lastfm_build_credentials.py'
            self.assertIn('test-app-key', target.read_text(encoding='utf-8'))
            self.assertNotIn('test-app-key', result.stdout + result.stderr)
            self.assertNotIn('test-app-secret', result.stdout + result.stderr)
            env.pop('LASTFM_API_KEY'); env.pop('LASTFM_API_SECRET')
            subprocess.run([sys.executable, str(copy)], env=env, capture_output=True,
                           text=True, check=True)
            self.assertFalse(target.exists())

    def test_partial_runtime_override_does_not_mix_application_keys(self):
        with patch.dict('os.environ', {'APISTAT_LASTFM_API_KEY': 'override'}, clear=True), \
                patch.object(lastfm, 'BUILD_API_KEY', 'build-key'), \
                patch.object(lastfm, 'BUILD_API_SECRET', 'build-secret'):
            self.assertIsNone(lastfm.application_credentials())

    def test_linking_uses_application_credentials_without_manual_entry(self):
        api = SimpleNamespace(get_token=Mock())
        player = SimpleNamespace(lastfm_key=Mock(), lastfm_secret=Mock(),
                                 lastfm_generation=0, lastfm_auth=None,
                                 lastfm_finish_button=SimpleNamespace(set_sensitive=Mock()),
                                 lastfm_status=SimpleNamespace(set_text=Mock()),
                                 lastfm_work=Mock())
        with patch.object(lastfm, 'application_credentials', return_value=('app-key', 'app-secret')), \
                patch.object(lastfm, 'LastFM', return_value=api) as create:
            Player.start_lastfm_link(player)
        create.assert_called_once_with('app-key', 'app-secret')
        player.lastfm_key.get_text.assert_not_called()
        player.lastfm_secret.get_text.assert_not_called()
        player.lastfm_work.assert_called_once()

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
        if lastfm.Secret is None:
            with patch.object(lastfm, 'write_secret') as store, \
                    patch.object(lastfm, 'read_secret', return_value=json.dumps(saved)):
                lastfm.save_session(saved)
                self.assertEqual(lastfm.load_session(), saved)
                self.assertIn('token', store.call_args.args[1])
        else:
            with patch.object(lastfm.Secret, 'password_store_sync', return_value=True) as store, \
                    patch.object(lastfm.Secret, 'password_lookup_sync', return_value=json.dumps(saved)):
                lastfm.save_session(saved)
                self.assertEqual(lastfm.load_session(), saved)
                self.assertIn('token', store.call_args.args[4])


if __name__ == '__main__':
    unittest.main()
