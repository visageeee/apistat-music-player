"""Private EGL context and framebuffer for rendering without GTK's GL compositor."""
import ctypes
import sys
from contextlib import contextmanager

import gi
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk

from gpu_gl import GL_RGBA, GL_TEXTURE_2D, GL_UNSIGNED_BYTE

EGL_NONE = 0x3038
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_BIT = 0x0008
EGL_OPENGL_API = 0x30A2
EGL_RED_SIZE = 0x3024
EGL_GREEN_SIZE = 0x3023
EGL_BLUE_SIZE = 0x3022
EGL_ALPHA_SIZE = 0x3021
EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056
EGL_CONTEXT_MAJOR_VERSION = 0x3098
EGL_CONTEXT_MINOR_VERSION = 0x30FB
EGL_CONTEXT_OPENGL_PROFILE_MASK = 0x30FD
EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT = 0x0001
EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
EGL_DRAW = 0x3059
EGL_READ = 0x305A
GL_FRAMEBUFFER = 0x8D40
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_BGRA = 0x80E1


def load_egl():
    egl = ctypes.CDLL('libEGL.so.1')
    pointer, integer, boolean = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint
    signatures = {
        'eglGetDisplay': (pointer, [pointer]),
        'eglInitialize': (boolean, [pointer, ctypes.POINTER(integer), ctypes.POINTER(integer)]),
        'eglChooseConfig': (boolean, [pointer, ctypes.POINTER(integer), ctypes.POINTER(pointer), integer, ctypes.POINTER(integer)]),
        'eglBindAPI': (boolean, [ctypes.c_uint]),
        'eglQueryAPI': (ctypes.c_uint, []),
        'eglCreatePbufferSurface': (pointer, [pointer, pointer, ctypes.POINTER(integer)]),
        'eglCreateContext': (pointer, [pointer, pointer, pointer, ctypes.POINTER(integer)]),
        'eglMakeCurrent': (boolean, [pointer, pointer, pointer, pointer]),
        'eglGetCurrentDisplay': (pointer, []),
        'eglGetCurrentContext': (pointer, []),
        'eglGetCurrentSurface': (pointer, [integer]),
        'eglDestroyContext': (boolean, [pointer, pointer]),
        'eglDestroySurface': (boolean, [pointer, pointer]),
        'eglTerminate': (boolean, [pointer]),
        'eglGetError': (integer, []),
    }
    if hasattr(egl, 'eglGetPlatformDisplay'):
        signatures['eglGetPlatformDisplay'] = (pointer, [ctypes.c_uint, pointer, ctypes.POINTER(integer)])
    for name, (result, args) in signatures.items():
        function = getattr(egl, name)
        function.restype, function.argtypes = result, args
    return egl


class OffscreenGPU:
    """Own a non-GDK context; GTK receives only ordinary Cairo pixels."""
    def __init__(self, gl, egl=None):
        if sys.byteorder != "little":
            raise RuntimeError("The GPU wall requires little-endian pixel storage")
        self.gl = gl
        self.egl = egl or load_egl()
        self.display = self.surface = self.context = None
        self.texture, self.framebuffer = ctypes.c_uint(), ctypes.c_uint()
        self.size = (0, 0)
        self._initialize()

    def _initialize(self):
        egl = self.egl
        displays = []
        if hasattr(egl, 'eglGetPlatformDisplay'):
            displays.append(egl.eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, None, None))
        displays.append(egl.eglGetDisplay(None))
        major, minor = ctypes.c_int(), ctypes.c_int()
        for display in displays:
            if display and egl.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)):
                self.display = display
                break
        if not self.display:
            raise RuntimeError('An offscreen EGL display could not be initialized')
        previous_api = egl.eglQueryAPI()
        try:
            if not egl.eglBindAPI(EGL_OPENGL_API):
                raise RuntimeError('Desktop OpenGL is unavailable through EGL')
            attributes = (ctypes.c_int * 13)(
                EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
                EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE)
            config, count = ctypes.c_void_p(), ctypes.c_int()
            if (not egl.eglChooseConfig(self.display, attributes, ctypes.byref(config), 1,
                                        ctypes.byref(count)) or count.value < 1):
                raise RuntimeError('No EGL framebuffer configuration is available')
            pbuffer = (ctypes.c_int * 5)(EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE)
            self.surface = egl.eglCreatePbufferSurface(self.display, config, pbuffer)
            if not self.surface:
                raise RuntimeError('EGL could not create an offscreen surface')
            context_attributes = (ctypes.c_int * 7)(
                EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 2,
                EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE)
            self.context = egl.eglCreateContext(self.display, config, None, context_attributes)
            if not self.context:
                raise RuntimeError('OpenGL 3.2 is unavailable through EGL')
        except Exception:
            self.close()
            raise
        finally:
            if previous_api:
                egl.eglBindAPI(previous_api)

    @contextmanager
    def current(self):
        egl = self.egl
        previous_gdk = Gdk.GLContext.get_current()
        previous_api = egl.eglQueryAPI()
        previous_display = egl.eglGetCurrentDisplay()
        previous_context = egl.eglGetCurrentContext()
        previous_draw = egl.eglGetCurrentSurface(EGL_DRAW)
        previous_read = egl.eglGetCurrentSurface(EGL_READ)
        if previous_gdk is not None:
            Gdk.GLContext.clear_current()
        if not egl.eglBindAPI(EGL_OPENGL_API) or not egl.eglMakeCurrent(
                self.display, self.surface, self.surface, self.context):
            if previous_api:
                egl.eglBindAPI(previous_api)
            if previous_gdk is not None:
                previous_gdk.make_current()
            elif previous_context and previous_display:
                egl.eglMakeCurrent(previous_display, previous_draw, previous_read, previous_context)
            raise RuntimeError('Could not activate the offscreen GPU context')
        try:
            yield
        finally:
            egl.eglMakeCurrent(self.display, None, None, None)
            if previous_api:
                egl.eglBindAPI(previous_api)
            if previous_gdk is not None:
                previous_gdk.make_current()
            elif previous_context and previous_display:
                egl.eglMakeCurrent(previous_display, previous_draw, previous_read, previous_context)

    def target(self, width, height):
        gl = self.gl
        if self.size == (width, height) and self.framebuffer.value:
            gl.glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)
            return
        if not self.texture.value:
            gl.glGenTextures(1, ctypes.byref(self.texture))
        if not self.framebuffer.value:
            gl.glGenFramebuffers(1, ctypes.byref(self.framebuffer))
        gl.glBindTexture(GL_TEXTURE_2D, self.texture)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0,
                        GL_RGBA, GL_UNSIGNED_BYTE, None)
        gl.glBindFramebuffer(GL_FRAMEBUFFER, self.framebuffer)
        gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                  GL_TEXTURE_2D, self.texture, 0)
        if gl.glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError('GPU wall framebuffer is unavailable')
        self.size = width, height

    def release_target(self):
        if self.framebuffer.value:
            self.gl.glDeleteFramebuffers(1, ctypes.byref(self.framebuffer))
            self.framebuffer = ctypes.c_uint()
        if self.texture.value:
            self.gl.glDeleteTextures(1, ctypes.byref(self.texture))
            self.texture = ctypes.c_uint()
        self.size = (0, 0)

    def close(self):
        egl = self.egl
        if self.context and self.display:
            egl.eglDestroyContext(self.display, self.context)
        if self.surface and self.display:
            egl.eglDestroySurface(self.display, self.surface)
        # EGL displays can be shared with GTK or another library. Terminating
        # one here would invalidate their contexts; destroy only what we own.
        self.context = self.surface = self.display = None


def create_offscreen_gpu(gl):
    if sys.platform == 'win32':
        from gpu_wgl import WindowsOffscreenGPU
        return WindowsOffscreenGPU(gl)
    return OffscreenGPU(gl)
