import unittest
import time

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import cairo

from ribbon_visualizer import (LINE_COUNT, NODE_COUNT, RibbonVisualizer, approach,
                               ribbon_profile, trace_curve)


class RibbonVisualizerTests(unittest.TestCase):
    def test_background_visualizer_paints_below_foreground_widgets(self):
        window = Gtk.OffscreenWindow()
        window.set_default_size(80, 80)
        overlay = Gtk.Overlay()
        window.add(overlay)
        base = Gtk.DrawingArea()
        overlay.add(base)
        ribbon = RibbonVisualizer(windowless=True)
        self.assertFalse(ribbon.get_has_window())
        def paint_red(_widget, context):
            context.set_source_rgb(1, 0, 0)
            context.paint()
            return False
        ribbon.connect_after('draw', paint_red)
        overlay.add_overlay(ribbon)
        overlay.set_overlay_pass_through(ribbon, True)
        foreground = Gtk.DrawingArea()
        foreground.set_has_window(False)
        foreground.set_halign(Gtk.Align.CENTER)
        foreground.set_valign(Gtk.Align.CENTER)
        foreground.set_size_request(30, 30)
        def paint_green(_widget, context):
            context.set_source_rgb(0, 1, 0)
            context.paint()
            return False
        foreground.connect('draw', paint_green)
        overlay.add_overlay(foreground)
        window.show_all()
        deadline = time.monotonic() + .1
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration()
        pixbuf = window.get_pixbuf()
        pixels = pixbuf.get_pixels()
        offset = 40 * pixbuf.get_rowstride() + 40 * pixbuf.get_n_channels()
        self.assertEqual(tuple(pixels[offset:offset + 3]), (0, 255, 0))
        window.destroy()

    def test_envelopes_attack_quickly_and_release_gently(self):
        self.assertGreater(approach(0, 1, .05, .075, .34), .4)
        self.assertGreater(approach(1, 0, .05, .075, .34), .8)

    def test_shared_shape_is_broad_and_highs_remain_subtle(self):
        values = [ribbon_profile(index / 100, .2, 0, 0)
                  for index in range(101)]
        self.assertGreater(max(values) - min(values), 1.0)
        self.assertLess(max(abs(ribbon_profile(index / 100, .2, 0, 1) - value)
                            for index, value in enumerate(values)), .04)

    def test_each_layer_is_one_smooth_full_width_path(self):
        surface = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        context = cairo.Context(surface)
        for layer in range(LINE_COUNT):
            context.new_path()
            trace_curve(context, 900, 420, layer, .2, .8, .4, .2, .1)
            path = list(context.copy_path())
            self.assertEqual(len(path), NODE_COUNT)
            self.assertEqual(path[0][0], cairo.PATH_MOVE_TO)
            self.assertEqual(path[-1][0], cairo.PATH_CURVE_TO)
            self.assertAlmostEqual(path[-1][1][-2], 900)

    def test_back_lines_have_broad_ripples_and_front_lines_have_fine_ripples(self):
        surface = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        context = cairo.Context(surface)

        def ripple(layer):
            context.new_path()
            trace_curve(context, 900, 420, layer, .2, .8, .4, .2, .1)
            plain = [step[1][-1] for step in list(context.copy_path())[1:]]
            context.new_path()
            trace_curve(context, 900, 420, layer, .2, .8, .4, .2, .1, 1.0)
            active = [step[1][-1] for step in list(context.copy_path())[1:]]
            return [a - b for a, b in zip(active, plain)]

        def crossings(values):
            return sum((a < 0 <= b) or (b < 0 <= a)
                       for a, b in zip(values, values[1:]))

        back = ripple(0)
        front = ripple(LINE_COUNT - 1)
        self.assertGreater(max(abs(value) for value in back), 3)
        self.assertGreater(max(abs(value) for value in front), 3)
        self.assertGreater(crossings(front), crossings(back) + 4)

    def test_volume_scales_whole_curve_including_frequency_ripples(self):
        surface = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        context = cairo.Context(surface)
        def points(volume):
            context.new_path()
            trace_curve(context, 900, 420, 12, .2, .8, .4, .2, .1, .8, volume)
            return [step[1][-1] for step in list(context.copy_path())]
        muted, half, full = points(0), points(.5), points(1)
        center = 420 * .51
        self.assertTrue(all(abs(y - center) < .01 for y in muted))
        for quiet, loud in zip(half, full):
            self.assertAlmostEqual(quiet - center, (loud - center) * .5, delta=.02)

    def test_frequency_distortion_is_visible_across_the_line(self):
        surface = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        context = cairo.Context(surface)

        def endpoints(energy):
            context.new_path()
            trace_curve(context, 900, 420, 12, .2, .6, .4, .3, .1, energy)
            return [entry[1][-1] for entry in list(context.copy_path())[1:]]

        quiet, active = endpoints(0), endpoints(.4)
        displacement = [abs(a - b) for a, b in zip(active, quiet)]
        for section in (displacement[:10], displacement[10:20], displacement[20:]):
            self.assertGreater(max(section), 5)


if __name__ == '__main__':
    unittest.main()
