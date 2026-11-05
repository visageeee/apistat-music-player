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
    font = max(14, min(100, text_size * .78 * scale))
    title_font = min(112, font * 1.06)
    header = max(46, title_font * 2.1)
    footer = max(40, font * 1.8)
    row_height = max(27, font * 1.36)
    capacity = max(0, int((BACK_SIZE - header - footer - 12) // row_height))
    offset = max(0, min(offset, max(0, count - capacity)))
    rows = min(capacity, max(0, count - offset))
    start = header + max(0, (BACK_SIZE - header - footer - rows * row_height) / 2)
    return {'font': font, 'title_font': title_font, 'header': header, 'footer': footer,
            'row_height': row_height, 'capacity': capacity, 'offset': offset,
            'rows': rows, 'start': start}


def card_hit(layout, local_y, display_size, tracks):
    y = local_y * BACK_SIZE / max(1, display_size)
    if y < layout['header']:
        return 'album', None
    if y >= BACK_SIZE - layout['footer']:
        return 'close', None
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

    def text(value, x, y, width, font, bold=False, align=Pango.Alignment.LEFT, color=(1, 1, 1, .94)):
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
        context.move_to(x, y)
        PangoCairo.show_layout(context, pango)

    text(flip.album.title, 18, 12, BACK_SIZE - 36, layout['title_font'], True,
         Pango.Alignment.CENTER)
    if flip.tracks is None:
        label = 'Could not load tracks' if flip.error else 'Loading tracks…'
        text(label, 20, BACK_SIZE / 2 - layout['font'] / 2, BACK_SIZE - 40,
             layout['font'], align=Pango.Alignment.CENTER)
    elif not flip.tracks:
        text('No tracks found', 20, BACK_SIZE / 2 - layout['font'] / 2,
             BACK_SIZE - 40, layout['font'], align=Pango.Alignment.CENTER)
    else:
        font = layout['font']
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
            text(str(index + 1) + '.', font * 1.1 + 12, y, font * 2.1, font, True)
            text(track.title, font * 3.3 + 12, y, max(1, BACK_SIZE - font * 7.2 - 25), font)
            text(format_time(track.duration), BACK_SIZE - font * 3.7 - 10, y,
                 font * 3.0, font, align=Pango.Alignment.RIGHT)
    text('‹ Cover', 18, BACK_SIZE - layout['footer'] + 6,
         BACK_SIZE - 36, layout['font'], align=Pango.Alignment.CENTER)
    surface.flush()
    pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0, BACK_SIZE, BACK_SIZE)
    return pixbuf.get_pixels()
