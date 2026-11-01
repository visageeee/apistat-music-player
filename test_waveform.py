import math
import os
import struct
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from waveform import Waveform, band_energies, spectrum_values, wave_frequency, wave_height


class WaveformTests(unittest.TestCase):
    def test_layered_waves_respond_to_energy(self):
        self.assertGreater(wave_frequency(5), wave_frequency(0))
        quiet = wave_height(0.35, 0.2, 1.7, 10, 2)
        loud = wave_height(0.35, 0.2, 1.7, 30, 2)
        self.assertAlmostEqual(loud, quiet * 3)
        self.assertNotEqual(wave_height(0.35, 0.2, 1.7, 30, 2),
                            wave_height(0.35, 0.2, 2.4, 30, 2))

    def test_audio_energy_does_not_change_drift_speed(self):
        def frame(target):
            subject = SimpleNamespace(target=[target] * 6, energy=[0.0] * 6,
                                      pulse=[0.0] * 6, phase=0.0, last_frame=1.0,
                                      get_mapped=lambda: True, queue_draw=lambda: None)
            with patch('waveform.time.monotonic', return_value=1.05):
                Waveform.animate(subject)
            return subject
        quiet, loud = frame(0.0), frame(1.0)
        self.assertEqual(quiet.phase, loud.phase)
        self.assertGreater(loud.energy[0], quiet.energy[0])

    def test_each_line_uses_its_own_frequency_range(self):
        magnitudes = [-90.0] * 512
        magnitudes[round(200 / (44100 / 1024))] = -20.0
        magnitudes[round(4000 / (44100 / 1024))] = -20.0
        bands = band_energies(magnitudes, 44100)
        self.assertEqual(len(bands), 6)
        self.assertGreater(bands[1], 0.8)
        self.assertGreater(bands[4], 0.8)
        self.assertEqual(bands[0], 0.0)
        self.assertEqual(bands[3], 0.0)

    def test_playbin_spectrum_filter_emits_frequency_measurements(self):
        Gst.init(None)
        if not Gst.ElementFactory.find('spectrum'):
            self.skipTest('GStreamer spectrum plugin unavailable')
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as file:
            path = file.name
        playbin = None
        try:
            with wave.open(path, 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(44100)
                output.writeframes(b''.join(
                    struct.pack('<h', int(9000 * math.sin(i * 2 * math.pi * 200 / 44100) +
                                          7000 * math.sin(i * 2 * math.pi * 4000 / 44100)))
                    for i in range(11025)))
            playbin = Gst.ElementFactory.make('playbin')
            spectrum = Gst.ElementFactory.make('spectrum')
            spectrum.set_property('interval', 30 * Gst.MSECOND)
            spectrum.set_property('bands', 512)
            spectrum.set_property('threshold', -90)
            spectrum.set_property('post-messages', True)
            playbin.set_property('audio-filter', spectrum)
            playbin.set_property('audio-sink', Gst.ElementFactory.make('fakesink'))
            playbin.set_property('uri', Gst.filename_to_uri(path))
            playbin.set_state(Gst.State.PLAYING)
            measured = False
            for _ in range(20):
                message = playbin.get_bus().timed_pop_filtered(
                    Gst.SECOND, Gst.MessageType.ELEMENT | Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if not message or message.type in (Gst.MessageType.ERROR, Gst.MessageType.EOS):
                    break
                structure = message.get_structure()
                if structure and structure.get_name() == 'spectrum':
                    bands = band_energies(spectrum_values(structure), 44100)
                    measured = bands[1] > 0.5 and bands[4] > 0.5
                    if measured:
                        break
            self.assertTrue(measured)
        finally:
            if playbin:
                playbin.set_state(Gst.State.NULL)
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
