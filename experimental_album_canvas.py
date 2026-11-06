"""An opt-in, zoomable GPU album canvas independent of the regular wall."""
import math
import time
from bisect import bisect_right
from datetime import datetime

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango, PangoCairo

from gpu_album_wall import GPUAlbumWall
from local_cache import LocalCache, sort_albums
from plex_client import ALBUM_SORT_ARTIST
from thumbnail_atlas import ThumbnailAtlas, CELL as THUMB_SIZE

COLUMNS = 24
MIN_COLUMNS, MAX_COLUMNS = 4, 64
COVER = 160
GAP = 34
MARGIN = 24
MIN_ZOOM, MAX_ZOOM = .08, 2.5
SORT_SECONDS = .65
WORLD_WIDTH = 2 * MARGIN + COLUMNS * COVER + (COLUMNS - 1) * GAP


def world_width(columns):
    return 2 * MARGIN + columns * COVER + (columns - 1) * GAP


def year_label(album, order):
    if order == ALBUM_SORT_ARTIST:
        return (album.artist or '').strip() or 'Unknown artist'
    if order == 'year:desc':
        value = str(album.year or '')
        return value if len(value) == 4 and value.isdigit() and int(value) > 0 else 'Unknown year'
    if order == 'addedAt:desc':
        try:
            return (f'Added {datetime.fromtimestamp(album.added_at).year}'
                    if album.added_at > 0 else 'Date added unknown')
        except (OSError, ValueError, OverflowError, TypeError):
            return 'Date added unknown'
    return None


def alphabet_letter(value):
    value = (value or '').strip()
    return value[0].upper() if value and value[0].isalpha() else '#'


def heading_accent_range(label, count):
    """Return the byte range for the actual year or alphabet character."""
    if count is None:
        return 0, len(label.encode('utf-8'))
    if label.isdigit() and len(label) == 4:
        return 0, len(label)
    if label.startswith('Added ') and len(label) == 10 and label[6:].isdigit():
        return 6, 10
    return None


def grid_slots(albums, order, columns=COLUMNS):
    """Place year headings in rows and artist labels inline between albums."""
    slots, indices, markers = [], [], []
    previous = None
    previous_letter = None
    for index, album in enumerate(albums):
        label = year_label(album, order)
        if order in (ALBUM_SORT_ARTIST, 'titleSort'):
            letter = alphabet_letter(album.artist if order == ALBUM_SORT_ARTIST else album.title)
            if letter != previous_letter:
                slots.extend([None] * (-len(slots) % columns))
                markers.append([len(slots), letter, None])
                slots.extend([None] * columns)
                previous_letter = letter
                previous = None
        if label is not None and (previous is None or label.casefold() != previous.casefold()):
            if order != ALBUM_SORT_ARTIST:
                slots.extend([None] * (-len(slots) % columns))
            markers.append([len(slots), label, 0])
            slots.extend([None] * (1 if order == ALBUM_SORT_ARTIST else columns))
        previous = label
        indices.append(len(slots))
        slots.append(index)
        if label is not None:
            markers[-1][2] += 1
    return slots, indices, [tuple(marker) for marker in markers]


def year_font_size(zoom, text_size=18):
    """Scale headings with the user's text size and keep them readable at a distance."""
    return text_size * min(1.6, math.sqrt(max(1., zoom / .35)))


def artist_font_size(zoom, cover_size, text_size):
    scale = min(1., max(.5, math.sqrt(zoom / .35)))
    return min(text_size * .85 * scale, max(4., cover_size * .48))


def row_offsets(row_count, marker_rows, row_height, heading_height):
    offsets = [0.]
    marker_rows = set(marker_rows)
    for row in range(row_count):
        offsets.append(offsets[-1] + (heading_height if row in marker_rows else row_height))
    return offsets


def zoom_row_anchor(offset, cursor, old_top, old_rows, new_top, new_rows):
    """Preserve the point within a row when differently sized headers scale."""
    position = offset + cursor - old_top
    if not old_rows or len(old_rows) < 2 or position < 0 or position >= old_rows[-1]:
        return offset + new_top - old_top
    row = max(0, bisect_right(old_rows, position) - 1)
    fraction = (position - old_rows[row]) / (old_rows[row + 1] - old_rows[row])
    return new_top + new_rows[row] + fraction * (new_rows[row + 1] - new_rows[row]) - cursor


def zoom_anchor(offset, cursor, old_zoom, new_zoom):
    """Keep the same canvas coordinate under the pointer during a zoom."""
    return (offset + cursor) * new_zoom / old_zoom - cursor


def sort_progress(start, now):
    fraction = min(1., max(0., (now - start) / SORT_SECONDS))
    return fraction * fraction * (3 - 2 * fraction)


def search_catalog(albums, query, order):
    needle = query.strip().casefold()
    filtered = (album for album in albums if not needle or
                needle in (album.title or '').casefold() or
                needle in (album.artist or '').casefold())
    return sort_albums(filtered, order)


class CanvasPlayer:
    """Expose a canvas-specific scale without changing the main wall settings."""
    def __init__(self, player, embedded=False):
        self.player = player
        self.zoom = .6
        self.embedded = embedded

    def __getattr__(self, name):
        return getattr(self.player, name)

    def __setattr__(self, name, value):
        if name in ('player', 'zoom', 'embedded'):
            object.__setattr__(self, name, value)
        else:
            setattr(self.player, name, value)

    # This is a separate top-level window, so it cannot sample the main
    # window's GTK background or its visualizer.
    @property
    def shared_background(self):
        return getattr(self.player, 'shared_background', None) if self.embedded else None

    @property
    def background_visualizer(self):
        return getattr(self.player, 'background_visualizer', None) if self.embedded else None

    @property
    def album_art_size(self):
        return COVER * self.zoom

    @property
    def album_spacing(self):
        return GAP * self.zoom

    @property
    def album_margin(self):
        return MARGIN * self.zoom

    @property
    def show_album_details(self):
        # Labels remain legible at useful zoom levels; otherwise they overlap.
        return self.player.show_album_details and self.zoom >= .7

    @property
    def text_size(self):
        return max(9, min(self.player.text_size, round(self.player.text_size * self.zoom)))


class CanvasPan:
    def __init__(self, wall):
        self.wall = wall
        self.start = None

    def press(self, event):
        if event.button != 1 or event.state & (Gdk.ModifierType.CONTROL_MASK |
                                               Gdk.ModifierType.MOD1_MASK):
            return False
        self.start = (event.x_root, event.y_root, self.wall.x_adjustment.get_value(),
                      self.wall.adjustment.get_value())
        return True

    def motion(self, event):
        if self.start is None:
            return False
        if not event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.start = None
            return False
        x, y, ox, oy = self.start
        self.wall.x_adjustment.set_value(ox + x - event.x_root)
        self.wall.adjustment.set_value(oy + y - event.y_root)
        return True

    def release(self, event):
        if event.button != 1 or self.start is None:
            return False
        self.start = None
        return True


class ExperimentalAlbumCanvas(GPUAlbumWall):
    def __init__(self, player, failed, pressed, *, embedded=False):
        self.canvas_player = CanvasPlayer(player, embedded)
        self.target_zoom = self.canvas_player.zoom
        self.anchor = (0., 0.)
        self.x_adjustment = Gtk.Adjustment()
        self.sort_start = None
        self.sort_origins = None
        self.animation_tick = 0
        self.columns = COLUMNS
        self.ctrl_scroll_remainder = 0.
        self.sort_order = 'year:desc'
        self.grid_items, self.album_slots, self.year_markers = [], [], []
        self._fit_pending = True
        self.thumbnail_atlas = None
        self.low_detail = True
        self.refresh_indices = set()
        self._rows_key = None
        self._rows_offsets = [0.]
        super().__init__(self.canvas_player, failed, album_pressed=pressed, load_more=False)
        self.background_scroller = CanvasPan(self)
        self.x_adjustment.connect('value-changed', self.changed)
        if not embedded:
            self.render_surface.set_margin_top(0)
            self.scrollbar.set_margin_top(0)
        self.input_surface.get_accessible().set_name('Experimental album canvas')
        self.input_surface.add_events(Gdk.EventMask.TOUCH_MASK | Gdk.EventMask.TOUCHPAD_GESTURE_MASK)
        self.pinch = Gtk.GestureZoom.new(self.input_surface)
        self.pinch.connect('begin', self.pinch_begin)
        self.pinch.connect('scale-changed', self.pinch_scale_changed)
        self.pinch.connect('end', self.pinch_end)
        self.pinch.connect('cancel', self.pinch_end)
        self.pinch_start_zoom = None
        self.pinch_last_target = None

    def draw_background(self, _widget, context):
        if self.canvas_player.embedded:
            return super().draw_background(_widget, context)
        context.set_source_rgb(.035, .035, .045)
        context.paint()
        return False

    def shared_background_drawn(self, *args):
        return super().shared_background_drawn(*args) if self.canvas_player.embedded else False

    def visualizer_drawn(self, *args):
        return super().visualizer_drawn(*args) if self.canvas_player.embedded else False

    def glass_targets(self):
        return super().glass_targets() if self.canvas_player.embedded else []

    def geometry(self):
        width = max(1, self.area.get_allocated_width())
        size = self.player.album_art_size
        gap = self.player.album_spacing
        margin = self.player.album_margin
        extra = ((3 * (self.canvas_player.player.text_size + 4) + 6) * self.canvas_player.zoom
                 if self.canvas_player.player.show_album_details else 0)
        row_height = size + gap + extra
        offsets = self.get_row_offsets(row_height)
        total = offsets[-1] + 2 * margin
        canvas_width = world_width(self.columns) * self.canvas_player.zoom
        x0 = margin + max(0., (width - canvas_width) / 2)
        return width, size, gap, margin, self.columns, row_height, total, x0

    def get_row_offsets(self, row_height):
        count = math.ceil(len(self.grid_items) / self.columns)
        heading_height = max(year_font_size(self.canvas_player.zoom,
                                            self.canvas_player.player.text_size) + 8, row_height * .35)
        marker_rows = tuple(slot // self.columns for slot, _label, count in self.year_markers
                            if self.sort_order != ALBUM_SORT_ARTIST or count is None)
        key = (count, marker_rows, row_height, heading_height)
        if self._rows_key != key:
            self._rows_offsets = row_offsets(count, marker_rows, row_height, heading_height)
            self._rows_key = key
        return self._rows_offsets

    def set_albums(self, client, albums, reset=False):
        super().set_albums(client, albums, reset)
        self.grid_items, self.album_slots, self.year_markers = grid_slots(self.albums, self.sort_order, self.columns)
        if reset:
            self.refresh_indices.clear()
            if self.thumbnail_atlas is not None:
                self.thumbnail_atlas.close()
            self.thumbnail_atlas = ThumbnailAtlas(client, self.albums) if client and self.albums else None
            if self.thumbnail_atlas:
                self.prewarm_thumbnails(client, tuple(self.albums), self.thumbnail_atlas, self.epoch)
        self.layout_changed()

    def shutdown(self):
        super().shutdown()
        if self.thumbnail_atlas is not None:
            self.thumbnail_atlas.close()

    @staticmethod
    def decode_art(data, size):
        loader = GdkPixbuf.PixbufLoader()
        loader.set_size(size, size)
        loader.write(data)
        loader.close()
        image = loader.get_pixbuf()
        if image is None:
            raise ValueError('Invalid album artwork')
        return image

    def prewarm_thumbnails(self, client, albums, atlas, epoch):
        """Build atlas cells from existing art, without fetching the library again."""
        def work():
            cache = LocalCache(client)
            for album in albums:
                if self.closed or self.epoch != epoch:
                    return
                if not album.thumb or atlas.read(album.thumb) is not None:
                    continue
                data = cache.read_art(album.thumb, 480)
                if data:
                    try:
                        atlas.write(album.thumb, self.pixbuf_bytes(self.decode_art(data, THUMB_SIZE), THUMB_SIZE))
                    except (ValueError, GLib.Error):
                        pass
        self.art_workers.submit(work)

    def request_art(self, index):
        if (self.closed or not self.client or index in self.pending or
                not self.art_needs_refresh(index) or index in self.failed_art):
            return
        album, client, epoch = self.albums[index], self.client, self.epoch
        revision, size, low, atlas = self.art_revision, self.cell_size, self.low_detail, self.thumbnail_atlas
        if not album.thumb:
            return
        self.pending.add(index)
        def work():
            if self.closed or revision != self.art_revision or index not in self.needed_indices:
                return None, True
            pixels = atlas.read(album.thumb) if low and atlas else None
            if pixels is not None:
                image = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB,
                                                        True, 8, THUMB_SIZE, THUMB_SIZE, THUMB_SIZE * 4)
            else:
                cache = LocalCache(client)
                data = cache.read_art(album.thumb, 480)
                if data is None:
                    data = client.get('/photo/:/transcode', width=480, height=480,
                                      minSize=1, upscale=1, url=album.thumb)
                    try:
                        cache.save_art(album.thumb, 480, data)
                    except OSError:
                        pass
                image = self.decode_art(data, THUMB_SIZE if low else size)
                if atlas:
                    atlas.write(album.thumb, self.pixbuf_bytes(image, THUMB_SIZE))
            return self.pixbuf_bytes(image, size), False
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

    def update_detail_tier(self):
        low = self.player.album_art_size * self.area.get_scale_factor() <= 128
        if low == self.low_detail:
            return
        self.low_detail = low
        self.art_revision += 1
        self.pending.clear()
        self.failed_art.clear()
        self.uploads.clear()
        self.refresh_indices = set() if low else set(self.slots)

    def art_needs_refresh(self, index):
        return index not in self.slots or index in self.refresh_indices

    def art_uploaded(self, index):
        self.refresh_indices.discard(index)

    def resize_atlas(self, size):
        # Repack the currently visible pixels before drawing the new atlas.
        # They remain on screen while full-resolution replacements load.
        size = THUMB_SIZE if self.low_detail else size
        if size == self.cell_size:
            return
        old_size = self.cell_size
        old_slots = self.slots.copy()
        old_pixels = self.slot_pixels.copy()
        capacity = (self.atlas_size // size) ** 2
        visible = [index for index, _x, _y in self.visible()]
        order = list(dict.fromkeys(visible + list(old_slots)))[:capacity - 1]
        previous_refresh = self.refresh_indices
        super().resize_atlas(size)
        self.refresh_indices = set()
        for index in order:
            pixels = old_pixels.get(old_slots.get(index))
            if not pixels:
                continue
            image = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB,
                                                    True, 8, old_size, old_size, old_size * 4)
            pixels = self.pixbuf_bytes(image, size)
            slot = len(self.slots) + 1
            self.slots[index] = slot
            self.slot_keys[slot] = index
            self.slot_pixels[slot] = pixels
            self.upload(slot, pixels)
            if not self.low_detail and (size > old_size or index in previous_refresh):
                self.refresh_indices.add(index)

    def size_changed(self, *_args):
        width = self.area.get_allocated_width()
        if width > 100:
            if self._fit_pending:
                fit = min(MAX_ZOOM, max(MIN_ZOOM, width / world_width(self.columns)))
                self.canvas_player.zoom = fit
                self.target_zoom = fit
                self._fit_pending = False
        self.layout_changed()

    def layout_changed(self, x_value=None, y_value=None):
        for flip in self.flips.values():
            flip.dirty = True
        width, size, gap, margin, _columns, row_height, total, _x0 = self.geometry()
        height = max(1, self.area.get_allocated_height())
        canvas_width = 2 * margin + self.columns * size + (self.columns - 1) * gap
        self.adjustment.configure(self.adjustment.get_value() if y_value is None else y_value,
                                  0, max(total, height),
                                  row_height / 3, height * .8, height)
        self.x_adjustment.configure(self.x_adjustment.get_value() if x_value is None else x_value,
                                    0, max(canvas_width, width),
                                    size / 3, width * .8, width)
        self.queue_frame()
        self.labels.queue_draw()

    def positions(self, now=None):
        """Yield indices and screen positions, including in-flight sorting."""
        _width, size, gap, top, _columns, row_height, _total, x0 = self.geometry()
        offsets = self.get_row_offsets(row_height)
        ox, oy = self.x_adjustment.get_value(), self.adjustment.get_value()
        progress = (sort_progress(self.sort_start, time.monotonic() if now is None else now)
                    if self.sort_start is not None else 1.)
        for index in range(len(self.albums)):
            slot = self.album_slots[index]
            col, row = slot % self.columns, offsets[slot // self.columns] / row_height
            if self.sort_origins is not None and progress < 1:
                old_col, old_row = self.sort_origins[index]
                col = old_col + (col - old_col) * progress
                row = old_row + (row - old_row) * progress
            yield index, x0 + col * (size + gap) - ox, top + row * row_height - oy

    def visible_in_rect(self, rect):
        rx, ry, width, height = rect
        size = self.player.album_art_size
        if self.sort_origins is not None:
            candidates = self.positions()
        else:
            _w, _size, gap, top, columns, row_height, _total, x0 = self.geometry()
            ox, oy = self.x_adjustment.get_value(), self.adjustment.get_value()
            offsets = self.get_row_offsets(row_height)
            first = max(0, bisect_right(offsets, oy + ry - top) - 1)
            last = min(len(offsets) - 1, bisect_right(offsets, oy + ry + height - top))
            candidates = ((self.grid_items[slot], x0 + (slot % columns) * (size + gap) - ox,
                           top + offsets[slot // columns] - oy)
                          for slot in range(first * columns, min(len(self.grid_items), last * columns))
                          if self.grid_items[slot] is not None)
        for index, x, y in candidates:
            if x + size >= rx and x <= rx + width and y + size >= ry and y <= ry + height:
                yield index, x, y

    def visible(self):
        return self.visible_in_rect((0, 0, self.area.get_allocated_width(),
                                     self.area.get_allocated_height()))

    def draw_labels(self, widget, context):
        super().draw_labels(widget, context)
        if self.sort_origins is not None:
            return False
        _width, size, gap, top, columns, row_height, _total, x0 = self.geometry()
        offsets = self.get_row_offsets(row_height)
        ox, oy = self.x_adjustment.get_value(), self.adjustment.get_value()
        width, height = self.area.get_allocated_width(), self.area.get_allocated_height()
        artist_mode = self.sort_order == ALBUM_SORT_ARTIST
        accent = (getattr(self.player, 'current_art_bright', None)
                  if getattr(self.player, 'art_accent_enabled', False) else None)
        accent = accent or getattr(self.player, 'accent_color', '#e7a641')
        accent_color = Gdk.RGBA()
        if not accent_color.parse(accent):
            accent_color.parse('#e7a641')
        for slot, label, count in self.year_markers:
            inline = artist_mode and count is not None
            x = x0 + (slot % columns) * (size + gap) - ox if inline else x0 - ox
            row = slot // columns
            y = top + offsets[row] - oy
            heading_height = size if inline else offsets[row + 1] - offsets[row]
            right = x + (size if inline else columns * size + (columns - 1) * gap)
            left = max(0., x)
            right = min(width, right)
            if right <= left or y + heading_height < 0 or y > height:
                continue
            text = label if inline or count is None else f'{label}  ·  {count} {"album" if count == 1 else "albums"}'
            layout = self.labels.create_pango_layout(text)
            font = Pango.FontDescription('Sans Bold')
            text_size = self.canvas_player.player.text_size
            font_size = (artist_font_size(self.canvas_player.zoom, size, text_size) if inline else
                         year_font_size(self.canvas_player.zoom, text_size))
            font.set_absolute_size(int(font_size * Pango.SCALE))
            layout.set_font_description(font)
            layout.set_width(int((right - left) * Pango.SCALE))
            layout.set_alignment(Pango.Alignment.CENTER)
            if not inline:
                accent_range = heading_accent_range(label, count)
                if accent_range is not None:
                    attributes = Pango.AttrList()
                    color = Pango.attr_foreground_new(round(accent_color.red * 65535),
                                                      round(accent_color.green * 65535),
                                                      round(accent_color.blue * 65535))
                    color.start_index, color.end_index = accent_range
                    attributes.insert(color)
                    layout.set_attributes(attributes)
            if inline:
                layout.set_wrap(Pango.WrapMode.WORD_CHAR)
                layout.set_height(int(max(1., heading_height) * Pango.SCALE))
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            _logical, ink = layout.get_pixel_extents()
            context.save()
            context.rectangle(left, y, right - left, heading_height)
            context.clip()
            context.set_source_rgba(.92, .92, .94, .95)
            context.move_to(left, y + (heading_height - ink.height) / 2)
            PangoCairo.show_layout(context, layout)
            context.restore()
        return False

    def reorder(self, sort, albums=None, columns=None):
        ordered = sort_albums(self.albums, sort) if albums is None else list(albums)
        columns = self.columns if columns is None else max(MIN_COLUMNS, min(MAX_COLUMNS, columns))
        if ordered == self.albums and sort == self.sort_order and columns == self.columns:
            return
        now = time.monotonic()
        progress = sort_progress(self.sort_start, now) if self.sort_start is not None else 1.
        row_height = self.geometry()[5]
        offsets = self.get_row_offsets(row_height)
        old_positions = {}
        for i, album in enumerate(self.albums):
            slot = self.album_slots[i]
            col, row = slot % self.columns, offsets[slot // self.columns] / row_height
            if self.sort_origins is not None and progress < 1:
                old_col, old_row = self.sort_origins[i]
                col = old_col + (col - old_col) * progress
                row = old_row + (row - old_row) * progress
            old_positions[album.key] = (col, row)
        new_index = {album.key: i for i, album in enumerate(ordered)}
        # Requests in flight use old indices. Keep already uploaded textures but
        # invalidate those requests before mapping slots to the new order.
        self.art_revision += 1
        self.pending.clear()
        self.failed_art.clear()
        self.uploads.clear()
        slots = {new_index[self.albums[i].key]: slot for i, slot in self.slots.items()
                 if self.albums[i].key in new_index}
        self.slots = slots
        self.refresh_indices = {new_index[self.albums[i].key] for i in self.refresh_indices
                                if i < len(self.albums) and self.albums[i].key in new_index}
        self.slot_keys = [None] * self.capacity
        for index, slot in slots.items():
            self.slot_keys[slot] = index
        if ordered != self.albums:
            self.clear_card()
        self.albums = ordered
        self.sort_order = sort
        self.columns = columns
        self.grid_items, self.album_slots, self.year_markers = grid_slots(ordered, sort, columns)
        new_row_height = self.geometry()[5]
        new_offsets = self.get_row_offsets(new_row_height)
        self.sort_origins = [old_positions.get(album.key, (slot % columns,
                             new_offsets[slot // columns] / new_row_height))
                             for album, slot in zip(ordered, self.album_slots)]
        self.sort_start = now
        self.layout_changed()
        self.start_animation()
        self.queue_frame()

    def unflip_for_zoom_out(self):
        if not self.flips:
            return
        self.pending_exclusive_flip = None
        for flip in self.flips.values():
            if flip.target:
                flip.turn(0)
        if not self.flip_tick_id and self.area.get_mapped():
            self.flip_tick_id = self.area.add_tick_callback(self.animate_flip)
        self.queue_frame()

    def scroll(self, _area, event):
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            valid, _dx, dy = event.get_scroll_deltas()
            step = dy if valid else 0
        elif event.direction == Gdk.ScrollDirection.UP:
            step = -1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            step = 1
        else:
            return False
        if step:
            self.anchor = (event.x, event.y)
            if getattr(event, 'state', 0) & Gdk.ModifierType.CONTROL_MASK:
                # Stop any in-flight wheel zoom before changing the layout.
                self.target_zoom = self.canvas_player.zoom
                self.ctrl_scroll_remainder += step
                delta = math.trunc(self.ctrl_scroll_remainder)
                self.ctrl_scroll_remainder -= delta
                if delta:
                    columns = max(MIN_COLUMNS, min(MAX_COLUMNS, self.columns + delta))
                    if columns != self.columns:
                        self.reorder(self.sort_order, albums=self.albums, columns=columns)
            else:
                if step > 0:
                    self.unflip_for_zoom_out()
                self.target_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.target_zoom * math.exp(-.17 * step)))
            self.start_animation()
        return True

    def pinch_begin(self, _gesture, _sequence):
        self.pinch_start_zoom = self.canvas_player.zoom
        self.pinch_last_target = self.pinch_start_zoom
        self.target_zoom = self.pinch_start_zoom

    def pinch_scale_changed(self, gesture, scale):
        if self.pinch_start_zoom is None or not math.isfinite(scale) or scale <= 0:
            return
        valid, x, y = gesture.get_bounding_box_center()
        if not valid:
            x, y = self.area.get_allocated_width() / 2, self.area.get_allocated_height() / 2
        self.anchor = (x, y)
        target = max(MIN_ZOOM, min(MAX_ZOOM, self.pinch_start_zoom * scale))
        if target < self.pinch_last_target:
            self.unflip_for_zoom_out()
        self.target_zoom = target
        self.pinch_last_target = target
        self.start_animation()

    def pinch_end(self, _gesture, _sequence):
        self.pinch_start_zoom = None
        self.pinch_last_target = None

    def start_animation(self):
        if not self.animation_tick and self.area.get_mapped():
            self.animation_tick = self.area.add_tick_callback(self.animate_canvas)

    def animate_canvas(self, _area, clock):
        now = time.monotonic()
        previous = getattr(self, '_last_animation', None) or now - 1 / 60
        self._last_animation = now
        factor = 1 - math.exp(-min(.1, now - previous) * 13)
        old = self.canvas_player.zoom
        new = old + (self.target_zoom - old) * factor
        if abs(new - self.target_zoom) < .001:
            new = self.target_zoom
        if new != old:
            x, y = self.anchor
            width = self.area.get_allocated_width()
            old_center = max(0., (width - world_width(self.columns) * old) / 2)
            new_center = max(0., (width - world_width(self.columns) * new) / 2)
            ox = zoom_anchor(self.x_adjustment.get_value(), x - old_center, old, new) + new_center - old_center
            old_geometry = self.geometry()
            old_rows = self.get_row_offsets(old_geometry[5])
            old_offset = self.adjustment.get_value()
            self.canvas_player.zoom = new
            new_geometry = self.geometry()
            new_rows = self.get_row_offsets(new_geometry[5])
            oy = zoom_row_anchor(old_offset, y, old_geometry[3], old_rows,
                                 new_geometry[3], new_rows)
            self.update_detail_tier()
            self.layout_changed(ox, oy)
        if self.sort_start is not None and now - self.sort_start >= SORT_SECONDS:
            self.sort_start = None
            self.sort_origins = None
        self.queue_frame()
        self.labels.queue_draw()
        if self.sort_start is None and new == self.target_zoom:
            self.animation_tick = 0
            self._last_animation = None
            return False
        return True

    def area_unmapped(self, area):
        if self.animation_tick:
            self.area.remove_tick_callback(self.animation_tick)
            self.animation_tick = 0
        self._last_animation = None
        self.pinch_start_zoom = None
        self.pinch_last_target = None
        super().area_unmapped(area)

    def area_mapped(self, area):
        super().area_mapped(area)
        if self.sort_start is not None or self.canvas_player.zoom != self.target_zoom:
            self.start_animation()
