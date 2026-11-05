"""Optional continuous wheel motion for GTK scrolled windows."""

import math

import gi

gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk


class SmoothScroller:
    RESPONSE_RATE = 28.0

    def __init__(self, window, enabled=False):
        self.window = window
        self.adjustment = window.get_vadjustment()
        self.enabled = False
        self.source = 0
        self.setting_value = False
        self.target = 0.0
        self.last_frame_time = None
        self.last_discrete_time = None
        self.last_discrete_direction = 0
        window.connect('scroll-event', self.scroll_event)
        window.connect('destroy', self.close)
        self.adjustment_handler = self.adjustment.connect(
            'value-changed', self.adjustment_changed)
        self.set_enabled(enabled)

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.window is not None:
            # GTK's kinetic handler also moves the adjustment for wheel events,
            # which cancels the animation below before it can be seen.
            self.window.set_kinetic_scrolling(False)
        if not self.enabled:
            self.cancel()

    def cancel(self):
        if self.source:
            if self.window is not None:
                self.window.remove_tick_callback(self.source)
            self.source = 0
        self.last_frame_time = None

    def close(self, *_args):
        self.cancel()
        if self.adjustment is not None:
            self.adjustment.disconnect(self.adjustment_handler)
            self.adjustment = None
        self.window = None

    def adjustment_changed(self, _adjustment):
        if self.source and not self.setting_value:
            self.cancel()

    def scroll_event(self, _window, event):
        if (not self.enabled or event.state & (Gdk.ModifierType.CONTROL_MASK |
                                             Gdk.ModifierType.SHIFT_MASK)):
            return False
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            deltas = getattr(event, 'get_scroll_deltas', None)
            if deltas is None:
                return False
            success, delta_x, delta_y = deltas()
            if not success or abs(delta_y) < 0.001 or abs(delta_x) > abs(delta_y):
                return False
            timestamp = getattr(event, 'time', None)
            if (timestamp is not None and self.last_discrete_time is not None and
                    0 <= timestamp - self.last_discrete_time <= 15 and
                    delta_y * self.last_discrete_direction > 0):
                return True  # GDK can report the same wheel notch in both forms.
            amount = delta_y
        elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            amount = -1 if event.direction == Gdk.ScrollDirection.UP else 1
            self.last_discrete_time = getattr(event, 'time', None)
            self.last_discrete_direction = amount
        else:
            return False
        adjustment = self.adjustment
        current = adjustment.get_value()
        lower = adjustment.get_lower()
        upper = max(lower, adjustment.get_upper() - adjustment.get_page_size())
        page_size = adjustment.get_page_size()
        # Match GTK's wheel distance, which grows with the visible page.
        step = max(60.0, min(page_size ** (2.0 / 3.0), page_size / 2.0))
        anchor = self.target if self.source else current
        target = max(lower, min(upper, anchor + amount * step))
        if target == current:
            if self.source:
                # Opposite wheel input can cancel the remaining glide exactly.
                # Consume it rather than letting GTK start a competing scroll.
                self.cancel()
                self.target = current
                return True
            return False
        self.target = target
        if not self.source:
            frame_clock = self.window.get_frame_clock()
            self.last_frame_time = (frame_clock.get_frame_time()
                                    if frame_clock is not None else None)
            self.source = self.window.add_tick_callback(self.tick)
        return True

    def tick(self, _widget, frame_clock):
        if not self.enabled or self.window is None:
            self.source = 0
            return False
        now = frame_clock.get_frame_time()
        elapsed = (max(0.0, (now - self.last_frame_time) / 1_000_000)
                   if self.last_frame_time is not None else 0.0)
        self.last_frame_time = now
        if elapsed == 0:
            return True
        position = self.adjustment.get_value()
        decay = math.exp(-self.RESPONSE_RATE * elapsed)
        next_position = self.target + (position - self.target) * decay
        lower = self.adjustment.get_lower()
        upper = max(lower, self.adjustment.get_upper() -
                    self.adjustment.get_page_size())
        clamped = max(lower, min(upper, next_position))
        next_position = clamped
        finished = abs(self.target - next_position) < 0.25
        if finished:
            next_position = self.target
        self.setting_value = True
        try:
            self.adjustment.set_value(next_position)
        finally:
            self.setting_value = False
        if finished:
            self.source = 0
            return False
        return True
