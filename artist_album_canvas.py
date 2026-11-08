"""Artist album canvas with a description beside each cover."""
import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gdk, Pango, PangoCairo

from experimental_album_canvas import ExperimentalAlbumCanvas, year_label


def artist_album_slots(albums, columns):
    """Reserve a neighboring slot for each album's text and full rows for years."""
    slots, indices, markers = [], [], []
    previous = None
    for index, album in enumerate(albums):
        label = year_label(album, 'year:desc')
        if label != previous:
            slots.extend([None] * (-len(slots) % columns))
            markers.append([len(slots), label, 0])
            slots.extend([None] * columns)
            previous = label
        if len(slots) % columns == columns - 1:
            slots.append(None)
        indices.append(len(slots))
        slots.extend([index, None])
        markers[-1][2] += 1
    return slots, indices, [tuple(marker) for marker in markers]


class ArtistAlbumCanvas(ExperimentalAlbumCanvas):
    suppress_album_labels = True

    def __init__(self, *args, **kwargs):
        self.descriptions = {}
        self.read_more_hits = []
        self.read_more_pressed = None
        super().__init__(*args, **kwargs)

    def make_grid_slots(self, albums, _order, columns):
        return artist_album_slots(albums, columns)

    def set_descriptions(self, descriptions):
        self.descriptions = descriptions
        self.labels.queue_draw()

    def read_more_at(self, x, y):
        for left, top, width, height, album in self.read_more_hits:
            if left <= x < left + width and top <= y < top + height:
                return left, top, width, height, album
        return None

    def pressed(self, widget, event):
        if event.button == 1:
            hit = self.read_more_at(event.x, event.y)
            if hit:
                self.read_more_pressed = hit
                return True
        return super().pressed(widget, event)

    def released(self, widget, event):
        if event.button == 1 and self.read_more_pressed:
            hit, self.read_more_pressed = self.read_more_pressed, None
            current = self.read_more_at(event.x, event.y)
            if current and current[4].key == hit[4].key:
                left, top, width, height, album = current
                rect = Gdk.Rectangle()
                rect.x, rect.y = round(left), round(top)
                rect.width, rect.height = max(1, round(width)), max(1, round(height))
                self.player.show_album_description(album, self.descriptions.get(album.key, ''),
                                                   self.input_surface, rect)
            return True
        return super().released(widget, event)

    def draw_labels(self, widget, context):
        super().draw_labels(widget, context)
        size = self.player.album_art_size
        gap = self.player.album_spacing
        color = (.1, .1, .1) if self.player.theme == 'light' else (.94, .94, .94)
        self.read_more_hits = []
        for index, x, y in self.visible():
            album = self.albums[index]
            lines = [(album.title, True), (str(album.year or ''), False)]
            py = y + min(8, size * .05)
            context.save()
            context.rectangle(x + size + gap, y, size, size)
            context.clip()
            for value, bold in lines:
                if not value:
                    continue
                layout = self.labels.create_pango_layout(value)
                layout.set_width(max(1, int(size * Pango.SCALE)))
                layout.set_wrap(Pango.WrapMode.WORD_CHAR)
                layout.set_ellipsize(Pango.EllipsizeMode.END)
                remaining = max(1, y + size - py)
                layout.set_height(int(remaining * Pango.SCALE))
                if bold:
                    attrs = Pango.AttrList()
                    attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
                    layout.set_attributes(attrs)
                context.set_source_rgba(*color, .96 if bold else .72)
                context.move_to(x + size + gap, py)
                PangoCairo.show_layout(context, layout)
                py += layout.get_pixel_size()[1] + 4
                if py >= y + size:
                    break
            description = self.descriptions.get(album.key, '')
            remaining = y + size - py
            if description and remaining > 0:
                layout = self.labels.create_pango_layout(description)
                layout.set_width(max(1, int(size * Pango.SCALE)))
                layout.set_wrap(Pango.WrapMode.WORD_CHAR)
                full_height = layout.get_pixel_size()[1]
                link = self.labels.create_pango_layout('Read more…')
                link_height = link.get_pixel_size()[1]
                clipped = full_height > remaining
                if clipped and remaining >= link_height:
                    preview_height = remaining - link_height - 4
                    link_y = y + size - link_height
                    context.set_source_rgba(*color, .9)
                    context.move_to(x + size + gap, link_y)
                    PangoCairo.show_layout(context, link)
                    link_width = min(size, link.get_pixel_size()[0])
                    self.read_more_hits.append((x + size + gap, link_y, link_width,
                                                link_height, album))
                    if preview_height <= 0:
                        context.restore()
                        continue
                    layout.set_height(max(1, int(preview_height * Pango.SCALE)))
                    layout.set_ellipsize(Pango.EllipsizeMode.END)
                else:
                    layout.set_height(max(1, int(remaining * Pango.SCALE)))
                    layout.set_ellipsize(Pango.EllipsizeMode.END)
                context.set_source_rgba(*color, .72)
                context.move_to(x + size + gap, py)
                PangoCairo.show_layout(context, layout)
            context.restore()
        return False
