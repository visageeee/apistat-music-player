"""Application storage paths and migration from the prototype's old name."""
import os
import shutil
import sys
from pathlib import Path

from gi.repository import GLib

APP_DIR = 'apistat'
LEGACY_DIR = 'plex-music-prototype'
CONFIG_DIR = Path(GLib.get_user_config_dir()) / APP_DIR
CACHE_DIR = Path(GLib.get_user_cache_dir()) / APP_DIR


def migrate_legacy_directory(root):
    """Move old files without replacing data already written under the new name."""
    root = Path(root)
    old, new = root / LEGACY_DIR, root / APP_DIR
    if not old.is_dir():
        return
    if not new.exists():
        try:
            old.rename(new)
            return
        except OSError:
            pass
    for directory, dirs, files in os.walk(old, topdown=False):
        source = Path(directory)
        relative = source.relative_to(old)
        target = new / relative
        for name in files:
            src, dst = source / name, target / name
            if dst.exists():
                continue
            try:
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.move(str(src), str(dst))
            except OSError as error:
                print(f'Apistat could not migrate {src}: {error}', file=sys.stderr)
        for name in dirs:
            try:
                (source / name).rmdir()
            except OSError:
                pass
    try:
        old.rmdir()
    except OSError:
        pass


def migrate_legacy_data():
    for root in {Path(GLib.get_user_config_dir()), Path(GLib.get_user_cache_dir())}:
        migrate_legacy_directory(root)
