import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gpu_flip import BACK_SIZE, FLIP_DURATION, GPUFlip, back_pixels, card_hit, card_layout
from plex_client import Item


class GPUFlipTests(unittest.TestCase):
    def setUp(self):
        self.album = Item('/library/metadata/1', 'Album', 'Artist')
        self.tracks = [Item('/library/metadata/' + str(i + 2), 'Track ' + str(i),
                            'Artist', duration=180000) for i in range(30)]

    def test_flip_moves_smoothly_and_can_reverse(self):
        flip = GPUFlip(self.album, 0, started=10.0)
        self.assertTrue(flip.animate(10.0 + FLIP_DURATION / 2))
        self.assertAlmostEqual(flip.progress, .5)
        self.assertAlmostEqual(flip.scale, 0, places=6)
        flip.turn(0, now=10.0 + FLIP_DURATION / 2)
        self.assertFalse(flip.animate(10.0 + FLIP_DURATION * 1.5))
        self.assertAlmostEqual(flip.progress, 0)

    def test_hit_testing_tracks_uses_current_scroll_offset(self):
        layout = card_layout(300, 18, len(self.tracks), 5)
        y = (layout['start'] + layout['row_height'] * 1.5) * 300 / BACK_SIZE
        self.assertEqual(card_hit(layout, y, 300, self.tracks), ('track', 6))
        self.assertEqual(card_hit(layout, 0, 300, self.tracks), ('album', None))
        self.assertEqual(card_hit(layout, 299, 300, self.tracks), ('close', None))

    def test_space_before_centered_tracks_is_not_clickable(self):
        layout = card_layout(300, 18, 1, 0)
        y = (layout['start'] - 1) * 300 / BACK_SIZE
        self.assertEqual(card_hit(layout, y, 300, self.tracks[:1]), (None, None))

    def test_back_face_contains_texture_and_highlighted_track(self):
        flip = GPUFlip(self.album, 0, tracks=self.tracks)
        marker = Mock(return_value='')
        pixels = back_pixels(flip, 300, 18, ('#292238', '#111e2b'), marker)
        self.assertEqual(len(pixels), BACK_SIZE * BACK_SIZE * 4)
        self.assertGreater(flip.layout['rows'], 0)
        self.assertEqual(marker.call_count, flip.layout['rows'])

    def test_track_offset_is_clamped_for_small_lists(self):
        layout = card_layout(300, 18, 4, 99)
        self.assertEqual(layout['offset'], 0)


if __name__ == '__main__':
    unittest.main()
