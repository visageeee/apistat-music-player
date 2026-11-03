import os
import sys
import unittest
from unittest.mock import Mock, patch

from app_font import DEFAULT_FONT_FAMILY, font_path, register_bundled_font


class BundledFontTests(unittest.TestCase):
    def test_windows_uses_private_font_registration(self):
        import app_font
        add = Mock(return_value=1)
        fontmap = Mock()
        from gi.repository import PangoCairo
        with patch.object(app_font.ctypes, 'WinDLL', create=True,
                          return_value=Mock(AddFontResourceExW=add)), \
                patch.object(PangoCairo.FontMap, 'get_default', return_value=fontmap):
            self.assertTrue(app_font._register_windows_font('Nunito.ttf'))
        add.assert_called_once_with('Nunito.ttf', app_font.FR_PRIVATE, None)
        fontmap.changed.assert_called_once()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows font registration test')
    def test_bundled_font_is_available_to_windows_pango(self):
        import gi
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import PangoCairo
        self.assertTrue(register_bundled_font())
        names = {family.get_name() for family in PangoCairo.FontMap.get_default().list_families()}
        self.assertIn(DEFAULT_FONT_FAMILY, names)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Pango font registration varies by platform')
    def test_rounded_font_is_available_to_pango(self):
        import gi
        gi.require_version('PangoCairo', '1.0')
        from gi.repository import PangoCairo

        self.assertTrue(font_path().is_file())
        self.assertTrue((font_path().parent / 'OFL.txt').is_file())
        self.assertTrue(register_bundled_font())
        families = {family.get_name()
                    for family in PangoCairo.FontMap.get_default().list_families()}
        self.assertIn(DEFAULT_FONT_FAMILY, families)


if __name__ == '__main__':
    unittest.main()
