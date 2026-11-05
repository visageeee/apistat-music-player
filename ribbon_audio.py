"""Low-cost bass, mid, and high analysis from the playback audio sink."""

import math
import warnings

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst


BANDS = 512
LINE_FREQUENCIES = (85, 120, 170, 240, 340, 480, 680,
                    960, 1360, 1920, 2700, 3800, 5600)


def _normalized(magnitudes):
    return [max(0.0, min(1.0, (float(db) + 70.0) / 56.0))
            for db in magnitudes]


def _strongest(levels, sample_rate, low_hz, high_hz, count):
    hz_per_band = sample_rate / (2 * BANDS)
    start = max(1, int(low_hz / hz_per_band))
    if start >= BANDS:
        return 0.0
    end = min(BANDS, max(start + 1, math.ceil(high_hz / hz_per_band)))
    values = sorted(levels[start:end], reverse=True)[:count]
    return sum(values) / len(values) if values else 0.0


def band_levels(magnitudes, sample_rate):
    """Convert spectrum dB bins at the stream's rate into three envelopes."""
    if len(magnitudes) != BANDS:
        return None
    return _broad_levels(_normalized(magnitudes), sample_rate)


def _broad_levels(levels, sample_rate):
    return (_strongest(levels, sample_rate, 60, 250, 2),
            _strongest(levels, sample_rate, 250, 1600, 4),
            _strongest(levels, sample_rate, 1600, 8000, 8))


def line_band_levels(magnitudes, sample_rate):
    if len(magnitudes) != BANDS:
        return None
    return _line_levels(_normalized(magnitudes), sample_rate)


def _line_levels(levels, sample_rate):
    return tuple(_strongest(levels, sample_rate, center / 1.55,
                            center * 1.55, 2)
                 for center in LINE_FREQUENCIES)


class RibbonAudioTap:
    def __init__(self, output='autoaudiosink'):
        description = (
            'audioconvert ! audioresample ! '
            'spectrum name=ribbon_spectrum bands=512 threshold=-80 '
            'interval=30000000 post-messages=false message-magnitude=true '
            f'message-phase=false ! {output}'
        )
        self.sink_bin = Gst.parse_bin_from_description(description, True)
        self.spectrum = self.sink_bin.get_by_name('ribbon_spectrum')
        if self.spectrum is None:
            raise RuntimeError('GStreamer spectrum is unavailable')
        self.enabled = False

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled != self.enabled:
            self.enabled = enabled
            self.spectrum.set_property('post-messages', enabled)

    def read_message(self, message):
        if not self.enabled or message.type != Gst.MessageType.ELEMENT:
            return None
        structure = message.get_structure()
        if structure is None or structure.get_name() != 'spectrum':
            return None
        valid, values = structure.get_list('magnitude')
        if not valid or values is None or values.n_values != BANDS:
            return None
        caps = self.spectrum.get_static_pad('sink').get_current_caps()
        if caps is None:
            return None
        valid_rate, sample_rate = caps.get_structure(0).get_int('rate')
        if not valid_rate or sample_rate <= 0:
            return None
        # GI exposes Gst's legacy ValueArray here; get_nth is its usable accessor.
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=DeprecationWarning,
                                    message='GObject.ValueArray.get_nth is deprecated')
            magnitudes = [values.get_nth(index) for index in range(BANDS)]
        levels = _normalized(magnitudes)
        return _broad_levels(levels, sample_rate) + _line_levels(levels, sample_rate)
