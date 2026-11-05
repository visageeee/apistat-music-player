import tempfile
from datetime import date
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

import session
from player import Player
from plex_client import Item


class Control:
    def __init__(self, active=False):
        self.active = active

    def get_active(self):
        return self.active

    def set_active(self, active):
        self.active = active


class SessionTests(unittest.TestCase):
    def test_time_machine_dates_are_saved_and_validated(self):
        data = {'version': 1, 'time_machine_dates': {'from': '2005-03-02', 'to': '2012-10-20'}}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(session, 'SESSION_PATH', Path(directory) / 'session.json'):
                session.save_session(data)
                self.assertEqual(session.load_session()['time_machine_dates'],
                                 {'from': date(2005, 3, 2), 'to': date(2012, 10, 20)})
                data['time_machine_dates']['to'] = '2012-02-30'
                session.save_session(data)
                self.assertNotIn('time_machine_dates', session.load_session())

    def test_round_trip_keeps_window_panel_queue_and_position(self):
        track = Item('/library/metadata/12', 'Song', artist='Artist', duration=180000)
        album = Item('/library/metadata/10', 'Album', artist='Artist', added_at=1700000000)
        data = {
            'version': 1,
            'window': {'width': 1440, 'height': 900, 'maximized': True},
            'panel': 'now', 'settings_page': 'shortcuts', 'settings_tab': 3,
            'server': 'http://localhost:32400', 'section': '3',
            'history': [session.item_to_data(track)],
            'playback': {'queue': [session.item_to_data(track)], 'index': 0,
                         'position_ms': 42500, 'album': session.item_to_data(album),
                         'shuffle': True, 'repeat': False},
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(session, 'SESSION_PATH', Path(directory) / 'session.json'):
                session.save_session(data)
                restored = session.load_session()
        self.assertEqual(restored['window'], data['window'])
        self.assertEqual(restored['panel'], 'now')
        self.assertEqual(restored['settings_page'], 'shortcuts')
        self.assertEqual(restored['settings_tab'], 3)
        self.assertEqual(restored['playback']['queue'], [track])
        self.assertEqual(restored['playback']['album'], album)
        self.assertEqual(restored['playback']['position_ms'], 42500)
        self.assertEqual(restored['history'], [track])

    def test_invalid_saved_queue_does_not_break_window_restore(self):
        data = {'version': 1, 'window': {'width': 1200, 'height': 750},
                'panel': 'library', 'server': 'http://localhost:32400',
                'playback': {'queue': [{'key': 'invalid', 'title': 'Song'}],
                             'index': 0, 'position_ms': 1000}}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(session, 'SESSION_PATH', Path(directory) / 'session.json'):
                session.save_session(data)
                restored = session.load_session()
        self.assertEqual(restored['window']['width'], 1200)
        self.assertEqual(restored['panel'], 'library')
        self.assertNotIn('playback', restored)

    def test_more_than_five_previous_tracks_survive_restart(self):
        tracks = [Item(f'/library/metadata/{index}', f'Song {index}')
                  for index in range(12)]
        data = {'version': 1, 'server': 'http://localhost:32400',
                'history': [session.item_to_data(track) for track in tracks]}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(session, 'SESSION_PATH', Path(directory) / 'session.json'):
                session.save_session(data)
                restored = session.load_session()
        self.assertEqual(restored['history'], tracks)

    def test_malformed_panel_and_sort_fall_back_safely(self):
        data = {'version': 1, 'panel': [], 'song_sort': []}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(session, 'SESSION_PATH', Path(directory) / 'session.json'):
                session.save_session(data)
                restored = session.load_session()
        self.assertEqual(restored['panel'], 'albums')
        self.assertNotIn('song_sort', restored)

    def test_queue_panel_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(session, 'SESSION_PATH', Path(directory) / 'session.json'):
                session.save_session({'version': 1, 'panel': 'queue'})
                restored = session.load_session()
        self.assertEqual(restored['panel'], 'queue')

    def test_player_restores_queue_paused_at_saved_position(self):
        track = Item('/library/metadata/12', 'Song', duration=180000)
        calls = []
        player = SimpleNamespace(
            session_applied=False,
            saved_session={'server': 'http://localhost:32400', 'playback': {
                'queue': [track], 'album': None, 'index': 0,
                'position_ms': 42500, 'shuffle': True, 'repeat': False}},
            client=SimpleNamespace(address='http://localhost:32400'),
            song_sort='addedAt:desc', shuffle=Control(), repeat=Control(),
            start_track=lambda **options: calls.append(options),
        )
        Player.restore_saved_session(player)
        self.assertEqual(player.queue, [track])
        self.assertEqual(player.index, 0)
        self.assertTrue(player.shuffle.get_active())
        self.assertEqual(calls, [{'resume_paused': True, 'resume_position_ms': 42500}])

    def test_local_track_album_metadata_survives_session_round_trip(self):
        from session import item_from_data, item_to_data
        track = Item('/local/track/abc', 'Song', album_key='/local/album/abc',
                     album_thumb='/local/art/abc/123')
        restored = item_from_data(item_to_data(track))
        self.assertEqual(restored.album_key, track.album_key)
        self.assertEqual(restored.album_thumb, track.album_thumb)

    def test_mismatched_server_does_not_consume_saved_playback(self):
        player = SimpleNamespace(session_applied=False,
                                 saved_session={'server': 'https://saved.example'},
                                 client=SimpleNamespace(address='https://other.example'))
        Player.restore_saved_session(player)
        self.assertFalse(player.session_applied)

    def test_snapshot_uses_last_normal_size_and_open_panel(self):
        track = Item('/library/metadata/12', 'Song', duration=180000)
        player = SimpleNamespace(
            is_maximized=lambda: True, normal_size=(1260, 810),
            content_views=SimpleNamespace(get_visible_child_name=lambda: 'library'),
            settings_stack=SimpleNamespace(get_visible_child_name=lambda: 'main'),
            settings_tabs=SimpleNamespace(get_current_page=lambda: 0),
            client=SimpleNamespace(address='http://localhost:32400'),
            library=SimpleNamespace(get_active_id=lambda: '2'),
            active_playlist=None, song_sort='addedAt:desc', selected_album=None,
            queue=[track], queue_album=None, index=0, playback_position_ms=42500,
            stream_open=True, playing=False, pending_resume_seek_ms=0,
            pipeline=SimpleNamespace(query_position=lambda _format: (True, 0)),
            shuffle=Control(), repeat=Control(),
        )
        snapshot = Player.session_snapshot(player)
        self.assertEqual(snapshot['window'], {'width': 1260, 'height': 810,
                                               'maximized': True})
        self.assertEqual(snapshot['panel'], 'library')
        self.assertNotIn('art_mode', snapshot)
        self.assertEqual(snapshot['playback']['queue'], [session.item_to_data(track)])
        self.assertEqual(snapshot['playback']['position_ms'], 42500)

    def test_pending_resume_seek_uses_saved_position(self):
        seeks = []
        player = SimpleNamespace(
            stream_open=True, pending_resume_seek_ms=42500,
            queue=[Item('/library/metadata/12', 'Song', duration=180000)], index=0,
            pipeline=SimpleNamespace(seek_simple=lambda *args: seeks.append(args) or True),
            mpris=SimpleNamespace(seeked=lambda position: None),
        )
        Player.apply_pending_resume_seek(player)
        self.assertEqual(seeks[0][0], Gst.Format.TIME)
        self.assertEqual(seeks[0][2], 42500 * Gst.MSECOND)
        self.assertEqual(player.pending_resume_seek_ms, 0)
        self.assertEqual(player.playback_position_ms, 42500)


if __name__ == '__main__':
    unittest.main()
