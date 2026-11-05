import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import gi
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
from background_drag_scroll import BackgroundDragScroller


class BackgroundDragScrollTests(unittest.TestCase):
    def setUp(self):
        self.value = 150
        self.adjustment = SimpleNamespace(
            get_value=lambda: self.value, get_lower=lambda: 0,
            get_upper=lambda: 1000, get_page_size=lambda: 300,
            set_value=lambda value: setattr(self, 'value', value))
        self.scroller = BackgroundDragScroller(self.adjustment)

    def test_drag_tracks_pointer_and_clamps_to_scroll_bounds(self):
        self.assertTrue(self.scroller.press(SimpleNamespace(button=1, state=0, y_root=200)))
        self.assertTrue(self.scroller.motion(SimpleNamespace(state=Gdk.ModifierType.BUTTON1_MASK,
                                                            y_root=100)))
        self.assertEqual(self.value, 250)
        self.scroller.motion(SimpleNamespace(state=Gdk.ModifierType.BUTTON1_MASK, y_root=-2000))
        self.assertEqual(self.value, 700)
        self.assertTrue(self.scroller.release(SimpleNamespace(button=1)))
        self.assertFalse(self.scroller.motion(SimpleNamespace(state=Gdk.ModifierType.BUTTON1_MASK,
                                                             y_root=50)))

    def test_ignores_modified_and_unscrollable_presses(self):
        self.assertFalse(self.scroller.press(SimpleNamespace(button=1, state=Gdk.ModifierType.SHIFT_MASK)))
        self.adjustment.get_upper = lambda: 300
        self.assertFalse(self.scroller.press(SimpleNamespace(button=1, state=0)))
