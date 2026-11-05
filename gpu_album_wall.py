"""Virtualized GPU album wall for GTK 3."""
import ctypes
import math
from types import SimpleNamespace
import time

import cairo
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango, PangoCairo

from app_assets import placeholder_art
from appearance import added_age_label
from local_cache import LocalCache
from gpu_offscreen import create_offscreen_gpu, GL_BGRA
from background_drag_scroll import BackgroundDragScroller
from gpu_flip import BACK_SIZE, GPUFlip, back_pixels, card_hit, card_layout
from gpu_glass import GPUBlur, glass_rect
from gpu_gl import (GLProgram, load_gl, GL_TEXTURE_2D, GL_TEXTURE0, GL_BLEND, GL_RGBA, GL_UNSIGNED_BYTE,
                    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_LINEAR,
                    GL_COLOR_BUFFER_BIT, GL_ARRAY_BUFFER, GL_STREAM_DRAW, GL_TRIANGLES)

ATLAS_LIMIT = 4096
LOW_CELL = 128
MEDIUM_CELL = 256
HIGH_CELL = 512
GL_MAX_TEXTURE_SIZE = 0x0D33
PREFETCH_ROWS = 2
DRAG_GRACE_SECONDS = .12
DRAG_DISTANCE = 12


def atlas_cell_size(display_pixels, atlas_size, visible_count):
    """Choose the sharpest practical tier while leaving room for visible covers."""
    desired = HIGH_CELL if display_pixels > MEDIUM_CELL else MEDIUM_CELL
    for size in (desired, MEDIUM_CELL, LOW_CELL):
        columns = atlas_size // size
        if columns > 0 and columns * columns - 1 >= visible_count:
            return size
    return LOW_CELL


class GPUAlbumWall(Gtk.Box, GLProgram):
    """Draw only visible covers, keeping artwork in a bounded GPU atlas."""
    def __init__(self, player, failed):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL)
        self.player = player
        self.failed_callback = failed
        self.gl = load_gl()
        self.texture, self.vao, self.buffer = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        self.program = 0
        self.ready = False
        self.offscreen = None
        self.frame_surface = None
        self.scene_dirty = True
        self.closed = False
        self.frame_source = 0
        self.epoch = 0
        self.albums = []
        self.client = None
        self.atlas_size = ATLAS_LIMIT
        self.cell_size = MEDIUM_CELL
        self.atlas_columns = self.atlas_size // self.cell_size
        self.capacity = self.atlas_columns ** 2
        self.art_revision = 0
        self.needed_indices = set()
        self.slots = {}
        self.slot_keys = [None] * self.capacity
        self.slot_pixels = {}
        self.pending = set()
        self.failed_art = set()
        self.uploads = []
        self.art_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix='gpu-album-art')
        self.adjustment = Gtk.Adjustment()
        self.background_scroller = BackgroundDragScroller(self.adjustment)
        self.adjustment.connect('value-changed', self.changed)
        self.overlay = Gtk.Overlay()
        self.overlay.set_hexpand(True)
        self.overlay.set_vexpand(True)
        self.area = Gtk.DrawingArea()
        self.area.set_has_window(False)
        self.area.connect('realize', self.realize_gl)
        self.area.connect('unrealize', self.unrealize_gl)
        self.area.connect('draw', self.draw_gpu)
        self.area.connect('map', self.area_mapped)
        self.area.connect('unmap', self.area_unmapped)
        self.area.connect('size-allocate', self.size_changed)
        self.input_surface = Gtk.EventBox()
        self.input_surface.set_visible_window(False)
        self.input_surface.set_above_child(True)
        self.input_surface.set_hexpand(True)
        self.input_surface.set_vexpand(True)
        self.input_surface.connect('scroll-event', self.scroll)
        self.input_surface.connect('button-press-event', self.pressed)
        self.input_surface.connect('button-release-event', self.released)
        self.input_surface.connect('motion-notify-event', self.drag_motion)
        self.input_surface.connect('drag-begin', self.drag_begin)
        self.input_surface.connect('drag-end', self.drag_end)
        self.input_surface.connect('drag-data-get', self.drag_data_get)
        self.drag_album = None
        self.dragging = False
        self.drag_started_at = None
        self.drag_origin = None
        self.drag_exceeded = False
        self.drag_targets = None
        self.input_surface.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK |
                                      Gdk.EventMask.BUTTON_PRESS_MASK |
                                      Gdk.EventMask.BUTTON_RELEASE_MASK |
                                      Gdk.EventMask.POINTER_MOTION_MASK)
        self.overlay.add(self.area)
        self.labels = Gtk.DrawingArea()
        # Keep labels in the same native surface as the GL scene. A separate
        # drawing-area window can retain black damage after GL composition.
        self.labels.set_has_window(False)
        self.labels.connect('draw', self.draw_labels)
        self.overlay.add_overlay(self.labels)
        self.overlay.set_overlay_pass_through(self.labels, True)
        self.overlay.add_overlay(self.input_surface)
        self.flip = None
        self.flips = {}
        self.pending_exclusive_flip = None
        self.flip_tick_id = 0
        self.retired_textures = []
        self.glass_renderer = None
        self.glass_surfaces = {}
        self.glass_failed = False
        self.pressed_hit = None
        self.drag_track = None
        self.flip_scroll_remainder = 0.0
        self.render_surface = Gtk.EventBox()
        self.render_surface.set_visible_window(True)
        self.render_surface.set_app_paintable(True)
        self.render_surface.set_margin_top(36)
        self.render_surface.connect('draw', self.draw_background)
        self.render_surface.add(self.overlay)
        self.pack_start(self.render_surface, True, True, 0)
        background = getattr(player, 'shared_background', None)
        self.background_state = None
        if background is not None:
            background.connect_after('draw', self.shared_background_drawn)
        visualizer = getattr(player, 'background_visualizer', None)
        if visualizer is not None:
            visualizer.connect_after('draw', self.visualizer_drawn)
        self.scrollbar = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=self.adjustment)
        self.scrollbar.set_margin_top(36)
        self.pack_start(self.scrollbar, False, False, 0)
        self.set_name('gpu-album-wall')
        self.input_surface.set_can_focus(True)
        self.input_surface.connect('key-press-event', player.search_escape_pressed)
        self.input_surface.get_accessible().set_name('Album wall')

    def draw_background(self, _widget, context):
        background = getattr(self.player, 'shared_background', None)
        if background is None:
            return False
        position = self.render_surface.translate_coordinates(background, 0, 0)
        if position is None:
            return False
        context.save()
        context.translate(-position[-2], -position[-1])
        background.draw_gradient(background, context)
        visualizer = getattr(self.player, 'background_visualizer', None)
        if visualizer is not None and visualizer.get_visible():
            visualizer.draw_ribbon(visualizer, context)
        context.restore()
        return False

    def visualizer_drawn(self, _visualizer, _context):
        if not self.closed and self.render_surface.get_mapped():
            self.render_surface.queue_draw()
        return False

    def shared_background_drawn(self, background, _context):
        if self.closed or not self.render_surface.get_mapped():
            return False
        fade = background._fade_started
        state = (background.colors, background.fallback_color,
                 id(background._cache), id(background._previous), fade,
                 int((time.monotonic() - fade) * 60) if fade is not None else None)
        if state != self.background_state:
            self.background_state = state
            self.render_surface.queue_draw()
        return False

    def set_bottom_inset(self, inset):
        inset = max(0, int(inset))
        if self.render_surface.get_margin_bottom() != inset:
            self.render_surface.set_margin_bottom(inset)
            self.scrollbar.set_margin_bottom(inset)

    def clear_card(self):
        for flip in self.flips.values():
            if flip.texture.value:
                self.retired_textures.append(flip.texture)
        self.flips.clear()
        self.flip = None
        self.pending_exclusive_flip = None
        self.flip_scroll_remainder = 0.0
        self.pressed_hit = None
        self.drag_track = None
        if self.flip_tick_id:
            self.area.remove_tick_callback(self.flip_tick_id)
            self.flip_tick_id = 0
        self.queue_frame()

    def toggle_album(self, album):
        try:
            index = next(i for i, item in enumerate(self.albums) if item is album)
        except StopIteration:
            return
        if index in self.flips:
            flip = self.flips[index]
            flip.turn(0 if flip.target else 1)
            self.flip = flip
            self.pending_exclusive_flip = (flip if flip.target and
                                           self.player.single_flip_enabled else None)
        else:
            flip = GPUFlip(album, index)
            flip.texture = ctypes.c_uint()
            self.flip_scroll_remainder = 0.0
            self.flip = flip
            self.flips[index] = flip
            self.pending_exclusive_flip = flip if self.player.single_flip_enabled else None
            client, epoch = self.client, self.epoch
            if client is not None:
                def loaded(tracks):
                    flip.tracks = tracks
                    flip.dirty = True
                    self.queue_frame()
                def failed():
                    flip.error = True
                    flip.dirty = True
                    self.queue_frame()
                self.player.async_work(lambda: client.tracks(album), loaded,
                                       lambda: self.flips.get(index) is flip and self.epoch == epoch and
                                       self.client is client, failed)
        if not self.flip_tick_id:
            self.flip_tick_id = self.area.add_tick_callback(self.animate_flip)
        self.queue_frame()

    def animate_flip(self, _area, _clock):
        if self.closed or not self.flips:
            self.flip_tick_id = 0
            return False
        now = time.monotonic()
        running = False
        for index, flip in list(self.flips.items()):
            still_running = flip.animate(now)
            running = running or still_running
            if not still_running and flip.target == 0:
                if flip.texture.value:
                    self.retired_textures.append(flip.texture)
                del self.flips[index]
                if self.flip is flip:
                    self.flip = next(reversed(self.flips.values()), None)
        selected = self.pending_exclusive_flip
        if (selected is not None and selected.target == 1 and
                selected.progress >= 1 and self.flips.get(selected.index) is selected):
            self.pending_exclusive_flip = None
            for other in self.flips.values():
                if other is not selected and other.target != 0:
                    other.turn(0, now)
                    running = True
        self.queue_frame()
        if not running:
            self.flip_tick_id = 0
            return False
        return True

    def enforce_single_flip(self):
        if not self.flip:
            return
        now = time.monotonic()
        for flip in self.flips.values():
            if flip is not self.flip and flip.target != 0:
                flip.turn(0, now)
        if not self.flip_tick_id:
            self.flip_tick_id = self.area.add_tick_callback(self.animate_flip)
        self.queue_frame()

    def refresh_flip(self):
        if self.flips:
            for flip in self.flips.values():
                flip.dirty = True
            self.queue_frame()

    def flip_colors(self, index):
        data = self.slot_pixels.get(self.slots.get(index))
        if not data:
            return ('#292238', '#111e2b')
        channels = [[], [], []]
        for i in range(0, len(data), 4 * 97):
            if data[i + 3] >= 128:
                for n in range(3):
                    channels[n].append(data[i + n])
        if not channels[0]:
            return ('#292238', '#111e2b')
        avg = [sum(values) / len(values) for values in channels]
        color = lambda factor, extra: '#' + ''.join(
            f'{max(0, min(255, round(value * factor + extra))):02x}' for value in avg)
        return color(.38, 12), color(.14, 8)

    def fail(self):
        if not self.closed:
            self.ready = False
            GLib.idle_add(self.failed_callback)
        return False

    def realize_gl(self, _area):
        try:
            self.offscreen = create_offscreen_gpu(self.gl)
            with self.offscreen.current():
                self.setup_program()
                gl = self.gl
                gl.glActiveTexture(GL_TEXTURE0)
                maximum = ctypes.c_int()
                gl.glGetIntegerv(GL_MAX_TEXTURE_SIZE, ctypes.byref(maximum))
                if maximum.value < LOW_CELL * 2:
                    raise RuntimeError('GPU texture limit is too small for the album wall')
                self.atlas_size = min(ATLAS_LIMIT, maximum.value)
                self.cell_size = MEDIUM_CELL if self.atlas_size >= MEDIUM_CELL * 2 else LOW_CELL
                self.atlas_columns = self.atlas_size // self.cell_size
                self.capacity = self.atlas_columns ** 2
                self.slot_keys = [None] * self.capacity
                gl.glGenTextures(1, ctypes.byref(self.texture))
                gl.glBindTexture(GL_TEXTURE_2D, self.texture)
                gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, self.atlas_size, self.atlas_size,
                                0, GL_RGBA, GL_UNSIGNED_BYTE, None)
                self.upload(0, self.pixbuf_bytes(placeholder_art(self.cell_size, 0.6), self.cell_size))
                if gl.glGetError():
                    raise RuntimeError('GPU initialization failed')
                self.ready = True
            self.queue_frame()
        except (OSError, RuntimeError, AttributeError, ValueError):
            if self.offscreen is not None:
                self.offscreen.close()
                self.offscreen = None
            return self.fail()
        return False

    def unrealize_gl(self, _area):
        self.ready = False
        self.art_revision += 1
        self.pending.clear()
        self.needed_indices.clear()
        if self.offscreen is not None:
            try:
                with self.offscreen.current():
                    gl = self.gl
                    if self.texture.value:
                        gl.glDeleteTextures(1, ctypes.byref(self.texture))
                    for flip in self.flips.values():
                        if flip.texture.value:
                            gl.glDeleteTextures(1, ctypes.byref(flip.texture))
                            flip.texture = ctypes.c_uint()
                        flip.dirty = True
                    for texture in self.retired_textures:
                        if texture.value:
                            gl.glDeleteTextures(1, ctypes.byref(texture))
                    self.retired_textures.clear()
                    if self.glass_renderer is not None:
                        self.glass_renderer.close()
                        self.glass_renderer = None
                    self.glass_surfaces.clear()
                    if self.buffer.value:
                        gl.glDeleteBuffers(1, ctypes.byref(self.buffer))
                    if self.vao.value:
                        gl.glDeleteVertexArrays(1, ctypes.byref(self.vao))
                    if self.program:
                        gl.glDeleteProgram(self.program)
                    self.offscreen.release_target()
            finally:
                self.offscreen.close()
                self.offscreen = None
        self.frame_surface = None
        self.scene_dirty = True
        self.texture, self.buffer, self.vao, self.program = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), 0
        self.slots.clear()
        self.slot_keys = [None] * self.capacity
        self.slot_pixels.clear()
        self.uploads.clear()

    def draw_gpu(self, area, context):
        if self.closed or not self.ready or self.offscreen is None:
            return False
        scale = area.get_scale_factor()
        width = max(1, area.get_allocated_width() * scale)
        height = max(1, area.get_allocated_height() * scale)
        if self.scene_dirty or self.frame_surface is None or self.offscreen.size != (width, height):
            try:
                with self.offscreen.current():
                    self.offscreen.target(width, height)
                    self.render(area, None)
                    if (self.frame_surface is None or self.frame_surface.get_width() != width or
                            self.frame_surface.get_height() != height):
                        self.frame_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                    pixels = (ctypes.c_ubyte * (self.frame_surface.get_stride() * height)).from_buffer(
                        self.frame_surface.get_data())
                    self.gl.glReadPixels(0, 0, width, height, GL_BGRA, GL_UNSIGNED_BYTE, pixels)
                    if self.gl.glGetError():
                        raise RuntimeError('GPU wall readback failed')
                    self.frame_surface.mark_dirty()
                    self.scene_dirty = False
            except (OSError, RuntimeError, AttributeError, ValueError, GLib.Error, MemoryError):
                return self.fail()
        context.save()
        context.scale(1 / scale, 1 / scale)
        context.translate(0, height)
        context.scale(1, -1)
        context.set_source_surface(self.frame_surface, 0, 0)
        context.paint()
        context.restore()
        return False

    def shutdown(self):
        self.closed = True
        self.epoch += 1
        if self.frame_source:
            GLib.source_remove(self.frame_source)
            self.frame_source = 0
        self.art_workers.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def pixbuf_bytes(image, size):
        if not image.get_has_alpha():
            image = image.add_alpha(False, 0, 0, 0)
        if image.get_width() != size or image.get_height() != size:
            image = image.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
        source = image.get_pixels()
        stride = image.get_rowstride()
        return b''.join(source[row * stride:row * stride + size * 4] for row in range(size))

    def set_albums(self, client, albums, reset=False):
        if reset or client is not self.client:
            self.clear_card()
            self.epoch += 1
            self.art_revision += 1
            self.client = client
            self.albums = []
            self.slots.clear()
            self.slot_keys = [None] * self.capacity
            self.slot_pixels.clear()
            self.pending.clear()
            self.failed_art.clear()
            self.uploads.clear()
            self.adjustment.set_value(0)
        self.albums.extend(albums)
        self.layout_changed()

    def geometry(self):
        width = max(1, self.area.get_allocated_width())
        size = max(1, self.player.album_art_size)
        gap = self.player.album_spacing
        margin = self.player.album_margin
        columns = max(1, min(16, (max(0, width - 2 * margin) + gap) // (size + gap)))
        extra = (3 * (self.player.text_size + 4) + 6) if self.player.show_album_details else 0
        row_height = size + gap + extra
        total = math.ceil(len(self.albums) / columns) * row_height + margin
        x0 = max(margin, (width - (columns * size + (columns - 1) * gap)) // 2)
        return width, size, gap, margin, columns, row_height, total, x0

    def layout_changed(self):
        for flip in self.flips.values():
            flip.dirty = True
        _width, _size, _gap, _margin, _cols, row_height, total, _x0 = self.geometry()
        height = max(1, self.area.get_allocated_height())
        value = min(self.adjustment.get_value(), max(0, total - height))
        self.adjustment.configure(value, 0, max(total, height), row_height / 3,
                                  height * .8, height)
        self.queue_frame()
        self.labels.queue_draw()

    def queue_frame(self):
        """Coalesce updates without invalidating unrelated GTK widgets."""
        self.scene_dirty = True
        if self.closed or not self.area.get_mapped():
            return
        if not self.frame_source:
            self.frame_source = GLib.timeout_add(0, self.flush_frame, priority=GLib.PRIORITY_HIGH)

    def flush_frame(self):
        self.frame_source = 0
        if not self.closed and self.area.get_mapped():
            self.area.queue_draw()
        return False

    def area_mapped(self, _area):
        self.area.add_tick_callback(self.first_frame_tick)

    def first_frame_tick(self, _area, _clock):
        self.queue_frame()
        return False

    def area_unmapped(self, _area):
        if self.frame_source:
            GLib.source_remove(self.frame_source)
            self.frame_source = 0

    def size_changed(self, *_):
        self.layout_changed()

    def changed(self, *_):
        self.queue_frame()
        self.labels.queue_draw()
        if (self.adjustment.get_value() + self.adjustment.get_page_size() >=
                self.adjustment.get_upper() - 160):
            GLib.idle_add(self.player.gpu_load_more_albums)

    def scroll(self, _area, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            result = self.player.zoom_art(self.area, event, 'albums')
            self.layout_changed()
            return result
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            valid, _dx, dy = event.get_scroll_deltas()
            step = dy if valid else 0
        else:
            step = -1 if event.direction == Gdk.ScrollDirection.UP else 1
        if self.flips:
            for index, x, y in self.visible():
                flip = self.flips.get(index)
                if (flip and flip.back_visible and flip.tracks and
                        x <= event.x < x + self.player.album_art_size and
                        y <= event.y < y + self.player.album_art_size):
                    layout = card_layout(self.player.album_art_size, self.player.text_size,
                                         len(flip.tracks), flip.offset + int(self.flip_scroll_remainder + step))
                    self.flip_scroll_remainder = (self.flip_scroll_remainder + step -
                                                  int(self.flip_scroll_remainder + step))
                    flip.offset = layout['offset']
                    flip.layout = layout
                    flip.dirty = True
                    self.queue_frame()
                    return True
        self.adjustment.set_value(max(0, min(self.adjustment.get_upper() - self.adjustment.get_page_size(),
                                              self.adjustment.get_value() + step * 90)))
        return True

    def visible(self):
        width, size, gap, top, columns, row_height, _total, x0 = self.geometry()
        offset = self.adjustment.get_value()
        height = self.area.get_allocated_height()
        first = max(0, int((offset - top) // row_height))
        last = min(math.ceil(len(self.albums) / columns), int((offset + height - top) // row_height) + 1)
        for index in range(first * columns, min(len(self.albums), last * columns)):
            yield index, x0 + (index % columns) * (size + gap), top + (index // columns) * row_height - offset

    def visible_in_rect(self, rect):
        _width, size, gap, top, columns, row_height, _total, x0 = self.geometry()
        _x, y, _w, height = rect
        offset = self.adjustment.get_value()
        first = max(0, int((offset + y - top) // row_height))
        last = min(math.ceil(len(self.albums) / columns),
                   int((offset + y + height - top) // row_height) + 1)
        for index in range(first * columns, min(len(self.albums), last * columns)):
            yield index, x0 + (index % columns) * (size + gap), top + (index // columns) * row_height - offset

    def glass_targets(self):
        if not getattr(self.player, 'frosted_player_bar', False):
            return []
        effects = [getattr(self.player, 'frosted_bar', None)]
        effects.extend(effect for widget, effect in getattr(self.player, 'top_frosted_bars', ())
                       if widget is getattr(self.player, 'album_sort_bar', None) or
                       widget is getattr(self.player, 'album_toolbar', None))
        result = []
        for effect in effects:
            if effect and effect.enabled and effect.bar.get_mapped():
                rect = glass_rect(effect.bar, self.area, effect.PAD)
                if rect is not None:
                    result.append((effect, rect, list(self.visible_in_rect(rect))))
        return result

    def request_art(self, index):
        if (self.closed or not self.client or index in self.pending or
                index in self.slots or index in self.failed_art):
            return
        album, client, epoch = self.albums[index], self.client, self.epoch
        revision, size = self.art_revision, self.cell_size
        if not album.thumb:
            return
        self.pending.add(index)
        def work():
            if self.closed or revision != self.art_revision or index not in self.needed_indices:
                return None, True
            cache = LocalCache(client)
            data = cache.read_art(album.thumb, 480)
            if data is None:
                data = client.get('/photo/:/transcode', width=480, height=480,
                                  minSize=1, upscale=1, url=album.thumb)
                try:
                    cache.save_art(album.thumb, 480, data)
                except OSError:
                    pass
            loader = GdkPixbuf.PixbufLoader()
            loader.set_size(size, size)
            loader.write(data)
            loader.close()
            return self.pixbuf_bytes(loader.get_pixbuf(), size), False
        def done(future):
            try:
                data, skipped = future.result()
            except Exception:
                data, skipped = None, False
            def deliver():
                if (self.closed or epoch != self.epoch or revision != self.art_revision or
                        client is not self.client):
                    return False
                self.pending.discard(index)
                if data and len(data) == size * size * 4:
                    self.uploads.append((index, data))
                    self.queue_frame()
                elif not skipped:
                    self.failed_art.add(index)
                return False
            GLib.idle_add(deliver, priority=GLib.PRIORITY_HIGH_IDLE)
        self.art_workers.submit(work).add_done_callback(done)

    def upload(self, slot, pixels):
        if len(pixels) != self.cell_size * self.cell_size * 4:
            raise ValueError('Invalid album artwork buffer size')
        data = (ctypes.c_ubyte * len(pixels)).from_buffer_copy(pixels)
        self.gl.glTexSubImage2D(GL_TEXTURE_2D, 0, (slot % self.atlas_columns) * self.cell_size,
                                (slot // self.atlas_columns) * self.cell_size,
                                self.cell_size, self.cell_size,
                                GL_RGBA, GL_UNSIGNED_BYTE, data)

    def resize_atlas(self, size):
        if size == self.cell_size:
            return
        self.art_revision += 1
        self.cell_size = size
        self.atlas_columns = self.atlas_size // size
        self.capacity = self.atlas_columns ** 2
        self.slots.clear()
        self.slot_keys = [None] * self.capacity
        self.slot_pixels.clear()
        self.pending.clear()
        self.failed_art.clear()
        self.uploads.clear()
        self.gl.glBindTexture(GL_TEXTURE_2D, self.texture)
        self.gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, self.atlas_size, self.atlas_size,
                             0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        self.upload(0, self.pixbuf_bytes(placeholder_art(size, .6), size))

    def upload_flip(self, flip):
        if not flip.texture.value:
            self.gl.glGenTextures(1, ctypes.byref(flip.texture))
            self.gl.glBindTexture(GL_TEXTURE_2D, flip.texture)
            self.gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            self.gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            flip.dirty = True
        if not flip.dirty:
            return
        pixels = back_pixels(flip, self.player.album_art_size, self.player.text_size,
                             self.flip_colors(flip.index), self.player.current_track_marker,
                             (self.player.current_art_bright
                              if self.player.art_accent_enabled and self.player.current_art_bright
                              else self.player.accent_color))
        texture_data = (ctypes.c_ubyte * len(pixels)).from_buffer_copy(pixels)
        self.gl.glBindTexture(GL_TEXTURE_2D, flip.texture)
        self.gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, BACK_SIZE, BACK_SIZE, 0,
                             GL_RGBA, GL_UNSIGNED_BYTE, texture_data)
        flip.dirty = False

    def draw_glass_scene(self, rect, items):
        gl = self.gl
        rx, ry, width, height = rect
        size = self.player.album_art_size
        vertices, back_vertices = [], {}
        for index, x, y in items:
            slot = self.slots.get(index, 0)
            flip = self.flips.get(index)
            factor = max(.001, flip.scale) if flip else 1
            left_x, right_x = x + size * (1 - factor) / 2, x + size * (1 + factor) / 2
            left, right = 2 * (left_x - rx) / width - 1, 2 * (right_x - rx) / width - 1
            top, bottom = 1 - 2 * (y - ry) / height, 1 - 2 * (y + size - ry) / height
            atlas_size = self.atlas_size
            u = ((slot % self.atlas_columns) * self.cell_size + .5) / atlas_size
            v = ((slot // self.atlas_columns) * self.cell_size + .5) / atlas_size
            du = (self.cell_size - 1) / atlas_size
            target = vertices
            if flip and flip.back_visible:
                u, v, du, target = 0, 0, 1, back_vertices.setdefault(index, [])
            a, b = (left, top, u, v), (right, top, u + du, v)
            c, d = (right, bottom, u + du, v + du), (left, bottom, u, v + du)
            for vertex in (a, b, c, a, c, d):
                target.extend(vertex)
        gl.glUseProgram(self.program)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(GL_ARRAY_BUFFER, self.buffer)
        gl.glActiveTexture(GL_TEXTURE0)
        gl.glBindTexture(GL_TEXTURE_2D, self.texture)
        data = (ctypes.c_float * len(vertices))(*vertices)
        gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL_STREAM_DRAW)
        gl.glDrawArrays(GL_TRIANGLES, 0, len(vertices) // 4)
        for index, vertices in back_vertices.items():
            flip = self.flips.get(index)
            if flip is None:
                continue
            self.upload_flip(flip)
            gl.glBindTexture(GL_TEXTURE_2D, flip.texture)
            data = (ctypes.c_float * len(vertices))(*vertices)
            gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL_STREAM_DRAW)
            gl.glDrawArrays(GL_TRIANGLES, 0, len(vertices) // 4)

    def render_glass(self, targets):
        if not targets or self.glass_failed:
            return
        try:
            if self.glass_renderer is None:
                self.glass_renderer = GPUBlur(self.gl)
            for effect, rect, items in targets:
                width = max(1, math.ceil(rect[2] / effect.SCALE))
                height = max(1, math.ceil(rect[3] / effect.SCALE))
                surface = self.glass_renderer.render(
                    id(effect.bar), width, height, self.vao, self.buffer,
                    lambda rect=rect, items=items: self.draw_glass_scene(rect, items))
                self.glass_surfaces[id(effect.bar)] = surface
                effect.bar.queue_draw()
        except (RuntimeError, ValueError, AttributeError, GLib.Error):
            self.glass_failed = True
            self.glass_surfaces.clear()

    def render(self, area, _context):
        if self.closed or not self.ready:
            return True
        gl = self.gl
        width, height = max(1, area.get_allocated_width()), max(1, area.get_allocated_height())
        scale = area.get_scale_factor()
        gl.glViewport(0, 0, width * scale, height * scale)
        gl.glDisable(GL_BLEND)
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        gl.glActiveTexture(GL_TEXTURE0)
        gl.glBindTexture(GL_TEXTURE_2D, self.texture)
        for texture in self.retired_textures:
            if texture.value:
                gl.glDeleteTextures(1, ctypes.byref(texture))
        self.retired_textures.clear()
        onscreen = list(self.visible())
        row_height = self.geometry()[5]
        visible = list(self.visible_in_rect((0, -row_height * PREFETCH_ROWS, width,
                                             height + row_height * PREFETCH_ROWS * 2)))
        targets = self.glass_targets()
        desired = atlas_cell_size(self.player.album_art_size * scale, self.atlas_size,
                                  len(onscreen))
        self.resize_atlas(desired)
        ordered = [item[0] for item in onscreen]
        ordered.extend(item[0] for item in visible)
        for _effect, _rect, items in targets:
            ordered.extend(item[0] for item in items)
        ordered = list(dict.fromkeys(ordered))[:self.capacity - 1]
        self.needed_indices = set(ordered)
        priority = {index: rank for rank, index in enumerate(ordered)}
        for index, data in sorted(self.uploads, key=lambda entry: priority.get(entry[0], self.capacity)):
            if index in self.slots or index not in self.needed_indices:
                continue
            free = next((i for i in range(1, self.capacity)
                         if self.slot_keys[i] is None or self.slot_keys[i] not in self.needed_indices), None)
            if free is None:
                continue
            old = self.slot_keys[free]
            if old is not None:
                self.slots.pop(old, None)
            self.slot_keys[free] = index
            self.slots[index] = free
            self.slot_pixels[free] = data
            self.upload(free, data)
            if index in self.flips:
                self.flips[index].dirty = True
        self.uploads.clear()
        for index in ordered:
            if index not in self.slots:
                self.request_art(index)
        vertices = []
        back_vertices = {}
        size = self.player.album_art_size
        for index, x, y in visible:
            slot = self.slots.get(index, 0)
            flip = self.flips.get(index)
            width_scale = max(.001, flip.scale) if flip else 1.0
            left_x = x + size * (1 - width_scale) / 2
            right_x = x + size * (1 + width_scale) / 2
            left, right = 2*left_x/width-1, 2*right_x/width-1
            top, bottom = 1-2*y/height, 1-2*(y+size)/height
            atlas_size = self.atlas_size
            u = ((slot % self.atlas_columns) * self.cell_size + .5) / atlas_size
            v = ((slot // self.atlas_columns) * self.cell_size + .5) / atlas_size
            du = (self.cell_size - 1) / atlas_size
            target = vertices
            if flip and flip.back_visible:
                u, v, du = 0, 0, 1
                target = back_vertices.setdefault(index, [])
            a, b = (left, top, u, v), (right, top, u+du, v)
            c, d = (right, bottom, u+du, v+du), (left, bottom, u, v+du)
            for vertex in (a, b, c, a, c, d):
                target.extend(vertex)
        data = (ctypes.c_float * len(vertices))(*vertices)
        gl.glUseProgram(self.program)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(GL_ARRAY_BUFFER, self.buffer)
        gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL_STREAM_DRAW)
        gl.glDrawArrays(GL_TRIANGLES, 0, len(vertices) // 4)
        for index, vertices in back_vertices.items():
            flip = self.flips.get(index)
            if flip is None:
                continue
            self.upload_flip(flip)
            gl.glBindTexture(GL_TEXTURE_2D, flip.texture)
            data = (ctypes.c_float * len(vertices))(*vertices)
            gl.glBufferData(GL_ARRAY_BUFFER, ctypes.sizeof(data), data, GL_STREAM_DRAW)
            gl.glDrawArrays(GL_TRIANGLES, 0, len(vertices) // 4)
        if gl.glGetError():
            return self.fail()
        self.render_glass(targets)
        return True

    def draw_labels(self, _widget, context):
        if not self.player.show_album_details:
            return False
        size = self.player.album_art_size
        color = (0.1, 0.1, 0.1) if self.player.theme == 'light' else (0.93, 0.93, 0.93)
        for index, x, y in self.visible():
            album = self.albums[index]
            for line, value in enumerate((album.title, album.artist, added_age_label(album.added_at))):
                layout = self.labels.create_pango_layout(value or '')
                layout.set_width(size * Pango.SCALE)
                layout.set_alignment(Pango.Alignment.CENTER)
                layout.set_ellipsize(Pango.EllipsizeMode.END)
                context.set_source_rgba(*color, 1 if line == 0 else .72)
                context.move_to(x, y + size + 4 + line * (self.player.text_size + 4))
                PangoCairo.show_layout(context, layout)
        return False

    def pressed(self, _area, event):
        if event.button not in (1, 3):
            return False
        size = self.player.album_art_size
        for index, x, y in self.visible():
            if x <= event.x < x + size:
                if self.player.show_album_details and y + size + self.player.text_size + 8 <= event.y < y + size + 2 * (self.player.text_size + 4) + 8:
                    if event.button == 1:
                        self.player.show_artist_albums(self.albums[index].artist)
                        return True
                if y <= event.y < y + size:
                    flip = self.flips.get(index)
                    if flip:
                        self.flip = flip
                    hit = (None, None)
                    if flip and flip.index == index and flip.back_visible:
                        if flip.layout is None:
                            flip.layout = card_layout(size, self.player.text_size,
                                                      len(flip.tracks or ()), flip.offset)
                        hit = card_hit(flip.layout, event.y - y, size, flip.tracks)
                    if event.button == 3:
                        if hit[0] == 'track':
                            song = flip.tracks[hit[1]]
                            self.player.show_song_context_menu(
                                event, song, hit[1], lambda: self.play_flip_track(hit[1]))
                            return True
                        self.player.gpu_album_pressed(self.albums[index], event, x, y)
                        return True
                    self.drag_album = (self.albums[index], x, y)
                    self.pressed_hit = hit
                    self.drag_track = flip.tracks[hit[1]] if hit[0] == 'track' else None
                    if _area is not None:
                        target_name = ('application/x-plex-song-key' if self.drag_track else
                                       'application/x-plex-album-key')
                        target_info = 0 if self.drag_track else 1
                        self.drag_targets = Gtk.TargetList.new([Gtk.TargetEntry.new(
                            target_name, Gtk.TargetFlags.SAME_APP, target_info)])
                    self.drag_started_at = time.monotonic()
                    self.drag_origin = (event.x, event.y)
                    self.drag_exceeded = False
                    self.dragging = False
                    return False
        if event.button == 1 and _area is not None:
            return self.background_scroller.press(event)
        return False

    def drag_motion(self, widget, event):
        if self.background_scroller.motion(event):
            return True
        if (not self.drag_album or self.dragging or self.drag_origin is None or
                not event.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        dx, dy = event.x - self.drag_origin[0], event.y - self.drag_origin[1]
        if dx * dx + dy * dy < DRAG_DISTANCE * DRAG_DISTANCE:
            return False
        self.drag_exceeded = True
        if time.monotonic() - self.drag_started_at < DRAG_GRACE_SECONDS:
            return False
        self.dragging = True
        widget.drag_begin_with_coordinates(self.drag_targets, Gdk.DragAction.COPY,
                                           1, event, -1, -1)
        return True

    def released(self, _area, event):
        if self.background_scroller.release(event):
            return True
        if event.button == 1 and self.drag_album and not self.dragging:
            album, x, y = self.drag_album
            self.drag_album = None
            self.drag_started_at = None
            self.drag_origin = None
            if self.drag_exceeded:
                self.drag_exceeded = False
                self.drag_track = None
                self.pressed_hit = None
                return True
            hit = self.pressed_hit or (None, None)
            self.pressed_hit = None
            self.drag_track = None
            if hit[0] == 'track':
                self.play_flip_track(hit[1])
            elif hit[0] == 'album':
                self.player.select_album(album)
            elif hit[0] == 'close':
                self.toggle_album(album)
            else:
                self.player.gpu_album_pressed(album, event, x, y)
            return True
        return False

    def play_flip_track(self, index):
        flip = self.flip
        if flip and flip.tracks and 0 <= index < len(flip.tracks):
            self.player.play_card_track(SimpleNamespace(album=flip.album, tracks=flip.tracks), index)

    def drag_begin(self, _area, context):
        self.dragging = True
        if self.drag_track:
            self.player.album_drag_tracks = [self.drag_track]
            self.player.album_drag_client = self.player.client
            label = Gtk.Label(label=self.drag_track.title)
            label.set_name('song-drag-ghost')
            label.show()
            Gtk.drag_set_icon_widget(context, label, 8, 8)
            return
        if self.drag_album:
            album = self.drag_album[0]
            self.player.dragged_album = (self.player.client, album)
            index = next((i for i, item in enumerate(self.albums) if item is album), None)
            pixels = self.slot_pixels.get(self.slots.get(index))
            if pixels:
                pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
                    GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB, True, 8,
                    self.cell_size, self.cell_size, self.cell_size * 4)
                pixbuf = pixbuf.scale_simple(96, 96, GdkPixbuf.InterpType.BILINEAR)
            else:
                pixbuf = placeholder_art(96, 0.6)
            Gtk.drag_set_icon_pixbuf(context, pixbuf, 8, 8)

    def drag_end(self, _area, _context):
        self.player.dragged_album = None
        self.player.album_drag_tracks = None
        self.player.album_drag_client = None
        self.drag_album = None
        self.drag_track = None
        self.pressed_hit = None
        self.drag_started_at = None
        self.drag_origin = None
        self.drag_exceeded = False
        self.dragging = False

    def drag_data_get(self, _area, _context, selection, _info, _time):
        if self.drag_track and _info == 0:
            selection.set(selection.get_target(), 8, self.drag_track.key.encode('utf-8'))
        elif self.drag_album:
            selection.set(selection.get_target(), 8, self.drag_album[0].key.encode('utf-8'))
