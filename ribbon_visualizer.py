"""A restrained, audio-reactive ribbon drawn with a few smooth Cairo paths."""

import math
import time
import cairo

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk


LINE_COUNT = 13
NODE_COUNT = 31
PERSPECTIVE_NODE_COUNT = 55


def approach(current, target, dt, attack, release):
    tau = attack if target > current else release
    return current + (target - current) * (1.0 - math.exp(-dt / tau))


def ribbon_profile(u, phase, mid, high):
    broad = math.sin(2 * math.pi * (2.62 * u - phase * 0.105) +
                     0.27 * math.sin(2 * math.pi * (0.82 * u + phase * 0.045)))
    broad += 0.52 * math.sin(2 * math.pi * (1.12 * u + phase * 0.055) + 3.4)
    shape = 0.18 * mid * math.sin(2 * math.pi * (3.15 * u - phase * 0.13))
    detail = 0.045 * high * math.sin(2 * math.pi * (5.2 * u + phase * 0.17))
    return (broad + shape + detail) / 1.4


def trace_curve(context, width, height, layer, phase, bass, mid, high, pulse,
                line_energy=0.0, volume=1.0):
    center = height * 0.51
    swell = min(1.0, 0.035 + 0.72 * bass + 0.26 * mid + 0.16 * pulse)
    spread = (0.25 + 0.92 * layer / (LINE_COUNT - 1)) * (1.0 + 0.32 * mid)
    amplitude = height * 0.34 * swell * spread * volume
    offset = (layer - (LINE_COUNT - 1) / 2) * 0.014
    fraction = layer / (LINE_COUNT - 1)
    ripple_cycles = 1.15 + 4.85 * fraction
    # Keep quiet bands visible while preserving a continuous response to silence.
    ripple_amplitude = height * (0.12 - 0.030 * fraction) * math.sqrt(line_energy) * volume
    points = []
    for index in range(NODE_COUNT):
        u = index / (NODE_COUNT - 1)
        shared = ribbon_profile(u, phase + offset, mid, high)
        ripple_phase = 2 * math.pi * (ripple_cycles * u -
                                      phase * (0.19 + 0.10 * fraction) +
                                      layer * 0.012)
        center_gain = 1.0 + 0.65 * math.sin(math.pi * u) ** 2
        ripple = ripple_amplitude * center_gain * (
            0.82 * math.sin(ripple_phase) + 0.18 * math.sin(ripple_phase * 0.5 + 0.7))
        points.append((width * u, center - amplitude * shared - ripple))
    trace_smooth_points(context, points)


def trace_smooth_points(context, points):
    context.move_to(*points[0])
    for index in range(len(points) - 1):
        before = points[max(0, index - 1)]
        start = points[index]
        end = points[index + 1]
        after = points[min(len(points) - 1, index + 2)]
        context.curve_to(start[0] + (end[0] - before[0]) / 6,
                         start[1] + (end[1] - before[1]) / 6,
                         end[0] - (after[0] - start[0]) / 6,
                         end[1] - (after[1] - start[1]) / 6,
                         *end)


def trace_perspective_curve(context, width, height, layer, phase,
                            bass, mid, high, pulse, line_energy=0., volume=1.):
    """Trace a string from the horizon toward the viewer."""
    fraction = layer / (LINE_COUNT - 1)
    lane = (fraction - .5) * 1.65
    swell = .08 + .50 * bass + .18 * mid + .10 * pulse
    ripple_strength = .48 * math.sqrt(max(0., line_energy))
    points = []
    for index in range(PERSPECTIVE_NODE_COUNT):
        # Continue the geometry past the viewport, so waves near the bottom
        # never expose a visible endpoint as their amplitude changes.
        depth = 1.8 * index / (PERSPECTIVE_NODE_COUNT - 1)
        perspective = depth ** 1.2
        # Decreasing phase sends the crests down the string toward the viewer.
        travel = 2 * math.pi * (2.1 * depth - phase * .30 + fraction * .10)
        wave = math.sin(travel) + .35 * math.sin(travel * .55 + 1.1)
        ripple = math.sin(2 * math.pi * ((2.5 + 2 * fraction) * depth - phase * .38 + layer * .025))
        # Let the ridges develop through the middle of the view rather than
        # concentrating all their height near the bottom edge.
        elevation = height * .17 * depth ** .55 * volume * (swell * wave + ripple_strength * ripple)
        points.append((width * (.5 + lane * perspective),
                       height * (.24 + .72 * depth) - elevation))
    trace_smooth_points(context, points)


class RibbonVisualizer(Gtk.DrawingArea):
    def __init__(self, *, windowless=False):
        super().__init__()
        if windowless:
            self.set_has_window(False)
        self.colors = (self._rgba('#5fe1df'), self._rgba('#b58cce'))
        self.view = 'ribbon'
        self.target = (0.0, 0.0, 0.0)
        self.line_target = (0.0,) * LINE_COUNT
        self.line_envelopes = [0.0] * LINE_COUNT
        self.bass = self.mid = self.high = self.pulse = 0.0
        self.phase = 0.0
        self.volume = self.target_volume = 1.0
        self.active = False
        self.playing = False
        self.last_audio = 0.0
        self.last_frame = 0.0
        self.last_render = 0.0
        self.tick_id = 0
        self._surface = None
        self._surface_size = None
        self.get_accessible().set_name('Music ribbon; click to show album artwork')
        self.connect('draw', self.draw_ribbon)

    @staticmethod
    def _rgba(color):
        result = Gdk.RGBA()
        result.parse(color)
        return result

    def set_colors(self, primary, secondary):
        self.colors = self._rgba(primary), self._rgba(secondary)
        self.queue_draw()

    def set_view(self, view):
        self.view = view if view in ('ribbon', 'perspective') else 'ribbon'
        self.queue_draw()

    def set_audio(self, levels):
        if self.active and self.playing and levels is not None:
            self.target = tuple(max(0.0, min(1.0, value)) for value in levels[:3])
            if len(levels) == 3 + LINE_COUNT:
                self.line_target = tuple(max(0.0, min(1.0, value))
                                         for value in levels[3:])
            else:
                self.line_target = (0.0,) * LINE_COUNT
            self.last_audio = time.monotonic()

    def set_volume(self, value):
        self.target_volume = max(0.0, min(1.0, float(value)))
        if self.active:
            self._start_ticking()
        else:
            self.volume = self.target_volume

    def set_active(self, active):
        self.active = bool(active)
        if self.active:
            self._start_ticking()
        else:
            self._stop_ticking()
            self.target = (0.0, 0.0, 0.0)
            self.line_target = (0.0,) * LINE_COUNT
            self.line_envelopes = [0.0] * LINE_COUNT
            self.bass = self.mid = self.high = self.pulse = 0.0

    def set_playing(self, playing):
        self.playing = bool(playing)
        if not self.playing:
            self.target = (0.0, 0.0, 0.0)
            self.line_target = (0.0,) * LINE_COUNT
        if self.active:
            self._start_ticking()

    def _start_ticking(self):
        if not self.tick_id:
            self.last_frame = time.monotonic()
            self.last_render = 0.0
            self.tick_id = self.add_tick_callback(self._tick)

    def _stop_ticking(self):
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0

    def _tick(self, _widget, _clock):
        if not self.active:
            self.tick_id = 0
            return False
        now = time.monotonic()
        if now - self.last_render < 1 / 75:
            return True
        self.last_render = now
        dt = max(0.001, min(0.05, now - self.last_frame))
        self.last_frame = now
        self.volume = approach(self.volume, self.target_volume, dt, 0.10, 0.16)
        if self.playing and now - self.last_audio > 0.9:
            self.target = (0.0, 0.0, 0.0)
            self.line_target = (0.0,) * LINE_COUNT
        bass, mid, high = self.target
        rise = max(0.0, bass - self.bass)
        self.bass = approach(self.bass, bass, dt, 0.075, 0.34)
        self.mid = approach(self.mid, mid, dt, 0.095, 0.28)
        self.high = approach(self.high, high, dt, 0.065, 0.22)
        self.pulse = approach(self.pulse, min(0.4, rise * 0.65),
                              dt, 0.06, 0.24)
        for layer, target in enumerate(self.line_target):
            fraction = layer / (LINE_COUNT - 1)
            self.line_envelopes[layer] = approach(
                self.line_envelopes[layer], target, dt,
                0.11 - 0.05 * fraction, 0.32 - 0.12 * fraction)
        if self.playing:
            self.phase += dt * (0.22 + 0.12 * self.bass + 0.06 * self.mid)
        self.queue_draw()
        if (not self.playing and
                max(self.bass, self.mid, self.high, self.pulse,
                    *self.line_envelopes) < 0.003 and
                abs(self.target_volume - self.volume) < 0.003):
            self.tick_id = 0
            return False
        return True

    def draw_ribbon(self, _widget, context):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        if width < 2 or height < 2:
            return False
        scale = 0.65
        surface_size = (max(1, math.ceil(width * scale)),
                        max(1, math.ceil(height * scale)))
        if surface_size != self._surface_size:
            self._surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *surface_size)
            self._surface_size = surface_size
        drawing = cairo.Context(self._surface)
        drawing.set_operator(cairo.OPERATOR_CLEAR)
        drawing.paint()
        drawing.set_operator(cairo.OPERATOR_OVER)
        drawing.scale(scale, scale)
        self._paint_curves(drawing, width, height)
        context.save()
        context.scale(1 / scale, 1 / scale)
        context.set_source_surface(self._surface, 0, 0)
        context.get_source().set_filter(cairo.FILTER_BILINEAR)
        context.paint()
        context.restore()
        return False

    def _paint_curves(self, context, width, height):
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.set_line_join(cairo.LINE_JOIN_ROUND)
        primary, secondary = self.colors
        perspective = self.view == 'perspective'
        for layer in range(LINE_COUNT):
            fraction = layer / (LINE_COUNT - 1)
            color = (secondary.red * (1 - fraction) + primary.red * fraction,
                     secondary.green * (1 - fraction) + primary.green * fraction,
                     secondary.blue * (1 - fraction) + primary.blue * fraction)
            strength = 0.34 + 0.66 * fraction
            context.new_path()
            if perspective:
                trace_perspective_curve(context, width, height, layer, self.phase,
                                        self.bass, self.mid, self.high, self.pulse,
                                        self.line_envelopes[layer], self.volume)
            else:
                trace_curve(context, width, height, layer, self.phase,
                            self.bass, self.mid, self.high, self.pulse,
                            self.line_envelopes[layer], self.volume)
            if perspective:
                glow = cairo.LinearGradient(0, height * .24, 0, height * .90)
                glow.add_color_stop_rgba(0, *color, 0)
                glow.add_color_stop_rgba(1, *color, 0.095 * strength)
                context.set_source(glow)
            else:
                context.set_source_rgba(*color, 0.095 * strength)
            context.set_line_width(8 + 2 * fraction + 2 * self.pulse)
            context.stroke_preserve()
            alpha = min(0.9, (0.32 + 0.50 * fraction) *
                        (0.85 + 0.13 * self.high + 0.08 * self.pulse +
                         0.08 * self.line_envelopes[layer]))
            if perspective:
                core = cairo.LinearGradient(0, height * .24, 0, height * .90)
                core.add_color_stop_rgba(0, *color, 0)
                core.add_color_stop_rgba(1, *color, alpha)
                context.set_source(core)
            else:
                context.set_source_rgba(*color, alpha)
            context.set_line_width(1.25 + 1.05 * fraction)
            context.stroke()
