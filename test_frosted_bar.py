import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cairo

from frosted_bar import FrostedBar


class FrostedBarTests(unittest.TestCase):
    def test_gpu_sampling_uses_precise_resolution_and_restores_cpu_fallback(self):
        bar = SimpleNamespace(connect=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock())
        glass = FrostedBar(bar, content, background, lambda: 'dark', sample_wall_frame=True)
        self.assertEqual(glass.SCALE, 28)
        previous = glass.surface = object()
        glass.configure_gpu_sampling(True)
        self.assertEqual(glass.SCALE, 4)
        self.assertTrue(glass.exact_scaling)
        self.assertIs(glass.surface, previous)
        glass.configure_gpu_sampling(False)
        self.assertEqual(glass.SCALE, 28)
        self.assertTrue(glass.exact_scaling)
        self.assertIs(glass.surface, previous)

    def test_exact_scaling_aligns_non_multiple_backdrop_dimensions(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 127,
                              get_allocated_height=lambda: 63, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock())
        glass = FrostedBar(bar, content, background, lambda: 'dark',
                           cache_frames=True, scale=12, exact_scaling=True)
        glass.enabled = True
        glass._backdrop_dirty = False
        glass.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 11, 10)
        context = Mock()
        glass.draw(bar, context)
        context.scale.assert_called_once_with(127 / 11, (63 + glass.PAD) / 10)

    def test_gpu_backdrop_is_composited_without_redrawing_content(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                     draw=lambda context: None)
        gpu = cairo.ImageSurface(cairo.FORMAT_ARGB32, 5, 5)
        context = cairo.Context(gpu)
        context.set_source_rgb(1, 0, 0)
        context.paint()
        glass = FrostedBar(bar, content, background, lambda: 'dark',
                           capture_content=lambda: False, gpu_surface=lambda: gpu)
        glass.enabled = True
        glass.drawn(content, None)
        glass.drawn(background, None)
        glass.refresh()
        content.draw.assert_not_called()
        pixel = struct.unpack_from('=I', glass.surface.get_data(), 0)[0]
        self.assertGreater((pixel >> 16) & 255, pixel & 255)

    def test_cached_backdrop_is_not_recaptured_for_control_only_redraws(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=Mock())
        glass = FrostedBar(bar, content, background, lambda: 'dark', cache_frames=True)
        glass.enabled = True
        glass.drawn(content, None); glass.drawn(background, None)
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 60)
        glass.draw(bar, cairo.Context(canvas))
        glass.draw(bar, cairo.Context(canvas))
        self.assertEqual(content.draw.call_count, 1)
        self.assertEqual(background.draw.call_count, 1)
        glass.backdrop_changed()
        glass.draw(bar, cairo.Context(canvas))
        self.assertEqual(content.draw.call_count, 2)
        self.assertEqual(background.draw.call_count, 2)
        glass.bar_allocated(bar, SimpleNamespace(x=0, y=0, width=120, height=61))
        glass.draw(bar, cairo.Context(canvas))
        self.assertEqual(content.draw.call_count, 3)
        glass.stop()

    def test_missing_gpu_frame_keeps_previous_backdrop_until_resize_completes(self):
        height = [60]
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: height[0], queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=Mock())
        frame = [cairo.ImageSurface(cairo.FORMAT_ARGB32, 5, 5)]
        glass = FrostedBar(bar, content, background, lambda: 'dark',
                           capture_content=lambda: False, gpu_surface=lambda: frame[0],
                           retain_missing_gpu=lambda: True)
        glass.enabled = True
        glass.drawn(content, None); glass.drawn(background, None)
        glass.refresh()
        previous = glass.surface
        frame[0] = None
        glass.refresh()
        self.assertIs(glass.surface, previous)
        height[0] = 100
        glass.refresh()
        self.assertIs(glass.surface, previous)
        frame[0] = cairo.ImageSurface(cairo.FORMAT_ARGB32, 5, 6)
        glass.refresh()
        self.assertIsNot(glass.surface, previous)
        self.assertEqual((glass.surface.get_width(), glass.surface.get_height()), (5, 6))

    def test_shared_gpu_glass_keeps_last_frame_when_new_one_is_unavailable(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True, get_allocated_height=lambda: 400)
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=Mock())
        frame = [cairo.ImageSurface(cairo.FORMAT_ARGB32, 30, 29)]
        glass = FrostedBar(bar, content, background, lambda: 'dark', sample_wall_frame=True,
                           capture_content=lambda: False, gpu_surface=lambda: frame[0])
        glass.enabled = True
        glass.drawn(content, None); glass.drawn(background, None)
        glass.refresh()
        previous = glass.surface
        frame[0] = None
        glass.refresh()
        self.assertIs(glass.surface, previous)

    def test_backdrop_can_skip_gpu_content_but_still_draw_background(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=Mock())
        safe = [False]
        glass = FrostedBar(bar, content, background, lambda: 'dark',
                           capture_content=lambda: safe[0])
        glass.enabled = True
        glass.drawn(content, None)
        glass.drawn(background, None)
        glass.refresh()
        background.draw.assert_called_once()
        content.draw.assert_not_called()
        safe[0] = True
        glass.refresh()
        content.draw.assert_called_once()

    def test_capture_waits_for_library_rows_and_resumes_afterwards(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=Mock())
        allowed = [False]
        glass = FrostedBar(bar, content, background, lambda: 'dark',
                           capture_allowed=lambda: allowed[0])
        glass.enabled = True
        glass.drawn(content, None)
        glass.drawn(background, None)
        glass.refresh()
        content.draw.assert_not_called()
        background.draw.assert_not_called()
        allowed[0] = True
        glass.refresh()
        content.draw.assert_called_once()
        background.draw.assert_called_once()

    def test_top_glass_paints_across_the_full_bar_including_edge_space(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 280,
                              get_allocated_height=lambda: 56,
                              translate_coordinates=lambda _content, _x, _y: (0, 0),
                              queue_draw=Mock())
        def draw_content(context):
            context.set_source_rgb(1, 0, 0)
            context.rectangle(0, 0, 140, 100)
            context.fill()
            context.set_source_rgb(0, 0, 1)
            context.rectangle(140, 0, 140, 100)
            context.fill()
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400,
                                  translate_coordinates=lambda _widget, _x, _y: (0, 0),
                                  draw=draw_content)
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                     draw=lambda _context: None)
        glass = FrostedBar(bar, content, background, lambda: 'dark', edge='top')
        glass.drawn(content, None)
        glass.drawn(background, None)
        glass.enabled = True
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 280, 56)
        glass.draw(bar, cairo.Context(canvas))
        data = canvas.get_data()
        row = 28 * canvas.get_stride()
        left = struct.unpack_from('=I', data, row + 20 * 4)[0]
        right = struct.unpack_from('=I', data, row + 260 * 4)[0]
        self.assertGreater((left >> 16) & 255, left & 255)
        self.assertGreater(right & 255, (right >> 16) & 255)

    def test_switching_top_bar_source_discards_the_old_backdrop(self):
        bar = SimpleNamespace(connect=Mock(), queue_draw=Mock())
        old = SimpleNamespace(connect=Mock(), connect_after=Mock())
        new = SimpleNamespace(connect=Mock(), connect_after=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock())
        glass = FrostedBar(bar, old, background, lambda: 'dark', edge='top')
        glass.surface = object()
        glass.set_content(new)
        glass.drawn(old, None)
        self.assertIsNone(glass.surface)
        self.assertNotIn(id(old), glass._ready)
        self.assertFalse(glass._ready[id(new)])
        glass.drawn(new, None)
        self.assertTrue(glass._ready[id(new)])

    def test_top_bar_samples_its_scrolling_content(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 56,
                              translate_coordinates=lambda _content, _x, _y: (0, -20),
                              queue_draw=Mock())
        def draw_content(context):
            context.set_source_rgb(0, 0, 1)
            context.paint()
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400,
                                  translate_coordinates=lambda _widget, _x, _y: (0, 0),
                                  draw=draw_content)
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                     draw=lambda _context: None)
        glass = FrostedBar(bar, content, background, lambda: 'dark', edge='top')
        glass.drawn(content, None)
        glass.drawn(background, None)
        glass.enabled = True
        self.assertFalse(glass._refresh_top())
        glass.draw(bar, cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 56)))
        self.assertIsNotNone(glass.surface)
        pixel = struct.unpack_from('=I', glass.surface.get_data(),
                                   2 * glass.surface.get_stride())[0]
        self.assertGreater(pixel & 255, (pixel >> 16) & 255)
        bar.queue_draw.assert_called_once()

    def test_repeated_identical_allocations_do_not_delay_new_frames(self):
        bar = SimpleNamespace(connect=Mock(), queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock())
        glass = FrostedBar(bar, content, background, lambda: 'dark')
        allocation = SimpleNamespace(x=0, y=0, width=800, height=600)
        with patch('frosted_bar.time.monotonic', side_effect=[1.0]):
            glass.invalidate(content, allocation)
            glass.drawn(content, None)
            glass.invalidate(content, allocation)
        self.assertTrue(glass._ready[id(content)])
        self.assertEqual(glass._last_layout, 1.0)

    def test_resize_does_not_force_layout_until_backdrop_settles(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(), get_mapped=lambda: True,
                                  check_resize=Mock())
        background = SimpleNamespace(connect=Mock(), connect_after=Mock())
        glass = FrostedBar(bar, content, background, lambda: 'dark')
        glass.enabled = True
        glass._ready = {id(content): True, id(background): True}
        glass._last_layout = 10.0
        with patch('frosted_bar.time.monotonic', return_value=10.1), \
                patch('frosted_bar.GLib.timeout_add', return_value=1):
            self.assertTrue(glass.refresh())
        content.check_resize.assert_not_called()

    def test_backdrop_checks_layout_once_per_geometry_change(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(), get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400,
                                  check_resize=Mock(), draw=lambda _context: None)
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=lambda _context: None)
        glass = FrostedBar(bar, content, background, lambda: 'dark')
        glass.enabled = True
        with patch('frosted_bar.time.monotonic', return_value=10.0):
            glass.invalidate(content, SimpleNamespace(x=0, y=0, width=800, height=600))
            glass.drawn(content, None)
            glass.drawn(background, None)
        with patch('frosted_bar.time.monotonic', return_value=11.0):
            glass.refresh()
            glass.refresh()
        content.check_resize.assert_called_once()

    def test_capture_samples_the_content_behind_the_bar(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60,
                              queue_draw=Mock())
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(), get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400,
                                  draw=lambda _context: None)

        def draw_background(context):
            context.set_source_rgb(1, 0, 0)
            context.rectangle(0, 284, 120, 58)
            context.fill()
            context.set_source_rgb(0, 0, 1)
            context.rectangle(0, 342, 120, 58)
            context.fill()

        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=draw_background)
        backdrop = FrostedBar(bar, content, background, lambda: 'dark')
        backdrop.enabled = True
        backdrop.drawn(content, None)
        backdrop.drawn(background, None)
        self.assertTrue(backdrop.refresh())
        self.assertEqual((backdrop.surface.get_width(), backdrop.surface.get_height()),
                         (5, 5))
        data = backdrop.surface.get_data()
        stride = backdrop.surface.get_stride()
        red = struct.unpack_from('=I', data, stride + 4 * 2)[0]
        blue = struct.unpack_from('=I', data, stride * 4 + 4 * 2)[0]
        self.assertGreater((red >> 16) & 255, red & 255)
        self.assertGreater(blue & 255, (blue >> 16) & 255)
        bar.queue_draw.assert_not_called()

    def test_each_bar_draw_captures_the_current_content(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        color = [1.0, 0.0, 0.0]
        def draw_content(context):
            context.set_source_rgb(*color)
            context.paint()
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=draw_content)
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                     draw=lambda _context: None)
        backdrop = FrostedBar(bar, content, background, lambda: 'dark')
        backdrop.enabled = True
        backdrop.drawn(content, None)
        backdrop.drawn(background, None)
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 60)
        backdrop.draw(bar, cairo.Context(canvas))
        first = struct.unpack_from('=I', backdrop.surface.get_data(), 0)[0]
        color[:] = [0.0, 0.0, 1.0]
        backdrop.draw(bar, cairo.Context(canvas))
        second = struct.unpack_from('=I', backdrop.surface.get_data(), 0)[0]
        self.assertGreater((first >> 16) & 255, first & 255)
        self.assertGreater(second & 255, (second >> 16) & 255)

    def test_waveform_keeps_glass_instead_of_solid_timeline_background(self):
        from player import Player
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        color = [1.0, 0.0, 0.0]
        def draw_content(context):
            context.set_source_rgb(*color)
            context.paint()
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=draw_content)
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(), draw=lambda _context: None)
        stack = SimpleNamespace(get_visible_child_name=lambda: 'waveform')
        glass = FrostedBar(bar, content, background, lambda: 'dark',
                           lambda: Player.solid_timeline_background(SimpleNamespace(timeline_stack=stack)))
        glass.enabled = True
        glass.drawn(content, None); glass.drawn(background, None)
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 60)
        glass.draw(bar, cairo.Context(canvas))
        first = bytes(canvas.get_data())
        color[:] = [0.0, 0.0, 1.0]
        glass.draw(bar, cairo.Context(canvas))
        second = bytes(canvas.get_data())
        top = 10 * canvas.get_stride() + 60 * 4
        self.assertNotEqual(first[top:top + 4], second[top:top + 4])

    def test_timeline_has_an_opaque_background_over_changing_content(self):
        bar = SimpleNamespace(connect=Mock(), get_mapped=lambda: True,
                              get_allocated_width=lambda: 120,
                              get_allocated_height=lambda: 60, queue_draw=Mock())
        color = [1.0, 0.0, 0.0]
        def draw_content(context):
            context.set_source_rgb(*color)
            context.paint()
        content = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                  get_mapped=lambda: True,
                                  get_allocated_height=lambda: 400, draw=draw_content)
        background = SimpleNamespace(connect=Mock(), connect_after=Mock(),
                                     draw=lambda _context: None)
        timeline = SimpleNamespace(get_visible=lambda: True,
                                   translate_coordinates=lambda _bar, _x, _y: (0, 0),
                                   get_allocated_width=lambda: 120,
                                   get_allocated_height=lambda: 20)
        glass = FrostedBar(bar, content, background, lambda: 'dark', lambda: timeline)
        glass.enabled = True
        glass.drawn(content, None)
        glass.drawn(background, None)
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 60)
        glass.draw(bar, cairo.Context(canvas))
        first = bytes(canvas.get_data())
        color[:] = [0.0, 0.0, 1.0]
        glass.draw(bar, cairo.Context(canvas))
        second = bytes(canvas.get_data())
        top = 10 * canvas.get_stride() + 60 * 4
        bottom = 40 * canvas.get_stride() + 60 * 4
        self.assertEqual(first[top:top + 4], second[top:top + 4])
        self.assertNotEqual(first[bottom:bottom + 4], second[bottom:bottom + 4])


if __name__ == '__main__':
    unittest.main()
