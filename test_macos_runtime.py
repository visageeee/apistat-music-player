import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from macos_runtime import configure_bundled_icons, configure_gstreamer_registry


class MacOSRuntimeTests(unittest.TestCase):
    def test_bundled_icon_theme_is_selected_only_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            settings, theme = Mock(), Mock()
            self.assertFalse(configure_bundled_icons(settings, theme, directory))
            settings.set_property.assert_not_called()
            (Path(directory) / 'share' / 'icons' / 'Adwaita').mkdir(parents=True)
            self.assertTrue(configure_bundled_icons(settings, theme, directory))
            theme.prepend_search_path.assert_called_once_with(str(Path(directory) / 'share' / 'icons'))
            settings.set_property.assert_called_once_with('gtk-icon-theme-name', 'Adwaita')

    def test_registry_uses_user_cache_not_bundle(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(os.environ, {}, clear=False):
            self.assertIsNone(configure_gstreamer_registry(cache))
            registry = Path(os.environ['GST_REGISTRY'])
            self.assertEqual(registry, Path(cache) / 'apistat' / 'gstreamer-registry.bin')
            self.assertTrue(registry.parent.is_dir())

    def test_registry_falls_back_to_temporary_directory(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=False):
            blocked = Path(root) / 'not-a-directory'
            blocked.write_text('file')
            owner = configure_gstreamer_registry(blocked)
            try:
                self.assertIsNotNone(owner)
                self.assertEqual(Path(os.environ['GST_REGISTRY']).parent, Path(owner.name))
            finally:
                owner.cleanup()


if __name__ == '__main__':
    unittest.main()
