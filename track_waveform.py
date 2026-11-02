"""Decode and draw a compact waveform preview for the seek timeline."""

from array import array
import sys
from urllib.parse import urlsplit

import gi
gi.require_version('Gst', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gst, Gtk


PEAK_COUNT = 512
SAMPLE_RATE = 8000


def allowed_track_uri(uri, server_address):
    try:
        source, server = urlsplit(uri), urlsplit(server_address)
        return (source.scheme == server.scheme and source.hostname == server.hostname and
                source.port == server.port and source.path.startswith('/') and
                not source.username and not source.password and not source.fragment)
    except ValueError:
        return False


def analyze_audio_uri(uri, token, duration_ms, cancelled=lambda: False):
    """Decode mono samples without routing analysis audio to an output device."""
    pipeline = Gst.ElementFactory.make('playbin')
    if pipeline is None:
        return None
    pipeline.set_property('flags', 2)
    sink_bin = Gst.parse_bin_from_description(
        'audioconvert ! audioresample ! '
        'audio/x-raw,format=S16LE,channels=1,rate=8000 ! '
        'appsink name=wave_peaks sync=false', True)
    sink = sink_bin.get_by_name('wave_peaks')
    pipeline.set_property('audio-sink', sink_bin)
    def source_setup(_pipeline, source):
        if token and source.find_property('extra-headers'):
            headers = Gst.Structure.new_empty('headers')
            headers.set_value('X-Plex-Token', token)
            source.set_property('extra-headers', headers)
        if source.find_property('automatic-redirect'):
            source.set_property('automatic-redirect', False)
        if source.find_property('timeout'):
            source.set_property('timeout', 15)
    pipeline.connect('source-setup', source_setup)
    pipeline.set_property('uri', uri)
    peaks = [0.0] * PEAK_COUNT
    samples_seen = 0
    expected_samples = max(1, round(duration_ms * SAMPLE_RATE / 1000))
    try:
        pipeline.set_state(Gst.State.PLAYING)
        bus = pipeline.get_bus()
        while not cancelled():
            sample = sink.emit('try-pull-sample', 100 * Gst.MSECOND)
            if sample is not None:
                buffer = sample.get_buffer()
                ok, mapped = buffer.map(Gst.MapFlags.READ)
                if ok:
                    try:
                        values = array('h')
                        values.frombytes(mapped.data)
                        if sys.byteorder != 'little':
                            values.byteswap()
                        for value in values:
                            bucket = min(PEAK_COUNT - 1,
                                         samples_seen * PEAK_COUNT // expected_samples)
                            peaks[bucket] = max(peaks[bucket], abs(value) / 32768)
                            samples_seen += 1
                    finally:
                        buffer.unmap(mapped)
            message = bus.pop_filtered(Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if message:
                if message.type == Gst.MessageType.ERROR:
                    return None
                break
        if cancelled() or samples_seen == 0:
            return None
        ceiling = max(0.05, max(peaks))
        return [min(1.0, (peak / ceiling) ** 0.7) for peak in peaks]
    finally:
        pipeline.set_state(Gst.State.NULL)


def analyze_track_waveform(uri, server_address, token, duration_ms, cancelled=lambda: False):
    if not allowed_track_uri(uri, server_address):
        return None
    return analyze_audio_uri(uri, token, duration_ms, cancelled)


class TrackWaveform(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.peaks = None
        self.progress = 0.0
        self.color = Gdk.RGBA()
        self.color.parse('#e7a641')
        self.set_size_request(-1, 60)
        self.get_accessible().set_name('Song waveform timeline')
        self.connect('draw', self.draw_waveform)

    def set_peaks(self, peaks):
        self.peaks = peaks
        self.queue_draw()

    def set_progress(self, progress):
        progress = max(0.0, min(1.0, progress))
        if abs(progress - self.progress) > 0.0005:
            self.progress = progress
            self.queue_draw()

    def set_color(self, color):
        if self.color.parse(color):
            self.queue_draw()

    def draw_waveform(self, _widget, context):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        if width <= 0 or height <= 0:
            return False
        middle = height / 2
        peaks = self.peaks or [0.1] * PEAK_COUNT
        bar_width = max(1.0, width / PEAK_COUNT * 0.72)
        for index, peak in enumerate(peaks):
            x = index * width / PEAK_COUNT
            amplitude = 2 + peak * (height / 2 - 15)
            active = x / width <= self.progress
            context.set_source_rgba(self.color.red, self.color.green, self.color.blue,
                                    0.95 if active else 0.42)
            context.rectangle(x, middle - amplitude, bar_width, amplitude * 2)
            context.fill()
        return False
