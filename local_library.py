"""Persistent local music sources and a SQLite-backed local catalog."""
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from contextlib import contextmanager
from pathlib import Path

from gi.repository import GLib
from plex_client import Item, ALBUM_SORT_ARTIST

CONFIG = Path(GLib.get_user_config_dir()) / 'apistat' / 'sources.json'
LEGACY_DATA = Path(GLib.get_user_data_dir()) / 'apistat' / 'libraries'
DATA = (Path.home() / 'Library' / 'Application Support' / 'Apistat' / 'Libraries'
        if sys.platform == 'darwin' else LEGACY_DATA)
UNCHANGED_ART = object()
EXTENSIONS = {'.mp3', '.flac', '.m4a', '.mp4', '.ogg', '.opus', '.oga', '.wav', '.aiff', '.aif', '.wma', '.ape', '.wv'}


def load_sources():
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8'))
        libraries = data.get('local', [])
        if not isinstance(libraries, list):
            return {'local': [], 'active': ''}
        valid = [item for item in libraries if isinstance(item, dict) and
                 re.fullmatch(r'[0-9a-f]{32}', str(item.get('id', ''))) and
                 isinstance(item.get('path'), str) and Path(item['path']).is_absolute() and
                 isinstance(item.get('name'), str) and item['name'].strip()]
        active = data.get('active', '')
        return {'local': valid, 'active': active if isinstance(active, str) else ''}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'local': [], 'active': ''}


def save_sources(data):
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.sources-', dir=CONFIG.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(name, CONFIG)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def create_source(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Choose a music folder')
    return {'id': uuid.uuid4().hex, 'path': str(path), 'name': path.name or str(path)}


def digest(value):
    return hashlib.sha256(value.encode('utf-8', 'surrogatepass')).hexdigest()[:32]


def tag(tags, *keys):
    frames = {'title': 'TIT2', 'artist': 'TPE1', 'albumartist': 'TPE2',
              'album artist': 'TPE2', 'album': 'TALB', 'date': 'TDRC',
              'year': 'TYER', 'discnumber': 'TPOS', 'tracknumber': 'TRCK',
              'genre': 'TCON', 'mood': 'TMOO'}
    for key in keys:
        values = (tags.get(key) or tags.get(frames.get(key, ''))) if tags else None
        values = getattr(values, 'text', values)
        if values:
            return str(values[0] if isinstance(values, (tuple, list)) else values).strip()
    return ''


def number(value):
    match = re.match(r'\s*(\d+)', str(value))
    return int(match.group(1)) if match else 0


def _cover(directory, audio):
    for name in ('cover.jpg', 'cover.png', 'folder.jpg', 'folder.png', 'front.jpg', 'front.png'):
        try:
            path = directory / name
            if path.is_file() and path.stat().st_size <= 16 * 1024 * 1024:
                return path.read_bytes()
        except OSError:
            pass
    try:
        pictures = getattr(audio, 'pictures', ())
        if pictures:
            return pictures[0].data
        tags = getattr(audio, 'tags', None)
        if tags is not None:
            pictures = tags.getall('APIC') if hasattr(tags, 'getall') else tags.get('covr', ())
            if pictures:
                return getattr(pictures[0], 'data', pictures[0])
    except (AttributeError, TypeError, ValueError):
        pass
    return None


class LocalLibrary:
    """A local catalog; IDs are opaque and file access is limited to indexed paths."""
    is_local = True
    token = ''
    identifier = 'apistat-local'
    device_name = 'Apistat'

    def __init__(self, source, database_dir=None):
        self.source = dict(source)
        if not re.fullmatch(r'[0-9a-f]{32}', self.source.get('id', '')):
            raise ValueError('Invalid local library identity')
        self.root = Path(self.source['path'])
        self.address = 'local:' + self.source['id']
        self.database = (database_dir or DATA) / (self.source['id'] + '.sqlite3')
        self.database.parent.mkdir(parents=True, exist_ok=True)
        if database_dir is None and DATA != LEGACY_DATA and not self.database.exists():
            old = LEGACY_DATA / self.database.name
            if old.is_file():
                self._copy_legacy_database(old)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tracks (key TEXT PRIMARY KEY, path TEXT NOT NULL,
                    album_key TEXT NOT NULL, mtime INTEGER NOT NULL, size INTEGER NOT NULL,
                    data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS track_album ON tracks(album_key);
                CREATE TABLE IF NOT EXISTS albums (key TEXT PRIMARY KEY, data TEXT NOT NULL,
                    art BLOB);
                CREATE TABLE IF NOT EXISTS playlists (key TEXT PRIMARY KEY, title TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS playlist_tracks (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_key TEXT NOT NULL, track_key TEXT NOT NULL, position INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS playlist_order ON playlist_tracks(playlist_key, position);
                CREATE TABLE IF NOT EXISTS artist_info (name TEXT PRIMARY KEY, summary TEXT NOT NULL,
                    url TEXT NOT NULL, expires INTEGER NOT NULL);
            ''')

    def _copy_legacy_database(self, old):
        # Back up through SQLite so committed ratings survive an interrupted app.
        fd, temporary = tempfile.mkstemp(prefix='.library-migration-', dir=self.database.parent)
        os.close(fd)
        try:
            source = sqlite3.connect(str(old), timeout=15)
            destination = sqlite3.connect(temporary, timeout=15)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            os.replace(temporary, self.database)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.database), timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def sections(self):
        return [(self.source['id'], self.source['name'])]

    def scan(self, valid=lambda: True, force=False):
        from mutagen import File
        if not self.root.is_dir():
            raise OSError('The music folder is unavailable')
        with self.connect() as db:
            previous = {row[0]: row[1:] for row in db.execute('SELECT path,mtime,size,data FROM tracks')}
            previous_albums = {row[0]: row[1] for row in db.execute('SELECT key,data FROM albums')}
            rows, albums, seen, errors = [], {}, set(), []
            for directory, _dirs, files in os.walk(self.root, onerror=errors.append, followlinks=False):
                if not valid():
                    return None
                for filename in files:
                    path = Path(directory) / filename
                    if path.suffix.lower() not in EXTENSIONS:
                        continue
                    try:
                        resolved = path.resolve(strict=True)
                        relative = str(resolved.relative_to(self.root.resolve(strict=True)))
                        if relative in seen:
                            continue
                        stat = resolved.stat()
                        if not resolved.is_file():
                            continue
                        old = previous.get(relative)
                        if old and not force and old[0] == stat.st_mtime_ns and old[1] == stat.st_size:
                            item = Item(**json.loads(old[2]))
                            old_album = previous_albums.get(item.album_key)
                            if old_album:
                                if item.album_key not in albums:
                                    albums[item.album_key] = [Item(**json.loads(old_album)), UNCHANGED_ART]
                                rows.append((item.key, relative, item.album_key, stat.st_mtime_ns,
                                             stat.st_size, old[2]))
                                seen.add(relative)
                                continue
                        audio = File(str(resolved))
                        if audio is None:
                            if old:
                                errors.append(relative)
                            continue
                        easy = File(str(resolved), easy=True)
                        tags = easy.tags if easy is not None else None
                        artist = tag(tags, 'artist') or 'Unknown artist'
                        album_artist = tag(tags, 'albumartist', 'album artist') or artist
                        album_title = tag(tags, 'album') or resolved.parent.name or 'Unknown album'
                        album_folder = resolved.parent
                        if re.fullmatch(r'(?i)(?:cd|disc|disk)\s*\d+', album_folder.name):
                            album_folder = album_folder.parent
                        album_id = digest(str(album_folder.relative_to(self.root.resolve())) + '\0' +
                                          album_artist.casefold() + '\0' + album_title.casefold())
                        album_key = '/local/album/' + album_id
                        track_key = '/local/track/' + digest(relative)
                        old_item = json.loads(old[2]) if old else {}
                        added = int(old_item.get('added_at', time.time()))
                        date = tag(tags, 'date', 'year')
                        disc, track = number(tag(tags, 'discnumber')), number(tag(tags, 'tracknumber'))
                        info = getattr(audio, 'info', None)
                        item = Item(track_key, tag(tags, 'title') or resolved.stem, artist=artist,
                                    album=album_title, album_artist=album_artist,
                                    album_key=album_key, duration=max(0, int(getattr(info, 'length', 0) * 1000)),
                                    year=str(number(date)) if number(date) else '', release_date=date,
                                    number=str(track) if track else '', disc=disc, track_number=track,
                                    genre=tag(tags, 'genre'), mood=tag(tags, 'mood'),
                                    bitrate=max(0, int(getattr(info, 'bitrate', 0) / 1000)),
                                    codec=resolved.suffix[1:].lower(), added_at=added,
                                    user_rating=float(old_item.get('user_rating', 0)),
                                    play_count=int(old_item.get('play_count', 0)),
                                    last_played_at=int(old_item.get('last_played_at', 0)))
                        if album_key not in albums:
                            art = _cover(album_folder, audio)
                            art_key = '/local/art/' + album_id + '/' + hashlib.sha256(art).hexdigest()[:16] if art else ''
                            album = Item(album_key, album_title, artist=album_artist, year=item.year,
                                         added_at=added, thumb=art_key)
                            albums[album_key] = [album, art]
                        album, _art = albums[album_key]
                        album.added_at = max(album.added_at, added)
                        item.thumb = item.album_thumb = album.thumb
                        rows.append((track_key, relative, album_key, stat.st_mtime_ns, stat.st_size,
                                     json.dumps(asdict(item), ensure_ascii=False)))
                        seen.add(relative)
                    except Exception:
                        errors.append(str(path))
            if not valid():
                return None
            # Keep existing entries if a subtree or file could not be read.
            if errors:
                old_rows = list(db.execute('SELECT key,path,album_key,mtime,size,data FROM tracks'))
                old_albums = list(db.execute('SELECT key,data FROM albums'))
                rows.extend(row for row in old_rows if row[1] not in seen)
                for key, data in old_albums:
                    if key not in albums and any(row[2] == key for row in rows):
                        albums[key] = [Item(**json.loads(data)), UNCHANGED_ART]
            rows = self._group_compilations(db, rows, albums)
            # Lock out concurrent rating updates while taking the final snapshot.
            db.execute('BEGIN IMMEDIATE')
            current = {key: json.loads(data) for key, data in db.execute('SELECT key,data FROM tracks')}
            updated_rows = []
            for key, path, album_key, mtime, size, data in rows:
                item = json.loads(data)
                if key in current:
                    for field in ('user_rating', 'play_count', 'last_played_at'):
                        item[field] = current[key].get(field, item.get(field, 0))
                updated_rows.append((key, path, album_key, mtime, size, json.dumps(item, ensure_ascii=False)))
            rows = updated_rows
            db.execute('DELETE FROM tracks')
            db.executemany('INSERT INTO tracks VALUES (?,?,?,?,?,?)', rows)
            for key, (album, art) in albums.items():
                data = json.dumps(asdict(album), ensure_ascii=False)
                if art is UNCHANGED_ART:
                    db.execute('UPDATE albums SET data=? WHERE key=?', (data, key))
                else:
                    db.execute('INSERT INTO albums VALUES (?,?,?) ON CONFLICT(key) '
                               'DO UPDATE SET data=excluded.data, art=excluded.art', (key, data, art))
            db.execute('DELETE FROM albums WHERE key NOT IN (SELECT DISTINCT album_key FROM tracks)')
            return len(rows), len(errors)

    def _group_compilations(self, db, rows, albums):
        """Combine same-folder albums split only by their track artist tags."""
        groups = {}
        for index, row in enumerate(rows):
            item = json.loads(row[5])
            folder = Path(row[1]).parent
            if re.fullmatch(r'(?i)(?:cd|disc|disk)\s*\d+', folder.name):
                folder = folder.parent
            groups.setdefault((str(folder), item.get('album', '').casefold()), []).append((index, item))
        for (folder, title), entries in groups.items():
            old_keys = {rows[index][2] for index, _item in entries}
            artists = {item.get('artist', '').casefold() for _index, item in entries
                       if item.get('artist') and item.get('artist') != 'Unknown artist'}
            if not title or len(old_keys) < 2 or len(artists) < 2:
                continue
            # Avoid merging releases whose explicitly distinct album artists
            # are different from the individual track artists.
            if any(item.get('album_artist', '').casefold() not in
                   ('', item.get('artist', '').casefold(), 'various artists', 'various')
                   for _index, item in entries):
                continue
            index, first = entries[0]
            previous_key = rows[index][2]
            first_album, art = albums[previous_key]
            if art is UNCHANGED_ART:
                record = db.execute('SELECT art FROM albums WHERE key=?', (previous_key,)).fetchone()
                art = record[0] if record else None
            album_id = digest(folder + '\0various artists\0' + title)
            album_key = '/local/album/' + album_id
            thumb = ('/local/art/' + album_id + '/' + hashlib.sha256(art).hexdigest()[:16]
                     if art else '')
            album = Item(album_key, first.get('album', 'Unknown album'), artist='Various Artists',
                         year=first_album.year,
                         added_at=max(item.get('added_at', 0) for _index, item in entries),
                         thumb=thumb)
            albums[album_key] = [album, art]
            for index, item in entries:
                key, path, _old_album, mtime, size, _data = rows[index]
                item.update(album_key=album_key, album_artist='Various Artists',
                            thumb=thumb, album_thumb=thumb)
                rows[index] = (key, path, album_key, mtime, size,
                               json.dumps(item, ensure_ascii=False))
        return rows

    def albums(self, section, start=0, title='', sort='addedAt:desc', artist=''):
        with self.connect() as db:
            albums = [Item(**json.loads(row[0])) for row in db.execute('SELECT data FROM albums')]
        if title:
            albums = [a for a in albums if title.casefold() in a.title.casefold()]
        if artist:
            albums = [a for a in albums if artist.casefold() in a.artist.casefold()]
        if sort == 'addedAt:desc':
            albums.sort(key=lambda a: (-a.added_at, a.title.casefold(), a.key))
        elif sort == 'year:desc':
            albums.sort(key=lambda a: (-number(a.year), a.title.casefold(), a.key))
        elif sort == ALBUM_SORT_ARTIST:
            albums.sort(key=lambda a: (a.artist.casefold(), a.title.casefold(), a.key))
        elif sort == 'titleSort':
            albums.sort(key=lambda a: (a.title.casefold(), a.artist.casefold(), a.key))
        else:
            raise ValueError('Unsupported album sort')
        return albums[start:start + 100], len(albums)

    def songs(self, section, start=0, sort='addedAt:desc'):
        with self.connect() as db:
            items = [Item(**json.loads(row[0])) for row in db.execute('SELECT data FROM tracks')]
        if sort == 'addedAt:desc':
            items.sort(key=lambda item: (-item.added_at, item.title.casefold(), item.key))
        elif sort == 'titleSort':
            items.sort(key=lambda item: (item.title.casefold(), item.key))
        elif sort == 'artist.titleSort,titleSort':
            items.sort(key=lambda item: (item.artist.casefold(), item.title.casefold(), item.key))
        return items[start:start + 100], len(items)

    def tracks(self, album):
        with self.connect() as db:
            items = [Item(**json.loads(row[0])) for row in db.execute(
                'SELECT data FROM tracks WHERE album_key=?', (album.key,))]
        return sorted(items, key=lambda item: (item.disc, item.track_number, item.title.casefold()))

    def stream(self, track):
        with self.connect() as db:
            row = db.execute('SELECT path FROM tracks WHERE key=?', (track.key,)).fetchone()
        if row is None:
            raise ValueError('This track is not in the local library')
        root = self.root.resolve(strict=True)
        path = (root / row[0]).resolve(strict=True)
        path.relative_to(root)
        if not path.is_file():
            raise OSError('The local music file is unavailable')
        return path.as_uri()

    def get(self, path, **params):
        if path != '/photo/:/transcode':
            raise ValueError('Unsupported local artwork request')
        key = params.get('url', '')
        if not re.fullmatch(r'/local/art/[0-9a-f]{32}/[0-9a-f]{16}', key):
            raise ValueError('Invalid local artwork')
        album_key = '/local/album/' + key.split('/')[3]
        with self.connect() as db:
            row = db.execute('SELECT data,art FROM albums WHERE key=?', (album_key,)).fetchone()
        if not row or json.loads(row[0]).get('thumb') != key or not row[1]:
            raise ValueError('Local artwork is unavailable')
        return bytes(row[1])

    def playlists(self):
        with self.connect() as db:
            return [Item(key, title) for key, title in db.execute(
                'SELECT key, title FROM playlists ORDER BY rowid')]

    def create_playlist_with_tracks(self, title, tracks):
        title = title.strip()
        if not title or not tracks:
            raise ValueError('A playlist needs a name and at least one track')
        key = '/local/playlist/' + uuid.uuid4().hex
        with self.connect() as db:
            for track in tracks:
                if not db.execute('SELECT 1 FROM tracks WHERE key=?', (track.key,)).fetchone():
                    raise ValueError('A track is no longer in the local library')
            db.execute('INSERT INTO playlists VALUES (?, ?)', (key, title))
            db.executemany('INSERT INTO playlist_tracks (playlist_key, track_key, position) VALUES (?, ?, ?)',
                           ((key, track.key, i) for i, track in enumerate(tracks)))
        return Item(key, title)

    def create_playlist(self, title, first_track):
        return self.create_playlist_with_tracks(title, [first_track])

    def add_playlist_item(self, playlist, track):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM playlists WHERE key=?', (playlist.key,)).fetchone():
                raise ValueError('Playlist not found')
            if not db.execute('SELECT 1 FROM tracks WHERE key=?', (track.key,)).fetchone():
                raise ValueError('Track not found')
            db.execute('INSERT INTO playlist_tracks (playlist_key, track_key, position) '
                       'SELECT ?, ?, COALESCE(MAX(position), -1) + 1 FROM playlist_tracks WHERE playlist_key=?',
                       (playlist.key, track.key, playlist.key))

    def playlist_items(self, playlist, start=0):
        with self.connect() as db:
            rows = db.execute('SELECT tracks.data, playlist_tracks.id FROM playlist_tracks '
                              'JOIN tracks ON tracks.key=playlist_tracks.track_key '
                              'WHERE playlist_tracks.playlist_key=? ORDER BY playlist_tracks.position, playlist_tracks.id',
                              (playlist.key,)).fetchall()
        items = []
        for data, item_id in rows[start:start + 100]:
            item = Item(**json.loads(data))
            item.playlist_item_id = item_id
            items.append(item)
        return items, len(rows)

    def rename_playlist(self, playlist, title):
        if not title.strip():
            raise ValueError('Enter a playlist name')
        with self.connect() as db:
            if not db.execute('UPDATE playlists SET title=? WHERE key=?', (title.strip(), playlist.key)).rowcount:
                raise ValueError('Playlist not found')

    def delete_playlist(self, playlist):
        with self.connect() as db:
            db.execute('DELETE FROM playlist_tracks WHERE playlist_key=?', (playlist.key,))
            db.execute('DELETE FROM playlists WHERE key=?', (playlist.key,))

    def move_playlist_item(self, playlist, item_id, after_id=None):
        with self.connect() as db:
            ids = [row[0] for row in db.execute(
                'SELECT id FROM playlist_tracks WHERE playlist_key=? ORDER BY position, id', (playlist.key,))]
            if item_id not in ids or (after_id is not None and after_id not in ids):
                raise ValueError('Playlist item not found')
            if item_id == after_id:
                return
            ids.remove(item_id)
            ids.insert(ids.index(after_id) + 1 if after_id is not None else 0, item_id)
            db.executemany('UPDATE playlist_tracks SET position=? WHERE id=?',
                           ((position, item) for position, item in enumerate(ids)))

    def music_facets(self, section):
        return ()

    def rate_track(self, track, loved=True):
        self.set_track_rating(track, 10 if loved else 0)

    def set_track_rating(self, track, rating):
        with self.connect() as db:
            row = db.execute('SELECT data FROM tracks WHERE key=?', (track.key,)).fetchone()
            if not row:
                raise ValueError('Track not found')
            data = json.loads(row[0]); data['user_rating'] = max(0, min(10, rating))
            db.execute('UPDATE tracks SET data=? WHERE key=?', (json.dumps(data), track.key))

    def track_details(self, track):
        from urllib.parse import unquote, urlsplit
        path = Path(unquote(urlsplit(self.stream(track)).path))
        if os.name == 'nt' and re.match(r'^/[A-Za-z]:', str(path)):
            path = Path(str(path)[1:])
        return ({'file': str(path), 'codec': track.codec, 'bitrate': track.bitrate,
                 'title': track.title, 'artist': track.artist, 'album': track.album,
                 'album_artist': track.album_artist, 'year': track.year}, '')

    def artist_description(self, name, album=''):
        from local_artist_info import lookup_artist
        name = str(name or '').strip()
        if not name:
            return None
        key = 'v2:' + json.dumps([name.casefold(), str(album or '').strip().casefold()], ensure_ascii=False)
        now = int(time.time())
        with self.connect() as db:
            row = db.execute('SELECT summary, url, expires FROM artist_info WHERE name=?', (key,)).fetchone()
        if row and row[2] > now:
            return (row[0], row[1]) if row[0] else None
        result = lookup_artist(name, album)
        summary, url = result or ('', '')
        expires = now + (30 * 86400 if result else 86400)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO artist_info VALUES (?, ?, ?, ?)',
                       (key, summary, url, expires))
        return result
