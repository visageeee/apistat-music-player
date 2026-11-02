"""Now Playing color extraction and its local appearance preference."""

import colorsys
import json
import os
import random
import re
import tempfile
import time
from array import array
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cairo
import gi
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gtk', '3.0')
from gi.repository import GdkPixbuf, GLib, Gtk

from local_cache import read_gradient, save_gradient


SETTINGS_PATH = Path(GLib.get_user_config_dir()) / 'plex-music-prototype' / 'settings.json'
ALBUM_SIZE_RANGE = (100, 480)
ALBUM_COLUMN_RANGE = (4, 16)
ALBUM_WALL_MARGIN = 20
ALBUM_SPACING = 12
ALBUM_MARGIN_RANGE = (0, 64)
ALBUM_SPACING_RANGE = (0, 36)
NOW_SIZE_RANGE = (220, 1000)
DEFAULT_ALBUM_SIZE = 160
DEFAULT_NOW_SIZE = 360
DEFAULT_ACCENT_COLOR = '#e7a641'
THEMES = ('dark', 'black', 'light')
DEFAULT_SIDEBAR_ORDER = ('now', 'albums', 'library', 'queue', 'settings')
COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')
_gradient_executor = ThreadPoolExecutor(max_workers=1)


def render_dithered_gradient(width, height, colors):
    """Render a diagonal gradient with stable per-pixel dithering."""
    first, second = (tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
                     for color in colors)
    delta = tuple(end - start for start, end in zip(first, second))
    pixels = array('I', [0]) * (width * height)
    randomizer = random.Random(5182)
    dx, dy = max(1, width - 1), max(1, height - 1)
    denominator = dx * dx + dy * dy
    x_red = [delta[0] * x * dx / denominator for x in range(width)]
    x_green = [delta[1] * x * dx / denominator for x in range(width)]
    x_blue = [delta[2] * x * dx / denominator for x in range(width)]
    random_value = randomizer.random
    for y in range(height):
        row_offset = y * width
        red_row = first[0] + delta[0] * y * dy / denominator
        green_row = first[1] + delta[1] * y * dy / denominator
        blue_row = first[2] + delta[2] * y * dy / denominator
        for x in range(width):
            noise = (random_value() - 0.5) * 3.0 + 0.5
            red = max(0, min(255, int(red_row + x_red[x] + noise)))
            green = max(0, min(255, int(green_row + x_green[x] + noise)))
            blue = max(0, min(255, int(blue_row + x_blue[x] + noise)))
            pixels[row_offset + x] = 0xff000000 | red << 16 | green << 8 | blue
    surface = cairo.ImageSurface.create_for_data(
        pixels, cairo.FORMAT_ARGB32, width, height, width * 4)
    return surface, pixels


def cached_gradient(width, height, colors):
    surface = read_gradient(colors, width, height)
    if surface is not None:
        return surface, None
    surface, pixels = render_dithered_gradient(width, height, colors)
    try:
        save_gradient(colors, width, height, surface)
    except (OSError, cairo.Error):
        pass
    return surface, pixels


class DitheredGradient(Gtk.DrawingArea):
    """A smoothly dithered artwork gradient cached until colors or size change."""

    def __init__(self):
        super().__init__()
        self.colors = None
        self.fallback_color = '#000000'
        self._cache = None
        self._rendering = False
        self._failed_key = None
        self.connect('draw', self.draw_gradient)

    def set_colors(self, colors):
        if self.colors == colors:
            return
        self.colors = colors
        self._cache = None
        self._failed_key = None
        self.queue_draw()

    def set_fallback_color(self, color):
        if self.fallback_color != color:
            self.fallback_color = color
            self.queue_draw()

    def _start_render(self, key):
        self._rendering = True
        width, height, colors = key
        future = _gradient_executor.submit(cached_gradient, width, height, colors)
        future.add_done_callback(lambda completed: GLib.idle_add(self._finish_render, key, completed))

    def _finish_render(self, key, future):
        self._rendering = False
        current = self.get_allocated_width(), self.get_allocated_height(), self.colors
        if key == current:
            try:
                surface, pixels = future.result()
            except Exception:
                self._failed_key = key
            else:
                self._cache = key, surface, pixels
                self.queue_draw()
        elif self.colors and current[0] > 0 and current[1] > 0:
            self._start_render(current)
        return False

    def draw_gradient(self, _widget, context):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        fallback = tuple(int(self.fallback_color[index:index + 2], 16) / 255
                         for index in (1, 3, 5))
        context.set_source_rgb(*fallback)
        context.paint()
        if not self.colors or width <= 0 or height <= 0:
            return False
        key = width, height, self.colors
        if self._cache is not None and self._cache[0] == key:
            context.set_source_surface(self._cache[1], 0, 0)
        else:
            gradient = cairo.LinearGradient(0, 0, width, height)
            for offset, color in zip((0, 1), self.colors):
                channels = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
                gradient.add_color_stop_rgb(offset, *channels)
            context.set_source(gradient)
            if not self._rendering and self._failed_key != key:
                self._start_render(key)
        context.paint()
        return False


def _read_settings():
    try:
        value = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def load_gradient_enabled():
    return _read_settings().get('album_art_gradient') is True


def load_theme():
    theme = _read_settings().get('theme', 'dark')
    return theme if theme in THEMES else 'dark'


def save_theme(theme):
    if theme not in THEMES:
        raise ValueError('Invalid theme')
    settings = _read_settings()
    settings['theme'] = theme
    _write_settings(settings)


def theme_gradient_colors(colors, theme):
    if theme == 'black' or colors is None:
        return None
    if theme != 'light':
        return colors
    return tuple('#' + ''.join(f'{round(int(color[index:index + 2], 16) * 0.22 + 255 * 0.78):02x}'
                             for index in (1, 3, 5)) for color in colors)


def load_timeline_waveform_enabled():
    return _read_settings().get('waveform_timeline') is True


def save_timeline_waveform_enabled(enabled):
    settings = _read_settings()
    settings['waveform_timeline'] = bool(enabled)
    _write_settings(settings)


def load_sidebar_order():
    order = _read_settings().get('sidebar_order')
    return list(order) if (isinstance(order, list) and len(order) == 5 and
                           all(isinstance(item, str) for item in order) and
                           set(order) == set(DEFAULT_SIDEBAR_ORDER)) else list(DEFAULT_SIDEBAR_ORDER)


def save_sidebar_order(order):
    if len(order) != 5 or set(order) != set(DEFAULT_SIDEBAR_ORDER):
        raise ValueError('Invalid sidebar order')
    settings = _read_settings()
    settings['sidebar_order'] = list(order)
    _write_settings(settings)


def load_library_sort_buttons():
    value = _read_settings().get('library_sort_buttons', [])
    return [name for name in value if isinstance(name, str)] if isinstance(value, list) else []


def save_library_sort_buttons(names):
    settings = _read_settings()
    settings['library_sort_buttons'] = list(names)
    _write_settings(settings)


def load_tooltips_hidden():
    return _read_settings().get('hide_tooltips') is True


def load_art_accent_enabled():
    return _read_settings().get('art_accent_color') is True


def load_accent_color():
    color = _read_settings().get('accent_color')
    return color.lower() if isinstance(color, str) and COLOR_PATTERN.fullmatch(color) else DEFAULT_ACCENT_COLOR


def load_album_details_enabled():
    return _read_settings().get('album_grid_details') is True


def load_single_flip_enabled():
    return _read_settings().get('single_flipped_album') is True


def load_search_index_enabled():
    return _read_settings().get('cache_search_index') is True


def load_title_bar_hidden():
    return _read_settings().get('hide_title_bar') is True


def load_window_buttons_enabled():
    return _read_settings().get('compact_window_buttons') is True


def load_rounded_corners_enabled():
    return _read_settings().get('rounded_window_corners') is True


def load_text_size():
    size = _read_settings().get('text_size')
    return size if type(size) is int and 10 <= size <= 24 else 14


def load_custom_font():
    family = _read_settings().get('custom_font')
    return family if (isinstance(family, str) and len(family) <= 128 and
                      all(character.isprintable() for character in family)) else ''


def load_album_columns():
    settings = _read_settings()
    columns = settings.get('album_grid_columns')
    if type(columns) is int and ALBUM_COLUMN_RANGE[0] <= columns <= ALBUM_COLUMN_RANGE[1]:
        return columns
    old_size = settings.get('album_grid_size')
    if type(old_size) is int and ALBUM_SIZE_RANGE[0] <= old_size <= ALBUM_SIZE_RANGE[1]:
        return max(4, min(16, round(1000 / old_size)))
    return 8


def load_album_margins():
    settings = _read_settings()
    outer = settings.get('album_outer_margin', ALBUM_WALL_MARGIN)
    gap = settings.get('album_cover_spacing', ALBUM_SPACING)
    if type(outer) is not int or not ALBUM_MARGIN_RANGE[0] <= outer <= ALBUM_MARGIN_RANGE[1]:
        outer = ALBUM_WALL_MARGIN
    if type(gap) is not int or not ALBUM_SPACING_RANGE[0] <= gap <= ALBUM_SPACING_RANGE[1]:
        gap = ALBUM_SPACING
    return outer, gap


def save_album_margins(outer, gap):
    if (type(outer) is not int or not ALBUM_MARGIN_RANGE[0] <= outer <= ALBUM_MARGIN_RANGE[1]
            or type(gap) is not int or not ALBUM_SPACING_RANGE[0] <= gap <= ALBUM_SPACING_RANGE[1]):
        raise ValueError('Invalid album margins')
    settings = _read_settings()
    settings['album_outer_margin'] = outer
    settings['album_cover_spacing'] = gap
    _write_settings(settings)


def album_cover_size(view_width, columns, outer=ALBUM_WALL_MARGIN, gap=ALBUM_SPACING):
    available = max(0, view_width - (2 * outer + 18) -
                    (columns - 1) * gap)
    return max(28, min(ALBUM_SIZE_RANGE[1], available // columns))


def load_library_layout(key):
    layouts = _read_settings().get('library_layouts', {})
    value = layouts.get(key) if isinstance(layouts, dict) else None
    return value if isinstance(value, dict) else None


def save_library_layout(key, layout):
    if not isinstance(key, str) or len(key) != 64 or not isinstance(layout, dict):
        raise ValueError('Invalid library layout')
    settings = _read_settings()
    layouts = settings.get('library_layouts', {})
    if not isinstance(layouts, dict):
        layouts = {}
    layouts[key] = layout
    while len(layouts) > 256:
        layouts.pop(next(iter(layouts)))
    settings['library_layouts'] = layouts
    _write_settings(settings)


def added_age_label(added_at, now=None):
    if not added_at:
        return 'Date added unknown'
    elapsed = max(0, (time.time() if now is None else now) - added_at)
    days = int(elapsed // 86400)
    if days == 0:
        return 'Added today'
    return f'Added {days} day' + ('' if days == 1 else 's') + ' ago'


def load_art_sizes():
    settings = _read_settings()
    album = settings.get('album_grid_size')
    now = settings.get('now_art_size')
    if type(album) is not int or not ALBUM_SIZE_RANGE[0] <= album <= ALBUM_SIZE_RANGE[1]:
        album = DEFAULT_ALBUM_SIZE
    if type(now) is not int or not NOW_SIZE_RANGE[0] <= now <= NOW_SIZE_RANGE[1]:
        now = DEFAULT_NOW_SIZE
    return album, now


def _write_settings(settings):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.settings-', dir=SETTINGS_PATH.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(settings, output)
        os.replace(temporary, SETTINGS_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_gradient_enabled(enabled):
    settings = _read_settings()
    settings['album_art_gradient'] = bool(enabled)
    _write_settings(settings)


def save_tooltips_hidden(hidden):
    settings = _read_settings()
    settings['hide_tooltips'] = bool(hidden)
    _write_settings(settings)


def save_art_accent_enabled(enabled):
    settings = _read_settings()
    settings['art_accent_color'] = bool(enabled)
    _write_settings(settings)


def save_accent_color(color):
    if not isinstance(color, str) or not COLOR_PATTERN.fullmatch(color):
        raise ValueError('Invalid accent color')
    settings = _read_settings()
    settings['accent_color'] = color.lower()
    _write_settings(settings)


def save_album_details_enabled(enabled):
    settings = _read_settings()
    settings['album_grid_details'] = bool(enabled)
    _write_settings(settings)


def save_single_flip_enabled(enabled):
    settings = _read_settings()
    settings['single_flipped_album'] = bool(enabled)
    _write_settings(settings)


def save_search_index_enabled(enabled):
    settings = _read_settings()
    settings['cache_search_index'] = bool(enabled)
    _write_settings(settings)


def save_title_bar_hidden(hidden):
    settings = _read_settings()
    settings['hide_title_bar'] = bool(hidden)
    _write_settings(settings)


def save_window_buttons_enabled(enabled):
    settings = _read_settings()
    settings['compact_window_buttons'] = bool(enabled)
    _write_settings(settings)


def save_rounded_corners_enabled(enabled):
    settings = _read_settings()
    settings['rounded_window_corners'] = bool(enabled)
    _write_settings(settings)


def save_text_size(size):
    if type(size) is not int or not 10 <= size <= 24:
        raise ValueError('Invalid text size')
    settings = _read_settings()
    settings['text_size'] = size
    _write_settings(settings)


def save_custom_font(family):
    if (not isinstance(family, str) or len(family) > 128 or
            not all(character.isprintable() for character in family)):
        raise ValueError('Invalid font family')
    settings = _read_settings()
    settings['custom_font'] = family
    _write_settings(settings)


def save_album_columns(columns):
    if type(columns) is not int or not ALBUM_COLUMN_RANGE[0] <= columns <= ALBUM_COLUMN_RANGE[1]:
        raise ValueError('Invalid album column count')
    settings = _read_settings()
    settings['album_grid_columns'] = columns
    _write_settings(settings)


def save_now_art_size(size):
    if type(size) is not int or not NOW_SIZE_RANGE[0] <= size <= NOW_SIZE_RANGE[1]:
        raise ValueError('Invalid Now Playing artwork size')
    settings = _read_settings()
    settings['now_art_size'] = size
    _write_settings(settings)


def save_art_sizes(album, now):
    if (type(album) is not int or not ALBUM_SIZE_RANGE[0] <= album <= ALBUM_SIZE_RANGE[1]
            or type(now) is not int or not NOW_SIZE_RANGE[0] <= now <= NOW_SIZE_RANGE[1]):
        raise ValueError('Invalid artwork size')
    settings = _read_settings()
    settings.update(album_grid_size=album, now_art_size=now)
    _write_settings(settings)


def sample_art_colors(pixbuf):
    """Find two prominent color groups in artwork."""
    small = pixbuf.scale_simple(32, 32, GdkPixbuf.InterpType.BILINEAR)
    pixels = small.get_pixels()
    channels = small.get_n_channels()
    stride = small.get_rowstride()
    buckets = {}
    for y in range(small.get_height()):
        for x in range(small.get_width()):
            offset = y * stride + x * channels
            if channels == 4 and pixels[offset + 3] < 128:
                continue
            rgb = tuple(pixels[offset + channel] for channel in range(3))
            hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
            bucket = int(hue * 12) if saturation >= 0.14 else (12 if value < 0.5 else 13)
            weight = 0.15 + saturation * saturation * 2
            data = buckets.setdefault(bucket, [0.0, 0.0, 0.0, 0.0])
            for channel in range(3):
                data[channel] += rgb[channel] * weight
            data[3] += weight
    if not buckets:
        return None
    ranked = sorted(buckets.values(), key=lambda data: data[3], reverse=True)
    first = tuple(channel / ranked[0][3] for channel in ranked[0][:3])
    second = tuple(channel / ranked[1][3] for channel in ranked[1][:3]) if len(ranked) > 1 else first
    return first, second


def _scaled_color(rgb, maximum):
    scale = maximum / max(rgb) if max(rgb) else 0
    return '#{:02x}{:02x}{:02x}'.format(*(round(channel * scale) for channel in rgb))


def gradient_colors(pixbuf):
    """Return two dark colors sampled from artwork, suitable behind white text."""
    colors = sample_art_colors(pixbuf)
    if not colors:
        return None
    return _scaled_color(colors[0], 86), _scaled_color(colors[1], 42)


def waveform_colors(pixbuf):
    """Return bright cover colors for a waveform on a dark background."""
    colors = sample_art_colors(pixbuf)
    if not colors or max(colors[0]) < 8:
        return '#d080dc', '#e7a641'
    second = colors[1] if max(colors[1]) >= 8 else colors[0]
    return _scaled_color(colors[0], 215), _scaled_color(second, 160)
