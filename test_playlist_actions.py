import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

from player import Player
from plex_client import Item


class PlaylistActionsTests(unittest.TestCase):
    def test_playlist_pointer_events_reorder_through_the_list(self):
        window = Gtk.OffscreenWindow()
        overlay = Gtk.Overlay()
        listing = Gtk.ListBox()
        hidden = Gtk.ListBoxRow()
        hidden.playlist = None
        hidden.set_no_show_all(True)
        listing.add(hidden)
        rows = []
        for number in (1, 2):
            row = Gtk.ListBoxRow()
            row.playlist = Item(f'/playlists/{number}/items', str(number))
            row.add(Gtk.Label(label=str(number)))
            listing.add(row)
            rows.append(row)
        overlay.add(listing)
        drag_overlay = Gtk.Fixed()
        overlay.add_overlay(drag_overlay)
        ghost, line = Gtk.Label(), Gtk.EventBox()
        drag_overlay.put(ghost, 0, 0)
        drag_overlay.put(line, 0, 0)
        window.add(overlay)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        player = SimpleNamespace(
            client=SimpleNamespace(address='http://plex', token='secret'),
            playlist_list=listing, smart_playlist_list=None, song_count=Mock(),
            song_drag_overlay=drag_overlay, song_drag_ghost=ghost, song_drop_line=line,
            hide_song_drag_ghost=ghost.hide, hide_song_drop_line=line.hide,
            pointer_position_in=lambda _widget, event: (event.x, event.y))
        player.playlist_drop_index = lambda widget, y: Player.playlist_drop_index(player, widget, y)
        player.reorder_playlist_sidebar = lambda widget, row, index: Player.reorder_playlist_sidebar(
            player, widget, row, index)
        listing.connect('button-press-event', lambda widget, event:
                        Player.playlist_list_pressed(player, widget, event))
        listing.connect('motion-notify-event', lambda widget, event:
                        Player.playlist_pointer_motion(player, widget, event))
        listing.connect('button-release-event', lambda widget, event:
                        Player.playlist_pointer_release(player, widget, event))
        def event(kind, y):
            result = Gdk.Event.new(kind)
            result.window = listing.get_window()
            result.send_event = True
            result.time = Gdk.CURRENT_TIME
            result.x, result.y = 5, y
            if kind == Gdk.EventType.MOTION_NOTIFY:
                result.state = Gdk.ModifierType.BUTTON1_MASK
            else:
                result.button = 1
            return result
        first_y = rows[0].get_allocation().y + 5
        second_bottom = rows[1].get_allocation().y + rows[1].get_allocated_height() - 1
        try:
            with patch('player.save_playlist_order') as save:
                listing.event(event(Gdk.EventType.BUTTON_PRESS, first_y))
                self.assertTrue(listing.event(event(Gdk.EventType.MOTION_NOTIFY, second_bottom)))
                self.assertTrue(line.get_visible())
                self.assertTrue(listing.event(event(Gdk.EventType.BUTTON_RELEASE, second_bottom)))
            self.assertEqual([row.playlist.key for row in listing.get_children()[1:]],
                             ['/playlists/2/items', '/playlists/1/items'])
            self.assertFalse(line.get_visible())
            save.assert_called_once()
        finally:
            window.destroy()

    def test_target_outline_moves_and_clears(self):
        first = Gtk.ListBoxRow()
        first.playlist = Item('/playlists/1/items', 'One')
        second = Gtk.ListBoxRow()
        second.playlist = Item('/playlists/2/items', 'Two')
        smart = Gtk.ListBoxRow()
        smart.playlist = Item('/playlists/3/items', 'Smart', smart=True)
        player = SimpleNamespace()
        self.assertTrue(Player.set_playlist_drop_target(player, first))
        self.assertTrue(first.get_style_context().has_class('playlist-drag-target'))
        self.assertTrue(Player.set_playlist_drop_target(player, second))
        self.assertFalse(first.get_style_context().has_class('playlist-drag-target'))
        self.assertTrue(second.get_style_context().has_class('playlist-drag-target'))
        self.assertFalse(Player.set_playlist_drop_target(player, smart))
        self.assertFalse(second.get_style_context().has_class('playlist-drag-target'))

    def test_native_and_pointer_track_drags_highlight_same_target(self):
        row = Gtk.ListBoxRow()
        row.playlist = Item('/playlists/2/items', 'Two')
        listing = Mock()
        listing.get_row_at_y.return_value = row
        listing.drag_dest_find_target.return_value.name.return_value = 'application/x-plex-song-key'
        player = SimpleNamespace(playlist_list=listing,
                                 pointer_position_in=lambda _widget, _event: (5, 7))
        player.set_playlist_drop_target = lambda value: Player.set_playlist_drop_target(player, value)
        self.assertFalse(Player.playlist_drag_motion(player, listing, Mock(), 5, 7, 0))
        self.assertTrue(row.get_style_context().has_class('playlist-drag-target'))
        Player.playlist_drag_leave(player, listing, None, 0)
        self.assertFalse(row.get_style_context().has_class('playlist-drag-target'))
        self.assertTrue(Player.update_playlist_drop_target(player, SimpleNamespace()))
        self.assertTrue(row.get_style_context().has_class('playlist-drag-target'))
        Player.set_playlist_drop_target(player, None)

    def test_song_drop_is_routed_to_playlist_under_pointer(self):
        playlist = Item('/playlists/7/items', 'Destination')
        row = SimpleNamespace(playlist=playlist)
        listing = Mock()
        listing.get_row_at_y.return_value = row
        player = SimpleNamespace(playlist_list=listing, hide_song_drop_line=Mock(),
                                 playlist_drop_received=Mock())
        selection = Mock()
        Player.playlist_list_drop_received(player, listing, 'context', 5, 23,
                                           selection, 0, 10)
        player.playlist_drop_received.assert_called_once_with(
            row, 'context', 5, 23, selection, 0, 10)

    def test_album_drop_loads_tracks_before_adding_to_playlist(self):
        album = Item('/library/metadata/10', 'Album')
        playlist = Item('/playlists/7/items', 'Destination')
        tracks = [Item('/library/metadata/11', 'Song')]
        client = SimpleNamespace(tracks=Mock(return_value=tracks))
        player = SimpleNamespace(client=client, albums=[], dragged_album=(client, album),
                                 song_count=Mock())
        player.async_work = lambda work, done, valid: done(work()) if valid() else None
        selection = SimpleNamespace(get_data=lambda: album.key.encode())
        with patch('player.Gtk.drag_finish') as finish, \
                patch.object(Player, 'add_tracks_to_playlist') as add:
            Player.playlist_drop_received(player, SimpleNamespace(playlist=playlist),
                                          None, 0, 0, selection, 3, 12)
        finish.assert_called_once_with(None, True, False, 12)
        client.tracks.assert_called_once_with(album)
        add.assert_called_once_with(player, playlist, tracks)

    def test_playlist_drop_cannot_cross_sidebar_sections(self):
        playlist_list, smart_list = Mock(), Mock()
        client = object()
        player = SimpleNamespace(playlist_list=playlist_list, client=client,
                                 hide_song_drop_line=Mock(),
                                 playlist_drag_source=(smart_list, object(), client))
        selection = SimpleNamespace(get_data=lambda: b'playlist')
        with patch('player.Gtk.drag_finish') as finish:
            Player.playlist_list_drop_received(player, playlist_list, None, 0, 0,
                                               selection, 1, 12)
        finish.assert_called_once_with(None, False, False, 12)

    def test_reorder_plex_playlists_persists_and_keeps_selection(self):
        window = Gtk.OffscreenWindow()
        listing = Gtk.ListBox()
        hidden = Gtk.ListBoxRow()
        hidden.playlist = None
        hidden.set_no_show_all(True)
        listing.add(hidden)
        rows = []
        for number in (1, 2, 3):
            row = Gtk.ListBoxRow()
            row.playlist = Item(f'/playlists/{number}/items', str(number))
            row.add(Gtk.Label(label=str(number)))
            listing.add(row)
            rows.append(row)
        window.add(listing)
        window.show_all()
        listing.select_row(rows[0])
        client = SimpleNamespace(address='http://plex', token='secret')
        player = SimpleNamespace(playlist_list=listing, smart_playlist_list=None,
                                 client=client, song_count=Mock())
        try:
            with patch('player.save_playlist_order') as save:
                self.assertTrue(Player.reorder_playlist_sidebar(player, listing, rows[0], 3))
            self.assertEqual([row.playlist.key for row in listing.get_children()[1:]],
                             ['/playlists/2/items', '/playlists/3/items', '/playlists/1/items'])
            self.assertIs(listing.get_selected_row(), rows[0])
            save.assert_called_once_with('http://plex', 'secret',
                                         ['/playlists/2/items', '/playlists/3/items',
                                          '/playlists/1/items'])
        finally:
            window.destroy()

    def test_reorder_smart_playlists_uses_local_definitions(self):
        listing = Gtk.ListBox()
        rows = []
        for name in ('One', 'Two'):
            row = Gtk.ListBoxRow()
            row.definition = {'id': name}
            row.show()
            listing.add(row)
            rows.append(row)
        player = SimpleNamespace(smart_playlist_list=listing, playlist_list=None,
                                 smart_playlists=[row.definition for row in rows],
                                 save_smart_playlist_definitions=Mock(return_value=True))
        self.assertTrue(Player.reorder_playlist_sidebar(player, listing, rows[1], 0))
        self.assertEqual([item['id'] for item in player.smart_playlists], ['Two', 'One'])
        player.save_smart_playlist_definitions.assert_called_once()

    def test_right_click_on_list_dispatches_to_clicked_playlist(self):
        window = Gtk.OffscreenWindow()
        playlist_list = Gtk.ListBox()
        first = Gtk.ListBoxRow()
        first.playlist = Item('/playlists/7/items', 'First')
        first.add(Gtk.Label(label='First'))
        second = Gtk.ListBoxRow()
        second.playlist = Item('/playlists/8/items', 'Second')
        second.add(Gtk.Label(label='Second'))
        playlist_list.add(first)
        playlist_list.add(second)
        window.add(playlist_list)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        player = SimpleNamespace(playlist_list=playlist_list, smart_playlist_list=None,
                                 playlist_row_pressed=Mock(return_value=True))
        playlist_list.connect('button-press-event',
                              lambda widget, event: Player.playlist_list_pressed(player, widget, event))
        event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
        event.window = playlist_list.get_window()
        event.send_event = True
        event.time = Gdk.CURRENT_TIME
        event.x = 5
        event.y = second.get_allocation().y + second.get_allocated_height() / 2
        event.button = 3
        try:
            self.assertTrue(playlist_list.event(event))
            self.assertIs(player.playlist_row_pressed.call_args.args[0], second)
        finally:
            window.destroy()

    def test_smart_playlist_and_empty_space_dispatch(self):
        row = SimpleNamespace(definition={'id': 'smart'})
        smart_list = Mock()
        smart_list.get_row_at_y.return_value = row
        player = SimpleNamespace(playlist_list=Mock(), smart_playlist_list=smart_list,
                                 smart_playlist_pressed=Mock(return_value=True))
        event = SimpleNamespace(button=3, y=12)
        self.assertTrue(Player.playlist_list_pressed(player, smart_list, event))
        player.smart_playlist_pressed.assert_called_once_with(row, event)
        smart_list.get_row_at_y.return_value = None
        self.assertFalse(Player.playlist_list_pressed(player, smart_list, event))
        event.button = 1
        self.assertFalse(Player.playlist_list_pressed(player, smart_list, event))

    def make_player(self):
        playlist = Item('/playlists/7/items', 'Old name')
        other = Item('/playlists/8/items', 'Other')
        client = Mock()
        row = Mock(playlist=playlist)
        other_row = Mock(playlist=other)
        all_row = Mock(playlist=None)
        playlist_list = Mock()
        playlist_list.get_children.return_value = [all_row, row, other_row]
        player = SimpleNamespace(
            client=client, sections=[('2', 'Music')], playlists=[playlist, other],
            playlist_list=playlist_list, all_songs_row=all_row,
            active_playlist=playlist, playlist_generation=0,
            song_view_cache={(client, '2', playlist.key, None): 'cached',
                             (client, '2', other.key, None): 'other'},
            songs_heading=Mock(), song_count=Mock(), select_playlist=Mock())
        jobs = []
        player.async_work = lambda work, done, **kwargs: jobs.append((work, done, kwargs['on_error']))
        return player, playlist, other, row, jobs

    def test_rename_updates_sidebar_and_active_heading_after_server_success(self):
        player, playlist, other, row, jobs = self.make_player()
        Player.change_plex_playlist(player, playlist, 'New name')
        self.assertEqual(playlist.title, 'Old name')
        work, done, _failed = jobs[0]
        work()
        player.client.rename_playlist.assert_called_once_with(playlist, 'New name')
        done(None)
        self.assertEqual(playlist.title, 'New name')
        self.assertEqual(other.title, 'Other')
        row.get_child().set_text.assert_called_once_with('New name')
        player.songs_heading.set_text.assert_called_once_with('New name')
        self.assertEqual(player.playlist_generation, 1)

    def test_delete_removes_only_playlist_and_returns_active_view_to_library(self):
        player, playlist, other, row, jobs = self.make_player()
        Player.change_plex_playlist(player, playlist, None)
        work, done, _failed = jobs[0]
        with patch('player.LocalCache') as cache:
            work()
            cache.return_value.song_index_path.assert_called_once_with('2', playlist.key)
            cache.return_value.song_index_path.return_value.unlink.assert_called_once_with(missing_ok=True)
        done(None)
        player.client.delete_playlist.assert_called_once_with(playlist)
        self.assertEqual(player.playlists, [other])
        row.destroy.assert_called_once()
        player.playlist_list.select_row.assert_called_once_with(player.all_songs_row)
        self.assertEqual(list(player.song_view_cache), [(player.client, '2', other.key, None)])

    def test_failure_keeps_playlist_and_allows_retry(self):
        player, playlist, _other, row, jobs = self.make_player()
        Player.change_plex_playlist(player, playlist, None)
        Player.change_plex_playlist(player, playlist, 'Name')
        self.assertEqual(len(jobs), 1)
        jobs[0][2]()
        row.destroy.assert_not_called()
        self.assertIn(playlist, player.playlists)
        player.song_count.set_text.assert_called_once_with('Could not delete playlist on Plex')
        Player.change_plex_playlist(player, playlist, 'Name')
        self.assertEqual(len(jobs), 2)

    def test_result_from_old_server_does_not_change_current_sidebar(self):
        player, playlist, _other, row, jobs = self.make_player()
        Player.change_plex_playlist(player, playlist, 'Name')
        player.client = Mock()
        jobs[0][1](None)
        self.assertEqual(playlist.title, 'Old name')
        row.get_child.assert_not_called()


if __name__ == '__main__':
    unittest.main()
