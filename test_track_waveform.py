import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import wave

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import local_cache
from track_waveform import (PEAK_COUNT, allowed_track_uri, analyze_audio_uri,
                            analyze_track_waveform)


class TrackWaveformTests(unittest.TestCase):
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
            self.assertFalse(appearance.load_timeline_waveform_enabled())
            appearance.save_timeline_waveform_enabled(True)
            self.assertTrue(appearance.load_timeline_waveform_enabled())

    def test_gstreamer_decodes_actual_song_peaks(self):
        if not Gst.ElementFactory.find('appsink'):
            self.skipTest('GStreamer appsink unavailable')
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
            peaks = analyze_audio_uri(Gst.filename_to_uri(path), '', 1000)
            self.assertEqual(len(peaks), PEAK_COUNT)
            self.assertLess(max(peaks[:200]), 0.05)
            self.assertGreater(max(peaks[300:]), 0.8)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
