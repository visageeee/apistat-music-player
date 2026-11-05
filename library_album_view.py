"""Album grouping and artwork overlay for the library song table."""
from bisect import bisect_right
from collections import OrderedDict
import math

import cairo
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gdk, Gtk, Pango, PangoCairo

from app_assets import placeholder_art, SMALL_PLACEHOLDER_LOGO_RATIO
from plex_client import Item


def album_identity(song):
    if song.album_key:
        return ('key', song.album_key)
    return ('tags', (song.album_artist or song.artist or '').casefold(),
            (song.album or '').casefold())


def group_songs_by_album(songs):
    """Keep first-album order and the original relative order within each album."""
    groups = OrderedDict()
    for song in songs:
        groups.setdefault(album_identity(song), []).append(song)
    return [song for album in groups.values() for song in album]


def album_ranges(songs):
    ranges = []
    for index, song in enumerate(songs):
        key = album_identity(song)
        if not ranges or ranges[-1][2] != key:
            ranges.append([index, index, key])
        else:
            ranges[-1][1] = index
    return ranges


def album_group_row_height(track_count, text_size):
    """Reserve a cover, three labels and a gap without inserting fake tracks."""
    line_height = max(28, int(text_size) + 14)
    label_font = max(9, round(text_size * .72))
    labels = 3 * (math.ceil(label_font * 1.65) + 2)
    group_height = 176 + 8 + 5 + labels + 8 + 16
    return max(line_height + 16, group_height - max(0, track_count - 1) * line_height)


def album_details(song):
    return (song.album_artist or song.artist or 'Unknown artist',
            song.album or 'Unknown album', str(song.year or ''))


class AlbumGroupOverlay(Gtk.DrawingArea):
    """Paint non-interactive covers and dividers over the song table gutter."""
    GUTTER = 240
    MIN_GUTTER = 150
    MAX_GUTTER = 600
    ART_SIZE = 176
    CACHE_LIMIT = 256

    def __init__(self, player, view, scroll, gutter_column=None, model_offset=0):
        super().__init__()
        self.player, self.view = player, view
        self.gutter_column = gutter_column
        self.model_offset = model_offset
        self.results = None
        self.ranges = []
        self.starts = []
        self.group_ends = {}
        self.art = OrderedDict()
        self.requested = set()
        self.client = None
        self.model = None
        self.model_handlers = []
        # An input window here covers the TreeView even with overlay pass-through.
        self.set_has_window(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_focus(False)
        self.connect('draw', self.draw_groups)
        self.connect('notify::visible', lambda *_args: self.model_changed(self.view, None))
        scroll.get_vadjustment().connect('value-changed', self.redraw)
        scroll.get_hadjustment().connect('value-changed', self.redraw)
        view.connect('size-allocate', self.redraw)
        view.connect('notify::model', self.model_changed)
        view.connect('destroy', self.close)
        self.model_changed(view, None)

    def model_changed(self, view, _property):
        if self.model is not None:
            for handler in self.model_handlers:
                self.model.disconnect(handler)
        self.model = view.get_model() if self.get_visible() else None
        self.model_handlers = []
        if self.model is not None:
            for signal in ('row-inserted', 'row-deleted', 'rows-reordered'):
                self.model_handlers.append(self.model.connect(signal, self.redraw))
        self.redraw()

    def close(self, *_args):
        if self.model is not None:
            for handler in self.model_handlers:
                self.model.disconnect(handler)
        self.model = None
        self.model_handlers = []

    def redraw(self, *_args):
        if self.get_visible():
            self.queue_draw()

    def set_results(self, songs):
        client = getattr(self.player, 'client', None)
        if client is not self.client:
            self.client = client
            self.art.clear()
            self.requested.clear()
        if songs is self.results:
            return
        self.results = songs
        self.ranges = album_ranges(songs)
        self.starts = [group[0] for group in self.ranges]
        self.group_ends = {end: end - start + 1 for start, end, _key in self.ranges}
        if self.get_visible():
            self.view.queue_resize()
        self.redraw()

    def cover_for(self, song):
        thumb = song.album_thumb or song.thumb
        client = getattr(self.player, 'client', None)
        if not thumb or client is None:
            return placeholder_art(self.ART_SIZE, SMALL_PLACEHOLDER_LOGO_RATIO)
        key = (client.address, thumb)
        if key in self.art:
            self.art.move_to_end(key)
            return self.art[key]
        if key not in self.requested:
            self.requested.add(key)
            image = Gtk.Image()
            album = Item(song.album_key or song.key, song.album or 'Album', thumb=thumb)
            def valid():
                return not self.player.closed and self.player.client is client
            def loaded(pixbuf):
                if not valid():
                    return
                self.art[key] = pixbuf
                self.art.move_to_end(key)
                while len(self.art) > self.CACHE_LIMIT:
                    old, _ = self.art.popitem(last=False)
                    self.requested.discard(old)
                self.redraw()
            self.player.load_art(client, album, image, self.ART_SIZE, valid, loaded)
        return placeholder_art(self.ART_SIZE, SMALL_PLACEHOLDER_LOGO_RATIO)

    def draw_groups(self, _widget, context):
        if not self.ranges or self.results is None:
            return False
        visible = self.view.get_visible_range()
        origin = self.view.translate_coordinates(self, 0, 0)
        if not visible or origin is None:
            return False
        first = max(0, visible[0].get_indices()[0] - self.model_offset)
        last = visible[1].get_indices()[0] - self.model_offset
        count = min(max(0, len(self.view.get_model()) - self.model_offset), len(self.results))
        header_x, header_y = self.view.convert_bin_window_to_widget_coords(0, 0)
        x = origin[0] + header_x
        top = origin[1] + header_y
        width = self.view.get_allocated_width()
        column = self.gutter_column or getattr(self.player, 'album_gutter_column', None)
        gutter = (column.get_width() or column.get_fixed_width()) if column is not None else self.GUTTER
        gutter = max(self.MIN_GUTTER, gutter)
        context.save()
        context.rectangle(origin[0], top, width, max(0, self.view.get_allocated_height() - header_y))
        context.clip()
        index = max(0, bisect_right(self.starts, first) - 1)
        for group_index in range(index, len(self.ranges)):
            start, end, _key = self.ranges[group_index]
            if start > last or start >= count:
                break
            end = min(end, count - 1)
            first_row = self.view.get_background_area(Gtk.TreePath.new_from_indices([start + self.model_offset]), None)
            last_row = self.view.get_background_area(Gtk.TreePath.new_from_indices([end + self.model_offset]), None)
            y = origin[1] + self.view.convert_bin_window_to_widget_coords(0, first_row.y)[1]
            bottom = origin[1] + self.view.convert_bin_window_to_widget_coords(0, last_row.y + last_row.height)[1]
            context.set_source_rgba(*( (0.15, 0.15, 0.15, 0.24) if self.player.theme == 'light'
                                       else (1, 1, 1, 0.16)))
            context.set_line_width(1)
            context.move_to(origin[0], y - 7.5)
            context.line_to(origin[0] + width, y - 7.5)
            context.stroke()
            available = max(0, bottom - y - 16)
            size = min(self.ART_SIZE, max(0, int(available)), gutter - 16)
            if size < 8 or bottom <= top:
                continue
            context.save()
            context.rectangle(max(origin[0], x), y + 8,
                              max(0, min(gutter, origin[0] + width - x)),
                              available)
            context.clip()
            if y + 8 + size > top:
                pixbuf = self.cover_for(self.results[start])
                context.save()
                context.translate(x + 8, y + 8)
                context.scale(size / pixbuf.get_width(), size / pixbuf.get_height())
                Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
                context.get_source().set_filter(cairo.FILTER_BILINEAR)
                context.paint()
                context.restore()
            layout = PangoCairo.create_layout(context)
            font = self.get_style_context().get_property('font', Gtk.StateFlags.NORMAL).copy()
            font.set_size(max(9, round(getattr(self.player, 'text_size', 18) * .72)) * Pango.SCALE)
            layout.set_font_description(font)
            layout.set_width((gutter - 16) * Pango.SCALE)
            layout.set_alignment(Pango.Alignment.LEFT)
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            context.set_source_rgba(*( (0.12, 0.12, 0.12, .9) if self.player.theme == 'light'
                                       else (.94, .94, .94, .9)))
            text_y = y + 8 + size + 5
            for text in album_details(self.results[start]):
                if not text:
                    continue
                layout.set_text(text, -1)
                context.move_to(x + 8, text_y)
                PangoCairo.show_layout(context, layout)
                text_y += layout.get_pixel_size()[1] + 2
            context.restore()
        context.restore()
        return False
