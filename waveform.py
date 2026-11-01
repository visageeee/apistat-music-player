"""Draw layered, audio-reactive waves using colors sampled from album art."""

import math
import time
import warnings

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk


def rgb(hex_color):
    return tuple(int(hex_color[index:index + 2], 16) / 255.0 for index in (1, 3, 5))


def wave_height(position, phase, frequency, amplitude, layer):
    """Return a smooth layered wave at a horizontal position from 0 to 1."""
    envelope = math.sin(math.pi * position) ** 0.65
    angle = 2 * math.pi * (frequency * position - phase)
    primary = math.sin(angle + layer * 0.12)
    detail = math.sin(angle * 0.53 + phase * 1.7 - layer * 0.18) * 0.24
    return envelope * amplitude * (primary + detail)


def wave_frequency(layer):
    """Keep each line's wavelength fixed while its amplitude follows the music."""
    return 1.55 * (0.90 + layer * 0.04)


FREQUENCY_RANGES = ((40, 160), (160, 400), (400, 1000),
                    (1000, 2500), (2500, 6000), (6000, 12000))


def band_energies(magnitudes, sample_rate):
    """Map linear FFT bins to six roughly musical frequency ranges."""
    if not magnitudes or sample_rate <= 0:
        return [0.0] * len(FREQUENCY_RANGES)
    bin_width = sample_rate / (2 * len(magnitudes))
    result = []
    for low, high in FREQUENCY_RANGES:
        first = max(0, math.ceil(low / bin_width - 0.5))
        last = min(len(magnitudes), max(first + 1, math.ceil(high / bin_width - 0.5)))
        strongest = max(magnitudes[first:last], default=-90.0)
        result.append(max(0.0, min(1.0, (strongest + 70) / 50)) ** 1.25)
    return result


def spectrum_values(structure):
    """Read GstValueList magnitudes through the available PyGObject binding."""
    success, values = structure.get_list('magnitude')
    if not success:
        return []
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        return [values.get_nth(index) for index in range(values.n_values)]


class Waveform(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.colors = (rgb('#d080dc'), rgb('#e7a641'))
        self.target = [0.0] * 6
        self.energy = [0.0] * 6
        self.pulse = [0.0] * 6
        self.phase = 0.0
        self.last_frame = time.monotonic()
        self.get_accessible().set_name('Live layered audio waves')
        self.connect('draw', self.draw_waveform)
        GLib.timeout_add(33, self.animate)

    def set_colors(self, first, second):
        self.colors = rgb(first), rgb(second)
        self.queue_draw()

    def push_spectrum(self, magnitudes, sample_rate):
        for index, level in enumerate(band_energies(magnitudes, sample_rate)):
            self.pulse[index] = max(self.pulse[index], max(0.0, level - self.target[index]))
            self.target[index] = level

    def clear(self):
        self.target = [0.0] * 6
        self.energy = [0.0] * 6
        self.pulse = [0.0] * 6
        self.queue_draw()

    def pause(self):
        self.target = [0.0] * 6
        self.pulse = [0.0] * 6

    def animate(self):
        now = time.monotonic()
        elapsed = min(now - self.last_frame, 0.1)
        self.last_frame = now
        if not self.get_mapped():
            return True
        for index in range(6):
            response = 24 if self.target[index] > self.energy[index] else 9
            self.energy[index] += (self.target[index] - self.energy[index]) * min(1.0, elapsed * response)
            self.pulse[index] *= max(0.0, 1 - elapsed * 9)
        self.phase += elapsed * 0.055
        self.queue_draw()
        return True

    def draw_waveform(self, _widget, context):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0 or height <= 0:
            return False
        middle = height / 2
        spread = min(height * 0.27, 160)
        for layer in range(6):
            mix = layer / 5
            color = tuple(a * (1 - mix) + b * mix for a, b in zip(*self.colors))
            alpha = 0.30 + mix * 0.30
            context.set_source_rgba(*color, alpha)
            context.set_line_width(3.2 + mix * 2.0)
            layer_amplitude = spread * (0.44 + self.energy[layer] * 0.72 + self.pulse[layer] * 0.34)
            layer_amplitude *= 0.22 + layer * 0.17
            layer_frequency = wave_frequency(layer)
            layer_phase = self.phase + layer * 0.05
            baseline = middle + (2.5 - layer) * 6
            context.move_to(0, baseline + wave_height(0, layer_phase, layer_frequency,
                                                    layer_amplitude, layer))
            for x in range(3, width + 3, 3):
                position = min(1.0, x / width)
                y = baseline + wave_height(position, layer_phase, layer_frequency,
                                         layer_amplitude, layer)
                context.line_to(min(width, x), y)
            context.stroke()
        return False
