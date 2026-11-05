import unittest
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lastfm import LastFM, LastFMError
from plex_client import Item
from time_machine import albums_for_history, match_history, partition_history, timestamps
from time_machine_view import TimeMachineView


class TimeMachineTests(unittest.TestCase):
    def test_paged_history_includes_completed_scrobbles_and_filters_boundaries(self):
        api = LastFM('key', 'secret')
        api.request = Mock(side_effect=[
            {'recenttracks': {'@attr': {'totalPages': '2'}, 'track': [
                {'artist': {'#text': 'Artist'}, 'album': {'#text': 'Album'},
                 'name': 'Track', 'date': {'uts': '100'}},
                {'artist': {'#text': 'Artist'}, 'name': 'Now playing', '@attr': {'nowplaying': 'true'}},
                {'artist': {'#text': 'Artist'}, 'name': 'Before', 'date': {'uts': '99'}}]}},
            {'recenttracks': {'@attr': {'totalPages': '2'}, 'track': {
                'artist': {'#text': 'Artist'}, 'name': 'Other', 'date': {'uts': '199'}}}},
        ])
        progress = Mock()
        result = api.listening_history('user', 100, 200, 'session', progress=progress)
        self.assertEqual([item['title'] for item in result], ['Track', 'Other'])
        self.assertEqual(api.request.call_args_list[0].args[1],
                         {'user': 'user', 'from': 99, 'to': 200, 'limit': 200,
                          'page': 1, 'sk': 'session'})
        self.assertEqual(api.request.call_args_list[1].args[1]['page'], 2)
        progress.assert_called_with(2, 2, 2)

    def test_count_uses_one_result_and_validates_response(self):
        api = LastFM('key', 'secret')
        api.request = Mock(return_value={'recenttracks': {'@attr': {'total': '4321'}}})
        self.assertEqual(api.listening_history_count('user', 100, 200, 'session'), 4321)
        self.assertEqual(api.request.call_args.args[1],
                         {'user': 'user', 'from': 99, 'to': 200, 'limit': 1,
                          'page': 1, 'sk': 'session'})
        for response in ({}, {'recenttracks': {'@attr': {'total': '-1'}}}):
            api.request.return_value = response
            with self.assertRaises(LastFMError):
                api.listening_history_count('user', 100, 200)

    def test_changing_dates_invalidates_an_inflight_count(self):
        pending = []
        session = {'api_key': 'k', 'secret': 's', 'username': 'user', 'session': 'token'}
        player = SimpleNamespace(lastfm_session=session, lastfm_generation=0, closed=False,
                                 async_work=lambda work, done, valid, failed:
                                 pending.append((work, done, valid)))
        panel = SimpleNamespace(player=player, selected_dates=lambda: (date(2020, 1, 1), date(2020, 1, 31)),
                                generation=0, checked_range=None, show_button=Mock(), go=Mock(),
                                play=Mock(), save_playlist=Mock(), queue_random=Mock(), status=Mock(), source=None,
                                start_search_effect=Mock(), stop_search_effect=Mock())
        with patch('lastfm.LastFM.listening_history_count', return_value=42):
            TimeMachineView.count_listens(panel)
            self.assertTrue(pending[0][2]())
            TimeMachineView.date_changed(panel)
            self.assertFalse(pending[0][2]())
            self.assertIsNone(panel.checked_range)

    def test_future_range_does_not_query_lastfm(self):
        tomorrow = date.today().replace(year=date.today().year + 1)
        session = {'api_key': 'k', 'secret': 's', 'username': 'user', 'session': 'token'}
        player = SimpleNamespace(lastfm_session=session, async_work=Mock())
        panel = SimpleNamespace(player=player, status=Mock(),
                                selected_dates=lambda: (tomorrow, tomorrow))
        TimeMachineView.count_listens(panel)
        from time_machine_view import _FUTURE_ERRORS
        self.assertIn(panel.status.set_text.call_args.args[0], _FUTURE_ERRORS)
        player.async_work.assert_not_called()

    def test_date_field_scroll_and_edit(self):
        from time_machine_view import DateField
        from gi.repository import Gdk
        field = DateField(1, 12, 4, 2)
        field.set_text('09')
        self.assertEqual(field.get_value_as_int(), 9)
        field.scroll_value(field, SimpleNamespace(direction=Gdk.ScrollDirection.UP))
        self.assertEqual(field.get_text(), '10')
        field.scroll_value(field, SimpleNamespace(direction=Gdk.ScrollDirection.DOWN))
        self.assertEqual(field.get_text(), '09')

    def test_display_event_window_routes_scroll_to_month(self):
        from time_machine_view import DateDial
        from gi.repository import Gdk
        dial = DateDial('FROM', date(2020, 2, 1), 'dial-start', lambda *_: None)
        field = dial.fields['MONTH']
        dial.scroll_controllers[0].emit('scroll', 0.0, -1.0)
        self.assertEqual(field.get_value_as_int(), 3)
        dial.scroll_controllers[0].emit('scroll', 0.0, 1.0)
        self.assertEqual(field.get_value_as_int(), 2)
        dial.destroy()

    def test_history_stops_when_cancelled_and_rejects_bad_response(self):
        api = LastFM('key', 'secret')
        api.request = Mock(return_value={'recenttracks': {'@attr': {'totalPages': '2'}, 'track': []}})
        self.assertIsNone(api.listening_history('user', 1, 2, valid=lambda: False))
        api.request.assert_not_called()
        api.request.return_value = {'recenttracks': []}
        with self.assertRaises(LastFMError):
            api.listening_history('user', 1, 2)

    def test_library_matching_preserves_listens_without_guessing_wrong_album(self):
        one = Item('/local/1', 'Song', artist='Artist', album='One', album_key='/local/a')
        two = Item('/local/2', 'Song', artist='Artist', album='Two', album_key='/local/b')
        other = Item('/local/3', 'Only', artist='Artist', album='One', album_key='/local/a')
        history = [{'artist': ' artist ', 'title': 'SONG', 'album': 'One'},
                   {'artist': 'Artist', 'title': 'Song', 'album': 'One'},
                   {'artist': 'Artist', 'title': 'Song', 'album': ''},
                   {'artist': 'Artist', 'title': 'Only', 'album': ''},
                   {'artist': 'Artist', 'title': 'Only', 'album': 'Different'}]
        matched, missing = match_history(history, [one, two, other])
        self.assertEqual(matched, [one, one, other])
        self.assertEqual(missing, 2)
        self.assertEqual([album.key for album in albums_for_history(matched)], ['/local/a'])

    def test_unmatched_history_retains_records_and_repeated_listens(self):
        song = Item('/track/1', 'Found', artist='Artist', album='Album')
        found = {'artist': 'Artist', 'album': 'Album', 'title': 'Found', 'timestamp': 10}
        lost = {'artist': 'Other', 'album': 'Unknown', 'title': 'Missing', 'timestamp': 20}
        matched, missing = partition_history([found, lost, lost], [song])
        self.assertEqual(matched, [song])
        self.assertEqual(missing, [lost, lost])
        self.assertEqual(match_history([found, lost, lost], [song]), ([song], 2))

    def test_date_range_uses_inclusive_days(self):
        start, end = timestamps(date(2020, 2, 1), date(2020, 2, 29))
        self.assertGreater(end, start)
        with self.assertRaises(ValueError):
            timestamps(date(2020, 2, 29), date(2020, 2, 1))

    def test_panel_explores_history_and_opens_an_album(self):
        song = Item('/local/1', 'Song', artist='Artist', album='Album', album_key='/local/album')
        client = object()
        def scroll(child):
            widget = Gtk.ScrolledWindow()
            widget.add(child)
            return widget
        def table(model, titles):
            view = Gtk.TreeView(model=model)
            for index, title in enumerate(titles):
                view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index))
            return view
        player = SimpleNamespace(album_spacing=12, album_margin=20, album_art_size=120,
                                 lastfm_session={'api_key': 'k', 'secret': 's',
                                                 'session': 'session', 'username': 'user'},
                                 lastfm_generation=0, closed=False, client=client,
                                 library=SimpleNamespace(get_active_id=lambda: 'library'),
                                 song_catalog=[song], song_catalog_source=(client, 'library', None, None),
                                 scroll=scroll, table=table,
                                 async_work=lambda work, done, valid, failed: done(work()),
                                 set_placeholder_art=lambda _image, _size: None,
                                 load_art=lambda *_args: None,
                                 song_column_value=lambda _song, _field: '3:00',
                                 set_art_size=Mock(), zoom_art=Mock(return_value=False),
                                 clear_remote_queue=Mock(), start_track=Mock(), enqueue_tracks=Mock(),
                                 show_context_menu=Mock(), show_lost_time_info=Mock())
        panel = TimeMachineView(player)
        panel.widget.show_all()
        self.assertTrue(panel.go.get_visible())
        self.assertFalse(panel.track_sort_bar.get_visible())
        self.assertEqual(panel.go.get_label(), 'ENGAGE')
        for button in (panel.play, panel.save_playlist, panel.queue_random):
            self.assertFalse(button.get_visible())
        session = player.lastfm_session
        player.lastfm_session = None
        panel.on_show()
        self.assertFalse(panel.dial_panel.get_sensitive())
        self.assertTrue(panel.settings_link.get_visible())
        self.assertEqual(panel.status.get_text(), 'Going back in time requires a last.fm account.')
        player.lastfm_session = session
        panel.on_show()
        self.assertTrue(panel.dial_panel.get_sensitive())
        self.assertFalse(panel.settings_link.get_visible())
        self.assertTrue(panel.engage_ready())
        panel.go.set_label('SHOW LISTENS')
        self.assertFalse(panel.engage_ready())
        panel.go.set_label('ENGAGE')
        grip = Mock()
        self.assertTrue(panel.start_column_resize(grip, SimpleNamespace(button=1, x_root=100), 'artist'))
        self.assertTrue(panel.move_column_resize(grip, SimpleNamespace(x_root=140)))
        self.assertEqual(panel.track_columns['artist'].get_fixed_width(), 160)
        self.assertTrue(panel.finish_column_resize(grip, SimpleNamespace(button=1)))
        self.assertIsNone(panel.resize_state)
        self.assertIn('selected', panel.selection_provider.to_string())
        panel.start_search_effect()
        self.assertTrue(panel.search_effect.get_visible())
        self.assertIn('SCANNING', panel.search_effect.get_text())
        panel.advance_search_effect()
        self.assertIn('MEMORY STRANDS', panel.search_effect.get_text())
        panel.stop_search_effect()
        self.assertFalse(panel.search_effect.get_visible())
        self.assertIsNone(panel.search_timer)
        with patch('lastfm.LastFM.listening_history_count', return_value=3) as count, \
                patch('lastfm.LastFM.listening_history', return_value=[
                    {'artist': 'Artist', 'album': 'Album', 'title': 'Song', 'timestamp': 1},
                    {'artist': 'Other', 'album': 'Gone', 'title': 'Missing', 'timestamp': 2},
                    {'artist': 'Other', 'album': 'Gone', 'title': 'Missing', 'timestamp': 3}]) as history:
            panel.engage_pressed()
            count.assert_called_once()
            history.assert_not_called()
            self.assertTrue(panel.go.get_visible())
            self.assertEqual(panel.go.get_label(), 'SHOW 3 LISTENS')
            self.assertEqual(panel.tracks, [])
            panel.engage_pressed()
            history.assert_called_once()
            self.assertEqual(panel.go.get_label(), 'ENGAGE')
        self.assertEqual(panel.tracks, [song])
        self.assertEqual(panel.group_overlay.results, [song])
        self.assertEqual(panel.group_overlay.group_ends, {0: 1})
        self.assertTrue(panel.gutter.get_resizable())
        self.assertEqual([column.get_title() for column in panel.list.get_columns()[1:]],
                         ['Name', 'Artist', 'Year', 'Time'])
        self.assertEqual(set(panel.sort_buttons), {'title', 'artist', 'year', 'duration'})
        for button in (panel.play, panel.save_playlist, panel.queue_random):
            self.assertTrue(button.get_visible())
        self.assertEqual(len(panel.albums), 1)
        self.assertEqual(len(panel.grid.get_children()), 1)
        wall = Gtk.Box()
        wall.render_surface = Gtk.EventBox()
        wall.scrollbar = Gtk.Scrollbar()
        wall.set_content_top_inset = Mock()
        wall.set_albums = Mock()
        wall.toggle_album = Mock()
        wall.shutdown = Mock()
        player.gpu_wall_enabled = True
        with patch('gpu_album_wall.GPUAlbumWall', return_value=wall) as gpu:
            panel.render_albums()
        self.assertEqual(panel.album_stack.get_visible_child_name(), 'gpu')
        gpu.assert_called_once()
        self.assertFalse(gpu.call_args.kwargs['load_more'])
        wall.set_albums.assert_called_with(client, panel.albums, reset=True)
        panel.gpu_album_pressed(panel.albums[0], SimpleNamespace(button=1), 0, 0)
        wall.toggle_album.assert_called_once_with(panel.albums[0])
        panel.gpu_album_pressed(panel.albums[0], SimpleNamespace(button=3), 0, 0)
        self.assertIs(player.show_context_menu.call_args.kwargs['gpu_wall'], wall)
        self.assertIn('2 lost to time', panel.status.get_text())
        self.assertTrue(panel.status.emit('activate-link', 'apistat:lost'))
        player.show_lost_time_info.assert_called_once_with(panel.lost_listens)
        self.assertEqual([entry['timestamp'] for entry in panel.lost_listens], [2, 3])
        panel.enqueue_random()
        player.enqueue_tracks.assert_called_once_with([song])
        panel.open_album(panel.albums[0])
        self.assertTrue(panel.track_sort_bar.get_visible())
        self.assertTrue(all(button.get_visible() for button, _label in panel.sort_buttons.values()))
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        self.assertEqual(panel.views.get_visible_child_name(), 'tracks')
        self.assertEqual(len(panel.store), 2)
        selection = panel.list.get_selection()
        selection.select_path(Gtk.TreePath.new_from_indices([0]))
        self.assertFalse(selection.path_is_selected(Gtk.TreePath.new_from_indices([0])))
        selection.select_path(Gtk.TreePath.new_from_indices([1]))
        self.assertTrue(selection.path_is_selected(Gtk.TreePath.new_from_indices([1])))
        self.assertEqual(panel.selected_track_indices(panel.list), [0])
        panel.play_track(0)
        player.start_track.assert_called_once_with()
        panel.start_dial.fields['DAY'].set_value(2)
        self.assertEqual(panel.go.get_label(), 'ENGAGE')
        self.assertEqual(panel.source, (client, 'library'))
        self.assertEqual(panel.tracks, [song])
        self.assertTrue(panel.play.get_sensitive())
        self.assertTrue(panel.save_playlist.get_sensitive())
        self.assertTrue(panel.queue_random.get_sensitive())
        original_dates = panel.result_dates
        self.assertEqual(panel.playlist_default_name(),
                         f'{original_dates[0].isoformat()} – {original_dates[1].isoformat()}')
        with patch('lastfm.LastFM.listening_history_count', return_value=0):
            panel.count_listens()
        self.assertIsNone(panel.source)
        self.assertEqual(panel.tracks, [])
        panel.widget.destroy()

    def test_loaded_lastfm_session_refreshes_time_machine(self):
        from player import Player
        session = {'username': 'linked-user'}
        player = SimpleNamespace(lastfm_generation=0, time_machine=Mock(),
                                 lastfm_unlink_button=Mock(), lastfm_status=Mock())
        player.lastfm_work = lambda _work, done, _generation: done(session)
        Player.initialize_lastfm(player)
        self.assertEqual(player.lastfm_session, session)
        player.time_machine.on_show.assert_called_once_with()

    def test_track_list_groups_history_and_keeps_duplicates(self):
        from library_album_view import group_songs_by_album
        a = Item('/a', 'A', album_key='album-1')
        b = Item('/b', 'B', album_key='album-2')
        c = Item('/c', 'C', album_key='album-1')
        self.assertEqual(group_songs_by_album([a, b, c, a]), [a, c, a, b])

    def test_track_drag_preserves_multiple_selected_rows(self):
        from drag_payload import decode_track_keys
        songs = [Item('/library/metadata/1', 'A'), Item('/library/metadata/2', 'B')]
        player = SimpleNamespace(client=object(), time_drag_candidates=[0, 1])
        panel = SimpleNamespace(player=player, display_tracks=songs)
        selection = Mock()
        view = SimpleNamespace(get_selection=lambda: selection, create_row_drag_icon=lambda _path: None)
        TimeMachineView.track_drag_begin(panel, view, None)
        self.assertEqual(player.time_drag_tracks, tuple(songs))
        payload = Mock()
        payload.get_target.return_value = 'application/x-plex-song-key'
        TimeMachineView.track_drag_data(panel, view, None, payload, 0, 0)
        self.assertEqual(decode_track_keys(payload.set.call_args.args[2]), ['/library/metadata/1', '/library/metadata/2'])
        TimeMachineView.track_drag_end(panel)
        self.assertIsNone(player.time_drag_tracks)

    def test_random_queue_samples_up_to_50_distinct_tracks_from_period(self):
        songs = [Item(f'/track/{i}', f'Track {i}') for i in range(70)]
        client = object()
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: '1'),
                                 lastfm_session={'username': 'user'}, enqueue_tracks=Mock())
        panel = SimpleNamespace(player=player, source=(client, '1'), account='user',
                                tracks=songs + songs[:10], status=Mock())
        TimeMachineView.enqueue_random(panel)
        chosen = player.enqueue_tracks.call_args.args[0]
        self.assertEqual(len(chosen), 50)
        self.assertEqual(len({song.key for song in chosen}), 50)
        panel.source = (object(), '1')
        TimeMachineView.enqueue_random(panel)
        player.enqueue_tracks.assert_called_once()

    def test_history_playback_uses_current_library_and_keeps_duplicates(self):
        song = Item('/track', 'Song')
        client = object()
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: '1'),
                                 lastfm_session={'username': 'user'},
                                 clear_remote_queue=Mock(), start_track=Mock(), enqueue_tracks=Mock())
        panel = SimpleNamespace(player=player, source=(client, '1'), account='user', display_tracks=[song, song])
        TimeMachineView.play_track(panel, 1)
        self.assertEqual(player.queue, [song, song])
        self.assertEqual(player.index, 1)
        self.assertIs(player.queue_client, client)
        player.start_track.assert_called_once_with()
        panel.source = (object(), '1')
        TimeMachineView.play_track(panel, 0)
        player.start_track.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
