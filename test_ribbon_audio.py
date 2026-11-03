import unittest

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from ribbon_audio import RibbonAudioTap, band_levels, line_band_levels


Gst.init(None)


class RibbonAudioTests(unittest.TestCase):
    def test_bands_distinguish_bass_mids_and_highs(self):
        self.assertIsNone(band_levels([-80] * 10, 44100))
        for peak, expected in ((4, 0), (24, 1), (84, 2)):
            magnitudes = [-80.0] * 512
            magnitudes[peak] = -8.0
            levels = band_levels(magnitudes, 44100)
            self.assertEqual(levels.index(max(levels)), expected)
            lines = line_band_levels(magnitudes, 44100)
            self.assertEqual(len(lines), 13)
            if expected == 0:
                self.assertGreater(max(lines[:4]), max(lines[9:]))
            elif expected == 2:
                self.assertGreater(max(lines[9:]), max(lines[:4]))

    def test_gstreamer_spectrum_responds_to_real_tones(self):
        if not all(Gst.ElementFactory.find(name) for name in
                   ('audiotestsrc', 'spectrum', 'fakesink')):
            self.skipTest('GStreamer spectrum test elements unavailable')
        for frequency, expected in ((120, 0), (700, 1), (2800, 2)):
            tap = RibbonAudioTap('fakesink sync=false')
            pipeline = Gst.Pipeline.new(None)
            source = Gst.parse_bin_from_description(
                f'audiotestsrc num-buffers=60 wave=sine freq={frequency} ! audioconvert',
                True)
            pipeline.add(source)
            pipeline.add(tap.sink_bin)
            self.assertTrue(source.link(tap.sink_bin))
            tap.set_enabled(True)
            try:
                pipeline.set_state(Gst.State.PLAYING)
                levels = None
                for _ in range(100):
                    message = pipeline.get_bus().timed_pop_filtered(
                        100 * Gst.MSECOND,
                        Gst.MessageType.ELEMENT | Gst.MessageType.EOS |
                        Gst.MessageType.ERROR)
                    if message is None:
                        continue
                    if message.type == Gst.MessageType.ERROR:
                        self.fail(str(message.parse_error()))
                    levels = tap.read_message(message)
                    if levels is not None and max(levels[:3]) > 0.1:
                        break
                self.assertIsNotNone(levels)
                self.assertEqual(len(levels), 16)
                self.assertEqual(levels[:3].index(max(levels[:3])), expected)
                tap.set_enabled(False)
                self.assertIsNone(tap.read_message(message))
            finally:
                pipeline.set_state(Gst.State.NULL)


if __name__ == '__main__':
    unittest.main()
