import math
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch
import wave
import cairo

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import local_cache
from track_waveform import (PEAK_COUNT, allowed_track_uri, analyze_audio_uri,
                            analyze_track_waveform, TrackWaveform, _fill_missing_peaks,
                            waveform_from_loudness)


class TrackWaveformTests(unittest.TestCase):
    def test_server_loudness_is_resampled_and_rejects_invalid_data(self):
        peaks = waveform_from_loudness(b'-60\n-20\n0\n')
        self.assertEqual(len(peaks), PEAK_COUNT)
        self.assertLess(peaks[0], peaks[PEAK_COUNT // 2])
        self.assertAlmostEqual(peaks[-1], 1.)
        for invalid in (b'', b'not loudness', b'nan', b'inf', b'\xff'):
            self.assertIsNone(waveform_from_loudness(invalid))

    def test_server_analysis_avoids_downloading_audio(self):
        from player import Player
        track = SimpleNamespace(key='/track', duration=1000)
        peaks = [.5] * PEAK_COUNT
        client = SimpleNamespace(address='http://localhost', token='secret', is_local=False,
                                 loudness_waveform=lambda _: peaks)
        player = SimpleNamespace(waveform_generation=0, play_generation=4, closed=False,
                                 timeline_waveform_enabled=True, wave_timeline=Mock(), busy=Mock(),
                                 waveform_workers=SimpleNamespace(submit=lambda work: work()))
        cache = SimpleNamespace(read_waveform=lambda *_: None, save_waveform=Mock())
        with patch('player.LocalCache', return_value=cache), \
                patch('player.analyze_track_waveform') as decode, \
                patch('player.GLib.idle_add', side_effect=lambda callback: callback()):
            Player.prepare_track_waveform(player, client, track, 'http://localhost/track', 4)
        decode.assert_not_called()
        player.wave_timeline.set_peaks.assert_called_with(peaks)
        cache.save_waveform.assert_called_once_with(track.key, track.duration, peaks)

    def test_drawing_reuses_mask_across_progress_and_resizes(self):
        calls = []
        def make_mask(peaks):
            calls.append(peaks)
            return TrackWaveform.build_mask(peaks)
        view = SimpleNamespace(peaks=[0.8] * PEAK_COUNT, _mask=None,
                               color=SimpleNamespace(red=1.0, green=0.5, blue=0),
                               progress=0.5, build_mask=make_mask,
                               get_allocated_width=lambda: 800,
                               get_allocated_height=lambda: 60)
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 60)
        TrackWaveform.draw_waveform(view, None, cairo.Context(canvas))
        self.assertEqual(view._mask_pattern.get_filter(), cairo.FILTER_BILINEAR)
        data = canvas.get_data()
        row = 30 * canvas.get_stride()
        played = struct.unpack_from('=I', data, row + 100 * 4)[0]
        upcoming = struct.unpack_from('=I', data, row + 700 * 4)[0]
        self.assertGreater(played >> 24, upcoming >> 24)
        view.get_allocated_width = lambda: 600
        view.progress = 0.75
        TrackWaveform.draw_waveform(view, None, cairo.Context(canvas))
        self.assertEqual(len(calls), 1)
        view.queue_draw = lambda: None
        TrackWaveform.set_peaks(view, [0.2] * PEAK_COUNT)
        TrackWaveform.draw_waveform(view, None, cairo.Context(canvas))
        self.assertEqual(len(calls), 2)

    def test_only_configured_server_can_supply_waveform(self):
        server = 'https://plex.example:32400'
        self.assertTrue(allowed_track_uri(server + '/library/parts/7/file.mp3', server))
        self.assertFalse(allowed_track_uri('https://other.example/track.mp3', server))
        self.assertFalse(allowed_track_uri('https://plex.example:32401/file', server))
        self.assertFalse(allowed_track_uri('https://plex.example@other.example/file', server))
        self.assertIsNone(analyze_track_waveform('https://other.example/file', server,
                                                 'secret', 1000))

    def test_waveform_peaks_are_cached_for_next_launch(self):
        client = SimpleNamespace(address='https://plex.example', token='secret')
        peaks = [index / (PEAK_COUNT - 1) for index in range(PEAK_COUNT)]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)):
            local_cache.LocalCache(client).save_waveform('/library/metadata/7', 120000, peaks)
            cached = local_cache.LocalCache(client).read_waveform('/library/metadata/7', 120000)
            self.assertEqual(len(cached), PEAK_COUNT)
            self.assertAlmostEqual(cached[255], peaks[255], places=6)
            self.assertIsNone(local_cache.LocalCache(client).read_waveform(
                '/library/metadata/8', 120000))

    def test_waveform_preference_persists(self):
        import appearance
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertTrue(appearance.load_timeline_waveform_enabled())
            appearance.save_timeline_waveform_enabled(False)
            self.assertFalse(appearance.load_timeline_waveform_enabled())

    def test_gstreamer_decodes_actual_song_peaks(self):
        if not all(Gst.ElementFactory.find(name) for name in ('appsink', 'level')):
            self.skipTest('GStreamer waveform elements unavailable')
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as file:
            path = file.name
        try:
            with wave.open(path, 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b''.join(struct.pack('<h',
                    0 if index < 4000 else int(16000 * math.sin(index * 2 * math.pi * 300 / 8000)))
                    for index in range(8000)))
            progress = []
            with patch('track_waveform.time.sleep', side_effect=AssertionError('local analysis must not be throttled')):
                peaks = analyze_audio_uri(Gst.filename_to_uri(path), '', 1000, on_progress=progress.append)
            self.assertEqual(len(peaks), PEAK_COUNT)
            self.assertLess(max(peaks[:200]), 0.05)
            self.assertGreater(max(peaks[300:]), 0.8)
            self.assertTrue(progress)
            self.assertTrue(all(len(update) == PEAK_COUNT for update in progress))
        finally:
            os.unlink(path)

    def test_missing_sample_aligned_buckets_are_interpolated(self):
        self.assertEqual(_fill_missing_peaks([None, .2, None, .8, None]),
                         [.2, .2, .5, .8, .8])
        self.assertIsNone(_fill_missing_peaks([None, None]))

    def test_cancellation_while_waiting_for_analysis_slot(self):
        import track_waveform
        cancelled = threading.Event()
        track_waveform._ANALYSIS_SLOT.acquire()
        try:
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(analyze_audio_uri, 'file:///unused', '', 1000, cancelled.is_set)
                cancelled.set()
                self.assertIsNone(future.result(timeout=2))
        finally:
            track_waveform._ANALYSIS_SLOT.release()

    def test_simultaneous_analysis_jobs_are_serialized(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def analyze(uri, _token, _duration, _cancelled, _progress):
            calls.append(uri)
            entered.set()
            release.wait(timeout=2)
            return [0.] * PEAK_COUNT
        with patch('track_waveform._analyze_audio_uri', side_effect=analyze), \
                ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(analyze_audio_uri, 'file:///first', '', 1000)
            self.assertTrue(entered.wait(timeout=2))
            second = workers.submit(analyze_audio_uri, 'file:///second', '', 1000)
            time.sleep(.15)
            self.assertEqual(calls, ['file:///first'])
            release.set()
            self.assertIsNotNone(first.result(timeout=2))
            self.assertIsNotNone(second.result(timeout=2))
            self.assertEqual(calls, ['file:///first', 'file:///second'])

    def test_progress_is_delivered_only_while_track_is_current(self):
        from player import Player
        track = SimpleNamespace(key='/track', duration=1000)
        client = SimpleNamespace(address='http://localhost', token='secret', is_local=False)
        callbacks = []
        player = SimpleNamespace(waveform_generation=0, play_generation=4, closed=False,
                                 timeline_waveform_enabled=True, wave_timeline=Mock(), busy=Mock(),
                                 waveform_workers=SimpleNamespace(submit=lambda work: work()))
        cache = SimpleNamespace(read_waveform=lambda *_: None, save_waveform=Mock())
        partial = [.1] * PEAK_COUNT
        full = [.8] * PEAK_COUNT
        def analyze(_uri, _address, _token, _duration, _cancelled, progress):
            progress(partial)
            return full
        with patch('player.LocalCache', return_value=cache), \
                patch('player.analyze_track_waveform', side_effect=analyze), \
                patch('player.GLib.idle_add', side_effect=lambda callback: callbacks.append(callback)):
            Player.prepare_track_waveform(player, client, track, 'http://localhost/track', 4)
            self.assertEqual(len(callbacks), 2)
            callbacks.pop(0)()
            player.wave_timeline.set_peaks.assert_called_with(partial)
            player.play_generation = 5
            callbacks.pop(0)()
            player.wave_timeline.set_peaks.assert_called_with(partial)
            player.busy.end.assert_called_once()

    def test_delayed_analysis_does_not_start_after_track_changes(self):
        from player import Player
        track = SimpleNamespace(key='/track', duration=1000)
        client = SimpleNamespace(address='http://localhost', token='secret')
        callbacks = []
        workers = SimpleNamespace(submit=Mock())
        player = SimpleNamespace(waveform_generation=0, play_generation=4, closed=False,
                                 timeline_waveform_enabled=True, wave_timeline=Mock(), busy=Mock(),
                                 waveform_workers=workers)
        cache = SimpleNamespace(read_waveform=lambda *_: None)
        with patch('player.LocalCache', return_value=cache), \
                patch('player.GLib.timeout_add', side_effect=lambda delay, callback: callbacks.append((delay, callback))):
            Player.prepare_track_waveform(player, client, track, 'http://localhost/track', 4, delay_ms=750)
            self.assertEqual(callbacks[0][0], 750)
            player.play_generation = 5
            self.assertFalse(callbacks[0][1]())
            workers.submit.assert_not_called()
            player.busy.begin.assert_not_called()


if __name__ == '__main__':
    unittest.main()
