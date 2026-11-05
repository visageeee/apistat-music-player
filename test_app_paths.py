import tempfile
import unittest
from pathlib import Path

from app_paths import migrate_legacy_directory


class ApplicationPathTests(unittest.TestCase):
    def test_moves_existing_settings_and_cache_without_resetting_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / 'plex-music-prototype'
            (old / 'nested').mkdir(parents=True)
            (old / 'session.json').write_text('session', encoding='utf-8')
            (old / 'nested' / 'cache').write_text('art', encoding='utf-8')
            migrate_legacy_directory(root)
            self.assertEqual((root / 'apistat' / 'session.json').read_text(), 'session')
            self.assertEqual((root / 'apistat' / 'nested' / 'cache').read_text(), 'art')
            self.assertFalse(old.exists())

    def test_merges_missing_files_without_overwriting_new_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / 'plex-music-prototype', root / 'apistat'
            old.mkdir(); new.mkdir()
            (old / 'settings.json').write_text('old')
            (new / 'settings.json').write_text('new')
            (old / 'session.json').write_text('session')
            migrate_legacy_directory(root)
            self.assertEqual((new / 'settings.json').read_text(), 'new')
            self.assertEqual((new / 'session.json').read_text(), 'session')
            self.assertEqual((old / 'settings.json').read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
