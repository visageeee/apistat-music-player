import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macos_runtime import configure_gstreamer_registry


class MacOSRuntimeTests(unittest.TestCase):
    def test_registry_uses_user_cache_not_bundle(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(os.environ, {}, clear=False):
            self.assertIsNone(configure_gstreamer_registry(cache))
            registry = Path(os.environ['GST_REGISTRY'])
            self.assertEqual(registry, Path(cache) / 'plex-music-prototype' / 'gstreamer-registry.bin')
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
