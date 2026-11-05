"""Solid, theme-colored sidebar icons drawn with Cairo."""
import math

import cairo
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

CUSTOM_SIDEBAR_ICONS = frozenset(('now', 'albums', 'library', 'styles', 'lyrics', 'queue', 'time'))


def _sparkle(context, x, y, radius, waist):
    for point in range(8):
        angle = -math.pi / 2 + point * math.pi / 4
        distance = radius if point % 2 == 0 else waist
        px, py = x + math.cos(angle) * distance, y + math.sin(angle) * distance
        (context.move_to if point == 0 else context.line_to)(px, py)
    context.close_path()
    context.fill()


def draw_sidebar_icon(context, name, width, height, color, note_fill=None, note_accent=None):
    """Draw one icon inside its allocation; geometry uses a 28×28 canvas."""
    context.save()
    scale = min(width, height) / 28.0
    context.translate((width - 28 * scale) / 2, (height - 28 * scale) / 2)
    context.scale(scale, scale)
    context.set_source_rgb(*(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)))
    if name == 'now':
        context.arc(7, 21, 3.7, 0, 2 * math.pi)
        context.new_sub_path()
        context.arc(19, 18.5, 3.7, 0, 2 * math.pi)
        context.rectangle(10, 5, 3.2, 16)
        context.rectangle(22, 3, 3.2, 15.5)
        context.move_to(10, 5); context.line_to(25.2, 2)
        context.line_to(25.2, 6); context.line_to(10, 9)
        context.close_path()
        if note_fill is None:
            context.fill()
        else:
            accent = note_accent or color
            rgb = tuple(int(accent[index:index + 2], 16) / 255 for index in (1, 3, 5))
            context.set_source_rgb(*(component * .65 + .10 for component in rgb))
            context.fill_preserve()
            context.clip()
            context.set_line_width(2.6)
            context.set_source_rgb(*(component * .60 + .40 for component in rgb))
            phase = note_fill % 1.0
            for ring in range(7):
                context.arc(14, 15, (ring + phase) * 5.0, 0, 2 * math.pi)
                context.stroke()
    elif name == 'albums':
        for x, y in ((3, 3), (16, 3), (3, 16), (16, 16)):
            context.rectangle(x, y, 9, 9); context.fill()
    elif name == 'queue':
        context.move_to(1, 5); context.line_to(11, 14); context.line_to(1, 23)
        context.close_path(); context.fill()
        for y in (6, 13, 20):
            context.rectangle(14, y, 12, 2.5); context.fill()
    elif name == 'time':
        context.set_line_width(3)
        context.arc(14, 14, 10, 0, 2 * math.pi)
        context.stroke()
        context.set_line_width(2.7)
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.move_to(14, 7); context.line_to(14, 14); context.line_to(19, 17)
        context.stroke()
    elif name == 'library':
        context.rectangle(3.5, 5, 5, 19); context.fill()
        context.rectangle(10, 5, 5, 19); context.fill()
        context.save(); context.translate(20, 14.5); context.rotate(-math.radians(14))
        context.rectangle(-2.5, -9.5, 5, 19); context.fill(); context.restore()
    elif name == 'styles':
        _sparkle(context, 10.5, 15.5, 8.5, 3.2)
        _sparkle(context, 21, 7, 4.6, 1.8)
    elif name == 'lyrics':
        for x in (4.0, 15.0):
            context.move_to(x + 8, 6); context.line_to(x + 2, 6)
            context.curve_to(x + 0.5, 6, x, 7, x, 8.5)
            context.line_to(x, 14); context.curve_to(x, 15.4, x + 1, 16, x + 2.5, 16)
            context.line_to(x + 5, 16); context.curve_to(x + 4.9, 18.4, x + 3.6, 20, x + 1.5, 21)
            context.line_to(x + 2.5, 23); context.curve_to(x + 7, 21.8, x + 9, 18, x + 9, 13.8)
            context.line_to(x + 9, 8); context.curve_to(x + 9, 6.7, x + 8.8, 6, x + 8, 6)
            context.close_path(); context.fill()
    context.restore()


def sidebar_icon_color(player, name):
    views = getattr(player, 'content_views', None)
    active = views is not None and views.get_visible_child_name() == name
    queue_button = getattr(player, 'queue_nav', None)
    pulsing = name == 'queue' and queue_button is not None and queue_button.get_style_context().has_class('queue-pulse')
    if active or pulsing:
        art = getattr(player, 'current_art_bright', None) if getattr(player, 'art_accent_enabled', False) else None
        return art or getattr(player, 'accent_color', '#e7a641')
    return '#202326' if getattr(player, 'theme', 'dark') == 'light' else '#eeeeee'


class SidebarIcon(Gtk.DrawingArea):
    def __init__(self, player, name):
        super().__init__()
        self.player, self.name = player, name
        self.icon_scale = 1.0
        self.playing = False
        self.animation_tick = 0
        self.animation_time = 0
        self.animation_last_draw = 0
        self.set_has_window(False)
        self.set_size_request(28, 28)
        self.connect('draw', self.draw_icon)

    def set_pixel_size(self, size):
        self.icon_scale = size / 24.0
        self.queue_draw()

    def set_playing(self, playing):
        playing = bool(playing) and self.name == 'now'
        if self.playing == playing:
            return
        self.playing = playing
        if playing:
            self.animation_tick = self.add_tick_callback(self.animate_fill)
        elif self.animation_tick:
            self.remove_tick_callback(self.animation_tick)
            self.animation_tick = 0
        self.queue_draw()

    def animate_fill(self, _widget, frame_clock):
        self.animation_time = frame_clock.get_frame_time() / 1_000_000
        if self.animation_time - self.animation_last_draw >= 1 / 30:
            self.animation_last_draw = self.animation_time
            self.queue_draw()
        return self.playing

    def draw_icon(self, widget, context):
        context.save()
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        context.translate(width / 2, height / 2)
        context.scale(self.icon_scale, self.icon_scale)
        context.translate(-width / 2, -height / 2)
        draw_sidebar_icon(context, self.name, widget.get_allocated_width(),
                          widget.get_allocated_height(), sidebar_icon_color(self.player, self.name),
                          (self.animation_time * .7) % 1 if self.playing else None,
                          (getattr(self.player, 'current_art_bright', None)
                           if getattr(self.player, 'art_accent_enabled', False) else None)
                          or getattr(self.player, 'accent_color', '#e7a641'))
        context.restore()
        return False
