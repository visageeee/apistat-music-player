"""Portable Windows build: run from the repository root with PyInstaller."""

from pathlib import Path


root = Path.cwd()
gst_plugins = [
    'app', 'audioconvert', 'audioresample', 'audioparsers', 'autodetect',
    'coreelements', 'directsound', 'faad', 'flac', 'id3demux', 'mpg123',
    'ogg', 'playback', 'soup', 'spectrum', 'typefindfunctions', 'volume',
    'vorbis', 'wasapi', 'wasapi2', 'wavparse',
]

a = Analysis(
    [str(root / 'player.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'apistat.png'), '.'),
           (str(root / 'assets' / 'time-machine'), 'assets/time-machine'),
           (str(root / 'fonts' / 'Nunito-wght.ttf'), 'fonts'),
           (str(root / 'fonts' / 'OFL.txt'), 'fonts'),
           (str(root / 'windows' / 'fonts.conf'), 'windows')],
    hiddenimports=['gi.repository.PangoFc', 'gpu_album_wall', 'gpu_wgl'],
    hookspath=[],
    hooksconfig={
        'gi': {
            'icons': ['Adwaita'],
            'themes': ['Adwaita'],
            'languages': ['en'],
            'module-versions': {'Gtk': '3.0'},
        },
        'gstreamer': {'include_plugins': gst_plugins},
    },
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Apistat',
    icon=str(root / 'windows' / 'Apistat.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Apistat',
)
