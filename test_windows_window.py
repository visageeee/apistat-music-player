import ctypes
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import windows_window


class WindowsWindowTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows compositor test')
    def test_real_gtk_window_supports_native_frame(self):
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        if not Gtk.init_check()[0]:
            self.skipTest('GTK display unavailable')
        window = Gtk.Window()
        try:
            window.realize()
            native = window.get_window()
            self.assertTrue(windows_window.native_handle(native))
            self.assertTrue(windows_window.configure_window(native, True))
        finally:
            window.destroy()

    def test_native_frame_sets_shadow_margin_and_corner_preference(self):
        extend = Mock(return_value=0)
        attributes = Mock(return_value=0)
        dwm = SimpleNamespace(DwmExtendFrameIntoClientArea=extend,
                              DwmSetWindowAttribute=attributes)
        with patch.object(windows_window.os, 'name', 'nt'), \
                patch.object(windows_window, 'native_handle', return_value=123), \
                patch.object(windows_window.ctypes, 'WinDLL', create=True, return_value=dwm):
            self.assertTrue(windows_window.configure_window(object(), True))
            self.assertTrue(windows_window.configure_window(object(), False))
        margins = ctypes.cast(extend.call_args.args[1],
                              ctypes.POINTER(windows_window.Margins)).contents
        self.assertEqual((margins.left, margins.right, margins.top, margins.bottom),
                         (1, 1, 1, 1))
        self.assertEqual(attributes.call_args.args[1], 33)
        preference = ctypes.cast(attributes.call_args.args[2],
                                 ctypes.POINTER(ctypes.c_int)).contents.value
        self.assertEqual(preference, 1)

    def test_native_frame_failure_is_nonfatal(self):
        with patch.object(windows_window.os, 'name', 'nt'), \
                patch.object(windows_window, 'native_handle', side_effect=OSError('unavailable')):
            self.assertFalse(windows_window.configure_window(object(), True))


if __name__ == '__main__':
    unittest.main()
