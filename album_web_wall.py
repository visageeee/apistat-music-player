"""Experimental one-hop album web rendered with the existing GPU artwork atlas."""
import math
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, Pango, PangoCairo

from experimental_album_canvas import CanvasPan, CanvasPlayer, is_touchpad_scroll
from gpu_album_wall import GPUAlbumWall


def radial_positions(count, width, height, size, ox=0, oy=0):
    if count <= 0:
        return []
    cx, cy = width / 2 - ox, height / 2 - oy
    result = [(cx - size / 2, cy - size / 2)]
    for index in range(count - 1):
        angle = -math.pi / 2 + index * 2 * math.pi / (count - 1)
        result.append((cx + math.cos(angle) * size * 2.25 - size / 2,
                       cy + math.sin(angle) * size * 2.15 - size / 2))
    return result


class AlbumWebWall(GPUAlbumWall):
    def __init__(self, player, failed, pressed):
        self.canvas_player = CanvasPlayer(player, embedded=True)
        self.canvas_player.zoom = .8
        self.x_adjustment = Gtk.Adjustment()
        self.origin = {}
        self.transition = None
        self.transition_tick = 0
        self.fit_pending = True
        super().__init__(self.canvas_player, failed, album_pressed=pressed, load_more=False)
        self.background_scroller = CanvasPan(self)
        self.x_adjustment.connect('value-changed', self.changed)
        self.render_surface.set_margin_top(0)
        self.scrollbar.set_margin_top(0)
        self.scrollbar.set_no_show_all(True)
        self.scrollbar.hide()
        self.input_surface.get_accessible().set_name('Related album web')
        self.pinch = Gtk.GestureZoom.new(self.input_surface)
        self.pinch.connect('begin', self.pinch_begin)
        self.pinch.connect('scale-changed', self.pinch_changed)
        self.pinch_start = None

    def size_changed(self, *_):
        if self.fit_pending:
            width, height = self.area.get_allocated_width(), self.area.get_allocated_height()
            if width > 100 and height > 100:
                # Reserve vertical room for the two metadata lines below covers.
                self.canvas_player.zoom = max(.18, min(1., (width - 24) / 880,
                                                        (height - 80) / 850))
                self.fit_pending = False
        self.layout_changed()

    def geometry(self):
        width = max(1, self.area.get_allocated_width())
        height = max(1, self.area.get_allocated_height())
        size = self.player.album_art_size
        return width, size, 0, 0, 1, size * 2, height, 0

    def layout_changed(self):
        size = self.player.album_art_size
        width, height = max(1, self.area.get_allocated_width()), max(1, self.area.get_allocated_height())
        margin = size * 2.25
        self.x_adjustment.configure(self.x_adjustment.get_value(), -margin, margin + width,
                                    size / 3, width * .8, width)
        self.adjustment.configure(self.adjustment.get_value(), -margin, margin + height,
                                  size / 3, height * .8, height)
        self.queue_frame()
        self.labels.queue_draw()

    def positions(self):
        size = self.player.album_art_size
        target = radial_positions(len(self.albums), self.area.get_allocated_width(),
                                  self.area.get_allocated_height(), size,
                                  self.x_adjustment.get_value(), self.adjustment.get_value())
        progress = min(1., max(0., (time.monotonic() - self.transition) / .45)) if self.transition else 1.
        progress = progress * progress * (3 - 2 * progress)
        for i, (x, y) in enumerate(target):
            if progress < 1:
                old_x, old_y = self.origin.get(self.albums[i].key, target[0])
                x, y = old_x + (x - old_x) * progress, old_y + (y - old_y) * progress
            yield i, x, y

    def visible_in_rect(self, rect):
        rx, ry, width, height = rect
        size = self.player.album_art_size
        for index, x, y in self.positions():
            if x + size >= rx and x <= rx + width and y + size >= ry and y <= ry + height:
                yield index, x, y

    def visible(self):
        return self.visible_in_rect((0, 0, self.area.get_allocated_width(), self.area.get_allocated_height()))

    def set_graph(self, client, seed, related):
        albums = [seed, *related]
        if self.client is not client:
            super().set_albums(client, albums, reset=True)
            self.origin, self.transition = {}, None
        else:
            self.origin = {self.albums[i].key: (x, y) for i, x, y in self.positions()}
            if self.albums and self.albums[0].key != seed.key:
                self.x_adjustment.set_value(0)
                self.adjustment.set_value(0)
            index = {album.key: i for i, album in enumerate(albums)}
            slots = {index[self.albums[i].key]: slot for i, slot in self.slots.items()
                     if i < len(self.albums) and self.albums[i].key in index}
            self.clear_card()
            self.epoch += 1
            self.art_revision += 1
            self.pending.clear()
            self.failed_art.clear()
            self.uploads.clear()
            self.slots = slots
            self.slot_keys = [None] * self.capacity
            for i, slot in slots.items():
                self.slot_keys[slot] = i
            self.albums = albums
            self.transition = time.monotonic()
            if not self.transition_tick and self.area.get_mapped():
                self.transition_tick = self.area.add_tick_callback(self.animate_transition)
        self.layout_changed()

    def animate_transition(self, *_):
        self.queue_frame()
        self.labels.queue_draw()
        if self.transition is None or time.monotonic() - self.transition >= .45:
            self.transition = None
            self.transition_tick = 0
            return False
        return True

    def draw_gpu(self, area, context):
        points = list(self.positions())
        if len(points) > 1:
            size = self.player.album_art_size
            x, y = points[0][1] + size / 2, points[0][2] + size / 2
            context.save()
            context.set_source_rgba(.75, .75, .78, .32)
            context.set_line_width(1.5)
            for _, px, py in points[1:]:
                context.move_to(x, y)
                context.line_to(px + size / 2, py + size / 2)
            context.stroke()
            context.restore()
        return super().draw_gpu(area, context)

    def draw_labels(self, _widget, context):
        size = self.player.album_art_size
        text_color = (.1, .1, .1) if self.player.theme == 'light' else (.94, .94, .94)
        for index, x, y in self.visible():
            album = self.albums[index]
            for line, value in enumerate((album.title, album.artist)):
                layout = self.labels.create_pango_layout(value or '')
                layout.set_width(int(size * Pango.SCALE))
                layout.set_alignment(Pango.Alignment.CENTER)
                layout.set_ellipsize(Pango.EllipsizeMode.END)
                context.set_source_rgba(*text_color, 1 if line == 0 else .7)
                context.move_to(x, y + size + 4 + line * (self.player.text_size + 4))
                PangoCairo.show_layout(context, layout)
        return False

    def changed(self, *_):
        super().changed()

    def zoom(self, scale, x, y):
        old = self.canvas_player.zoom
        new = max(.18, min(2., old * scale))
        if new == old:
            return
        cx, cy = self.area.get_allocated_width() / 2, self.area.get_allocated_height() / 2
        ox = (self.x_adjustment.get_value() + x - cx) * new / old - (x - cx)
        oy = (self.adjustment.get_value() + y - cy) * new / old - (y - cy)
        self.canvas_player.zoom = new
        self.layout_changed()
        self.x_adjustment.set_value(ox)
        self.adjustment.set_value(oy)

    def scroll(self, _area, event):
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            valid, dx, dy = event.get_scroll_deltas()
            if not valid:
                return False
        elif event.direction == Gdk.ScrollDirection.UP:
            dx, dy = 0, -1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            dx, dy = 0, 1
        else:
            return False
        if is_touchpad_scroll(event) and not event.state & Gdk.ModifierType.CONTROL_MASK:
            self.x_adjustment.set_value(self.x_adjustment.get_value() + dx * 80)
            self.adjustment.set_value(self.adjustment.get_value() + dy * 80)
        else:
            self.zoom(math.exp(-.16 * dy), event.x, event.y)
        return True

    def pinch_begin(self, *_):
        self.pinch_start = self.canvas_player.zoom

    def pinch_changed(self, gesture, scale):
        if self.pinch_start is None or not math.isfinite(scale) or scale <= 0:
            return
        valid, x, y = gesture.get_bounding_box_center()
        if not valid:
            x, y = self.area.get_allocated_width() / 2, self.area.get_allocated_height() / 2
        self.zoom(self.pinch_start * scale / self.canvas_player.zoom, x, y)

    def shutdown(self):
        if self.transition_tick:
            self.area.remove_tick_callback(self.transition_tick)
            self.transition_tick = 0
        super().shutdown()
