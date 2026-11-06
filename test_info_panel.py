import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from player import Player
from plex_client import Item


class InfoPanelTests(unittest.TestCase):
    def test_panel_builds_and_starts_closed(self):
        overlay = Gtk.Overlay()
        player = SimpleNamespace(content_overlay=overlay,
                                 icon_button=lambda *_args: Gtk.Button(),
                                 info_reveal_finished=Mock(),
                                 info_resize_handle=lambda _edge: Gtk.Box())
        with patch('player.load_info_panel_width', return_value=360):
            Player.build_info_panel(player)
        self.assertFalse(player.info_revealer.get_reveal_child())
        self.assertEqual(player.info_revealer.get_transition_type(),
                         Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.assertFalse(player.info_content_stack.get_hhomogeneous())
        self.assertEqual(player.info_artist_name.get_xalign(), 0.5)
        self.assertEqual(player.info_artist_name.get_name(), 'info-artist-name')
        overlay.destroy()

    def test_editor_panel_reports_requested_width_in_both_modes(self):
        overlay = Gtk.Overlay()
        player = SimpleNamespace(content_overlay=overlay, info_button=Gtk.ToggleButton(),
                                 icon_button=lambda *_args: Gtk.Button(), info_reveal_finished=Mock(),
                                 info_resize_handle=lambda _edge: Gtk.EventBox(width_request=10), closed=False)
        with patch('player.load_info_panel_width', return_value=300):
            Player.build_info_panel(player)
        overlay.show_all()
        player.info_content_stack.set_visible_child_name('edit')
        for local in (True, False):
            player.info_tag_editor.load(SimpleNamespace(is_local=local), 'library',
                                        [Item('/track', 'Song')])
            player.info_panel.set_size_request(240, -1)
            minimum, natural = player.info_panel.get_preferred_width_for_height(700)
            self.assertEqual((minimum, natural), (240, 240))
        overlay.destroy()

    def test_lost_list_uses_info_panel_and_stops_when_closed(self):
        overlay = Gtk.Overlay()
        player = SimpleNamespace(content_overlay=overlay, info_button=Gtk.ToggleButton(),
                                 icon_button=lambda *_args: Gtk.Button(),
                                 info_reveal_finished=Mock(),
                                 info_resize_handle=lambda _edge: Gtk.Box(), closed=False,
                                 load_current_info=Mock())
        with patch('player.load_info_panel_width', return_value=360):
            Player.build_info_panel(player)
        overlay.show_all()
        player.info_button.connect('toggled', lambda button: Player.info_toggled(player, button))
        records = [{'title': f'Song {index}', 'artist': 'Artist', 'album': 'Album', 'timestamp': 10}
                   for index in range(200)]
        Player.show_lost_time_info(player, records)
        self.assertEqual(player.info_mode, 'lost')
        self.assertEqual(player.info_content_stack.get_visible_child_name(), 'lost')
        self.assertTrue(player.info_revealer.get_reveal_child())
        player.load_current_info.assert_not_called()
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        self.assertEqual(len(player.info_lost_store), 200)
        self.assertEqual(player.info_lost_store[0][0:3], ['Song 0', 'Artist', 'Album'])
        player.info_button.set_active(False)
        self.assertEqual(player.info_mode, 'track')
        player.info_button.set_active(True)
        self.assertEqual(player.info_content_stack.get_visible_child_name(), 'track')
        player.load_current_info.assert_called_once_with()
        overlay.destroy()

    def test_loading_lost_list_stops_after_panel_changes(self):
        store = Gtk.ListStore(str, str, str, str)
        player = SimpleNamespace(info_generation=0, info_pending_update=None, info_target=None,
                                 info_artist_name=Mock(), info_lost_count=Mock(),
                                 info_lost_store=store, info_content_stack=Mock(),
                                 info_button=Mock(), closed=False)
        player.info_button.get_active.return_value = True
        records = [{'title': 'Song', 'artist': 'Artist'} for _ in range(200)]
        with patch('player.GLib.idle_add') as idle:
            Player.show_lost_time_info(player, records)
        append = idle.call_args.args[0]
        self.assertTrue(append())
        self.assertEqual(len(store), 150)
        player.info_mode = 'track'
        self.assertFalse(append())
        self.assertEqual(len(store), 150)

    def test_track_details_are_loaded_and_older_requests_are_invalidated(self):
        track = Item('/library/metadata/1', 'Song', artist='Artist', codec='flac')
        client = Mock()
        client.track_details.return_value = ({'codec': 'flac', 'sample_rate': '44100'}, 'First.\nSecond.')
        jobs = []
        player = SimpleNamespace(
            info_generation=0,
            info_source_label=Mock(), info_track_title=Mock(), info_artist_name=Mock(),
            info_file=Gtk.Label(), info_file_grid=Gtk.Grid(), info_biography=Mock(), queue_client=client, queue=[track],
            index=0, closed=False, info_revealer=SimpleNamespace(get_reveal_child=lambda: True))
        player.async_work = lambda work, done, valid, *args: jobs.append((work, done, valid))
        Player.load_current_info(player)
        self.assertEqual(len(jobs), 1)
        jobs[0][1](jobs[0][0]())
        player.info_biography.set_text.assert_called_with('First.\n\nSecond.')
        self.assertEqual(player.info_file_grid.get_child_at(0, 0).get_text(), 'Format')
        self.assertEqual(player.info_file_grid.get_child_at(1, 0).get_text(), 'flac')
        self.assertEqual(player.info_file_grid.get_child_at(0, 1).get_text(), 'Sample rate')
        self.assertEqual(player.info_file_grid.get_child_at(1, 1).get_text(), '44100 Hz')
        self.assertEqual(player.info_file_grid.get_child_at(0, 0).get_name(), 'info-field-name')
        old_valid = jobs[0][2]
        Player.load_current_info(player)
        self.assertFalse(old_valid())

    def test_plex_description_is_displayed(self):
        client = Mock()
        client.track_details.return_value = ({}, 'Plex description')
        player = SimpleNamespace(
            info_generation=0, info_source=Mock(), info_source_label=Mock(),
            info_track_title=Mock(), info_artist_name=Mock(), info_file=Gtk.Label(),
            info_file_grid=Gtk.Grid(),
            info_biography=Mock(), queue_client=client,
            queue=[Item('/library/metadata/1', 'Song', artist='Artist')], index=0,
            closed=False, info_revealer=SimpleNamespace(get_reveal_child=lambda: True))
        player.async_work = lambda work, done, valid, *args: done(work()) if valid() else None
        Player.load_current_info(player)
        player.info_biography.set_text.assert_called_with('Plex description')
        player.info_source_label.set_text.assert_called_with('Artist information from Plex')

    def test_local_artist_lookup_is_on_demand_and_updates_after_file_info(self):
        client = Mock(is_local=True)
        client.track_details.return_value = ({'codec': 'flac'}, '')
        client.artist_description.return_value = ('A biography.', 'https://en.wikipedia.org/wiki/Artist')
        jobs = []
        player = SimpleNamespace(
            info_generation=0, info_source_label=Mock(), info_track_title=Mock(),
            info_artist_name=Mock(), info_file=Gtk.Label(), info_file_grid=Gtk.Grid(),
            info_biography=Mock(), queue_client=client,
            queue=[Item('/local/track/1', 'Song', artist='Artist')], index=0,
            closed=False, info_revealer=SimpleNamespace(get_reveal_child=lambda: True))
        player.async_work = lambda work, done, valid, *args: jobs.append((work, done, valid))
        Player.load_current_info(player)
        client.artist_description.assert_not_called()
        jobs[0][1](jobs[0][0]())
        self.assertEqual(len(jobs), 2)
        jobs[1][1](jobs[1][0]())
        client.artist_description.assert_called_once_with('Artist', '')
        player.info_biography.set_text.assert_called_with('A biography.')
        player.info_source_label.set_text.assert_called_with('Wikipedia · https://en.wikipedia.org/wiki/Artist')

    def test_overlay_player_bar_does_not_cover_info_panel_actions(self):
        info = Gtk.Revealer()
        bar = Mock()
        bar.get_allocated_height.return_value = 96
        bar.get_visible.return_value = True
        player = SimpleNamespace(player_bar=bar, frosted_player_bar=True, info_revealer=info)
        Player.update_queue_bottom_inset(player)
        self.assertEqual(info.get_margin_bottom(), 96)
        player.frosted_player_bar = False
        Player.update_queue_bottom_inset(player)
        self.assertEqual(info.get_margin_bottom(), 0)
        player.frosted_player_bar = True
        bar.get_visible.return_value = False
        Player.update_queue_bottom_inset(player)
        self.assertEqual(info.get_margin_bottom(), 0)
        info.destroy()

    def test_resize_from_both_edges_clamps_and_saves_width(self):
        from gi.repository import Gdk
        player = SimpleNamespace(info_panel_resize=None, info_panel_width=360,
                                 info_panel=Mock(), info_source_label=Mock(),
                                 content_overlay=SimpleNamespace(get_allocated_width=lambda: 800))
        press = SimpleNamespace(button=1, x_root=500)
        self.assertTrue(Player.info_resize_pressed(player, None, press, 'right'))
        self.assertTrue(Player.info_resize_motion(player, None, SimpleNamespace(
            x_root=580, state=Gdk.ModifierType.BUTTON1_MASK)))
        self.assertEqual(player.info_panel_width, 440)
        with patch('player.save_info_panel_width') as save:
            self.assertTrue(Player.info_resize_released(player, None, press))
        save.assert_called_once_with(440)
        Player.info_resize_pressed(player, None, press, 'left')
        Player.info_resize_motion(player, None, SimpleNamespace(
            x_root=900, state=Gdk.ModifierType.BUTTON1_MASK))
        self.assertEqual(player.info_panel_width, 240)
        Player.info_resize_motion(player, None, SimpleNamespace(
            x_root=-1000, state=Gdk.ModifierType.BUTTON1_MASK))
        self.assertEqual(player.info_panel_width, 776)

    def test_resize_grabs_pointer_until_release(self):
        from gi.repository import Gdk
        handle = Mock()
        player = SimpleNamespace(info_panel_resize=None, info_panel_width=300,
                                 info_panel=Mock(), info_source_label=Mock(),
                                 content_overlay=SimpleNamespace(get_allocated_width=lambda: 800))
        self.assertTrue(Player.info_resize_pressed(player, handle, SimpleNamespace(button=1, x_root=500), 'left'))
        handle.grab_add.assert_called_once_with()
        self.assertTrue(Player.info_resize_motion(player, handle,
                         SimpleNamespace(x_root=450, state=Gdk.ModifierType.BUTTON1_MASK)))
        self.assertEqual(player.info_panel_width, 350)
        with patch('player.save_info_panel_width') as save:
            self.assertTrue(Player.info_resize_released(player, handle, SimpleNamespace(button=1)))
        handle.grab_remove.assert_called_once_with()
        save.assert_called_once_with(350)

    def test_requested_track_opens_panel_without_changing_playback(self):
        track = Item('/library/metadata/7', 'Selected', artist='Artist')
        client = object()
        button = Mock()
        button.get_active.return_value = False
        player = SimpleNamespace(client=client, info_button=button, load_current_info=Mock())
        Player.show_track_info(player, track)
        self.assertEqual(player.info_target, (client, track))
        button.set_active.assert_called_once_with(True)
        player.load_current_info.assert_not_called()
        button.get_active.return_value = True
        Player.show_track_info(player, track)
        player.load_current_info.assert_called_once_with()

    def test_library_edit_button_uses_entire_selection(self):
        songs = [Item('/library/metadata/1', 'One'), Item('/library/metadata/2', 'Two')]
        player = SimpleNamespace(songs=songs, selected_song_indices=lambda: [0, 1],
                                 show_tag_editor=Mock())
        Player.edit_selected_library_tracks(player)
        player.show_tag_editor.assert_called_once_with(songs)

    def test_edit_selected_tracks_opens_editor_in_info_panel(self):
        song = Item('/library/metadata/7', 'Selected')
        client = object()
        button = Mock()
        button.get_active.return_value = False
        player = SimpleNamespace(client=client, library=SimpleNamespace(get_active_id=lambda: '2'),
                                 info_generation=3, info_pending_update=None, info_target=None,
                                 info_button=button, info_artist_name=Mock(),
                                 info_tag_editor=Mock(), info_content_stack=Mock())
        Player.show_tag_editor(player, [song])
        self.assertEqual(player.info_mode, 'edit')
        player.info_tag_editor.load.assert_called_once_with(client, '2', [song])
        player.info_content_stack.set_visible_child_name.assert_called_once_with('edit')
        button.set_active.assert_called_once_with(True)

    def test_expensive_results_wait_until_slide_finishes(self):
        revealer = SimpleNamespace(get_child_revealed=lambda: False,
                                   get_reveal_child=lambda: True)
        player = SimpleNamespace(info_revealer=revealer, info_generation=4,
                                 info_pending_update=None)
        update = Mock()
        Player.apply_info_after_slide(player, 4, update)
        update.assert_not_called()
        revealer.get_child_revealed = lambda: True
        Player.info_reveal_finished(player, revealer, None)
        update.assert_called_once_with()
        self.assertIsNone(player.info_pending_update)

    def test_results_from_previous_track_are_not_applied(self):
        revealer = SimpleNamespace(get_child_revealed=lambda: True,
                                   get_reveal_child=lambda: True)
        update = Mock()
        player = SimpleNamespace(info_revealer=revealer, info_generation=5,
                                 info_pending_update=(4, update))
        Player.info_reveal_finished(player, revealer, None)
        update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
