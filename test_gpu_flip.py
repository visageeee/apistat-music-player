import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gpu_flip import BACK_SIZE, FLIP_DURATION, GPUFlip, back_pixels, card_hit, card_layout
from plex_client import Item
from album_highlights import track_highlights


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

    def test_track_text_stays_close_to_configured_size(self):
        for size in (160, 200, 300):
            with self.subTest(size=size):
                layout = card_layout(size, 18, 30, 0)
                self.assertGreaterEqual(layout['font'] * size / BACK_SIZE, 16)
                self.assertGreater(layout['capacity'], 0)

    def test_duration_requires_a_close_zoom(self):
        self.assertFalse(card_layout(359, 18, 2, 0)['show_duration'])
        self.assertTrue(card_layout(360, 18, 2, 0)['show_duration'])

    def test_hit_testing_tracks_uses_current_scroll_offset(self):
        layout = card_layout(300, 18, len(self.tracks), 5)
        y = (layout['start'] + layout['row_height'] * 1.5) * 300 / BACK_SIZE
        self.assertEqual(card_hit(layout, y, 300, self.tracks), ('track', 6))
        self.assertEqual(card_hit(layout, 0, 300, self.tracks), (None, None))
        bottom_y = (layout['explore_top'] + layout['explore_height'] / 2) * 300 / BACK_SIZE
        self.assertEqual(card_hit(layout, bottom_y, 300, self.tracks, 50), ('close', None))

    def test_explore_button_has_its_own_hit_area_below_tracks(self):
        layout = card_layout(300, 18, len(self.tracks), 5)
        y = (layout['explore_top'] + layout['explore_height'] / 2) * 300 / BACK_SIZE
        self.assertEqual(card_hit(layout, y, 300, self.tracks, 240), ('explore', None))
        self.assertNotEqual(card_hit(layout, y, 300, self.tracks, 2)[0], 'explore')
        self.assertLessEqual(layout['start'] + layout['rows'] * layout['row_height'],
                             layout['explore_top'])
        self.assertEqual(card_hit(layout, y, 300, self.tracks, 50), ('close', None))
        self.assertEqual(layout['cover_left'], BACK_SIZE - layout['explore_right'])
        self.assertAlmostEqual(layout['cover_left'], layout['explore_left'] - layout['cover_right'])
        self.assertAlmostEqual(layout['cover_left'], BACK_SIZE - layout['explore_top'] - layout['explore_height'])
        self.assertEqual(card_hit(layout, 299, 300, self.tracks, 240), (None, None))

    def test_highlights_use_loved_ratings_and_album_play_counts(self):
        self.tracks[0].user_rating = 10
        self.tracks[1].user_rating = 8
        self.tracks[2].play_count = 5
        self.tracks[3].play_count = 1
        self.assertEqual(track_highlights(self.tracks), {
            self.tracks[0].key: '♥', self.tracks[1].key: '★', self.tracks[2].key: '★'})
        self.tracks[2].play_count = 1
        self.assertNotIn(self.tracks[2].key, track_highlights(self.tracks))

    def test_space_before_centered_tracks_is_not_clickable(self):
        layout = card_layout(300, 18, 1, 0)
        y = (layout['start'] - 1) * 300 / BACK_SIZE
        self.assertEqual(card_hit(layout, y, 300, self.tracks[:1]), (None, None))

    def test_tracklist_has_only_a_small_top_margin(self):
        layout = card_layout(160, 18, len(self.tracks), 0)
        self.assertEqual(layout['header'], 12)
        self.assertLess(layout['start'], 512 * .1)

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
