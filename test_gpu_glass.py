import unittest
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

from gpu_glass import (GPUBlur, glass_rect, scene_quad, scene_covers_bar, GL_VIEWPORT, GL_COLOR_CLEAR_VALUE,
                       GL_FRAMEBUFFER, GL_FRAMEBUFFER_BINDING, GL_CURRENT_PROGRAM,
                       GL_VERTEX_ARRAY_BINDING, GL_ARRAY_BUFFER_BINDING,
                       GL_ACTIVE_TEXTURE, GL_TEXTURE_BINDING_2D)
from gpu_gl import GL_ARRAY_BUFFER, GL_TEXTURE_2D


class GPUGlassTests(unittest.TestCase):
    def test_bar_region_includes_blur_padding_and_translated_coordinates(self):
        bar = SimpleNamespace(translate_coordinates=lambda area, x, y: (12, -36),
                              get_allocated_width=lambda: 800,
                              get_allocated_height=lambda: 36)
        self.assertEqual(glass_rect(bar, object(), 56), (12, -92, 800, 92))

    def test_unallocated_or_untranslatable_bars_are_ignored(self):
        bar = SimpleNamespace(translate_coordinates=lambda *args: None)
        self.assertIsNone(glass_rect(bar, object(), 56))
        bar = SimpleNamespace(translate_coordinates=lambda *args: (0, 0),
                              get_allocated_width=lambda: 1,
                              get_allocated_height=lambda: 36)
        self.assertIsNone(glass_rect(bar, object(), 56))

    def test_scene_rectangle_maps_to_the_same_frame_coordinates(self):
        quad = list(scene_quad((10, -20, 50, 40), (100, 100)))
        self.assertAlmostEqual(quad[2], .1)
        self.assertAlmostEqual(quad[3], 1.2)
        self.assertAlmostEqual(quad[6], .6)
        self.assertAlmostEqual(quad[11], .8)

    def test_direct_sampling_requires_the_bar_to_fit_in_the_scene(self):
        self.assertTrue(scene_covers_bar((0, -56, 800, 180), 56, (800, 600)))
        self.assertFalse(scene_covers_bar((0, 500, 800, 156), 56, (800, 600)))
        self.assertFalse(scene_covers_bar((-5, -56, 800, 180), 56, (800, 600)))

    def test_blur_restores_gl_state_even_when_framebuffer_setup_fails(self):
        gl = Mock()
        values = {GL_FRAMEBUFFER_BINDING: 5, GL_CURRENT_PROGRAM: 7,
                  GL_VERTEX_ARRAY_BINDING: 9, GL_ARRAY_BUFFER_BINDING: 11,
                  GL_ACTIVE_TEXTURE: 0x84C0, GL_TEXTURE_BINDING_2D: 13}
        def get_integer(name, pointer):
            target = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))
            if name == GL_VIEWPORT:
                for index, value in enumerate((2, 3, 800, 600)):
                    target[index] = value
            else:
                target[0] = values[name]
        def get_float(name, pointer):
            self.assertEqual(name, GL_COLOR_CLEAR_VALUE)
            target = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_float))
            for index, value in enumerate((.1, .2, .3, .4)):
                target[index] = value
        gl.glGetIntegerv.side_effect = get_integer
        gl.glGetFloatv.side_effect = get_float
        blur = GPUBlur.__new__(GPUBlur)
        blur.gl = gl
        blur._ensure = Mock(side_effect=RuntimeError('unsupported'))
        with self.assertRaises(RuntimeError):
            blur.render('bar', 10, 4, 9, 11, Mock())
        gl.glBindFramebuffer.assert_called_with(GL_FRAMEBUFFER, 5)
        gl.glViewport.assert_called_with(2, 3, 800, 600)
        gl.glUseProgram.assert_called_with(7)
        gl.glBindVertexArray.assert_called_with(9)
        gl.glBindBuffer.assert_called_with(GL_ARRAY_BUFFER, 11)
        gl.glActiveTexture.assert_called_with(0x84C0)
        gl.glBindTexture.assert_called_with(GL_TEXTURE_2D, 13)


if __name__ == '__main__':
    unittest.main()
