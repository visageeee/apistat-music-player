"""Prepare the next queue item's visual assets without touching GTK widgets."""

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf

from appearance import (cached_gradient, gradient_colors, theme_gradient_colors,
                        waveform_colors)
from local_cache import LocalCache
from track_waveform import analyze_track_waveform


def preload_next_art(client, thumb, theme, gradient_enabled, background_size,
                     cancelled=lambda: False):
    if not thumb or cancelled():
        return
    cache = LocalCache(client)
    palette = cache.read_palette(thumb)
    data = cache.read_art(thumb, 1000)
    if data is None and not cancelled():
        try:
            data = client.get('/photo/:/transcode', width=1000, height=1000,
                              minSize=1, upscale=1, url=thumb)
            if not cancelled():
                cache.save_art(thumb, 1000, data)
        except Exception:
            data = None
    if palette is None and data and not cancelled():
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.set_size(64, 64)
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            gradient, wave = gradient_colors(pixbuf), waveform_colors(pixbuf)
            if gradient and not cancelled():
                palette = gradient, wave
                cache.save_palette(thumb, gradient, wave)
        except Exception:
            pass
    if palette and gradient_enabled and not cancelled():
        colors = theme_gradient_colors(palette[0], theme)
        width, height = background_size
        if colors and width > 0 and height > 0:
            try:
                cached_gradient(width, height, colors)
            except Exception:
                pass


def preload_next_waveform(client, track, cancelled=lambda: False):
    if track.duration <= 0 or cancelled():
        return
    cache = LocalCache(client)
    if cache.read_waveform(track.key, track.duration) is not None:
        return
    try:
        uri = client.stream(track)
        if cancelled():
            return
        peaks = analyze_track_waveform(uri, client.address, client.token,
                                       track.duration, cancelled)
        if peaks is not None and not cancelled():
            cache.save_waveform(track.key, track.duration, peaks)
    except Exception:
        pass
