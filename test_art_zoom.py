import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk

from appearance import album_cover_size
from player import Player


class ArtZoomTests(unittest.TestCase):
    def test_ctrl_wheel_changes_each_view_independently(self):
        resized = []
        layouts = []
        subject = SimpleNamespace(
            album_columns=8, now_art_size=360,
            zoom_remainder={'albums': 0.0, 'now': 0.0},
            apply_album_grid_layout=lambda: layouts.append(True),
            hero_cover=object(),
            set_art_size=lambda target, size: resized.append((target, size)),
            status=SimpleNamespace(set_text=lambda _message: None),
        )
        up = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                             direction=Gdk.ScrollDirection.UP)
        down = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                               direction=Gdk.ScrollDirection.DOWN)
        plain = SimpleNamespace(state=0, direction=Gdk.ScrollDirection.UP)

        with patch('player.save_album_columns') as save_columns, \
                patch('player.save_now_art_size') as save_now:
            self.assertFalse(Player.zoom_art(subject, None, plain, 'albums'))
            self.assertTrue(Player.zoom_art(subject, None, up, 'albums'))
            self.assertTrue(Player.zoom_art(subject, None, up, 'now'))
            self.assertTrue(Player.zoom_art(subject, None, down, 'albums'))

        self.assertEqual((subject.album_columns, subject.now_art_size), (8, 400))
        self.assertEqual(len(layouts), 2)
        self.assertIn((subject.hero_cover, 400), resized)
        self.assertEqual(save_columns.call_args.args, (8,))
        self.assertEqual(save_now.call_args.args, (400,))

    def test_zoom_limits_are_four_to_sixteen_columns(self):
        subject = SimpleNamespace(
            album_columns=4, zoom_remainder={'albums': 0.0, 'now': 0.0},
            apply_album_grid_layout=lambda: None,
            status=SimpleNamespace(set_text=lambda _message: None),
        )
        up = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                             direction=Gdk.ScrollDirection.UP)
        down = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                               direction=Gdk.ScrollDirection.DOWN)
        with patch('player.save_album_columns'):
            Player.zoom_art(subject, None, up, 'albums')
            self.assertEqual(subject.album_columns, 4)
            for _ in range(20):
                Player.zoom_art(subject, None, down, 'albums')
            self.assertEqual(subject.album_columns, 16)
        self.assertGreater(album_cover_size(1100, 4), album_cover_size(1100, 16))


if __name__ == '__main__':
    unittest.main()
