import unittest

import cairo

from ribbon_visualizer import (LINE_COUNT, NODE_COUNT, approach,
                               ribbon_profile, trace_curve)


class RibbonVisualizerTests(unittest.TestCase):
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
