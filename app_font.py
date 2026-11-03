"""Register Apistat's redistributable UI font without installing it system-wide."""

import ctypes
import ctypes.util
import sys
from functools import lru_cache
from pathlib import Path


DEFAULT_FONT_FAMILY = 'Nunito'
def _register_pango_font(path):
    """Register the font directly with Pango's active platform backend."""
    try:
        import gi
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import GLib, PangoCairo
    except (ImportError, ValueError):
        return False
    try:
        fontmap = PangoCairo.FontMap.get_default()
        add = getattr(fontmap, 'add_font_file', None)
        return bool(add and add(str(path)))
    except (ImportError, AttributeError, RuntimeError, TypeError, GLib.Error):
        return False


def font_path():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'fonts' / 'Nunito-wght.ttf'


@lru_cache(maxsize=1)
def register_bundled_font():
    path = font_path()
    if not path.is_file():
        return False
    if _register_pango_font(path):
        return True
    names = [ctypes.util.find_library('fontconfig'), 'libfontconfig.so.1',
             'libfontconfig-1.dll']
    for name in filter(None, names):
        try:
            library = ctypes.CDLL(name)
            library.FcConfigGetCurrent.restype = ctypes.c_void_p
            library.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            library.FcConfigAppFontAddFile.restype = ctypes.c_int
            config = library.FcConfigGetCurrent()
            if config and library.FcConfigAppFontAddFile(config, str(path).encode()):
                return True
        except (OSError, AttributeError):
            continue
    return False
