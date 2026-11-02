"""Pixel region for optional rounded GTK window corners."""

import math

import cairo


def rounded_region(width, height, radius=14):
    if width < 1 or height < 1:
        raise ValueError('Window dimensions must be positive')
    radius = max(0, min(radius, width // 2, height // 2))
    region = cairo.Region()
    if not radius:
        region.union(cairo.RectangleInt(0, 0, width, height))
        return region
    if height > 2 * radius:
        region.union(cairo.RectangleInt(0, radius, width, height - 2 * radius))
    for y in range(radius):
        distance = radius - y - 0.5
        inset = math.ceil(radius - math.sqrt(radius * radius - distance * distance))
        region.union(cairo.RectangleInt(inset, y, width - 2 * inset, 1))
        region.union(cairo.RectangleInt(inset, height - 1 - y, width - 2 * inset, 1))
    return region
