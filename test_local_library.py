import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from mutagen.wave import WAVE
from mutagen.id3 import TIT2, TPE1, TALB, TPE2, TRCK

import local_library
from local_library import LocalLibrary, create_source, load_sources, save_sources


def track(path, title, number):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000)
        output.writeframes(b'\x00\x00' * 800)
    audio = WAVE(str(path))
    audio.add_tags()
    for frame in (TIT2(encoding=3, text=title), TPE1(encoding=3, text='Singer'),
                  TPE2(encoding=3, text='Album artist'), TALB(encoding=3, text='Record'),
                  TRCK(encoding=3, text=str(number))):
        audio.tags.add(frame)
    audio.save()


class LocalLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'music'; self.root.mkdir()
        self.album = self.root / 'Record'; self.album.mkdir()
        track(self.album / 'one.wav', 'First', 1)
        track(self.album / 'two.wav', 'Second', 2)
        self.source = create_source(self.root)
        self.library = LocalLibrary(self.source, Path(self.tmp.name) / 'db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_browse_and_play_with_persistent_index(self):
        self.assertEqual(self.library.scan(), (2, 0))
        albums, total = self.library.albums(self.source['id'])
        self.assertEqual(total, 1)
        self.assertEqual((albums[0].title, albums[0].artist), ('Record', 'Album artist'))
        songs = self.library.tracks(albums[0])
        self.assertEqual([song.title for song in songs], ['First', 'Second'])
        self.assertEqual(self.library.stream(songs[0]), (self.album / 'one.wav').resolve().as_uri())
        reopened = LocalLibrary(self.source, Path(self.tmp.name) / 'db')
        self.assertEqual(reopened.songs(self.source['id'])[1], 2)

    def test_saved_playlist_preserves_order_duplicates_and_survives_restart(self):
        self.library.scan()
        songs = self.library.songs(self.source['id'])[0]
        playlist = self.library.create_playlist_with_tracks('History', [songs[0], songs[1], songs[0]])
        reopened = LocalLibrary(self.source, Path(self.tmp.name) / 'db')
        self.assertEqual([item.title for item in reopened.playlists()], ['History'])
        items, total = reopened.playlist_items(playlist)
        self.assertEqual(total, 3)
        self.assertEqual([item.key for item in items], [songs[0].key, songs[1].key, songs[0].key])
        reopened.move_playlist_item(playlist, items[2].playlist_item_id, None)
        self.assertEqual(reopened.playlist_items(playlist)[0][0].playlist_item_id,
                         items[2].playlist_item_id)
        reopened.rename_playlist(playlist, 'Memories')
        self.assertEqual(reopened.playlists()[0].title, 'Memories')
        reopened.delete_playlist(playlist)
        self.assertEqual(reopened.playlists(), [])

    def test_edit_selected_tracks_updates_files_and_album_index(self):
        from mutagen.id3 import ID3
        from test_tag_edit import PNG
        self.library.scan()
        album = self.library.albums(self.source['id'])[0][0]
        songs = self.library.tracks(album)
        saved, failures = self.library.edit_tracks(
            [songs[0]], {'title': 'Renamed', 'genre': 'Jazz'}, PNG, section=self.source['id'])
        self.assertEqual((saved, failures), (1, []))
        refreshed = self.library.tracks(self.library.albums(self.source['id'])[0][0])
        self.assertEqual([song.title for song in refreshed], ['Renamed', 'Second'])
        self.assertEqual(refreshed[0].genre, 'Jazz')
        self.assertEqual(refreshed[1].title, 'Second')
        self.assertTrue(refreshed[0].album_thumb.startswith('/local/art/'))
        self.assertEqual(refreshed[0].album_thumb, refreshed[1].album_thumb)
        self.assertEqual(self.library.get('/photo/:/transcode', url=refreshed[0].album_thumb), PNG)
        audio = __import__('mutagen').File(self.album / 'one.wav')
        self.assertEqual(audio.tags.getall('TIT2')[0].text, ['Renamed'])
        self.assertEqual(audio.tags.getall('APIC')[0].data, PNG)
        other = __import__('mutagen').File(self.album / 'two.wav')
        self.assertFalse(other.tags.getall('APIC'))

    def test_unchanged_files_use_cached_metadata_and_forced_scan_reloads(self):
        self.library.scan()
        with patch('mutagen.File', side_effect=AssertionError('unexpected file re-read')):
            self.assertEqual(self.library.scan(), (2, 0))
        with patch('mutagen.File', wraps=__import__('mutagen').File) as read:
            self.assertEqual(self.library.scan(force=True), (2, 0))
            self.assertGreaterEqual(read.call_count, 2)

    def test_various_artists_without_album_artist_share_one_album(self):
        for filename, artist in (('one.wav', 'Artist One'), ('two.wav', 'Artist Two')):
            audio = WAVE(str(self.album / filename))
            audio.tags.delall('TPE2')
            audio.tags.delall('TPE1')
            audio.tags.add(TPE1(encoding=3, text=artist))
            audio.save()
        (self.album / 'cover.jpg').write_bytes(b'cover bytes')
        self.assertEqual(self.library.scan(), (2, 0))
        albums, total = self.library.albums(self.source['id'])
        self.assertEqual(total, 1)
        self.assertEqual(albums[0].artist, 'Various Artists')
        songs = self.library.tracks(albums[0])
        self.assertEqual([song.artist for song in songs], ['Artist One', 'Artist Two'])
        self.assertEqual(self.library.get('/photo/:/transcode', url=albums[0].thumb), b'cover bytes')
        self.library.set_track_rating(songs[0], 8)
        self.assertEqual(self.library.scan(), (2, 0))
        self.assertEqual(self.library.albums(self.source['id'])[1], 1)
        self.assertEqual(self.library.tracks(albums[0])[0].user_rating, 8)

    def test_distinct_album_artists_in_same_folder_are_not_merged(self):
        for filename, album_artist in (('one.wav', 'Band One'), ('two.wav', 'Band Two')):
            audio = WAVE(str(self.album / filename))
            audio.tags.delall('TPE2')
            audio.tags.add(TPE2(encoding=3, text=album_artist))
            audio.save()
        self.library.scan()
        self.assertEqual(self.library.albums(self.source['id'])[1], 2)

    def test_legacy_database_migration_preserves_ratings_and_original(self):
        old = Path(self.tmp.name) / 'old'; new = Path(self.tmp.name) / 'new'
        prior = LocalLibrary(self.source, old)
        prior.scan()
        song = prior.songs(self.source['id'])[0][0]
        prior.set_track_rating(song, 8)
        with patch.object(local_library, 'DATA', new), patch.object(local_library, 'LEGACY_DATA', old):
            moved = LocalLibrary(self.source)
        self.assertEqual(moved.songs(self.source['id'])[0][0].user_rating, 8)
        self.assertTrue((old / (self.source['id'] + '.sqlite3')).exists())
        self.assertTrue((new / (self.source['id'] + '.sqlite3')).exists())

    def test_scan_removes_deleted_tracks_and_preserves_ratings(self):
        self.library.scan()
        first = self.library.songs(self.source['id'])[0][0]
        self.library.set_track_rating(first, 8)
        self.library.scan()
        self.assertEqual(next(x for x in self.library.songs(self.source['id'])[0]
                              if x.key == first.key).user_rating, 8)
        (self.album / 'two.wav').unlink()
        self.assertEqual(self.library.scan(), (1, 0))

    def test_scan_cancellation_and_unavailable_folder_keep_index(self):
        self.library.scan()
        self.assertIsNone(self.library.scan(lambda: False))
        self.root.rename(self.root.with_name('disconnected'))
        with self.assertRaises(OSError):
            self.library.scan()
        self.assertEqual(self.library.songs(self.source['id'])[1], 2)

    def test_indexed_art_and_track_paths_are_constrained(self):
        (self.album / 'cover.jpg').write_bytes(b'example cover')
        self.library.scan()
        album = self.library.albums(self.source['id'])[0][0]
        self.assertEqual(self.library.get('/photo/:/transcode', url=album.thumb), b'example cover')
        with self.assertRaises(ValueError):
            self.library.get('/photo/:/transcode', url='file:///etc/passwd')
        with self.assertRaises(ValueError):
            self.library.stream(type('Track', (), {'key': '/local/track/unknown'})())

    def test_sources_persist_without_credentials(self):
        with patch.object(local_library, 'CONFIG', Path(self.tmp.name) / 'sources.json'):
            config = {'local': [self.source], 'active': 'local:' + self.source['id']}
            save_sources(config)
            self.assertEqual(load_sources(), config)


if __name__ == '__main__':
    unittest.main()
