"""Helpers for drawing GTK widgets into offscreen Cairo surfaces."""

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


def draw_allocated(widget, context):
    """Settle a pending allocation before asking GTK to draw the widget.

    GTK skips unchanged allocations, so this is cheap on normal animation frames.
    Reusing the current allocation lets the parent complete its normal layout later.
    """
    if isinstance(widget, Gtk.Widget):
        widget.size_allocate(widget.get_allocation())
    widget.draw(context)


def normalize_surface_origin(surface):
    """Remove GTK tree-row drag offsets before using a surface as an image."""
    if surface.get_device_offset() != (0.0, 0.0):
        surface.set_device_offset(0, 0)
    return surface
