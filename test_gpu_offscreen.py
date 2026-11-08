"""Exercise private GPU rendering without involving GTK's GL compositor."""
import ctypes
import struct
import unittest
from unittest.mock import Mock

import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
from gpu_gl import (load_gl, GLProgram, GL_COLOR_BUFFER_BIT, GL_UNSIGNED_BYTE,
                    GL_RGBA, GL_TEXTURE_2D)
from gpu_glass import GPUBlur
from gpu_offscreen import GL_BGRA, create_offscreen_gpu


class OffscreenGPUTests(unittest.TestCase):
    def test_glass_blurs_the_actual_rendered_frame(self):
        try:
            gl = load_gl()
            gpu = create_offscreen_gpu(gl)
        except (OSError, RuntimeError) as error:
            self.skipTest(str(error))
        try:
            with gpu.current():
                gpu.target(128, 128)
                gl.glViewport(0, 0, 128, 128)
                gl.glClearColor(1, 0, 0, 1)
                gl.glClear(GL_COLOR_BUFFER_BIT)
                program = GLProgram()
                program.gl, program.vao, program.buffer = gl, ctypes.c_uint(), ctypes.c_uint()
                program.setup_program()
                blur = GPUBlur(gl)
                try:
                    draw_scene = Mock()
                    surface = blur.render('artist', 32, 32, program.vao, program.buffer, draw_scene,
                                          source_texture=gpu.texture, source_rect=(0, 0, 128, 128),
                                          source_size=(128, 128))
                    draw_scene.assert_not_called()
                    pixel = struct.unpack_from('=I', surface.get_data(), 16 * surface.get_stride() + 16 * 4)[0]
                    self.assertGreater((pixel >> 16) & 255, 240)
                    self.assertLess(pixel & 255, 5)
                    row = bytes((255, 0, 0, 255)) * 64 + bytes((0, 0, 255, 255)) * 64
                    raw = ctypes.create_string_buffer(row * 128)
                    gl.glBindTexture(GL_TEXTURE_2D, gpu.texture)
                    gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 128, 128,
                                       GL_RGBA, GL_UNSIGNED_BYTE, ctypes.cast(raw, ctypes.c_void_p))
                    for x, color_shift in ((0, 16), (64, 0)):
                        cropped = blur.render('artist', 16, 32, program.vao, program.buffer, draw_scene,
                                              source_texture=gpu.texture, source_rect=(x, 0, 64, 128),
                                              source_size=(128, 128))
                        pixel = struct.unpack_from('=I', cropped.get_data(),
                                                   16 * cropped.get_stride() + 8 * 4)[0]
                        self.assertGreater((pixel >> color_shift) & 255, 200)
                    raw = ctypes.create_string_buffer(
                        bytes((0, 0, 255, 255)) * (128 * 64) +
                        bytes((255, 0, 0, 255)) * (128 * 64))
                    gl.glBindTexture(GL_TEXTURE_2D, gpu.texture)
                    gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 128, 128,
                                       GL_RGBA, GL_UNSIGNED_BYTE, ctypes.cast(raw, ctypes.c_void_p))
                    for y, color_shift in ((0, 16), (64, 0)):
                        cropped = blur.render('artist', 32, 16, program.vao, program.buffer, draw_scene,
                                              source_texture=gpu.texture, source_rect=(0, y, 128, 64),
                                              source_size=(128, 128))
                        pixel = struct.unpack_from('=I', cropped.get_data(),
                                                   8 * cropped.get_stride() + 16 * 4)[0]
                        self.assertGreater((pixel >> color_shift) & 255, 200)
                    def draw_green():
                        gl.glClearColor(0, 1, 0, 1)
                        gl.glClear(GL_COLOR_BUFFER_BIT)
                    redrawn = blur.render('outside', 32, 32, program.vao, program.buffer,
                                          draw_green, supersample=2)
                    pixel = struct.unpack_from('=I', redrawn.get_data(),
                                               16 * redrawn.get_stride() + 16 * 4)[0]
                    self.assertGreater((pixel >> 8) & 255, 240)
                    # Tiny covers and high-frequency artwork must be filtered
                    # before reducing the glass image, independent of pan phase.
                    checks = bytearray()
                    for y in range(128):
                        for x in range(128):
                            value = 255 if (x // 2 + y // 2) % 2 else 0
                            checks.extend((value, value, value, 255))
                    raw = ctypes.create_string_buffer(bytes(checks))
                    gl.glBindTexture(GL_TEXTURE_2D, gpu.texture)
                    gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 128, 128,
                                       GL_RGBA, GL_UNSIGNED_BYTE, ctypes.cast(raw, ctypes.c_void_p))
                    for x in (0, 1):
                        filtered = blur.render('detail', 32, 32, program.vao, program.buffer, draw_scene,
                                               source_texture=gpu.texture, source_rect=(x, 0, 127, 128),
                                               source_size=(128, 128), supersample=4)
                        samples = [struct.unpack_from('=I', filtered.get_data(),
                                                      row * filtered.get_stride() + col * 4)[0] & 255
                                   for row in range(8, 24) for col in range(8, 24)]
                        self.assertLess(max(samples) - min(samples), 12)
                        self.assertGreater(sum(samples) / len(samples), 110)
                        self.assertLess(sum(samples) / len(samples), 145)
                    self.assertEqual(gl.glGetError(), 0)
                finally:
                    blur.close()
                    gl.glDeleteBuffers(1, ctypes.byref(program.buffer))
                    gl.glDeleteVertexArrays(1, ctypes.byref(program.vao))
                    gl.glDeleteProgram(program.program)
                    gpu.release_target()
        finally:
            gpu.close()

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
