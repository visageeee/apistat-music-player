import configparser
import json
import unittest
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent


class FlatpakPackagingTests(unittest.TestCase):
    def test_manifest_permissions_and_bundled_assets(self):
        manifest = json.loads((ROOT / 'org.apistat.Apistat.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['id'], 'org.apistat.Apistat')
        self.assertEqual(manifest['command'], 'apistat')
        self.assertEqual(manifest['runtime-version'], '50')
        permissions = set(manifest['finish-args'])
        self.assertTrue({'--share=network', '--socket=pulseaudio',
                         '--talk-name=org.freedesktop.secrets',
                         '--own-name=org.mpris.MediaPlayer2.plexmusicprototype'} <= permissions)
        self.assertFalse(any(flag.startswith('--filesystem=host') or flag == '--filesystem=home'
                             for flag in permissions))
        modules = {module['name']: module for module in manifest['modules']}
        self.assertIn('python3-mutagen', modules)
        self.assertEqual(len(modules['python3-mutagen']['sources'][0]['sha256']), 64)
        commands = '\n'.join(modules['apistat']['build-commands'])
        for asset in ('apistat.png', 'fonts/Nunito-wght.ttf', 'fonts/OFL.txt',
                      'flatpak/apistat', 'flatpak/org.apistat.Apistat.desktop',
                      'flatpak/org.apistat.Apistat.metainfo.xml'):
            self.assertTrue((ROOT / asset).is_file(), asset)
            self.assertIn(asset, commands)

    def test_desktop_metainfo_and_launcher_use_the_same_id(self):
        desktop = configparser.ConfigParser(interpolation=None)
        desktop.read(ROOT / 'flatpak/org.apistat.Apistat.desktop', encoding='utf-8')
        self.assertEqual(desktop['Desktop Entry']['Exec'], 'apistat')
        self.assertEqual(desktop['Desktop Entry']['Icon'], 'org.apistat.Apistat')
        self.assertEqual(desktop['Desktop Entry']['StartupWMClass'], 'org.apistat.Apistat')
        metadata = ElementTree.parse(ROOT / 'flatpak/org.apistat.Apistat.metainfo.xml').getroot()
        self.assertEqual(metadata.findtext('id'), 'org.apistat.Apistat')
        self.assertEqual(metadata.findtext('launchable'), 'org.apistat.Apistat.desktop')
        self.assertIn('exec python3 /app/share/apistat/player.py "$@"',
                      (ROOT / 'flatpak/apistat').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
