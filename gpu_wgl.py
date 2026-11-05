"""Private Windows OpenGL context for the album-wall framebuffer."""
import ctypes
from contextlib import contextmanager

import gi
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk

from gpu_offscreen import OffscreenGPU


class PixelFormatDescriptor(ctypes.Structure):
    _fields_ = [('nSize', ctypes.c_uint16), ('nVersion', ctypes.c_uint16),
                ('dwFlags', ctypes.c_uint32), ('iPixelType', ctypes.c_ubyte),
                ('cColorBits', ctypes.c_ubyte), ('cRedBits', ctypes.c_ubyte),
                ('cRedShift', ctypes.c_ubyte), ('cGreenBits', ctypes.c_ubyte),
                ('cGreenShift', ctypes.c_ubyte), ('cBlueBits', ctypes.c_ubyte),
                ('cBlueShift', ctypes.c_ubyte), ('cAlphaBits', ctypes.c_ubyte),
                ('cAlphaShift', ctypes.c_ubyte), ('cAccumBits', ctypes.c_ubyte),
                ('cAccumRedBits', ctypes.c_ubyte), ('cAccumGreenBits', ctypes.c_ubyte),
                ('cAccumBlueBits', ctypes.c_ubyte), ('cAccumAlphaBits', ctypes.c_ubyte),
                ('cDepthBits', ctypes.c_ubyte), ('cStencilBits', ctypes.c_ubyte),
                ('cAuxBuffers', ctypes.c_ubyte), ('iLayerType', ctypes.c_ubyte),
                ('bReserved', ctypes.c_ubyte), ('dwLayerMask', ctypes.c_uint32),
                ('dwVisibleMask', ctypes.c_uint32), ('dwDamageMask', ctypes.c_uint32)]


def _bind(library, name, result, arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


class WindowsOffscreenGPU(OffscreenGPU):
    """Render to an FBO in a hidden native window, never a GTK GL surface."""
    def __init__(self, gl):
        self.gl = gl
        self.user = ctypes.WinDLL('user32.dll', use_last_error=True)
        self.gdi = ctypes.WinDLL('gdi32.dll', use_last_error=True)
        self.wgl = gl.library
        pointer, integer = ctypes.c_void_p, ctypes.c_int
        _bind(self.user, 'CreateWindowExW', pointer,
              [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
               integer, integer, integer, integer, pointer, pointer, pointer, pointer])
        _bind(self.user, 'GetDC', pointer, [pointer])
        _bind(self.user, 'ReleaseDC', integer, [pointer, pointer])
        _bind(self.user, 'DestroyWindow', integer, [pointer])
        descriptor = ctypes.POINTER(PixelFormatDescriptor)
        _bind(self.gdi, 'ChoosePixelFormat', integer, [pointer, descriptor])
        _bind(self.gdi, 'SetPixelFormat', integer, [pointer, integer, descriptor])
        _bind(self.wgl, 'wglCreateContext', pointer, [pointer])
        _bind(self.wgl, 'wglMakeCurrent', integer, [pointer, pointer])
        _bind(self.wgl, 'wglDeleteContext', integer, [pointer])
        _bind(self.wgl, 'wglGetCurrentContext', pointer, [])
        _bind(self.wgl, 'wglGetCurrentDC', pointer, [])
        self.window = self.dc = self.context = None
        self.texture, self.framebuffer = ctypes.c_uint(), ctypes.c_uint()
        self.size = (0, 0)
        try:
            # A tiny hidden window supplies a device context; all pixels are
            # rendered to our FBO and handed to GTK as a Cairo image.
            self.window = self.user.CreateWindowExW(0, 'STATIC', '', 0x86000000,
                                                    0, 0, 1, 1, None, None, None, None)
            if not self.window:
                raise RuntimeError('Could not create an offscreen OpenGL window')
            self.dc = self.user.GetDC(self.window)
            if not self.dc:
                raise RuntimeError('Could not acquire an OpenGL device context')
            pfd = PixelFormatDescriptor()
            pfd.nSize, pfd.nVersion = ctypes.sizeof(pfd), 1
            pfd.dwFlags = 0x00000004 | 0x00000020  # DRAW_TO_WINDOW | SUPPORT_OPENGL
            pfd.iPixelType, pfd.cColorBits, pfd.cAlphaBits = 0, 32, 8
            pixel_format = self.gdi.ChoosePixelFormat(self.dc, ctypes.byref(pfd))
            if not pixel_format or not self.gdi.SetPixelFormat(self.dc, pixel_format, ctypes.byref(pfd)):
                raise RuntimeError('No suitable Windows OpenGL pixel format')
            legacy = self.wgl.wglCreateContext(self.dc)
            if not legacy:
                raise RuntimeError('Could not initialize Windows OpenGL')
            self.context = legacy
            with self.current():
                address = gl.get_proc(b'wglCreateContextAttribsARB')
                if address in (None, 0, 1, 2, 3, ctypes.c_void_p(-1).value):
                    raise RuntimeError('OpenGL 3.2 context creation is unavailable')
                create = ctypes.WINFUNCTYPE(pointer, pointer, pointer,
                                            ctypes.POINTER(integer))(address)
                attributes = (integer * 7)(0x2091, 3, 0x2092, 2, 0x9126, 1, 0)
                modern = create(self.dc, None, attributes)
                if not modern:
                    raise RuntimeError('OpenGL 3.2 core profile is unavailable')
            self.context = modern
            self.wgl.wglDeleteContext(legacy)
        except Exception:
            self.close()
            raise

    @contextmanager
    def current(self):
        previous_gdk = Gdk.GLContext.get_current()
        previous_context = self.wgl.wglGetCurrentContext()
        previous_dc = self.wgl.wglGetCurrentDC()
        if previous_gdk is not None:
            Gdk.GLContext.clear_current()
        if not self.wgl.wglMakeCurrent(self.dc, self.context):
            if previous_gdk is not None:
                previous_gdk.make_current()
            elif previous_context:
                self.wgl.wglMakeCurrent(previous_dc, previous_context)
            raise RuntimeError('Could not activate the private Windows OpenGL context')
        try:
            yield
        finally:
            self.wgl.wglMakeCurrent(None, None)
            if previous_gdk is not None:
                previous_gdk.make_current()
            elif previous_context:
                self.wgl.wglMakeCurrent(previous_dc, previous_context)

    def close(self):
        if self.context:
            self.wgl.wglDeleteContext(self.context)
        if self.dc and self.window:
            self.user.ReleaseDC(self.window, self.dc)
        if self.window:
            self.user.DestroyWindow(self.window)
        self.context = self.dc = self.window = None
