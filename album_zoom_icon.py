"""Theme-colored magnifying glass icons for album canvas zoom controls."""
import math

import cairo
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


class AlbumZoomIcon(Gtk.DrawingArea):
    def __init__(self, zoom_in):
        super().__init__()
        self.zoom_in = zoom_in
        self.set_size_request(20, 20)
        self.connect('draw', self.draw_icon)

    def draw_icon(self, widget, context):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        scale = min(width, height) / 20
        color = widget.get_style_context().get_color(widget.get_state_flags())
        context.save()
        context.translate((width - 20 * scale) / 2, (height - 20 * scale) / 2)
        context.scale(scale, scale)
        context.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        context.set_line_width(1.8)
        context.set_line_cap(cairo.LINE_CAP_ROUND)
        context.arc(8, 8, 5.7, 0, 2 * math.pi)
        context.stroke()
        context.move_to(12.2, 12.2)
        context.line_to(17.4, 17.4)
        context.move_to(5.4, 8)
        context.line_to(10.6, 8)
        if self.zoom_in:
            context.move_to(8, 5.4)
            context.line_to(8, 10.6)
        context.stroke()
        context.restore()
        return False
