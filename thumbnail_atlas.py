"""Private, persistent pages of small RGBA album thumbnails.

A stable index assigns each thumbnail to a page and cell. Catalog reordering or
adding albums does not invalidate other thumbnails; changing a thumbnail URI
creates a separate cell. Existing v1 pages are migrated lazily when read.
"""
import hashlib
import os
import sqlite3
import threading

from local_cache import LocalCache, _private_dir

CELL = 64
PAGE_CELLS = 64
CELL_BYTES = CELL * CELL * 4


class ThumbnailAtlas:
    def __init__(self, client, albums):
        cache = LocalCache(client)
        self.root = cache.root / 'canvas-atlas-v2'
        self.legacy_root = cache.root / 'canvas-atlas-v1'
        self.lock = threading.Lock()
        self.connection = None
        self.closed = False
        self.entries = {}
        self.thumbs = {album.thumb for album in albums if album.thumb}
        self.legacy_entries = {}
        thumbs = sorted(self.thumbs)
        for start in range(0, len(thumbs), PAGE_CELLS):
            page = thumbs[start:start + PAGE_CELLS]
            digest = hashlib.sha256('\0'.join(page).encode('utf-8')).hexdigest()
            path = self.legacy_root / (digest + '.atlas')
            for cell, thumb in enumerate(page):
                self.legacy_entries[thumb] = (path, cell)

    def _database(self):
        if self.connection is None:
            _private_dir(self.root)
            connection = sqlite3.connect(str(self.root / 'index.sqlite3'), timeout=5,
                                         check_same_thread=False)
            try:
                connection.execute('CREATE TABLE IF NOT EXISTS thumbs (identity TEXT UNIQUE NOT NULL)')
                connection.commit()
            except Exception:
                connection.close()
                raise
            self.connection = connection
        return self.connection

    def _entry(self, thumb, create):
        if thumb not in self.thumbs:
            return None
        if thumb in self.entries:
            return self.entries[thumb]
        db = self._database()
        identity = hashlib.sha256(thumb.encode('utf-8')).hexdigest()
        if create:
            db.execute('INSERT OR IGNORE INTO thumbs (identity) VALUES (?)', (identity,))
            db.commit()
        row = db.execute('SELECT rowid FROM thumbs WHERE identity=?', (identity,)).fetchone()
        if row is None:
            return None
        page, cell = divmod(row[0] - 1, PAGE_CELLS)
        entry = (self.root / (f'{page:016x}.atlas'), cell)
        self.entries[thumb] = entry
        return entry

    @staticmethod
    def _read_cell(entry):
        if entry is None:
            return None
        path, cell = entry
        try:
            with path.open('rb') as file:
                file.seek(cell)
                if file.read(1) != b'\1':
                    return None
                file.seek(PAGE_CELLS + cell * CELL_BYTES)
                pixels = file.read(CELL_BYTES)
                return pixels if len(pixels) == CELL_BYTES else None
        except OSError:
            return None

    def read(self, thumb):
        try:
            with self.lock:
                if self.closed:
                    return None
                pixels = self._read_cell(self._entry(thumb, False))
                if pixels is not None:
                    return pixels
                pixels = self._read_cell(self.legacy_entries.get(thumb))
            if pixels is not None:
                self.write(thumb, pixels)
            return pixels
        except (OSError, sqlite3.Error):
            return None

    def write(self, thumb, pixels):
        if len(pixels) != CELL_BYTES:
            return
        try:
            with self.lock:
                if self.closed:
                    return
                entry = self._entry(thumb, True)
                if entry is None:
                    return
                path, cell = entry
                fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
                with os.fdopen(fd, 'r+b') as file:
                    file.seek(PAGE_CELLS + cell * CELL_BYTES)
                    file.write(pixels)
                    file.flush()
                    file.seek(cell)
                    file.write(b'\1')
        except (OSError, sqlite3.Error):
            pass

    def close(self):
        with self.lock:
            self.closed = True
            if self.connection is not None:
                self.connection.close()
                self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
