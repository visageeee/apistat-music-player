"""GPU album map using the normal wall's artwork atlas and interactions."""
import math
import sys
import time
from collections import defaultdict

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gdk, Pango, PangoCairo

from experimental_album_canvas import (ExperimentalAlbumCanvas, MAX_ZOOM, is_touchpad_scroll,
                                       pan_bounds, zoom_anchor)
from gpu_album_wall import GPUAlbumWall

SPATIAL_CELL = 512
MIN_MAP_ZOOM = .12


class AlbumMapCanvas(ExperimentalAlbumCanvas):
    def __init__(self, player, failed, pressed):
        self.map_layout = {'positions': {}, 'labels': [], 'width': 1., 'height': 1.}
        self.spatial = {}
        self.map_filter = ''
        super().__init__(player, failed, pressed, embedded=True)
        self.input_surface.get_accessible().set_name('Album map')

    def prewarm_thumbnails(self, _client, _albums, _atlas, _epoch):
        # The map requests only artwork in or near the viewport; it still
        # reuses and updates the persistent thumbnail atlas on demand.
        return

    def set_map(self, client, albums, layout, links):
        unchanged = (self.client is client and self.map_layout == layout and
                     len(self.albums) == len(albums) and
                     all(old == new for old, new in zip(self.albums, albums)))
        if unchanged:
            self.queue_frame()
            self.labels.queue_draw()
            return
        self.map_layout = layout
        self.spatial = defaultdict(list)
        for index, album in enumerate(albums):
            x, y = layout['positions'][album.key]
            self.spatial[(math.floor(x / SPATIAL_CELL), math.floor(y / SPATIAL_CELL))].append(index)
        self._fit_pending = True
        self.x_adjustment.set_value(0)
        self.adjustment.set_value(0)
        self.set_albums(client, albums, reset=True)
        self.fit_map()

    def set_filter(self, value):
        self.map_filter = str(value or '').strip().casefold()
        self.queue_frame()
        self.labels.queue_draw()

    def origin(self, zoom=None):
        zoom = self.canvas_player.zoom if zoom is None else zoom
        width = max(1, self.area.get_allocated_width())
        height = max(1, self.area.get_allocated_height())
        return (max(0., (width - self.map_layout['width'] * zoom) / 2),
                max(0., (height - self.map_layout['height'] * zoom) / 2))

    def geometry(self):
        width = max(1, self.area.get_allocated_width())
        size = self.player.album_art_size
        zoom = self.canvas_player.zoom
        x, y = self.origin()
        return width, size, self.player.album_spacing, y, 1, max(1, size * 1.2), self.map_layout['height'] * zoom, x

    def layout_changed(self, x_value=None, y_value=None):
        if not hasattr(self, 'flips'):
            return
        for flip in self.flips.values():
            flip.dirty = True
        zoom = self.canvas_player.zoom
        width = max(1, self.area.get_allocated_width())
        height = max(1, self.area.get_allocated_height())
        x0, y0 = self.origin()
        xmin, xmax = pan_bounds(width, x0, self.map_layout['width'] * zoom)
        ymin, ymax = pan_bounds(height, y0, self.map_layout['height'] * zoom)
        self.x_adjustment.configure(self.x_adjustment.get_value() if x_value is None else x_value,
                                    xmin, xmax + width, max(1, self.player.album_art_size / 3), width * .8, width)
        self.adjustment.configure(self.adjustment.get_value() if y_value is None else y_value,
                                  ymin, ymax + height, max(1, self.player.album_art_size / 3), height * .8, height)
        self.queue_frame()
        self.labels.queue_draw()

    def minimum_zoom(self):
        width, height = self.area.get_allocated_width(), self.area.get_allocated_height()
        if width <= 1 or height <= 1:
            return MIN_MAP_ZOOM
        return max(.000001, min(MIN_MAP_ZOOM, width / max(1., self.map_layout['width']),
                               height / max(1., self.map_layout['height'])))

    def fit_map(self):
        width, height = self.area.get_allocated_width(), self.area.get_allocated_height()
        if width <= 100 or height <= 100 or not self.albums:
            return
        self.canvas_player.zoom = max(self.minimum_zoom(), min(MAX_ZOOM, width / self.map_layout['width'],
                                                   height / self.map_layout['height']))
        self.target_zoom = self.canvas_player.zoom
        self._fit_pending = False
        self.layout_changed(0, 0)

    def size_changed(self, *_args):
        if self._fit_pending:
            self.fit_map()
        self.layout_changed()

    def visible_in_rect(self, rect):
        rx, ry, width, height = rect
        zoom = max(.0001, self.canvas_player.zoom)
        x0, y0 = self.origin()
        ox, oy = self.x_adjustment.get_value(), self.adjustment.get_value()
        size = self.player.album_art_size
        left, top = (rx + ox - x0 - size) / zoom, (ry + oy - y0 - size) / zoom
        right, bottom = (rx + width + ox - x0) / zoom, (ry + height + oy - y0) / zoom
        minx, maxx = math.floor(left / SPATIAL_CELL), math.floor(right / SPATIAL_CELL)
        miny, maxy = math.floor(top / SPATIAL_CELL), math.floor(bottom / SPATIAL_CELL)
        count = (maxx - minx + 1) * (maxy - miny + 1)
        buckets = (self.spatial.values() if count > max(16, len(self.spatial) * 2) else
                   (self.spatial.get((x, y), ()) for x in range(minx, maxx + 1)
                    for y in range(miny, maxy + 1)))
        for indices in buckets:
            for index in indices:
                if index >= len(self.albums):
                    continue
                album = self.albums[index]
                if self.map_filter and self.map_filter not in (album.title + ' ' + album.artist).casefold():
                    continue
                wx, wy = self.map_layout['positions'][album.key]
                x, y = x0 + wx * zoom - ox, y0 + wy * zoom - oy
                if x + size >= rx and x <= rx + width and y + size >= ry and y <= ry + height:
                    yield index, x, y

    def visible(self):
        return self.visible_in_rect((0, 0, self.area.get_allocated_width(), self.area.get_allocated_height()))

    def draw_gpu(self, area, context):
        # Draw links on the same surface immediately before compositing the
        # transparent GPU artwork frame, so covers and flipped cards occlude them.
        if not self.closed:
            zoom = self.canvas_player.zoom
            x0, y0 = self.origin()
            ox, oy = self.x_adjustment.get_value(), self.adjustment.get_value()
            accent = (getattr(self.player, 'current_art_bright', None)
                      if getattr(self.player, 'art_accent_enabled', False) else None) or self.player.accent_color
            rgba = Gdk.RGBA()
            if not rgba.parse(accent):
                rgba.parse('#e7a641')
            context.save()
            context.set_source_rgba(rgba.red, rgba.green, rgba.blue, .55)
            context.set_line_width(5.0)
            labels = self.map_layout['labels']
            for parent, child in self.map_layout.get('group_links', ()):
                _, ax, ay = labels[parent]
                _, bx, by = labels[child]
                context.move_to(x0 + ax * zoom - ox, y0 + ay * zoom - oy)
                context.line_to(x0 + bx * zoom - ox, y0 + by * zoom - oy)
            context.stroke()
            context.restore()
        return super().draw_gpu(area, context)

    def draw_labels(self, widget, context):
        GPUAlbumWall.draw_labels(self, widget, context)
        zoom = self.canvas_player.zoom
        x0, y0 = self.origin()
        ox, oy = self.x_adjustment.get_value(), self.adjustment.get_value()
        width, height = self.area.get_allocated_width(), self.area.get_allocated_height()
        labels = self.map_layout['labels']
        for title, wx, wy in labels:
            x, y = x0 + wx * zoom - ox, y0 + wy * zoom - oy
            if not -200 <= x <= width + 200 or not -50 <= y <= height + 50:
                continue
            label = self.labels.create_pango_layout(title)
            font = Pango.FontDescription('Sans Bold')
            font.set_absolute_size(int(max(25, min(86, 74 * math.sqrt(zoom))) * Pango.SCALE))
            label.set_font_description(font)
            tw, th = label.get_pixel_size()
            context.move_to(x - tw / 2, y - th / 2)
            PangoCairo.layout_path(context, label)
            context.set_source_rgba(.12, .12, .12, .95)
            context.set_line_width(3.5)
            context.set_line_join(1)  # round
            context.stroke_preserve()
            context.set_source_rgba(0.94, 0.93, 0.90, 1.0)
            context.fill()
        return False

    def change_columns(self, delta):
        # A map has no columns; Ctrl+wheel changes its scale instead.
        self.target_zoom = max(self.minimum_zoom(), min(MAX_ZOOM, self.target_zoom * math.exp(.17 * delta)))
        if delta < 0:
            self.unflip_for_zoom_out()
        self.start_animation()

    def scroll(self, _area, event):
        windows = sys.platform == 'win32'
        emulated = getattr(event, 'get_pointer_emulated', None)
        if windows and event.direction != Gdk.ScrollDirection.SMOOTH and emulated and emulated():
            return True
        dx = 0.
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            valid, dx, dy = event.get_scroll_deltas()
            if not valid:
                return False
        elif event.direction == Gdk.ScrollDirection.UP:
            dy = -1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            dy = 1
        elif windows and event.direction in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.RIGHT):
            dx, dy = (-1 if event.direction == Gdk.ScrollDirection.LEFT else 1), 0
        else:
            return False
        if dy and self.scroll_flipped_tracklist(event, dy):
            return True
        control = bool(getattr(event, 'state', 0) & Gdk.ModifierType.CONTROL_MASK)
        if (is_touchpad_scroll(event) or windows) and not control:
            self.target_zoom = self.canvas_player.zoom
            if dx:
                self.x_adjustment.set_value(self.x_adjustment.get_value() + dx * 90)
            if dy:
                self.adjustment.set_value(self.adjustment.get_value() + dy * 90)
            return True
        if dy:
            self.anchor = (event.x, event.y)
            if dy > 0:
                self.unflip_for_zoom_out()
            self.target_zoom = max(self.minimum_zoom(), min(MAX_ZOOM, self.target_zoom * math.exp(-.17 * dy)))
            self.start_animation()
        return True

    def pinch_scale_changed(self, gesture, scale):
        if self.pinch_start_zoom is None or not math.isfinite(scale) or scale <= 0:
            return
        valid, x, y = gesture.get_bounding_box_center()
        if not valid:
            x, y = self.area.get_allocated_width() / 2, self.area.get_allocated_height() / 2
        self.anchor = (x, y)
        target = max(self.minimum_zoom(), min(MAX_ZOOM, self.pinch_start_zoom * scale))
        if target < self.pinch_last_target:
            self.unflip_for_zoom_out()
        self.target_zoom = target
        self.pinch_last_target = target
        self.start_animation()

    def animate_canvas(self, _area, _clock):
        now = time.monotonic()
        previous = getattr(self, '_last_animation', None) or now - 1 / 60
        self._last_animation = now
        factor = 1 - math.exp(-min(.1, now - previous) * 13)
        old = self.canvas_player.zoom
        new = old + (self.target_zoom - old) * factor
        if abs(new - self.target_zoom) < .001:
            new = self.target_zoom
        if new != old:
            old_x, old_y = self.origin(old)
            new_x, new_y = self.origin(new)
            x, y = self.anchor
            ox = zoom_anchor(self.x_adjustment.get_value(), x - old_x, old, new) + new_x - old_x
            oy = zoom_anchor(self.adjustment.get_value(), y - old_y, old, new) + new_y - old_y
            self.canvas_player.zoom = new
            self.update_detail_tier()
            self.layout_changed(ox, oy)
        self.queue_frame()
        self.labels.queue_draw()
        if new == self.target_zoom:
            self.animation_tick = 0
            self._last_animation = None
            return False
        return True
