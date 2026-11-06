"""Now Playing color extraction and its local appearance preference."""

import colorsys
import hashlib
import json
import os
import random
import re
import tempfile
import threading
import time
from array import array
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cairo
import gi
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Gtk', '3.0')
from gi.repository import GdkPixbuf, GLib, Gtk

from local_cache import read_gradient, save_gradient


SETTINGS_PATH = Path(GLib.get_user_config_dir()) / 'apistat' / 'settings.json'
ALBUM_SIZE_RANGE = (100, 480)
ALBUM_COLUMN_RANGE = (4, 16)
ALBUM_WALL_MARGIN = 40
ALBUM_SPACING = 30
ALBUM_MARGIN_RANGE = (0, 64)
ALBUM_SPACING_RANGE = (0, 36)
NOW_SIZE_RANGE = (220, 1000)
DEFAULT_ALBUM_SIZE = 160
DEFAULT_NOW_SIZE = 360
DEFAULT_ACCENT_COLOR = '#e7a641'
THEMES = ('dark', 'black', 'light')
DEFAULT_SIDEBAR_ORDER = ('now', 'albums', 'library', 'styles', 'queue', 'lyrics', 'time', 'settings')
COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')
_gradient_executor = ThreadPoolExecutor(max_workers=1)
_gradient_memory = OrderedDict()
_gradient_memory_lock = threading.Lock()
_gradient_noise_lock = threading.Lock()
_gradient_noise = None


def preloaded_gradient(width, height, colors):
    key = width, height, colors
    with _gradient_memory_lock:
        result = _gradient_memory.get(key)
        if result is not None:
            _gradient_memory.move_to_end(key)
        return result


def _gradient_noise_tile():
    """A reusable, low-opacity noise texture; the expensive work is done once."""
    global _gradient_noise
    with _gradient_noise_lock:
        if _gradient_noise is not None:
            return _gradient_noise
        size = 256
        pixels = array('I')
        randomizer = random.Random(5182)
        for _ in range(size * size):
            alpha = randomizer.randrange(1, 6)
            # ARGB32 stores premultiplied channels. Random black and white
            # pixels introduce a few levels of noise without tinting the art.
            channel = alpha if randomizer.getrandbits(1) else 0
            pixels.append(alpha << 24 | channel << 16 | channel << 8 | channel)
        surface = cairo.ImageSurface.create_for_data(
            pixels, cairo.FORMAT_ARGB32, size, size, size * 4)
        _gradient_noise = surface, pixels
        return _gradient_noise


def render_dithered_gradient(width, height, colors):
    """Render a diagonal gradient and subtle noise using Cairo's native paths."""
    pixels = array('I', [0]) * (width * height)
    surface = cairo.ImageSurface.create_for_data(
        pixels, cairo.FORMAT_ARGB32, width, height, width * 4)
    context = cairo.Context(surface)
    gradient = cairo.LinearGradient(0, 0, max(1, width - 1), max(1, height - 1))
    for offset, color in enumerate(colors):
        gradient.add_color_stop_rgb(offset, *(int(color[index:index + 2], 16) / 255
                                              for index in (1, 3, 5)))
    context.set_source(gradient)
    context.paint()
    noise, _noise_pixels = _gradient_noise_tile()
    pattern = cairo.SurfacePattern(noise)
    pattern.set_extend(cairo.EXTEND_REPEAT)
    context.set_source(pattern)
    context.paint()
    surface.flush()
    return surface, pixels


def cached_gradient(width, height, colors):
    ready = preloaded_gradient(width, height, colors)
    if ready is not None:
        return ready
    surface = read_gradient(colors, width, height)
    if surface is None:
        surface, pixels = render_dithered_gradient(width, height, colors)
        try:
            save_gradient(colors, width, height, surface)
        except (OSError, cairo.Error):
            pass
    else:
        pixels = None
    result = surface, pixels
    with _gradient_memory_lock:
        _gradient_memory[width, height, colors] = result
        _gradient_memory.move_to_end((width, height, colors))
        while len(_gradient_memory) > 4:
            _gradient_memory.popitem(last=False)
    return result


class DitheredGradient(Gtk.DrawingArea):
    """A smoothly dithered artwork gradient cached until colors or size change."""

    FADE_SECONDS = 0.8

    def __init__(self):
        super().__init__()
        self.colors = None
        self.fallback_color = '#000000'
        self._cache = None
        self._rendering = False
        self._failed_key = None
        self._previous = None
        self._previous_pixels = None
        self._fade_started = None
        self._fade_source = 0
        self._render_delay_source = 0
        self._scheduled_key = None
        self._disposed = False
        self.connect('draw', self.draw_gradient)
        self.connect('destroy', self._destroy_gradient)

    def _destroy_gradient(self, *_args):
        self._disposed = True
        self._stop_fade()
        if self._render_delay_source:
            GLib.source_remove(self._render_delay_source)
            self._render_delay_source = 0

    def _stop_fade(self, *_args):
        if self._fade_source:
            self.remove_tick_callback(self._fade_source)
            self._fade_source = 0

    @classmethod
    def fade_alpha(cls, elapsed):
        progress = max(0.0, min(1.0, elapsed / cls.FADE_SECONDS))
        return progress * progress * (3 - 2 * progress)

    def _fade_tick(self, _widget, _frame_clock):
        if self._fade_started is None:
            self._fade_source = 0
            return False
        self.queue_draw()
        if time.monotonic() - self._fade_started >= self.FADE_SECONDS:
            self._previous = None
            self._previous_pixels = None
            self._fade_started = None
            self._fade_source = 0
            return False
        return True

    def _begin_fade(self):
        self._fade_started = time.monotonic()
        if not self._fade_source:
            self._fade_source = self.add_tick_callback(self._fade_tick)
        self.queue_draw()

    def set_colors(self, colors):
        if self.colors == colors:
            return
        width, height = self.get_allocated_width(), self.get_allocated_height()
        old_surface = (self._cache[1] if self._cache is not None and
                       self._cache[0] == (width, height, self.colors) else None)
        if self._previous is not None and self._fade_started is None:
            previous = self._previous
            previous_pixels = self._previous_pixels
        elif self._previous is not None and width > 0 and height > 0:
            snapshot = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            snapshot_context = cairo.Context(snapshot)
            old_colors, previous_surface, old_fallback = self._previous
            self._paint_source(snapshot_context, width, height, old_colors,
                               previous_surface, old_fallback)
            self._paint_source(snapshot_context, width, height, self.colors,
                               old_surface, self.fallback_color,
                               self.fade_alpha(time.monotonic() - self._fade_started))
            previous = (None, snapshot, self.fallback_color)
            previous_pixels = None
        else:
            previous = (self.colors, old_surface, self.fallback_color)
            previous_pixels = self._cache[2] if old_surface is not None else None
        self._previous = previous
        self._previous_pixels = previous_pixels
        self._fade_started = None
        self.colors = colors
        self._cache = None
        self._failed_key = None
        ready = (preloaded_gradient(width, height, colors)
                 if colors and width > 0 and height > 0 else None)
        if ready is not None:
            self._cache = (width, height, colors), ready[0], ready[1]
        if colors is None or ready is not None:
            self._begin_fade()
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

    def _schedule_render(self, key):
        if self._scheduled_key == key and self._render_delay_source:
            return
        if self._render_delay_source:
            GLib.source_remove(self._render_delay_source)
        self._scheduled_key = key
        self._render_delay_source = GLib.timeout_add(180, self._render_after_resize)

    def _render_after_resize(self):
        self._render_delay_source = 0
        key = self._scheduled_key
        current = self.get_allocated_width(), self.get_allocated_height(), self.colors
        if not self._disposed and key == current and not self._rendering:
            self._start_render(key)
        return False

    def _finish_render(self, key, future):
        self._rendering = False
        if self._disposed:
            return False
        current = self.get_allocated_width(), self.get_allocated_height(), self.colors
        if key == current:
            try:
                surface, pixels = future.result()
            except Exception:
                self._failed_key = key
                if self._previous is not None:
                    self._begin_fade()
            else:
                self._cache = key, surface, pixels
                if self._previous is not None:
                    self._begin_fade()
                else:
                    self.queue_draw()
        elif self.colors and current[0] > 0 and current[1] > 0:
            self._schedule_render(current)
        return False

    def draw_gradient(self, _widget, context):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0 or height <= 0:
            return False
        key = width, height, self.colors
        surface = self._cache[1] if self._cache is not None and self._cache[0] == key else None
        if self.colors and surface is None and not self._rendering and self._failed_key != key:
            self._schedule_render(key)
        if self._previous is not None:
            old_colors, old_surface, old_fallback = self._previous
            self._paint_source(context, width, height, old_colors, old_surface, old_fallback)
            if self._fade_started is None:
                return False
            alpha = self.fade_alpha(time.monotonic() - self._fade_started)
            self._paint_source(context, width, height, self.colors, surface,
                               self.fallback_color, alpha)
        else:
            self._paint_source(context, width, height, self.colors, surface,
                               self.fallback_color)
        return False

    @staticmethod
    def _paint_source(context, width, height, colors, surface, fallback, alpha=1.0):
        if surface is not None and surface.get_width() == width and surface.get_height() == height:
            context.set_source_surface(surface, 0, 0)
        elif colors:
            gradient = cairo.LinearGradient(0, 0, width, height)
            for offset, color in zip((0, 1), colors):
                channels = tuple(int(color[index:index + 2], 16) / 255
                                 for index in (1, 3, 5))
                gradient.add_color_stop_rgb(offset, *channels)
            context.set_source(gradient)
        else:
            channels = tuple(int(fallback[index:index + 2], 16) / 255
                             for index in (1, 3, 5))
            context.set_source_rgb(*channels)
        context.paint_with_alpha(alpha)


def _read_settings():
    try:
        value = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def load_gradient_enabled():
    return _read_settings().get('album_art_gradient', True) is True


def load_background_visualizer_enabled():
    return _read_settings().get('background_visualizer', False) is True


def save_background_visualizer_enabled(enabled):
    settings = _read_settings()
    settings['background_visualizer'] = bool(enabled)
    _write_settings(settings)


def load_library_view_mode():
    mode = _read_settings().get('library_view_mode', 'songs')
    return mode if mode in ('songs', 'albums') else 'songs'


def save_library_view_mode(mode):
    if mode not in ('songs', 'albums'):
        raise ValueError('Invalid library view mode')
    settings = _read_settings()
    settings['library_view_mode'] = mode
    _write_settings(settings)


def load_gpu_album_wall_enabled():
    return _read_settings().get('gpu_album_wall', True) is True


def save_gpu_album_wall_enabled(enabled):
    settings = _read_settings()
    settings['gpu_album_wall'] = bool(enabled)
    _write_settings(settings)


def load_classic_album_wall_enabled():
    return _read_settings().get('classic_album_wall', False) is True


def save_classic_album_wall_enabled(enabled):
    settings = _read_settings()
    settings['classic_album_wall'] = bool(enabled)
    _write_settings(settings)


def load_info_panel_width():
    width = _read_settings().get('info_panel_width', 300)
    return width if type(width) is int and 240 <= width <= 1000 else 300


def save_info_panel_width(width):
    if type(width) is not int or not 240 <= width <= 1000:
        raise ValueError('Invalid information panel width')
    settings = _read_settings()
    settings['info_panel_width'] = width
    _write_settings(settings)


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
    return _read_settings().get('waveform_timeline', True) is True


def save_timeline_waveform_enabled(enabled):
    settings = _read_settings()
    settings['waveform_timeline'] = bool(enabled)
    _write_settings(settings)


def load_sidebar_order():
    order = _read_settings().get('sidebar_order')
    if isinstance(order, list) and all(isinstance(item, str) for item in order):
        if len(order) == len(DEFAULT_SIDEBAR_ORDER) and set(order) == set(DEFAULT_SIDEBAR_ORDER):
            return list(order)
        allowed_missing = {'styles', 'lyrics', 'time'}
        missing = set(DEFAULT_SIDEBAR_ORDER) - set(order)
        if (missing <= allowed_missing and len(order) == len(set(order)) and
                set(order) <= set(DEFAULT_SIDEBAR_ORDER) and 'settings' in order):
            result = list(order)
            for name in DEFAULT_SIDEBAR_ORDER:
                if name in missing:
                    result.insert(result.index('settings'), name)
            return result
    return list(DEFAULT_SIDEBAR_ORDER)


def save_sidebar_order(order):
    if len(order) != len(DEFAULT_SIDEBAR_ORDER) or set(order) != set(DEFAULT_SIDEBAR_ORDER):
        raise ValueError('Invalid sidebar order')
    settings = _read_settings()
    settings['sidebar_order'] = list(order)
    _write_settings(settings)


def load_playlist_order(address, token):
    scope = hashlib.sha256((address + '\0' + token).encode('utf-8')).hexdigest()
    orders = _read_settings().get('playlist_orders', {})
    order = orders.get(scope, []) if isinstance(orders, dict) else []
    if not isinstance(order, list):
        return []
    return list(dict.fromkeys(key for key in order[:10000]
                              if isinstance(key, str) and
                              re.fullmatch(r'/playlists/\d+/items', key)))


def save_playlist_order(address, token, order):
    if (len(order) > 10000 or len(set(order)) != len(order) or
            any(not isinstance(key, str) or not re.fullmatch(r'/playlists/\d+/items', key)
                for key in order)):
        raise ValueError('Invalid playlist order')
    scope = hashlib.sha256((address + '\0' + token).encode('utf-8')).hexdigest()
    settings = _read_settings()
    orders = settings.get('playlist_orders')
    if not isinstance(orders, dict):
        orders = {}
    orders[scope] = list(order)
    settings['playlist_orders'] = orders
    _write_settings(settings)


def load_sidebar_note_animation_enabled():
    return bool(_read_settings().get('sidebar_note_animation_enabled', True))


def save_sidebar_note_animation_enabled(enabled):
    settings = _read_settings()
    settings['sidebar_note_animation_enabled'] = bool(enabled)
    _write_settings(settings)


def load_sidebar_labels_enabled():
    return bool(_read_settings().get('sidebar_labels_enabled', False))


def save_sidebar_labels_enabled(enabled):
    settings = _read_settings()
    settings['sidebar_labels_enabled'] = bool(enabled)
    _write_settings(settings)


def load_sidebar_visible():
    settings = _read_settings()
    names = settings.get('sidebar_visible')
    optional = set(DEFAULT_SIDEBAR_ORDER) - {'settings'}
    if (isinstance(names, list) and
            all(isinstance(name, str) and name in optional for name in names) and
            len(names) == len(set(names))):
        result = set(names) | {'settings'}
        if settings.get('sidebar_visibility_version') not in (2, 3):
            result.add('lyrics')
        if settings.get('sidebar_visibility_version') != 3:
            result.add('time')
        return result
    return set(DEFAULT_SIDEBAR_ORDER)


def save_sidebar_visible(names):
    names = set(names)
    if not names <= set(DEFAULT_SIDEBAR_ORDER) or 'settings' not in names:
        raise ValueError('Invalid visible sidebar buttons')
    settings = _read_settings()
    settings['sidebar_visible'] = [name for name in DEFAULT_SIDEBAR_ORDER
                                   if name in names and name != 'settings']
    settings['sidebar_visibility_version'] = 3
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


def load_star_ratings_hidden():
    return _read_settings().get('hide_star_ratings') is True


def load_search_shortcut():
    value = _read_settings().get('search_shortcut', 'Tab')
    if not isinstance(value, str) or len(value) > 100:
        return 'Tab'
    key, _modifiers = Gtk.accelerator_parse(value)
    return value if key else 'Tab'


def save_search_shortcut(accelerator):
    key, _modifiers = Gtk.accelerator_parse(accelerator)
    if not key:
        raise ValueError('Invalid search shortcut')
    settings = _read_settings()
    settings['search_shortcut'] = accelerator
    _write_settings(settings)


def load_smooth_scrolling_enabled():
    return _read_settings().get('smooth_scrolling', True) is True


def load_art_accent_enabled():
    return _read_settings().get('art_accent_color') is True


def load_accent_color():
    color = _read_settings().get('accent_color')
    return color.lower() if isinstance(color, str) and COLOR_PATTERN.fullmatch(color) else DEFAULT_ACCENT_COLOR


def load_album_details_enabled():
    return _read_settings().get('album_grid_details', True) is True


def load_single_flip_enabled():
    return _read_settings().get('single_flipped_album') is True


def load_search_index_enabled():
    return _read_settings().get('cache_search_index') is True


def load_title_bar_hidden():
    return _read_settings().get('hide_title_bar') is True


def load_window_buttons_enabled():
    return _read_settings().get('compact_window_buttons') is True


def load_rounded_corners_enabled():
    return _read_settings().get('rounded_window_corners', True) is True


def load_frosted_player_bar():
    return _read_settings().get('frosted_player_bar') is True


def load_text_size():
    size = _read_settings().get('text_size')
    return size if type(size) is int and 10 <= size <= 24 else 18


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
    return 5


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


def load_keep_style_playing_enabled():
    return _read_settings().get('keep_style_playing') is True


def save_keep_style_playing_enabled(enabled):
    if type(enabled) is not bool:
        raise ValueError('Expected a checkbox value')
    settings = _read_settings()
    settings['keep_style_playing'] = enabled
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


def save_star_ratings_hidden(hidden):
    settings = _read_settings()
    settings['hide_star_ratings'] = bool(hidden)
    _write_settings(settings)


def save_smooth_scrolling_enabled(enabled):
    settings = _read_settings()
    settings['smooth_scrolling'] = bool(enabled)
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


def save_frosted_player_bar(enabled):
    settings = _read_settings()
    settings['frosted_player_bar'] = bool(enabled)
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
