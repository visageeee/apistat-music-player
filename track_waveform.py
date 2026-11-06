"""Decode and draw a compact waveform preview for the seek timeline."""

import math
import threading
import time
from urllib.parse import urlsplit
import cairo

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


# Keep current and next-track analysis from competing with each other or playback.
_ANALYSIS_SLOT = threading.Semaphore(1)
# Local files can be analyzed at full speed; a bounded remote fallback avoids
# an unrestricted second download competing with the playback stream.
REMOTE_ANALYSIS_SPEED = 8.0


def _fill_missing_peaks(peaks):
    """Interpolate buckets skipped by GStreamer's sample-aligned intervals."""
    known = [index for index, peak in enumerate(peaks) if peak is not None]
    if not known:
        return None
    for index in range(known[0]):
        peaks[index] = peaks[known[0]]
    for left, right in zip(known, known[1:]):
        for index in range(left + 1, right):
            ratio = (index - left) / (right - left)
            peaks[index] = peaks[left] + (peaks[right] - peaks[left]) * ratio
    for index in range(known[-1] + 1, len(peaks)):
        peaks[index] = peaks[known[-1]]
    return peaks


def waveform_from_loudness(data):
    """Convert Plex's one-decibel-value-per-line response to timeline peaks."""
    if not isinstance(data, bytes) or len(data) > 1024 * 1024:
        return None
    try:
        lines = data.decode('ascii').splitlines()
        if not lines or len(lines) > 100000:
            return None
        values = []
        for line in lines:
            decibels = float(line.strip())
            if math.isnan(decibels) or decibels == math.inf:
                return None
            values.append(10 ** (max(-120., min(20., decibels)) / 20) if decibels != -math.inf else 0.)
    except (ValueError, UnicodeError, OverflowError):
        return None
    ceiling = max(.05, max(values))
    normalized = [min(1., (value / ceiling) ** .7) for value in values]
    if len(normalized) == 1:
        return normalized * PEAK_COUNT
    result = []
    for index in range(PEAK_COUNT):
        position = index * (len(normalized) - 1) / (PEAK_COUNT - 1)
        left = int(position)
        right = min(left + 1, len(normalized) - 1)
        ratio = position - left
        result.append(normalized[left] * (1 - ratio) + normalized[right] * ratio)
    return result


def server_waveform(client, track, cancelled=lambda: False):
    """Prefer a server's existing analysis; missing analysis is not an error."""
    getter = getattr(client, 'loudness_waveform', None)
    if not callable(getter) or cancelled():
        return None
    try:
        result = getter(track)
        return result if not cancelled() else None
    except Exception:
        return None


def _wait_for_analysis_slot(cancelled):
    while not cancelled():
        if _ANALYSIS_SLOT.acquire(timeout=.1):
            return True
    return False


def analyze_audio_uri(uri, token, duration_ms, cancelled=lambda: False, on_progress=None):
    """Analyze audio off the UI thread with bounded decode/network demand."""
    if duration_ms <= 0 or not _wait_for_analysis_slot(cancelled):
        return None
    try:
        if cancelled():
            return None
        return _analyze_audio_uri(uri, token, duration_ms, cancelled, on_progress)
    finally:
        _ANALYSIS_SLOT.release()


def _analyze_audio_uri(uri, token, duration_ms, cancelled, on_progress=None):
    pipeline = Gst.ElementFactory.make('playbin')
    if pipeline is None:
        return None
    pipeline.set_property('flags', 2)
    sink_bin = Gst.parse_bin_from_description(
        'audioconvert ! audioresample ! '
        'audio/x-raw,format=S16LE,channels=1,rate=8000 ! '
        'level name=wave_levels post-messages=true ! '
        'appsink name=wave_peaks sync=false max-buffers=1', True)
    sink = sink_bin.get_by_name('wave_peaks')
    level = sink_bin.get_by_name('wave_levels')
    level.set_property('interval', max(1, int(duration_ms * Gst.MSECOND / PEAK_COUNT)))
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
    peaks = [None] * PEAK_COUNT
    duration_ns = duration_ms * Gst.MSECOND
    speed = None if urlsplit(uri).scheme == 'file' else REMOTE_ANALYSIS_SPEED
    deadline = time.monotonic()
    last_progress = 0.
    try:
        pipeline.set_state(Gst.State.PLAYING)
        bus = pipeline.get_bus()
        while not cancelled():
            sample = sink.emit('try-pull-sample', 100 * Gst.MSECOND)
            sample_seconds = 0.
            if sample is not None:
                buffer = sample.get_buffer()
                duration = buffer.duration
                if duration == Gst.CLOCK_TIME_NONE or duration <= 0:
                    duration = buffer.get_size() * Gst.SECOND / (2 * SAMPLE_RATE)
                sample_seconds = duration / Gst.SECOND
            finished = False
            while True:
                message = bus.pop_filtered(Gst.MessageType.ELEMENT | Gst.MessageType.EOS | Gst.MessageType.ERROR)
                if message is None:
                    break
                if message.type == Gst.MessageType.ERROR:
                    return None
                if message.type == Gst.MessageType.EOS:
                    finished = True
                    break
                structure = message.get_structure()
                if structure is None or structure.get_name() != 'level':
                    continue
                values = structure.get_value('peak')
                timestamp = structure.get_value('timestamp')
                if not values or timestamp is None or timestamp == Gst.CLOCK_TIME_NONE:
                    continue
                decibels = float(values[0])
                amplitude = 10 ** (decibels / 20) if math.isfinite(decibels) else 0.
                bucket = min(PEAK_COUNT - 1, max(0, int(timestamp * PEAK_COUNT / duration_ns)))
                peaks[bucket] = max(peaks[bucket] or 0., amplitude)
            now = time.monotonic()
            if on_progress is not None and now - last_progress >= .5:
                known = [i for i, value in enumerate(peaks) if value is not None]
                if known:
                    end = known[-1] + 1
                    partial = _fill_missing_peaks(peaks[:end])
                    ceiling = max(.05, max(partial))
                    on_progress([min(1., (value / ceiling) ** .7) for value in partial] +
                                [0.] * (PEAK_COUNT - end))
                    last_progress = now
            # Backpressure the appsink, rather than decoding/downloading the
            # whole track at full speed beside the active playback stream.
            if speed is not None:
                deadline = max(deadline, time.monotonic()) + sample_seconds / speed
                while not cancelled():
                    delay = deadline - time.monotonic()
                    if delay <= 0:
                        break
                    time.sleep(min(.05, delay))
            if finished:
                break
        if cancelled():
            return None
        peaks = _fill_missing_peaks(peaks)
        if peaks is None:
            return None
        ceiling = max(0.05, max(peaks))
        return [min(1.0, (peak / ceiling) ** 0.7) for peak in peaks]
    finally:
        pipeline.set_state(Gst.State.NULL)


def analyze_track_waveform(uri, server_address, token, duration_ms, cancelled=lambda: False, on_progress=None):
    if not allowed_track_uri(uri, server_address):
        return None
    return analyze_audio_uri(uri, token, duration_ms, cancelled, on_progress)


class TrackWaveform(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.peaks = None
        self._mask = None
        self._mask_pattern = None
        self.progress = 0.0
        self.color = Gdk.RGBA()
        self.color.parse('#e7a641')
        self.set_size_request(-1, 60)
        self.get_accessible().set_name('Song waveform timeline')
        self.connect('draw', self.draw_waveform)

    def set_peaks(self, peaks):
        self.peaks = peaks
        self._mask = None
        self._mask_pattern = None
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
        if self._mask is None:
            self._mask = self.build_mask(self.peaks)
            self._mask_pattern = cairo.SurfacePattern(self._mask)
            self._mask_pattern.set_filter(cairo.FILTER_BILINEAR)
        context.save()
        context.scale(width / self._mask.get_width(), height / self._mask.get_height())
        mask_width, mask_height = self._mask.get_width(), self._mask.get_height()
        for left, right, alpha in ((0, self.progress, 0.95), (self.progress, 1, 0.42)):
            if right <= left:
                continue
            context.save()
            context.rectangle(left * mask_width, 0, (right - left) * mask_width, mask_height)
            context.clip()
            context.set_source_rgba(self.color.red, self.color.green, self.color.blue, alpha)
            context.mask(self._mask_pattern)
            context.restore()
        context.restore()
        return False

    @staticmethod
    def build_mask(peaks):
        width, height = PEAK_COUNT * 2, 60
        surface = cairo.ImageSurface(cairo.FORMAT_A8, width, height)
        context = cairo.Context(surface)
        context.set_source_rgba(1, 1, 1, 1)
        for index, peak in enumerate(peaks or [0.1] * PEAK_COUNT):
            amplitude = 2 + peak * (height / 2 - 15)
            context.rectangle(index * 2, height / 2 - amplitude, 1.44, amplitude * 2)
        context.fill()
        return surface
