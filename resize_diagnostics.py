"""Opt-in, metadata-free GTK resize diagnostics."""

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gdk, Gtk
from frosted_bar import FrostedBar


MAX_SAMPLES = 4000
QUIET_MS = 600


def timing_summary(values):
    if not values:
        return {'count': 0}
    ordered = sorted(values)
    return {'count': len(values), 'mean_ms': round(statistics.fmean(values), 3),
            'p95_ms': round(ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)], 3),
            'max_ms': round(ordered[-1], 3)}


class ResizeDiagnostics:
    """Write one JSON record per resize gesture; do nothing unless installed."""

    def __init__(self, player, stream, clock=time.monotonic):
        self.player = player
        self.stream = stream
        self.clock = clock
        self.last_size = (player.get_allocated_width(), player.get_allocated_height())
        self.session = None
        self.timer = 0
        self.tick = 0
        self.heartbeat_source = 0
        self.last_heartbeat = None
        self.last_frame = None
        self.draw_starts = {}
        self.closed = False
        self.frosted_refresh = player.frosted_bar.refresh
        player.frosted_bar.refresh = self.profile_frosted_refresh
        self.shape_refresh = player.refresh_window_shape
        player.refresh_window_shape = self.profile_shape_refresh
        player.connect('configure-event', self.configure)
        player.connect('destroy', self.close)
        for name, widget in (
                ('content', player.content_views), ('album_grid', player.grid),
                ('library_list', player.song_view), ('now_panel', player.now_panel),
                ('player_bar', player.player_bar), ('timeline_line', player.seek),
                ('timeline_waveform', player.wave_timeline),
                ('background', player.shared_background)):
            widget.connect('draw', self.draw_begin, name)
            widget.connect_after('draw', self.draw_end, name)
        for name, widget in (('window', player), ('content', player.content_views),
                             ('player_bar', player.player_bar), ('lyrics',
                              player.content_views.get_child_by_name('lyrics'))):
            widget.connect('size-allocate', self.allocated, name)

    def context(self):
        player = self.player
        display = Gdk.Display.get_default()
        return {
            'panel': player.content_views.get_visible_child_name(),
            'timeline': player.timeline_stack.get_visible_child_name(),
            'frosted': bool(player.frosted_player_bar),
            'rounded_corners': bool(player.rounded_corners_enabled),
            'window_decorated': bool(player.get_decorated()),
            'theme': player.theme,
            'album_tiles': len(player.grid.get_children()),
            'library_rows': len(player.song_store),
            'session_type': os.environ.get('XDG_SESSION_TYPE', 'unknown'),
            'display_backend': display.__gtype__.name if display else 'unknown',
            'gtk_version': f'{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}',
        }

    @staticmethod
    def append_bounded(target, value):
        if len(target) < MAX_SAMPLES:
            target.append(value)
            return True
        return False

    def configure(self, _window, event):
        size = (event.width, event.height)
        if self.closed or size == self.last_size or min(size) <= 1:
            return False
        previous = self.last_size
        self.last_size = size
        now = self.clock()
        if self.session is None:
            self.session = {'started_utc': datetime.now(timezone.utc).isoformat(),
                            'started_monotonic': now, 'start_size': previous,
                            'context_start': self.context(), 'events': [],
                            'frames': [], 'heartbeat': [], 'allocations': {},
                            'draws': {}, 'truncated': False}
            self.last_frame = None
            self.last_heartbeat = now
            self.tick = self.player.add_tick_callback(self.frame)
            self.heartbeat_source = GLib.timeout_add(100, self.heartbeat)
        elapsed = round((now - self.session['started_monotonic']) * 1000, 3)
        if not self.append_bounded(self.session['events'], [elapsed, *size]):
            self.session['truncated'] = True
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(QUIET_MS, self.finish)
        return False

    def frame(self, _window, _frame_clock):
        if self.session is None or self.closed:
            self.tick = 0
            return False
        now = self.clock()
        if self.last_frame is not None:
            elapsed = round((now - self.session['started_monotonic']) * 1000, 3)
            gap = round((now - self.last_frame) * 1000, 3)
            if not self.append_bounded(self.session['frames'], [elapsed, *self.last_size, gap]):
                self.session['truncated'] = True
        self.last_frame = now
        return True

    def heartbeat(self):
        if self.session is None or self.closed:
            self.heartbeat_source = 0
            return False
        now = self.clock()
        elapsed = round((now - self.session['started_monotonic']) * 1000, 3)
        gap = round((now - self.last_heartbeat) * 1000, 3)
        self.last_heartbeat = now
        if not self.append_bounded(self.session['heartbeat'],
                                   [elapsed, gap, *self.last_size, len(self.player.song_store)]):
            self.session['truncated'] = True
        return True

    def allocated(self, _widget, allocation, name):
        if self.session is not None:
            elapsed = round((self.clock() - self.session['started_monotonic']) * 1000, 3)
            samples = self.session['allocations'].setdefault(name, [])
            if not self.append_bounded(samples, [elapsed, allocation.width, allocation.height]):
                self.session['truncated'] = True

    def draw_begin(self, widget, _context, name):
        if self.session is not None:
            key = (id(widget), name)
            self.draw_starts.setdefault(key, []).append(
                (self.clock(), bool(FrostedBar._capture_depth), self.session))
        return False

    def draw_end(self, widget, _context, name):
        starts = self.draw_starts.get((id(widget), name))
        if not starts:
            return False
        started, capture, session = starts.pop()
        if self.session is not session:
            return False
        name = name + ('_backdrop_capture' if capture else '')
        self.record_draw(session, widget, name, started)
        return False

    def record_draw(self, session, widget, name, started):
        now = self.clock()
        samples = session['draws'].setdefault(name, [])
        sample = [round((started - session['started_monotonic']) * 1000, 3),
                  widget.get_allocated_width(), widget.get_allocated_height(),
                  round((now - started) * 1000, 3)]
        if not self.append_bounded(samples, sample):
            session['truncated'] = True

    def profile_frosted_refresh(self):
        session = self.session
        started = self.clock() if session is not None else 0
        try:
            return self.frosted_refresh()
        finally:
            if session is not None and self.session is session:
                self.record_draw(session, self.player.player_bar, 'frosted_refresh', started)

    def profile_shape_refresh(self):
        session = self.session
        started = self.clock() if session is not None else 0
        try:
            return self.shape_refresh()
        finally:
            if session is not None and self.session is session:
                self.record_draw(session, self.player, 'window_shape_refresh', started)

    def finish(self):
        self.timer = 0
        session = self.session
        if session is None:
            return False
        self.session = None
        if self.tick:
            self.player.remove_tick_callback(self.tick)
            self.tick = 0
        if self.heartbeat_source:
            GLib.source_remove(self.heartbeat_source)
            self.heartbeat_source = 0
        session.pop('started_monotonic')
        session['duration_ms'] = session['events'][-1][0]
        session['end_size'] = self.last_size
        session['context_end'] = self.context()
        session['frame_gap_summary'] = timing_summary(
            [sample[3] for sample in session['frames']
             if sample[0] <= session['duration_ms'] + 50])
        session['heartbeat_gap_summary'] = timing_summary(
            [sample[1] for sample in session['heartbeat']
             if sample[0] <= session['duration_ms'] + 100])
        session['draw_summary'] = {name: timing_summary([sample[3] for sample in samples])
                                   for name, samples in session['draws'].items()}
        session['version'] = 2
        try:
            self.stream.write(json.dumps(session, separators=(',', ':')) + '\n')
            self.stream.flush()
        except OSError as error:
            print(f'Resize logging stopped: {error}', file=sys.stderr)
            self.closed = True
        return False

    def close(self, *_args):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.session is not None:
            self.finish()
        self.closed = True
        self.player.frosted_bar.refresh = self.frosted_refresh
        self.player.refresh_window_shape = self.shape_refresh
        self.stream.close()
