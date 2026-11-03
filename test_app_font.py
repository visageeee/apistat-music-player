import os
import unittest

from app_font import DEFAULT_FONT_FAMILY, font_path, register_bundled_font


class BundledFontTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Pango font registration varies with Windows GTK builds')
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
