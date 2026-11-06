import io
import cairo
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from mutagen import File
from mutagen.id3 import APIC, COMM

from plex_client import Item, PlexClient
from tag_edit import image_type, validate_changes, write_tags
from tag_editor import TagEditor

_image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 2, 2)
_buffer = io.BytesIO()
_image.write_to_png(_buffer)
PNG = _buffer.getvalue()


class TagEditTests(unittest.TestCase):
    def test_common_formats_preserve_other_tags_and_embed_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            for extension in ('mp3', 'flac', 'm4a'):
                path = Path(directory) / ('song.' + extension)
                shutil.copyfile(Path('test_fixtures/audio') / ('tone.' + extension), path)
                audio = File(path)
                if extension == 'mp3':
                    audio.tags.add(COMM(encoding=3, lang='eng', desc='keep', text=['untouched']))
                elif extension == 'flac':
                    audio.tags['comment'] = ['untouched']
                else:
                    audio.tags['\xa9cmt'] = ['untouched']
                audio.save()
                write_tags(path, {'title': 'New title', 'artist': 'New artist', 'year': '1998',
                                  'track_number': '4'}, PNG)
                updated = File(path)
                easy = File(path, easy=True)
                self.assertEqual(easy.tags['title'][0], 'New title')
                self.assertEqual(easy.tags['artist'][0], 'New artist')
                if extension == 'mp3':
                    self.assertEqual(updated.tags.getall('COMM')[0].text, ['untouched'])
                    self.assertEqual(updated.tags.getall('APIC')[0].data, PNG)
                elif extension == 'flac':
                    self.assertEqual(updated.tags['comment'], ['untouched'])
                    self.assertEqual(updated.pictures[0].data, PNG)
                else:
                    self.assertEqual(updated.tags['\xa9cmt'], ['untouched'])
                    self.assertEqual(bytes(updated.tags['covr'][0]), PNG)

    def test_replacing_front_cover_preserves_other_id3_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'song.mp3'
            shutil.copyfile('test_fixtures/audio/tone.mp3', path)
            audio = File(path)
            audio.tags.add(APIC(encoding=3, mime='image/png', type=4, desc='Cover', data=PNG))
            audio.save()
            write_tags(path, {}, PNG)
            pictures = File(path).tags.getall('APIC')
            self.assertEqual({picture.type for picture in pictures}, {3, 4})
            self.assertEqual(len(pictures), 2)

    def test_invalid_or_unsupported_files_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.mp3'
            path.write_bytes(b'not an audio file')
            with self.assertRaises(Exception):
                write_tags(path, {'title': 'New'})
            self.assertEqual(path.read_bytes(), b'not an audio file')
            self.assertEqual([item.name for item in Path(directory).iterdir()], ['bad.mp3'])
        for changes in ({'year': '-2'}, {'unknown': 'value'}, {'disc': '0'}):
            with self.assertRaises(ValueError):
                validate_changes(changes)
        with self.assertRaises(ValueError):
            image_type(b'not an image')

    def test_plex_requests_target_only_selected_tracks_and_album(self):
        client = PlexClient('http://127.0.0.1:32400', 'secret')
        client.request = Mock()
        client.opener = MagicMock()
        response = client.opener.open.return_value.__enter__.return_value
        response.read.return_value = b''
        one = Item('/library/metadata/20', 'One', album_key='/library/metadata/10')
        two = Item('/library/metadata/21', 'Two', album_key='/library/metadata/10')
        saved, errors = client.edit_tracks([one, two], {'title': 'New'}, PNG, section='2')
        self.assertEqual((saved, errors), (2, []))
        self.assertEqual(client.request.call_count, 2)
        self.assertEqual(client.request.call_args_list[0].kwargs['id'], '20')
        self.assertEqual(client.request.call_args_list[0].kwargs['title.locked'], 1)
        self.assertEqual(client.opener.open.call_count, 1)
        request = client.opener.open.call_args.args[0]
        self.assertTrue(request.full_url.endswith('/library/metadata/10/poster'))
        self.assertEqual(request.data, PNG)
        with self.assertRaises(ValueError):
            client.edit_tracks([one], {'title': 'x'}, section='../bad')
        with self.assertRaises(ValueError):
            client.edit_tracks([Item('https://example.org', 'bad')], {'title': 'x'}, section='2')

    def test_plex_failed_artwork_is_reported_without_claiming_success(self):
        client = PlexClient('http://127.0.0.1:32400', 'secret')
        client.opener = MagicMock()
        client.opener.open.side_effect = OSError('not available')
        song = Item('/library/metadata/20', 'Song', album_key='/library/metadata/10')
        saved, failures = client.edit_tracks([song], {}, PNG, section='2')
        self.assertEqual(saved, 0)
        self.assertEqual(failures, [('Album artwork', 'Plex rejected the artwork upload.')])

    def test_editor_save_applies_only_checked_fields_and_refreshes_library(self):
        client = SimpleNamespace(is_local=True, edit_tracks=Mock(return_value=(1, [])))
        player = SimpleNamespace(client=client, info_button=Mock(), closed=False, playlists=[],
                                 note_song_cache_edit=Mock(), invalidate_song_catalog=Mock(),
                                 song_view_cache={}, load_songs=Mock(), load_albums=Mock())
        player.async_work = lambda work, done, valid, failed: done(work()) if valid() else None
        editor = TagEditor(player)
        song = Item('/local/track/' + 'a' * 32, 'Original', artist='Artist')
        editor.load(client, 'music', [song])
        editor.entries['title'].set_text('New title')
        cache = MagicMock()
        with patch('tag_editor.LocalCache', return_value=cache):
            editor.save()
        client.edit_tracks.assert_called_once_with((song,), {'title': 'New title'}, None, section='music')
        player.note_song_cache_edit.assert_called_once_with(player)
        player.invalidate_song_catalog.assert_called_once_with()
        player.load_songs.assert_called_once_with()
        player.load_albums.assert_called_once_with(force_refresh=True)
        self.assertIn('Saved 1 of 1 tracks', editor.message.get_text())
        self.assertFalse(editor.checks['title'].get_active())
        editor.destroy()

    def test_editor_mixed_values_do_not_apply_without_user_choice(self):
        player = SimpleNamespace(info_button=Mock())
        editor = TagEditor(player)
        client = SimpleNamespace(is_local=True)
        editor.load(client, 'library', [Item('/one', 'First', artist='Artist'),
                                        Item('/two', 'Second', artist='Artist')])
        self.assertGreater(editor.get_children().index(editor.buttons),
                           editor.get_children().index(editor.fields_scroll))
        self.assertEqual(editor.save_button.get_label(), 'Save changes')
        self.assertEqual(editor.cancel_button.get_label(), 'Cancel')
        self.assertEqual(editor.intro.get_text(), '2 tracks selected')
        self.assertEqual(editor.source_heading.get_text(), 'Local files')
        self.assertIn('checked field left blank', editor.edit_instructions.get_text())
        self.assertEqual(editor.entries['title'].get_text(), '')
        self.assertEqual(editor.entries['title'].get_placeholder_text(), 'Multiple values')
        self.assertEqual(editor.entries['artist'].get_text(), 'Artist')
        self.assertFalse(any(check.get_active() for check in editor.checks.values()))
        editor.entries['artist'].set_text('Changed')
        self.assertTrue(editor.checks['artist'].get_active())
        self.assertFalse(editor.checks['title'].get_active())
        editor.load(SimpleNamespace(is_local=False), '2', [Item('/one', 'A')])
        self.assertEqual(editor.intro.get_text(), '1 track selected')
        self.assertEqual(editor.source_heading.get_text(), 'Plex library')
        self.assertIn('original music files are not changed', editor.source_description.get_text())
        self.assertIn('each album', editor.edit_instructions.get_text())
        self.assertTrue(editor.entries['title'].get_sensitive())
        self.assertFalse(editor.entries['artist'].get_sensitive())
        self.assertTrue(editor.rows['title'].get_visible())
        self.assertFalse(editor.rows['artist'].get_visible())
        editor.show_all()
        self.assertFalse(editor.rows['artist'].get_visible())
        editor.load(client, 'library', [Item('/one', 'A')])
        self.assertTrue(all(row.get_visible() for row in editor.rows.values()))
        editor.destroy()

    def test_remove_front_cover_keeps_other_pictures(self):
        with tempfile.TemporaryDirectory() as directory:
            for extension in ('mp3', 'flac', 'm4a'):
                with self.subTest(extension=extension):
                    path = Path(directory) / ('song.' + extension)
                    shutil.copyfile(Path('test_fixtures/audio') / ('tone.' + extension), path)
                    write_tags(path, {}, PNG)
                    if extension == 'mp3':
                        audio = File(path)
                        audio.tags.add(APIC(encoding=3, mime='image/png', type=4, desc='Back', data=PNG))
                        audio.save()
                    write_tags(path, {}, False)
                    audio = File(path)
                    if extension == 'mp3':
                        self.assertEqual([picture.type for picture in audio.tags.getall('APIC')], [4])
                    elif extension == 'flac':
                        self.assertFalse(any(picture.type == 3 for picture in audio.pictures))
                    else:
                        self.assertNotIn('covr', audio.tags)

    def test_remove_artwork_is_saved_for_plex(self):
        client = PlexClient('http://127.0.0.1:32400', 'secret')
        client.request = Mock()
        tracks = [Item('/library/metadata/20', 'Song', album_key='/library/metadata/10')]
        self.assertEqual(client.edit_tracks(tracks, {}, False, section='2'), (1, []))
        client.request.assert_called_once_with('DELETE', '/library/metadata/10/thumb')

    def test_editor_marks_art_for_removal(self):
        player = SimpleNamespace(info_button=Mock())
        editor = TagEditor(player)
        editor.load(SimpleNamespace(is_local=True), 'library', [Item('/one', 'A')])
        editor.remove_art()
        self.assertIs(editor.artwork, False)
        self.assertIn('removed', editor.art_label.get_text())
        editor.destroy()


if __name__ == '__main__':
    unittest.main()
