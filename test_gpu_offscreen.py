"""Exercise private GPU rendering without involving GTK's GL compositor."""
import ctypes
import unittest

import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
from gpu_gl import load_gl, GL_COLOR_BUFFER_BIT, GL_UNSIGNED_BYTE
from gpu_offscreen import GL_BGRA, create_offscreen_gpu


class OffscreenGPUTests(unittest.TestCase):
    def test_framebuffer_readback_and_context_restoration(self):
        try:
            gl = load_gl()
            gpu = create_offscreen_gpu(gl)
        except (OSError, RuntimeError) as error:
            self.skipTest(str(error))
        previous = Gdk.GLContext.get_current()
        try:
            with gpu.current():
                gpu.target(4, 3)
                gl.glViewport(0, 0, 4, 3)
                gl.glClearColor(.2, .1, 0, .5)
                gl.glClear(GL_COLOR_BUFFER_BIT)
                data = (ctypes.c_ubyte * 4)()
                gl.glReadPixels(0, 0, 1, 1, GL_BGRA, GL_UNSIGNED_BYTE, data)
                for actual, expected in zip(data, [0, 26, 51, 128]):
                    self.assertLessEqual(abs(actual - expected), 1)
                self.assertEqual(gl.glGetError(), 0)
                gpu.release_target()
            self.assertEqual(Gdk.GLContext.get_current(), previous)
        finally:
            gpu.close()
