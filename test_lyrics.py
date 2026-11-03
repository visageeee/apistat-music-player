import io
import json
import threading
import time
import unittest
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

from lyrics import (Lyrics, LyricsClient, LyricsLookupError, lookup_lyrics, lookup_lyrics_ovh,
                    parse_lrc, lyrics_error_message)
from player import Player
from plex_client import Item


class LyricsTests(unittest.TestCase):
    def test_lrc_timestamps_are_sorted_and_multiple_times_are_preserved(self):
        lines = parse_lrc('[00:12.5][00:03.20] Second\n[00:01.050] First\n[ar:Artist]')
        self.assertEqual(lines, ((1.05, 'First'), (3.2, 'Second'), (12.5, 'Second')))

    def test_lookup_sends_track_metadata_and_reads_synchronized_lyrics(self):
        requests = []
        payload = json.dumps({'syncedLyrics': '[00:01.00] First\n[00:03.20] Second',
                              'plainLyrics': 'First\nSecond'}).encode()
        def open_request(request, timeout):
            requests.append((request, timeout))
            return io.BytesIO(payload)
        result = lookup_lyrics('A & B', 'Artist', 'Album', 123400, open_request)
        request, timeout = requests[0]
        url = urlsplit(request.full_url)
        self.assertEqual((url.scheme, url.hostname, url.path), ('https', 'lrclib.net', '/api/get'))
        self.assertEqual(parse_qs(url.query), {'track_name': ['A & B'], 'artist_name': ['Artist'],
                                               'album_name': ['Album'], 'duration': ['123']})
        self.assertEqual(timeout, 8)
        self.assertIn('github.com/visageeee/apistat-music-player', request.get_header('User-agent'))
        self.assertEqual(result.text, 'First\nSecond')
        self.assertEqual(result.lines, ((1.0, 'First'), (3.2, 'Second')))

    def test_missing_and_instrumental_tracks_are_distinct(self):
        def missing(request, timeout):
            raise HTTPError(request.full_url, 404, 'Not found', {}, None)
        self.assertIsNone(lookup_lyrics('Song', 'Artist', opener=missing))
        result = lookup_lyrics('Song', 'Artist', opener=lambda *_args, **_kwargs:
                               io.BytesIO(b'{"instrumental": true}'))
        self.assertTrue(result.instrumental)

    def test_requests_are_serialized_and_spaced(self):
        client = LyricsClient()
        starts = []
        def lookup(*_args):
            starts.append(time.monotonic())
            time.sleep(0.03)
            return Lyrics('fixture')
        with patch('lyrics.lookup_lyrics', side_effect=lookup):
            threads = [threading.Thread(target=client.lookup,
                                        args=('Song', 'Artist', '', 0)) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1] - starts[0], 0.30)
        client.close()

    def test_rate_limit_retry_after_is_respected(self):
        client = LyricsClient()
        error = HTTPError('https://lrclib.net/api/get', 429, 'Rate limited',
                          {'Retry-After': '5'}, None)
        with patch('lyrics.lookup_lyrics', side_effect=error) as primary, \
                patch('lyrics.lookup_lyrics_ovh', return_value=Lyrics('fallback', source='lyrics.ovh')), \
                patch('lyrics.time.monotonic', return_value=100.0):
            self.assertEqual(client.lookup('Song', 'Artist', '', 0).source, 'lyrics.ovh')
            client._not_before = 100.0
            self.assertEqual(client.lookup('Song', 'Artist', '', 0).source, 'lyrics.ovh')
        self.assertEqual(primary.call_count, 1)
        self.assertEqual(client._retry_until, 105.0)
        client.close()

    def test_fallback_url_encodes_artist_and_title_and_reads_plain_lyrics(self):
        requests = []
        def open_request(request, timeout):
            requests.append((request, timeout))
            return io.BytesIO(b'{"lyrics": " Line one\\nLine two "}')
        result = lookup_lyrics_ovh('A/B?', 'Artist & Co', open_request)
        request, timeout = requests[0]
        self.assertEqual(urlsplit(request.full_url).path, '/v1/Artist%20%26%20Co/A%2FB%3F')
        self.assertEqual((result.text, result.source, result.lines, timeout),
                         ('Line one\nLine two', 'lyrics.ovh', (), 8))

    def test_fallback_on_missing_primary_and_errors_from_both_sources(self):
        client = LyricsClient()
        with patch('lyrics.lookup_lyrics', return_value=None), \
                patch('lyrics.lookup_lyrics_ovh', return_value=Lyrics('found', source='lyrics.ovh')):
            self.assertEqual(client.lookup('Song', 'Artist').source, 'lyrics.ovh')
        client._not_before = 0
        with patch('lyrics.lookup_lyrics', side_effect=URLError('network')), \
                patch('lyrics.lookup_lyrics_ovh', return_value=None):
            with self.assertRaises(LyricsLookupError) as raised:
                client.lookup('Song', 'Artist')
        self.assertIn('Could not connect to LRCLIB', str(raised.exception))
        self.assertIn('No matching lyrics found on lyrics.ovh', str(raised.exception))
        client.close()

    def test_no_fallback_for_instrumental_or_stale_request(self):
        client = LyricsClient()
        with patch('lyrics.lookup_lyrics', return_value=Lyrics(instrumental=True)), \
                patch('lyrics.lookup_lyrics_ovh') as fallback:
            self.assertTrue(client.lookup('Song', 'Artist').instrumental)
            fallback.assert_not_called()
        client._not_before = 0
        with patch('lyrics.lookup_lyrics', return_value=None), \
                patch('lyrics.lookup_lyrics_ovh') as fallback:
            checks = iter((True, True, False))
            self.assertIsNone(client.lookup('Song', 'Artist', valid=lambda: next(checks)))
            fallback.assert_not_called()
        client.close()

    def test_current_line_follows_seeks_in_both_directions(self):
        buffer = Gtk.TextBuffer()
        tag = buffer.create_tag('current-lyric')
        player = SimpleNamespace(
            lyrics_buffer=buffer, lyrics_highlight=tag,
            lyrics_text=SimpleNamespace(scroll_to_iter=Mock()),
            lyrics_status=SimpleNamespace(set_text=Mock()),
            lyrics_source=SimpleNamespace(set_text=Mock()),
            lyrics_content=SimpleNamespace(set_visible_child_name=Mock()),
            seek=SimpleNamespace(get_value=lambda: 0))
        player.update_lyrics_position = lambda seconds: Player.update_lyrics_position(player, seconds)
        Player.show_lyrics_result(player, Lyrics('First\nSecond', ((1.0, 'First'), (3.2, 'Second'))))
        Player.update_lyrics_position(player, 4.0)
        self.assertEqual(player.lyrics_current_line, 1)
        self.assertTrue(buffer.get_iter_at_offset(6).has_tag(tag))
        Player.update_lyrics_position(player, 1.5)
        self.assertEqual(player.lyrics_current_line, 0)
        self.assertTrue(buffer.get_iter_at_offset(0).has_tag(tag))
        self.assertFalse(buffer.get_iter_at_offset(6).has_tag(tag))

    def test_old_track_lookup_is_ignored_after_track_changes(self):
        jobs = []
        player = SimpleNamespace(
            index=0, queue=[Item('/track/1', 'First', artist='Artist')],
            queue_client=SimpleNamespace(address='http://plex.test'),
            lyrics_generation=0, lyrics_request_key=None, lyrics_cache=OrderedDict(), closed=False,
            lyrics_track_label=SimpleNamespace(set_text=Mock()),
            lyrics_status=SimpleNamespace(set_text=Mock()),
            lyrics_source=SimpleNamespace(set_text=Mock()),
            lyrics_buffer=SimpleNamespace(set_text=Mock()),
            set_lyrics_message=Mock(),
            update_lyrics_track_info=Mock(),
            async_work=lambda work, done, valid, failed: jobs.append((work, done, valid)))
        Player.load_current_lyrics(player)
        self.assertTrue(jobs[0][2]())
        player.lyrics_generation += 1
        self.assertFalse(jobs[0][2]())

    def test_refresh_bypasses_cache_and_invalidates_previous_lookup(self):
        jobs = []
        track = Item('/track/1', 'First', artist='Artist')
        key = ('http://plex.test', track.key, track.title, track.artist,
               track.album, track.duration)
        player = SimpleNamespace(
            index=0, queue=[track], queue_client=SimpleNamespace(address='http://plex.test'),
            lyrics_generation=0, lyrics_request_key=None,
            lyrics_cache=OrderedDict([(key, Lyrics('old'))]), closed=False,
            lyrics_track_label=SimpleNamespace(set_text=Mock()),
            lyrics_status=SimpleNamespace(set_text=Mock()),
            lyrics_source=SimpleNamespace(set_text=Mock()),
            lyrics_buffer=SimpleNamespace(set_text=Mock()),
            set_lyrics_message=Mock(),
            update_lyrics_track_info=Mock(),
            show_lyrics_result=Mock(),
            async_work=lambda work, done, valid, failed: jobs.append((work, done, valid)))
        Player.load_current_lyrics(player)
        player.show_lyrics_result.assert_called_once()
        Player.load_current_lyrics(player, force=True)
        self.assertNotIn(key, player.lyrics_cache)
        self.assertTrue(jobs[0][2]())
        Player.load_current_lyrics(player, force=True)
        self.assertFalse(jobs[0][2]())
        self.assertTrue(jobs[1][2]())

    def test_missing_lyrics_and_lookup_errors_offer_search(self):
        jobs = []
        player = SimpleNamespace(
            index=0, queue=[Item('/track/1', 'Song', artist='Artist')],
            queue_client=SimpleNamespace(address='http://plex.test'),
            lyrics_generation=0, lyrics_request_key=None, lyrics_cache=OrderedDict(), closed=False,
            lyrics_track_label=SimpleNamespace(set_text=Mock()),
            lyrics_status=SimpleNamespace(set_text=Mock()),
            lyrics_source=SimpleNamespace(set_text=Mock()),
            lyrics_buffer=SimpleNamespace(set_text=Mock()), set_lyrics_message=Mock(),
            update_lyrics_track_info=Mock(),
            lyrics_client=SimpleNamespace(lookup=Mock(side_effect=HTTPError(
                'https://lrclib.net/api/get', 429, 'Rate limited', {}, None))),
            async_work=lambda work, done, valid, failed: jobs.append((work, done, failed)))
        Player.load_current_lyrics(player)
        player.lyrics_track_label.set_text.assert_called_with('Lyrics')
        player.update_lyrics_track_info.assert_called_once_with(player.queue[0])
        jobs[0][1](jobs[0][0]())
        player.set_lyrics_message.assert_called_with(
            'LRCLIB is receiving too many requests. Wait a moment, then refresh.', search=True)
        Player.show_lyrics_result(player, None)
        player.set_lyrics_message.assert_called_with(
            'No lyrics found on LRCLIB or lyrics.ovh.', search=True)

    def test_lookup_errors_describe_the_cause_without_exposing_url(self):
        secret_url = 'https://lrclib.net/?token=secret'
        cases = [
            (HTTPError(secret_url, 503, 'error', {}, None), 'HTTP 503'),
            (HTTPError(secret_url, 403, 'error', {}, None), 'HTTP 403'),
            (URLError(TimeoutError()), 'timed out'),
            (URLError('DNS failure'), 'Could not connect'),
            (ValueError('bad content'), 'invalid response'),
        ]
        for error, expected in cases:
            message = lyrics_error_message(error)
            self.assertIn(expected, message)
            self.assertNotIn('secret', message)

    def test_track_information_reuses_art_and_invalidates_old_load(self):
        loads = []
        player = SimpleNamespace(
            lyrics_track_info=SimpleNamespace(hide=Mock(), show_all=Mock(), set_no_show_all=Mock()),
            lyrics_song_title=SimpleNamespace(set_text=Mock()),
            lyrics_artist=SimpleNamespace(set_text=Mock()),
            lyrics_album=SimpleNamespace(set_text=Mock()),
            lyrics_cover=object(), lyrics_art_key=None, queue_client=object(),
            queue_album=None, closed=False, set_placeholder_art=Mock(),
            load_art=lambda *args: loads.append(args))
        first = Item('/1', 'First', artist='Artist', thumb='/album/art')
        Player.update_lyrics_track_info(player, first)
        self.assertTrue(loads[0][4]())
        Player.update_lyrics_track_info(player, Item('/2', 'Second', artist='Artist', album='Second album',
                                                    thumb='/album/art'))
        self.assertEqual(len(loads), 1)
        player.lyrics_song_title.set_text.assert_called_with('Second')
        player.lyrics_album.set_text.assert_called_with('Second album')
        Player.update_lyrics_track_info(player)
        self.assertFalse(loads[0][4]())
        player.lyrics_track_info.hide.assert_called_once()

    def test_google_search_encodes_track_metadata(self):
        player = SimpleNamespace(index=0, queue=[Item('/track/1', 'A & B', artist='Artist')])
        with patch('player.Gtk.show_uri_on_window') as show:
            Player.google_current_lyrics(player)
        url = urlsplit(show.call_args.args[1])
        self.assertEqual(url.hostname, 'www.google.com')
        self.assertEqual(parse_qs(url.query), {'q': ['Artist A & B lyrics']})

    def test_control_scroll_zooms_and_plain_scroll_passes_through(self):
        changes = []
        player = SimpleNamespace(lyrics_zoom_remainder=0.0, change_lyrics_zoom=changes.append)
        plain = SimpleNamespace(state=0, direction=Gdk.ScrollDirection.UP)
        self.assertFalse(Player.lyrics_zoom_scroll(player, None, plain))
        up = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK, direction=Gdk.ScrollDirection.UP)
        self.assertTrue(Player.lyrics_zoom_scroll(player, None, up))
        smooth = SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK,
                                 direction=Gdk.ScrollDirection.SMOOTH,
                                 get_scroll_deltas=lambda: (True, 0, 0.6))
        Player.lyrics_zoom_scroll(player, None, smooth)
        Player.lyrics_zoom_scroll(player, None, smooth)
        self.assertEqual(changes, [1, -1])

    def test_lyrics_page_scroll_is_only_intercepted_for_lyrics(self):
        zoom = Mock(return_value=True)
        player = SimpleNamespace(lyrics_zoom_scroll=zoom)
        view = SimpleNamespace(get_visible_child_name=lambda: 'lyrics')
        event = object()
        self.assertTrue(Player.lyrics_view_scroll(player, view, event))
        zoom.assert_called_once_with(view, event)
        view.get_visible_child_name = lambda: 'albums'
        self.assertFalse(Player.lyrics_view_scroll(player, view, event))

    def test_song_link_opens_the_full_library_filtered_to_the_song(self):
        search = Mock()
        show = Mock()
        player = SimpleNamespace(client=object(), index=0,
                                 queue=[Item('/track/1', 'Song', artist='Artist')],
                                 show_full_music_library=show, library_search=search)
        Player.show_lyrics_song(player)
        show.assert_called_once()
        search.set_text.assert_called_once_with('Song')

    def test_long_lines_and_zoom_increase_requested_lyrics_width(self):
        current = ['']
        layout = SimpleNamespace(set_font_description=Mock(),
                                 set_text=lambda text, _length: current.__setitem__(0, text),
                                 get_pixel_size=lambda: (len(current[0]) * 20, 20))
        font = SimpleNamespace(set_absolute_size=Mock())
        context = SimpleNamespace(get_font=lambda _state: SimpleNamespace(copy=lambda: font))
        player = SimpleNamespace(
            lyrics_text=SimpleNamespace(create_pango_layout=lambda _text: layout,
                                        get_style_context=lambda: context),
            text_size=18, lyrics_zoom=2.0, lyrics_measure_lines=('short', 'x' * 40),
            lyrics_group=SimpleNamespace(set_target_width=Mock()))
        Player.update_lyrics_width(player)
        player.lyrics_group.set_target_width.assert_called_once_with(800 + 48 + 440 + 28)
        self.assertGreater(font.set_absolute_size.call_args.args[0], 0)


if __name__ == '__main__':
    unittest.main()
