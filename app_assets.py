"""Application artwork shared by source and frozen builds."""

import sys
from functools import lru_cache
from pathlib import Path

import gi

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

SMALL_PLACEHOLDER_LOGO_RATIO = 0.60


def icon_path():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'apistat.png'


@lru_cache(maxsize=1)
def app_icon():
    return GdkPixbuf.Pixbuf.new_from_file(str(icon_path()))


@lru_cache(maxsize=16)
def placeholder_art(size, logo_ratio=1.0):
    """Return the logo centered in a transparent artwork square."""
    if size < 1:
        raise ValueError('Artwork size must be positive')
    source = app_icon()
    logo_size = max(1, round(size * logo_ratio))
    scale = min(logo_size / source.get_width(), logo_size / source.get_height())
    width = max(1, round(source.get_width() * scale))
    height = max(1, round(source.get_height() * scale))
    scaled = source.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    square = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, size, size)
    square.fill(0)
    scaled.copy_area(0, 0, width, height, square,
                     (size - width) // 2, (size - height) // 2)
    return square
