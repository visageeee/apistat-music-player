"""Native Windows frame integration for a GTK toplevel."""

import ctypes
import os


class Margins(ctypes.Structure):
    _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                ('top', ctypes.c_int), ('bottom', ctypes.c_int)]


def native_handle(window):
    if os.name != 'nt':
        raise OSError('Windows window handles are unavailable on this platform')
    capsule = window.__gpointer__
    get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
    get_pointer.argtypes = (ctypes.py_object, ctypes.c_char_p)
    get_pointer.restype = ctypes.c_void_p
    pointer = get_pointer(capsule, None)
    gdk = ctypes.CDLL('libgdk-3-0.dll')
    get_handle = gdk.gdk_win32_window_get_handle
    get_handle.argtypes = (ctypes.c_void_p,)
    get_handle.restype = ctypes.c_void_p
    return get_handle(pointer)


def configure_window(window, rounded):
    """Ask DWM for its native shadow and, on Windows 11, corner preference."""
    if os.name != 'nt':
        return False
    try:
        handle = native_handle(window)
        if not handle:
            return False
        dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        extend = dwm.DwmExtendFrameIntoClientArea
        extend.argtypes = (ctypes.c_void_p, ctypes.POINTER(Margins))
        extend.restype = ctypes.c_long
        margins = Margins(1, 1, 1, 1)
        result = extend(handle, ctypes.byref(margins))
        set_attribute = dwm.DwmSetWindowAttribute
        set_attribute.argtypes = (ctypes.c_void_p, ctypes.c_uint,
                                  ctypes.c_void_p, ctypes.c_uint)
        set_attribute.restype = ctypes.c_long
        preference = ctypes.c_int(2 if rounded else 1)
        # The corner preference is supported on Windows 11; older systems
        # simply ignore it while still applying the native frame extension.
        set_attribute(handle, 33, ctypes.byref(preference), ctypes.sizeof(preference))
        return result == 0
    except (OSError, AttributeError, TypeError, ValueError):
        return False
