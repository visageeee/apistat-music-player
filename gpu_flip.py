"""GPU album-card state, hit testing, and back-face texture generation."""
import math
import ctypes
import time
from dataclasses import dataclass, field

import cairo
import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gdk, Pango, PangoCairo
from album_highlights import show_track_duration, track_highlights

BACK_SIZE = 512
FLIP_DURATION = .38


def format_time(milliseconds):
    seconds = max(0, int(milliseconds / 1000))
    return f'{seconds // 60}:{seconds % 60:02}'


@dataclass
class GPUFlip:
    album: object
    index: int
    tracks: object = None
    error: bool = False
    offset: int = 0
    progress: float = 0.0
    start_progress: float = 0.0
    target: float = 1.0
    started: float = field(default_factory=time.monotonic)
    dirty: bool = True
    layout: object = None
    texture: object = field(default_factory=ctypes.c_uint, repr=False)

    def animate(self, now):
        elapsed = max(0.0, now - self.started)
        p = min(1.0, elapsed / FLIP_DURATION)
        eased = p * p * (3 - 2 * p)
        self.progress = self.start_progress + (self.target - self.start_progress) * eased
        return p < 1.0

    def turn(self, target, now=None):
        now = time.monotonic() if now is None else now
        self.animate(now)
        self.start_progress, self.target, self.started = self.progress, float(target), now

    @property
    def back_visible(self):
        return self.progress >= .5

    @property
    def scale(self):
        return abs(math.cos(math.pi * self.progress))


def card_layout(display_size, text_size, count, offset):
    scale = BACK_SIZE / max(1, display_size)
    # Keep track text close to the configured UI size even on smaller covers.
    # The upper bound still leaves room for the track columns and scrolling.
    font = max(14, min(76, text_size * .95 * scale))
    header = 12
    footer = max(40, font * 1.45) + 12
    explore_height = footer - 12
    explore_top = BACK_SIZE - footer
    row_height = max(27, font * 1.36)
    capacity = max(0, int((explore_top - header - 12) // row_height))
    offset = max(0, min(offset, max(0, count - capacity)))
    rows = min(capacity, max(0, count - offset))
    start = header + max(0, (explore_top - header - rows * row_height) / 2)
    return {'font': font, 'header': header, 'footer': footer,
            'show_duration': show_track_duration(display_size),
            'explore_top': explore_top, 'explore_height': explore_height,
            'explore_left': BACK_SIZE * .53, 'explore_right': BACK_SIZE - 12,
            'cover_left': 12, 'cover_right': BACK_SIZE * .53 - 12,
            'row_height': row_height, 'capacity': capacity, 'offset': offset,
            'rows': rows, 'start': start}


def card_hit(layout, local_y, display_size, tracks, local_x=None):
    y = local_y * BACK_SIZE / max(1, display_size)
    x = BACK_SIZE / 2 if local_x is None else local_x * BACK_SIZE / max(1, display_size)
    if layout['explore_top'] <= y < layout['explore_top'] + layout['explore_height']:
        if layout['explore_left'] <= x < layout['explore_right']:
            return 'explore', None
        if layout['cover_left'] <= x < layout['cover_right']:
            return 'close', None
        return None, None
    row = math.floor((y - layout['start']) / layout['row_height'])
    if tracks and 0 <= row < layout['rows']:
        return 'track', layout['offset'] + row
    return None, None


def back_pixels(flip, display_size, text_size, colors, marker, accent='#e7a641'):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, BACK_SIZE, BACK_SIZE)
    context = cairo.Context(surface)
    gradient = cairo.LinearGradient(0, 0, BACK_SIZE, BACK_SIZE)
    for offset, value in enumerate(colors):
        channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        gradient.add_color_stop_rgb(offset, *channels)
    context.set_source(gradient)
    context.paint()
    count = len(flip.tracks or ())
    layout = card_layout(display_size, text_size, count, flip.offset)
    flip.offset, flip.layout = layout['offset'], layout

    def text(value, x, y, width, font, bold=False, align=Pango.Alignment.LEFT,
             color=(1, 1, 1, .94), center_height=None):
        pango = PangoCairo.create_layout(context)
        description = Pango.FontDescription('Sans')
        description.set_absolute_size(int(font * Pango.SCALE))
        if bold:
            description.set_weight(Pango.Weight.BOLD)
        pango.set_font_description(description)
        pango.set_text(str(value), -1)
        pango.set_width(int(width * Pango.SCALE))
        pango.set_alignment(align)
        pango.set_ellipsize(Pango.EllipsizeMode.END)
        context.set_source_rgba(*color)
        if center_height is not None:
            y += (center_height - pango.get_pixel_size()[1]) / 2
        context.move_to(x, y)
        PangoCairo.show_layout(context, pango)

    if flip.tracks is None:
        label = 'Could not load tracks' if flip.error else 'Loading tracks…'
        text(label, 20, BACK_SIZE / 2 - layout['font'] / 2, BACK_SIZE - 40,
             layout['font'], align=Pango.Alignment.CENTER)
    elif not flip.tracks:
        text('No tracks found', 20, BACK_SIZE / 2 - layout['font'] / 2,
             BACK_SIZE - 40, layout['font'], align=Pango.Alignment.CENTER)
    else:
        font = layout['font']
        highlights = track_highlights(flip.tracks)
        for row in range(layout['rows']):
            index = layout['offset'] + row
            track = flip.tracks[index]
            y = layout['start'] + row * layout['row_height']
            active = marker(track.key)
            if active:
                try:
                    rgb = tuple(int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5))
                except (TypeError, ValueError):
                    rgb = (1, .75, .3)
                text(active, 10, y, font * 1.1, font, color=(*rgb, 1))
            text(str(index + 1) + '.', font * .85 + 12, y, font * 1.45, font, True)
            reserved = 5.75 if layout['show_duration'] else 3.1
            text(track.title, font * 2.35 + 12, y, max(1, BACK_SIZE - font * reserved - 25), font)
            if layout['show_duration']:
                text(format_time(track.duration), BACK_SIZE - font * 3.35 - 10, y,
                     font * 2.65, font, align=Pango.Alignment.RIGHT)
            if track.key in highlights:
                text(highlights[track.key], BACK_SIZE - font * .7 - 8, y,
                     font * .65, font * .65, color=(1, .83, .65, .85))
    try:
        rgb = tuple(int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5))
        if len(accent) != 7 or not accent.startswith('#'):
            raise ValueError('Invalid accent')
    except (TypeError, ValueError):
        rgb = (0.91, 0.65, 0.25)
    top = layout['explore_top']
    height = layout['explore_height']
    context.set_source_rgba(*rgb, .38)
    context.rectangle(layout['cover_left'], top,
                      layout['cover_right'] - layout['cover_left'], height)
    context.rectangle(layout['explore_left'], top,
                      layout['explore_right'] - layout['explore_left'], height)
    context.fill()
    button_font = min(30, layout['font'] * .82)
    text('Explore Related', layout['explore_left'] + 4, top,
         layout['explore_right'] - layout['explore_left'] - 8, button_font, True,
         Pango.Alignment.CENTER, center_height=height)
    text('‹ Cover', layout['cover_left'] + 4, top,
         layout['cover_right'] - layout['cover_left'] - 8, button_font, True,
         Pango.Alignment.CENTER, center_height=height)
    surface.flush()
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, BACK_SIZE, BACK_SIZE)
    return pixbuf.get_pixels()
