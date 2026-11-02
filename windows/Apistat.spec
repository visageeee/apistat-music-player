"""Portable Windows build: run from the repository root with PyInstaller."""

from pathlib import Path


root = Path.cwd()
gst_plugins = [
    'app', 'audioconvert', 'audioresample', 'audioparsers', 'autodetect',
    'coreelements', 'directsound', 'flac', 'id3demux', 'libav', 'mpg123',
    'ogg', 'playback', 'soup', 'spectrum', 'typefindfunctions', 'volume',
    'vorbis', 'wasapi', 'wavparse',
]

a = Analysis(
    [str(root / 'player.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
debug_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Apistat-Debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    debug_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Apistat',
)
