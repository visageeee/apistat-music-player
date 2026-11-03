"""Square artwork previews for Plex category tiles."""

import gi

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf


def square_preview(pixbuf, size=224):
    """Crop the center of the artwork to a square without adding blur."""
    if pixbuf is None or size <= 0:
        raise ValueError('Invalid artwork preview')
    width, height = pixbuf.get_width(), pixbuf.get_height()
    side = min(width, height)
    if side <= 0:
        raise ValueError('Empty artwork preview')
    cropped = pixbuf.new_subpixbuf((width - side) // 2, (height - side) // 2,
                                   side, side)
    return cropped.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
