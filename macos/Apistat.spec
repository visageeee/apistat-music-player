"""Experimental native macOS app bundle, built on the target architecture."""
from pathlib import Path

root = Path.cwd()
plugins = ['app', 'audioconvert', 'audioresample', 'audioparsers', 'autodetect',
           'coreelements', 'coreaudio', 'osxaudio', 'faad', 'flac', 'id3demux',
           'mpg123', 'ogg', 'playback', 'soup', 'spectrum', 'typefindfunctions',
           'volume', 'vorbis', 'wavparse', 'isomp4']
a = Analysis(
    [str(root / 'player.py')], pathex=[str(root)], binaries=[],
    datas=[(str(root / 'apistat.png'), '.'),
           (str(root / 'fonts' / 'Nunito-wght.ttf'), 'fonts'),
           (str(root / 'fonts' / 'OFL.txt'), 'fonts')],
    hiddenimports=['keyring.backends.macOS', 'gi.repository.Soup'], hookspath=[],
    hooksconfig={'gi': {'icons': ['Adwaita'], 'themes': ['Adwaita'],
                        'languages': ['en'], 'module-versions': {'Gtk': '3.0', 'Soup': '3.0'}},
                 'gstreamer': {'include_plugins': plugins}},
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Apistat',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Apistat')
app = BUNDLE(
    coll, name='Apistat.app', icon=str(root / 'macos' / 'Apistat.icns'),
    bundle_identifier='org.apistat.Apistat',
    info_plist={'CFBundleName': 'Apistat', 'CFBundleDisplayName': 'Apistat',
                'CFBundleShortVersionString': '0.1.0',
                'NSHighResolutionCapable': True,
                'NSLocalNetworkUsageDescription':
                    'Apistat connects to your Plex server and accepts optional Plexamp controls on your local network.'},
)
