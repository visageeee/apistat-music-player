import time
import unittest
from collections import OrderedDict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import appearance
from library_album_view import (AlbumGroupOverlay, album_details, album_group_row_height,
                                album_identity, album_ranges, group_songs_by_album)
from plex_client import Item
from player import Player


class AlbumLibraryViewTests(unittest.TestCase):
    def test_groups_interleaved_tracks_by_album_without_losing_playlist_duplicates(self):
        tracks = [Item('a1', 'One', album='A', album_key='album-a', playlist_item_id=1),
                  Item('b1', 'Two', album='B', album_key='album-b', playlist_item_id=2),
                  Item('a2', 'Three', album='A', album_key='album-a', playlist_item_id=3),
                  Item('a1', 'One', album='A', album_key='album-a', playlist_item_id=4)]
        grouped = group_songs_by_album(tracks)
        self.assertEqual([item.playlist_item_id for item in grouped], [1, 3, 4, 2])
        self.assertEqual([(start, end) for start, end, _key in album_ranges(grouped)],
                         [(0, 2), (3, 3)])
        self.assertEqual([item.playlist_item_id for item in tracks], [1, 2, 3, 4])

    def test_library_filters_before_grouping_and_preserves_track_order(self):
        client = object()
        tracks = [Item('a1', 'Keep one', album='A', album_key='a'),
                  Item('b1', 'Keep two', album='B', album_key='b'),
                  Item('a2', 'Keep three', album='A', album_key='a'),
                  Item('b2', 'Omit', album='B', album_key='b')]
        displayed = []
        player = SimpleNamespace(
            client=client, library=SimpleNamespace(get_active_id=lambda: 'music'),
            active_playlist=None, active_smart_playlist=None, library_album_filter=None,
            library_search=SimpleNamespace(get_text=lambda: 'Keep'), library_view_mode='albums',
            song_generation=0, song_store=object(),
            song_view=SimpleNamespace(set_model=lambda _model: None),
            song_view_cache=OrderedDict(), song_view_key=None,
            song_catalog_source=(client, 'music', None, None), song_catalog=tracks,
            update_song_drag_mode=lambda: None, effective_library_sort=lambda: None,
            display_song_page=lambda results, *_args: displayed.extend(results))
        Player.load_songs(player)
        self.assertEqual([item.key for item in displayed], ['a1', 'a2', 'b1'])
        self.assertEqual(player.song_view_key[-1], 'album-groups')

    def test_album_details_and_group_spacing_for_short_and_long_albums(self):
        song = Item('1', 'Track', artist='Track artist', album_artist='Album artist',
                    album='Record', year='1998')
        self.assertEqual(album_details(song), ('Album artist', 'Record', '1998'))
        self.assertEqual(album_details(Item('2', 'Track')), ('Unknown artist', 'Unknown album', ''))
        line_height = 32
        for count in (1, 2, 6, 12):
            last_height = album_group_row_height(count, 18)
            self.assertGreaterEqual(last_height, line_height + 16)
            self.assertGreaterEqual((count - 1) * line_height + last_height, 220)

    def test_album_gutter_reserves_height_on_last_track_only(self):
        class Model:
            @staticmethod
            def get_path(row):
                return Gtk.TreePath.new_from_indices([row])
        player = SimpleNamespace(library_view_mode='albums', text_size=18,
                                 album_group_overlay=SimpleNamespace(group_ends={2: 3}))
        cell = Gtk.CellRendererText()
        Player.album_gutter_row_size(player, None, cell, Model(), 1)
        self.assertEqual(cell.get_fixed_size()[1], -1)
        Player.album_gutter_row_size(player, None, cell, Model(), 2)
        self.assertEqual(cell.get_fixed_size()[1], album_group_row_height(3, 18))
        player.library_view_mode = 'songs'
        Player.album_gutter_row_size(player, None, cell, Model(), 2)
        self.assertEqual(cell.get_fixed_size()[1], -1)

    def test_real_tree_reserves_space_for_short_albums(self):
        tracks = [Item('1', 'One', album_key='a'), Item('2', 'Two', album_key='a'),
                  Item('3', 'Three', album_key='b')]
        model = Gtk.ListStore(str)
        for item in tracks:
            model.append([item.title])
        player = SimpleNamespace(songs=tracks, client=None, closed=False, theme='dark',
                                 text_size=18, library_view_mode='albums')
        view = Gtk.TreeView(model=model)
        gutter_cell = Gtk.CellRendererText()
        gutter = Gtk.TreeViewColumn('', gutter_cell)
        gutter.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        gutter.set_fixed_width(AlbumGroupOverlay.GUTTER)
        gutter.set_cell_data_func(gutter_cell, lambda col, cell, model, row, data:
                                  Player.album_gutter_row_size(player, col, cell, model, row, data))
        view.append_column(gutter)
        view.append_column(Gtk.TreeViewColumn('Track', Gtk.CellRendererText(), text=0))
        scroll = Gtk.ScrolledWindow(); scroll.add(view)
        container = Gtk.Overlay(); container.add(scroll)
        overlay = AlbumGroupOverlay(player, view, scroll)
        player.album_group_overlay = overlay
        container.add_overlay(overlay); container.set_overlay_pass_through(overlay, True)
        window = Gtk.OffscreenWindow(); window.set_size_request(400, 300); window.add(container)
        window.show_all(); overlay.set_results(tracks)
        deadline = time.monotonic() + .15
        try:
            while time.monotonic() < deadline:
                while Gtk.events_pending():
                    Gtk.main_iteration()
            last_of_two = view.get_background_area(Gtk.TreePath.new_from_indices([1]), None)
            single = view.get_background_area(Gtk.TreePath.new_from_indices([2]), None)
            self.assertGreaterEqual(last_of_two.height, album_group_row_height(2, 18))
            self.assertGreaterEqual(single.height, album_group_row_height(1, 18))
        finally:
            window.destroy()

    def test_plain_list_icon_is_windowless_lines(self):
        icon = Player.library_list_lines_icon()
        self.assertIsInstance(icon, Gtk.DrawingArea)
        self.assertFalse(icon.get_has_window())
        self.assertEqual(icon.get_size_request().width, 20)
        icon.destroy()

    def test_tag_fallback_distinguishes_album_artists(self):
        first = Item('1', 'Song', album='Same', artist='Singer', album_artist='Artist A')
        other = Item('2', 'Song', album='Same', artist='Singer', album_artist='Artist B')
        self.assertNotEqual(album_identity(first), album_identity(other))
        self.assertEqual(album_identity(first), album_identity(
            Item('3', 'Another', album='same', album_artist='artist a')))

    def test_mode_preference_is_validated_and_persists(self):
        with TemporaryDirectory() as directory, patch.object(
                appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertEqual(appearance.load_library_view_mode(), 'songs')
            appearance.save_library_view_mode('albums')
            self.assertEqual(appearance.load_library_view_mode(), 'albums')
            with self.assertRaises(ValueError):
                appearance.save_library_view_mode('bad')

    def test_playlist_scrollbars_only_show_when_overflowing(self):
        listing = Gtk.ListBox()
        listing.add(Gtk.Label(label='One playlist'))
        player = SimpleNamespace(attach_smooth_scroll=lambda scroll: scroll)
        scroll = Player.scroll(player, listing, overlay_scrolling=False)
        row = Player.stable_library_scrollbar(scroll, auto_hide=True)
        window = Gtk.OffscreenWindow()
        window.set_size_request(250, 160)
        window.add(row)
        window.show_all()
        def settle():
            deadline = time.monotonic() + .12
            while time.monotonic() < deadline:
                while Gtk.events_pending():
                    Gtk.main_iteration()
        try:
            settle()
            bar = row.get_children()[1]
            self.assertFalse(bar.get_visible())
            for index in range(30):
                listing.add(Gtk.Label(label=f'Playlist {index}'))
            listing.show_all()
            settle()
            self.assertTrue(bar.get_visible())
            for child in listing.get_children()[1:]:
                child.destroy()
            settle()
            self.assertFalse(bar.get_visible())
        finally:
            window.destroy()

    def test_view_switch_updates_controls_and_loads_once(self):
        player = SimpleNamespace(library_view_mode='songs', library_list_mode_button=Mock(),
                                 library_album_mode_button=Mock(), album_gutter_column=Mock(),
                                 album_group_overlay=Mock(), status=Mock(), load_songs=Mock())
        with patch('player.save_library_view_mode') as save:
            Player.library_view_mode_changed(player, None, 'albums')
            Player.library_view_mode_changed(player, None, 'albums')
        self.assertEqual(player.library_view_mode, 'albums')
        player.album_gutter_column.set_visible.assert_called_once_with(True)
        player.album_group_overlay.set_visible.assert_called_once_with(True)
        player.load_songs.assert_called_once_with()
        save.assert_called_once_with('albums')

    def test_real_toggle_buttons_do_not_reenter_mode_switch(self):
        player = SimpleNamespace(library_view_mode='songs', library_list_mode_button=Gtk.ToggleButton(),
                                 library_album_mode_button=Gtk.ToggleButton(), album_gutter_column=Mock(),
                                 album_group_overlay=Mock(), status=Mock(), load_songs=Mock())
        player.library_list_mode_button.set_active(True)
        player.library_list_mode_button.connect(
            'clicked', lambda button: Player.library_view_mode_changed(player, button, 'songs'))
        player.library_album_mode_button.connect(
            'clicked', lambda button: Player.library_view_mode_changed(player, button, 'albums'))
        with patch('player.save_library_view_mode') as save:
            player.library_album_mode_button.clicked()
            self.assertEqual(player.library_view_mode, 'albums')
            self.assertTrue(player.library_album_mode_button.get_active())
            self.assertFalse(player.library_list_mode_button.get_active())
            player.library_list_mode_button.clicked()
        self.assertEqual(player.library_view_mode, 'songs')
        self.assertEqual(player.load_songs.call_count, 2)
        self.assertEqual(save.call_count, 2)

    def test_only_line_timeline_has_a_solid_glass_background(self):
        mode = ['line']
        stack = SimpleNamespace(get_visible_child_name=lambda: mode[0])
        player = SimpleNamespace(timeline_stack=stack)
        self.assertIs(Player.solid_timeline_background(player), stack)
        mode[0] = 'waveform'
        self.assertIsNone(Player.solid_timeline_background(player))
        self.assertIsNone(Player.solid_timeline_background(SimpleNamespace()))

    def test_frosted_inset_remains_on_list_after_count_moves_to_header(self):
        tracks = Gtk.Box()
        count = Gtk.Label()
        player = SimpleNamespace(library_tracks_container=tracks, song_count=count,
                                 frosted_player_bar=True,
                                 player_bar=SimpleNamespace(get_allocated_height=lambda: 100,
                                                            get_visible=lambda: True))
        Player.update_queue_bottom_inset(player)
        self.assertEqual(tracks.get_margin_bottom(), 108)
        self.assertEqual(count.get_margin_bottom(), 0)

    def test_overlay_loads_visible_album_covers_and_uses_existing_table(self):
        tracks = [Item('/track/1', 'One', album='A', album_key='/album/a', album_thumb='/art/a'),
                  Item('/track/2', 'Two', album='A', album_key='/album/a', album_thumb='/art/a'),
                  Item('/track/3', 'Three', album='B', album_key='/album/b', album_thumb='/art/b')]
        client = SimpleNamespace(address='http://example.invalid')
        requests = []
        def load_art(source, album, image, size, valid, loaded):
            requests.append((source, album.thumb, size, valid()))
        player = SimpleNamespace(songs=tracks, client=client, closed=False,
                                 theme='dark', load_art=load_art)
        model = Gtk.ListStore(str)
        for item in tracks:
            model.append([item.title])
        view = Gtk.TreeView(model=model)
        view.append_column(Gtk.TreeViewColumn('', Gtk.CellRendererText(), text=0))
        scroll = Gtk.ScrolledWindow(); scroll.add(view)
        container = Gtk.Overlay(); container.add(scroll)
        overlay = AlbumGroupOverlay(player, view, scroll)
        container.add_overlay(overlay); container.set_overlay_pass_through(overlay, True)
        window = Gtk.OffscreenWindow(); window.set_size_request(300, 200); window.add(container)
        window.show_all(); overlay.set_results(tracks)
        deadline = time.monotonic() + .12
        try:
            while time.monotonic() < deadline:
                while Gtk.events_pending():
                    Gtk.main_iteration()
            self.assertTrue(container.get_overlay_pass_through(overlay))
            self.assertFalse(overlay.get_has_window())
            self.assertEqual({request[1] for request in requests}, {'/art/a', '/art/b'})
            self.assertTrue(all(request[3] for request in requests))
            overlay.queue_draw()
            while Gtk.events_pending():
                Gtk.main_iteration()
            self.assertEqual(len(requests), 2)
        finally:
            window.destroy()

    def test_album_mode_disables_playlist_reordering(self):
        player = SimpleNamespace(library_view_mode='albums', active_playlist=SimpleNamespace(smart=False),
                                 active_smart_playlist=None, library_album_filter=None,
                                 library_search=SimpleNamespace(get_text=lambda: ''),
                                 effective_library_sort=lambda: None)
        self.assertFalse(Player.playlist_pointer_mode(player))


if __name__ == '__main__':
    unittest.main()
