import struct
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import appearance
import local_cache
from gpu_gradient import render_gpu_gradient


class GPUGradientTests(unittest.TestCase):
    def test_gpu_gradient_has_correct_corners_and_subtle_rounding(self):
        try:
            surface, pixels = render_gpu_gradient(256, 128, ('#502040', '#102850'))
        except (OSError, RuntimeError) as error:
            self.skipTest(f'Offscreen OpenGL unavailable: {error}')
        self.assertEqual((surface.get_width(), surface.get_height()), (256, 128))
        first, last = pixels[0], pixels[-1]
        self.assertEqual((first >> 16 & 255, first >> 8 & 255, first & 255), (80, 32, 64))
        self.assertEqual((last >> 16 & 255, last >> 8 & 255, last & 255), (16, 40, 80))
        self.assertTrue(all(value >> 24 == 255 for value in pixels))
        # Locally the shader varies by at most one quantization step, unlike
        # a multi-level visible noise overlay.
        flat, values = render_gpu_gradient(32, 32, ('#444444', '#444444'))
        self.assertEqual(len({value & 255 for value in values}), 1)

    def test_falls_back_to_cpu_and_reuses_cache_after_gpu_error(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(local_cache, 'CACHE_ROOT', Path(directory)), \
                patch.object(appearance, '_gradient_gpu_failed', False), \
                patch('gpu_gradient.render_gpu_gradient', side_effect=RuntimeError('no OpenGL')) as gpu:
            appearance._gradient_memory.clear()
            surface, pixels = appearance.cached_gradient(41, 31, ('#334455', '#112233'))
            self.assertEqual((surface.get_width(), surface.get_height()), (41, 31))
            self.assertIsNotNone(pixels)
            self.assertTrue(appearance._gradient_gpu_failed)
            appearance.cached_gradient(42, 32, ('#334455', '#112233'))
            gpu.assert_called_once()
            appearance._gradient_memory.clear()

    def test_offscreen_contexts_can_render_concurrently(self):
        def render(_):
            return render_gpu_gradient(48, 32, ('#554433', '#112233'))[0].get_width()
        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                self.assertEqual(list(workers.map(render, range(2))), [48, 48])
        except (OSError, RuntimeError) as error:
            self.skipTest(f'Offscreen OpenGL unavailable: {error}')


if __name__ == '__main__':
    unittest.main()
