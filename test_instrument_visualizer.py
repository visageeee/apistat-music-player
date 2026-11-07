import io
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from concurrent.futures import Future

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import appearance
import instrument_visualizer as instruments
import local_cache
from plex_client import Item


class InstrumentVisualizerTests(unittest.TestCase):
    def test_preference_is_opt_in_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertFalse(appearance.load_instrument_visualizer_enabled())
            appearance.save_instrument_visualizer_enabled(True)
            self.assertTrue(appearance.load_instrument_visualizer_enabled())
            appearance.save_instrument_visualizer_enabled(False)
            self.assertFalse(appearance.load_instrument_visualizer_enabled())

    def test_cache_validation_and_position_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'levels'
            frames = bytes([0] * 13 + [255] * 13 + [128] * 13)
            path.write_bytes(instruments.HEADER.pack(instruments.MAGIC, 150, 50, 3) + frames)
            data = instruments.read_analysis(path, 150)
            self.assertEqual(len(instruments.sample_analysis(data, 25)), 13)
            self.assertAlmostEqual(instruments.sample_analysis(data, 25)[0], .5)
            self.assertAlmostEqual(instruments.sample_analysis(data, 999)[0], 128 / 255)
            self.assertIsNone(instruments.read_analysis(path, 50000))
            path.write_bytes(path.read_bytes()[:-1])
            self.assertIsNone(instruments.read_analysis(path, 150))

    def test_rejects_cross_server_download_and_sends_token_in_header(self):
        client = SimpleNamespace(address='http://plex:32400', token='private', opener=Mock())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'track'
            with self.assertRaises(ValueError):
                instruments._copy_remote(client, 'http://elsewhere/track', path, lambda: False)
            client.opener.open.assert_not_called()
            response = io.BytesIO(b'music')
            client.opener.open.return_value = response
            with patch('instrument_visualizer.time.sleep'):
                self.assertTrue(instruments._copy_remote(client, 'http://plex:32400/track', path, lambda: False))
            request = client.opener.open.call_args.args[0]
            self.assertEqual(request.get_header('X-plex-token'), 'private')
            self.assertNotIn('private', request.full_url)
            self.assertEqual(path.read_bytes(), b'music')

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'NumPy is required only in the external worker')
    def test_real_worker_process_uses_stems_and_reuses_cache(self):
        # Simulate the optional Demucs package, while exercising the real
        # subprocess, WAV analysis, compact cache, and local-file handling.
        fake_demucs = '''\
from pathlib import Path
import math, struct, wave

def main(args):
    root = Path(args[args.index('-o') + 1]) / 'htdemucs' / Path(args[-1]).stem
    root.mkdir(parents=True)
    for stem, hz in [('bass', 80), ('drums', 700), ('vocals', 1000), ('other', 2000)]:
        with wave.open(str(root / (stem + '.wav')), 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000)
            out.writeframes(b''.join(struct.pack('<h', round(14000 * math.sin(2 * math.pi * hz * i / 8000))) for i in range(16000)))
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'demucs'
            package.mkdir()
            (package / '__init__.py').write_text('')
            (package / 'separate.py').write_text(fake_demucs)
            source = root / 'song.wav'
            source.write_bytes(b'only the fake separator reads this')
            track = Item('/local/1', 'Track', duration=2000)
            client = SimpleNamespace(address='local:testing', token='', is_local=True)
            with patch.object(local_cache, 'CACHE_ROOT', root / 'cache'), \
                    patch.dict(os.environ, {'APISTAT_DEMUCS_PYTHON': sys.executable,
                                            'PYTHONPATH': str(root)}):
                cache = local_cache.LocalCache(client)
                result, status = instruments.run_analysis(cache, client, track,
                                                          Gst.filename_to_uri(str(source)))
                self.assertEqual(status, 'ready')
                levels = instruments.sample_analysis(result, 1000)
                self.assertEqual(len(levels), 13)
                self.assertGreater(levels[0], levels[2])
                self.assertGreater(levels[7], levels[6])
                with patch('instrument_visualizer.subprocess.Popen', side_effect=AssertionError('cached')):
                    self.assertEqual(instruments.run_analysis(cache, client, track,
                                      Gst.filename_to_uri(str(source)))[1], 'ready')

    def test_cancellation_terminates_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            track = Item('/local/1', 'Track', duration=2000)
            client = SimpleNamespace(address='local:testing', token='', is_local=True)
            process = Mock()
            process.poll.side_effect = [None, 0]
            cancelled = Mock(side_effect=[False, False, True])
            with patch.object(local_cache, 'CACHE_ROOT', Path(directory)), \
                    patch('instrument_visualizer.python_executable', return_value=sys.executable), \
                    patch('instrument_visualizer.subprocess.Popen', return_value=process):
                result, status = instruments.run_analysis(local_cache.LocalCache(client), client, track,
                                                          'file:///music.wav', cancelled)
            self.assertIsNone(result)
            self.assertEqual(status, 'cancelled')
            process.terminate.assert_called_once()
            process.wait.assert_called_once()

    def test_missing_numpy_reports_actionable_status(self):
        with tempfile.TemporaryDirectory() as directory:
            track = Item('/local/1', 'Track', duration=2000)
            client = SimpleNamespace(address='local:testing', token='', is_local=True)
            process = SimpleNamespace(poll=lambda: 21, returncode=21)
            with patch.object(local_cache, 'CACHE_ROOT', Path(directory)), \
                    patch('instrument_visualizer.python_executable', return_value=sys.executable), \
                    patch('instrument_visualizer.subprocess.Popen', return_value=process):
                result, status = instruments.run_analysis(local_cache.LocalCache(client), client, track,
                                                          'file:///music.wav')
            self.assertIsNone(result)
            self.assertEqual(status, 'missing_numpy')

    def test_finds_linux_default_environment_without_an_environment_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            executable = home / '.local/share/apistat/demucs-env/bin/python'
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch('instrument_visualizer.Path.home', return_value=home), \
                    patch('instrument_visualizer.sys.platform', 'linux'), \
                    patch.dict(os.environ, {}, clear=True):
                self.assertEqual(instruments.python_executable(), str(executable))

    def test_track_change_keeps_analysis_and_queues_only_latest_track(self):
        from player import Player
        first, last = Future(), Future()
        workers = SimpleNamespace(submit=Mock(side_effect=[first, last]))
        callbacks = []
        player = SimpleNamespace(instrument_visualizer_enabled=True, instrument_future=None,
                                 instrument_pending=None, instrument_generation=1,
                                 instrument_analysis=None, play_generation=1, closed=False,
                                 instrument_workers=workers,
                                 instrument_visualizer_status=SimpleNamespace(set_text=Mock()))
        player.prepare_instrument_analysis = lambda *args: Player.prepare_instrument_analysis(player, *args)
        client = SimpleNamespace(address='local:testing', token='', is_local=True)
        track_a = Item('/a', 'A', duration=1000)
        track_b = Item('/b', 'B', duration=1000)
        track_c = Item('/c', 'C', duration=1000)
        with patch('player.GLib.idle_add', side_effect=lambda fn, *args: callbacks.append((fn, args))):
            player.prepare_instrument_analysis(client, track_a, 'file:///a', 1)
            player.play_generation = 2
            player.prepare_instrument_analysis(client, track_b, 'file:///b', 2)
            player.play_generation = 3
            player.prepare_instrument_analysis(client, track_c, 'file:///c', 3)
            first.set_result(('old data', 'ready'))
            fn, args = callbacks.pop(0)
            fn(*args)
            self.assertIsNone(player.instrument_analysis)
            self.assertEqual(workers.submit.call_count, 2)
            last.set_result(('current data', 'ready'))
            fn, args = callbacks.pop(0)
            fn(*args)
            self.assertEqual(player.instrument_analysis, 'current data')
            self.assertIsNone(player.instrument_pending)

    def test_playback_uses_stem_levels_and_falls_back_to_live_audio(self):
        from player import Player
        live = (.2, .3, .4) + (.1,) * 13
        levels = bytes([0] * 13 + [255] * 13)
        hero, background = Mock(), Mock()
        player = SimpleNamespace(live_waveform_tap=SimpleNamespace(read_message=lambda _: live),
                                 hero_waveform=hero, background_visualizer=background,
                                 instrument_analysis=(50, memoryview(levels)),
                                 instrument_visualizer_enabled=True, playing=True,
                                 buffering_busy=False, timeline_base_position=0., timeline_base_time=10.)
        message = SimpleNamespace(type=Gst.MessageType.ELEMENT)
        with patch('player.time.monotonic', return_value=10.025):
            Player.message(player, None, message)
        actual = hero.set_audio.call_args.args[0]
        self.assertEqual(actual[:3], live[:3])
        self.assertTrue(all(abs(value - .5) < 1e-6 for value in actual[3:]))
        self.assertEqual(background.set_audio.call_args.args[0], actual)
        player.instrument_analysis = None
        Player.message(player, None, message)
        hero.set_audio.assert_called_with(live)


if __name__ == '__main__':
    unittest.main()
