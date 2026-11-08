"""A frame-synchronized backdrop for the translucent player controls."""

import math
import cairo
import time
import gi
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, GLib
from gtk_snapshot import draw_allocated


class FrostedBar:
    SCALE = 28
    PAD = 56
    _capture_depth = 0

    def __init__(self, bar, content, background, theme, timeline=lambda: None,
                 edge='bottom', window_capture=False, capture_allowed=lambda: True,
                 capture_content=lambda: True, gpu_surface=lambda: None,
                 retain_missing_gpu=lambda: False, cache_frames=False,
                 scale=None, exact_scaling=False, sample_wall_frame=False):
        self.bar = bar
        self.content = content
        self.background = background
        self.theme = theme
        self.timeline = timeline
        self.edge = edge
        self.window_capture = window_capture
        self.capture_allowed = capture_allowed
        self.capture_content = capture_content
        self.gpu_surface = gpu_surface
        self.retain_missing_gpu = retain_missing_gpu
        self.cache_frames = bool(cache_frames)
        if scale is not None:
            self.SCALE = max(1, int(scale))
        self.exact_scaling = bool(exact_scaling)
        self.sample_wall_frame = bool(sample_wall_frame)
        if self.sample_wall_frame:
            self.exact_scaling = True
        self._base_scale = self.SCALE
        self._base_exact_scaling = self.exact_scaling
        self._gpu_sampling = False
        self._backdrop_dirty = True
        self.surface = None
        self.enabled = False
        self._top_idle = 0
        self._settle_timer = 0
        self._last_layout = 0.0
        self._needs_resize_check = False
        self._ignore_source_draw = False
        self._ready = {id(content): False, id(background): False}
        self._allocations = {}
        self._bar_geometry = None
        self._observed = {id(content), id(background)}
        for widget in (content, background):
            widget.connect('size-allocate', self.invalidate)
            widget.connect_after('draw', self.drawn)
        bar.connect('draw', self.draw)
        if self.cache_frames:
            bar.connect('size-allocate', self.bar_allocated)

    def bar_allocated(self, _widget, allocation):
        geometry = (allocation.x, allocation.y, allocation.width, allocation.height)
        if geometry != self._bar_geometry:
            self._bar_geometry = geometry
            self._backdrop_dirty = True

    def invalidate(self, widget, _allocation):
        if widget is not self.content and widget is not self.background:
            return
        if _allocation is not None:
            geometry = (_allocation.x, _allocation.y, _allocation.width, _allocation.height)
            if self._allocations.get(id(widget)) == geometry:
                return
            self._allocations[id(widget)] = geometry
        self._ready[id(widget)] = False
        self._backdrop_dirty = True
        self._last_layout = time.monotonic()
        self._needs_resize_check = True

    def drawn(self, widget, _context):
        if widget is not self.content and widget is not self.background:
            return False
        self._ready[id(widget)] = True
        if (not FrostedBar._capture_depth and
                (widget is self.background or self.capture_content())):
            self._backdrop_dirty = True
        should_refresh = (widget is self.content and
                          (not self.cache_frames or self.capture_content()))
        should_refresh = should_refresh or (self.cache_frames and widget is self.background)
        if (self.edge == 'top' and should_refresh and self.enabled and
                not FrostedBar._capture_depth and not self._ignore_source_draw and
                self.bar.get_mapped() and not self._top_idle):
            self._top_idle = GLib.idle_add(self._refresh_top,
                                          priority=GLib.PRIORITY_HIGH_IDLE + 30)
        return False

    def set_content(self, content):
        if content is self.content:
            return
        self._ready.pop(id(self.content), None)
        self._allocations.pop(id(self.content), None)
        self.content = content
        self._backdrop_dirty = True
        self._ready[id(content)] = False
        self._last_layout = time.monotonic()
        self._needs_resize_check = True
        self.surface = None
        if id(content) not in self._observed:
            self._observed.add(id(content))
            content.connect('size-allocate', self.invalidate)
            content.connect_after('draw', self.drawn)

    def _refresh_top(self):
        self._top_idle = 0
        if self.enabled and self.bar.get_mapped() and all(self._ready.values()):
            if self.window_capture:
                self.refresh()
            self._ignore_source_draw = True
            self.bar.queue_draw()
        return False

    def backdrop_changed(self):
        """Mark a freshly rendered external backdrop for compositing."""
        self._backdrop_dirty = True

    def configure_gpu_sampling(self, enabled):
        enabled = bool(enabled and self.sample_wall_frame)
        if self._gpu_sampling == enabled:
            return
        self._gpu_sampling = enabled
        self.SCALE = 4 if enabled else self._base_scale
        self.exact_scaling = True if enabled else self._base_exact_scaling
        self._backdrop_dirty = True

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.stop()
        self.bar.queue_draw()

    def stop(self):
        if self._top_idle:
            GLib.source_remove(self._top_idle)
            self._top_idle = 0
        if self._settle_timer:
            GLib.source_remove(self._settle_timer)
            self._settle_timer = 0
        self._ignore_source_draw = False
        self.surface = None
        self._backdrop_dirty = True

    def refresh(self):
        if not self.enabled:
            return False
        if not self.capture_allowed():
            return True
        if not self.bar.get_mapped() or not self.content.get_mapped():
            return True
        if not all(self._ready.values()):
            return True
        if time.monotonic() - self._last_layout < 0.20:
            if not self._settle_timer:
                self._settle_timer = GLib.timeout_add(210, self._after_layout)
            return True
        if self._needs_resize_check:
            self._needs_resize_check = False
            check_resize = getattr(self.content, 'check_resize', None)
            if check_resize is not None:
                check_resize()
        width = self.bar.get_allocated_width()
        height = self.bar.get_allocated_height()
        content_height = self.content.get_allocated_height()
        if min(width, height, content_height) < 2:
            return True
        capture_content = self.capture_content()
        self.configure_gpu_sampling(not capture_content)
        scale = self.SCALE
        size = math.ceil(width / scale), math.ceil((height + self.PAD) / scale)
        gpu = None if capture_content else self.gpu_surface()
        # A GPU frame can arrive after a GTK resize or redraw. Keep the last
        # complete backdrop instead of clearing it to the background alone.
        if (not capture_content and (self.sample_wall_frame or self.retain_missing_gpu()) and
                self.surface is not None and
                (gpu is None or (gpu.get_width(), gpu.get_height()) != size)):
            return True
        if self.surface is None or (self.surface.get_width(), self.surface.get_height()) != size:
            self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *size)
        context = cairo.Context(self.surface)
        context.set_operator(cairo.OPERATOR_CLEAR)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        if self.edge == 'top':
            position = self.bar.translate_coordinates(self.content, 0, 0)
            x = max(0, position[0]) if position is not None else 0
            y = max(0, position[1]) if position is not None else 0
        else:
            x, y = 0, content_height - height
        if self.window_capture:
            window = self.bar.get_toplevel()
            point = self.content.translate_coordinates(window, x, y)
            capture_width = min(width, self.content.get_allocated_width() - x)
            capture_height = min(height, content_height - y)
            if point is None or capture_width <= 0 or capture_height <= 0:
                return True
            pixels = Gdk.pixbuf_get_from_window(window.get_window(), point[0], point[1],
                                                capture_width, capture_height)
            if pixels is not None:
                pixels = pixels.scale_simple(max(1, math.ceil(capture_width / scale)),
                                             max(1, math.ceil(capture_height / scale)),
                                             GdkPixbuf.InterpType.BILINEAR)
                Gdk.cairo_set_source_pixbuf(context, pixels, 0, self.PAD / scale)
                context.paint()
            return True
        if self.exact_scaling:
            context.scale(size[0] / width, size[1] / (height + self.PAD))
        else:
            context.scale(1 / scale, 1 / scale)
        context.translate(-x, -(y - self.PAD))
        FrostedBar._capture_depth += 1
        try:
            if self.edge == 'top':
                origin = self.content.translate_coordinates(self.background, 0, 0)
                if origin is not None:
                    context.save()
                    context.translate(-origin[0], -origin[1])
                    draw_allocated(self.background, context)
                    context.restore()
            else:
                draw_allocated(self.background, context)
            if capture_content:
                draw_allocated(self.content, context)
            else:
                surface = gpu
                if (surface is not None and surface.get_width() == size[0] and
                        surface.get_height() == size[1]):
                    context.save()
                    context.identity_matrix()
                    context.set_source_surface(surface, 0, 0)
                    context.paint()
                    context.restore()
        finally:
            FrostedBar._capture_depth -= 1
        self._backdrop_dirty = False
        return True

    def _after_layout(self):
        self._settle_timer = 0
        if self.enabled and self.bar.get_mapped():
            if self.edge == 'top' and not self._top_idle:
                self._top_idle = GLib.idle_add(self._refresh_top,
                                              priority=GLib.PRIORITY_HIGH_IDLE + 30)
            else:
                self.bar.queue_draw()
        return False

    def draw(self, _bar, context):
        if not self.enabled:
            return False
        if not self.window_capture and (not self.cache_frames or self._backdrop_dirty):
            self.refresh()
        width = self.bar.get_allocated_width()
        height = self.bar.get_allocated_height()
        context.save()
        context.rectangle(0, 0, width, height)
        context.clip()
        if self.surface is not None:
            context.translate(0, -self.PAD)
            if self.exact_scaling:
                context.scale(width / self.surface.get_width(),
                              (height + self.PAD) / self.surface.get_height())
            else:
                context.scale(self.SCALE, self.SCALE)
            context.set_source_surface(self.surface, 0, 0)
            context.get_source().set_filter(cairo.FILTER_BILINEAR)
            context.paint()
            context.restore()
            context.save()
        light = self.theme() == 'light'
        context.set_source_rgba(*((0.88, 0.88, 0.87, 0.78) if light
                                  else (0.035, 0.035, 0.045, 0.76)))
        context.rectangle(0, 0, width, height)
        context.fill()
        timeline = self.timeline()
        if timeline is not None and timeline.get_visible():
            position = timeline.translate_coordinates(self.bar, 0, 0)
            if position is not None:
                color = ((0.90, 0.90, 0.89) if light else
                         ((0.0, 0.0, 0.0) if self.theme() == 'black'
                          else (0.082, 0.082, 0.082)))
                context.set_source_rgb(*color)
                context.rectangle(position[0], position[1],
                                  timeline.get_allocated_width(),
                                  timeline.get_allocated_height())
                context.fill()
        context.restore()
        self._ignore_source_draw = False
        return False
