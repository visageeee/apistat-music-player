import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

from play_queue import (insert_items, move_items, move_queue_or_history, playlist_move_plan,
                        remove_items, reorder_items,
                        select_similar_tracks)
from player import Player
from plex_client import Item


class PlayQueueTests(unittest.TestCase):
    def test_playlist_move_plan_preserves_duplicate_song_entries(self):
        songs = [Item('/library/metadata/1', 'Same', playlist_item_id=10),
                 Item('/library/metadata/1', 'Same', playlist_item_id=11),
                 Item('/library/metadata/2', 'Other', playlist_item_id=12),
                 Item('/library/metadata/3', 'Last', playlist_item_id=13)]
        updated, moves = playlist_move_plan(songs, [1, 2], 4)
        self.assertEqual([song.playlist_item_id for song in updated], [10, 13, 11, 12])
        self.assertEqual(moves, [(11, 13), (12, 11)])
        updated, moves = playlist_move_plan(songs, [2, 3], 0)
        self.assertEqual([song.playlist_item_id for song in updated], [12, 13, 10, 11])
        self.assertEqual(moves, [(12, None), (13, 12)])
        with self.assertRaises(ValueError):
            playlist_move_plan([Item('/library/metadata/1', 'Missing ID')], [0], 1)

    def test_playlist_drag_updates_rows_and_saves_order_on_server(self):
        songs = [Item(f'/library/metadata/{index}', str(index), playlist_item_id=10 + index)
                 for index in range(4)]
        store = Gtk.ListStore(str)
        for song in songs:
            store.append([song.title])
        playlist = Item('/playlists/7/items', 'Favorites')
        calls = []
        class Client:
            def move_playlist_item(self, _playlist, item_id, after):
                calls.append((item_id, after))
        client = Client()
        source = (client, '2', playlist.key, None)
        key = (*source, '', None)
        cache = {key: {'rows': songs, 'results': list(songs)}}
        player = SimpleNamespace(
            songs=songs, song_store=store, song_results=list(songs),
            song_view_cache=cache, song_view_key=key, song_catalog_source=source,
            song_catalog=list(songs), active_playlist=playlist, client=client,
            library=SimpleNamespace(get_active_id=lambda: '2'),
            song_count=SimpleNamespace(set_text=lambda _text: None),
            async_work=lambda work, done, *_args: done(work()))
        with patch('player.LocalCache') as local_cache:
            self.assertTrue(Player.move_playlist_rows(player, [1], 4))
            local_cache.return_value.save_song_index.assert_called_once()
        self.assertEqual([row[0] for row in store], ['0', '2', '3', '1'])
        self.assertEqual([song.title for song in player.songs], ['0', '2', '3', '1'])
        self.assertEqual(calls, [(11, 13)])

    def test_library_drag_exports_selected_songs_for_queue_icon(self):
        songs = [Item('/library/metadata/1', 'First'),
                 Item('/library/metadata/2', 'Second'),
                 Item('/library/metadata/3', 'Third')]
        payloads = []
        selection = SimpleNamespace(get_target=lambda: 'application/x-plex-song-key',
                                    set=lambda _target, _format, data: payloads.append(data))
        player = SimpleNamespace(songs=songs, song_drag_indices=[0, 2])
        Player.song_drag_data_get(player, None, None, selection, 0, 0)
        self.assertEqual(payloads, [b'/library/metadata/1\n/library/metadata/3'])

    def test_dragging_a_selected_group_preserves_selection_and_payload(self):
        songs = [Item(f'/library/metadata/{index}', f'Song {index}') for index in range(1, 5)]
        store = Gtk.ListStore(str)
        for song in songs:
            store.append([song.title])
        tree = Gtk.TreeView(model=store)
        selected = tree.get_selection()
        selected.set_mode(Gtk.SelectionMode.MULTIPLE)
        paths = [Gtk.TreePath.new_from_indices([index]) for index in (0, 2, 3)]
        for path in paths:
            selected.select_path(path)
        view = SimpleNamespace(get_selection=lambda: selected,
                               get_path_at_pos=lambda *_: (paths[1], object(), 0, 0))
        player = SimpleNamespace(songs=songs, client=object(), playlist_pointer_mode=lambda: False,
                                 set_track_drag_icon=Mock(), song_columns={})
        event = SimpleNamespace(button=1, x=10, y=10, state=0)
        self.assertFalse(Player.library_artist_pressed(player, view, event))
        selected.unselect_all()  # GTK can reduce selection after the button press.
        selected.select_path(paths[1])
        Player.song_drag_begin(player, view, object())
        self.assertEqual([path.get_indices()[0] for path in selected.get_selected_rows()[1]],
                         [0, 2, 3])
        player.songs = []  # The drag payload remains stable if the view changes.
        payloads = []
        selection = SimpleNamespace(get_target=lambda: 'songs',
                                    set=lambda _target, _format, data: payloads.append(data))
        Player.song_drag_data_get(player, view, None, selection, 0, 0)
        self.assertEqual(payloads, [b'/library/metadata/1\n/library/metadata/3\n/library/metadata/4'])

    def test_album_and_style_drags_keep_all_selected_tracks(self):
        songs = [Item(f'/library/metadata/{index}', f'Song {index}') for index in range(1, 4)]
        store = Gtk.ListStore(str)
        for song in songs:
            store.append([song.title])
        tree = Gtk.TreeView(model=store)
        selected = tree.get_selection()
        selected.set_mode(Gtk.SelectionMode.MULTIPLE)
        paths = [Gtk.TreePath.new_from_indices([index]) for index in (0, 2)]
        view = SimpleNamespace(get_selection=lambda: selected,
                               get_path_at_pos=lambda *_: (paths[0], object(), 0, 0),
                               get_columns=lambda: [object(), object(), object(), object()])
        player = SimpleNamespace(tracks=songs, track_view=view, style_display_songs=songs,
                                 client=object(), set_track_drag_icon=Mock())
        event = SimpleNamespace(button=1, x=5, y=5, state=0)
        for source, pressed, data_get in (
                ('album', Player.album_track_pressed, Player.album_track_drag_data_get),
                ('style', Player.style_song_pressed, Player.style_song_drag_data_get)):
            selected.unselect_all()
            for path in paths:
                selected.select_path(path)
            self.assertFalse(pressed(player, view, event))
            selected.unselect_all()
            selected.select_path(paths[0])
            Player.collection_drag_begin(player, view, object(), source)
            payloads = []
            payload = SimpleNamespace(get_target=lambda: 'songs',
                                      set=lambda _target, _format, data: payloads.append(data))
            data_get(player, view, None, payload, 0, 0)
            self.assertEqual(payloads, [b'/library/metadata/1\n/library/metadata/3'])
            self.assertEqual([path.get_indices()[0] for path in selected.get_selected_rows()[1]], [0, 2])
            Player.collection_drag_end(player, view, None, source)

    def test_resolves_style_tracks_in_one_pass_and_preserves_duplicates(self):
        tracks = [Item(f'/library/metadata/{index}', str(index)) for index in range(1, 101)]
        class Counted:
            passes = 0
            def __iter__(self):
                self.passes += 1
                return iter(tracks)
        collection = Counted()
        client = object()
        player = SimpleNamespace(client=client, style_result_source=(client, 'music', None),
                                 style_display_songs=collection)
        keys = [tracks[90].key, tracks[2].key, tracks[90].key]
        self.assertEqual(Player.resolve_loaded_tracks(player, keys),
                         [tracks[90], tracks[2], tracks[90]])
        self.assertEqual(collection.passes, 1)
        player.style_result_source = (object(), 'music', None)
        self.assertEqual(Player.resolve_loaded_tracks(player, keys), [])

    def test_drag_after_modifier_selection_uses_updated_selection(self):
        songs = [Item(f'/library/metadata/{index}', str(index)) for index in range(1, 4)]
        store = Gtk.ListStore(str)
        for song in songs:
            store.append([song.title])
        tree = Gtk.TreeView(model=store)
        selection = tree.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        paths = [Gtk.TreePath.new_from_indices([index]) for index in (0, 2)]
        selection.select_path(paths[0])
        view = SimpleNamespace(get_selection=lambda: selection,
                               get_path_at_pos=lambda *_: (paths[1], object(), 0, 0))
        event = SimpleNamespace(button=1, x=5, y=5, state=Gdk.ModifierType.SHIFT_MASK)
        player = SimpleNamespace(client=object(), style_display_songs=songs,
                                 set_track_drag_icon=Mock())
        self.assertFalse(Player.style_song_pressed(player, view, event))
        self.assertIsNone(player.style_drag_candidates)
        selection.select_path(paths[1])  # GTK applies the modifier after the press callback.
        Player.collection_drag_begin(player, view, object(), 'style')
        self.assertEqual(player.style_drag_tracks, (songs[0], songs[2]))

    def test_style_selection_can_drop_without_library_list_loaded(self):
        songs = [Item('/library/metadata/1', 'One'), Item('/library/metadata/2', 'Two')]
        client = object()
        player = SimpleNamespace(client=client, style_result_source=(client, 'music', None),
                                 style_display_songs=songs, enqueue_tracks=Mock())
        player.resolve_loaded_tracks = lambda keys: Player.resolve_loaded_tracks(player, keys)
        selection = SimpleNamespace(get_data=lambda: b'/library/metadata/2\n/library/metadata/1')
        playlist = SimpleNamespace(title='Mix')
        with patch('player.Gtk.drag_finish') as finish, \
                patch.object(Player, 'add_tracks_to_playlist') as add_playlist:
            Player.queue_drop_received(player, None, None, 0, 0, selection, 0, 1)
            Player.playlist_drop_received(player, SimpleNamespace(playlist=playlist),
                                          None, 0, 0, selection, 0, 2)
        player.enqueue_tracks.assert_called_once_with([songs[1], songs[0]])
        add_playlist.assert_called_once_with(player, playlist, [songs[1], songs[0]])
        self.assertTrue(all(call.args[1] for call in finish.call_args_list))

    def test_queue_drag_restores_all_selected_row_highlights(self):
        songs = [Item(f'/library/metadata/{index}', str(index)) for index in range(1, 4)]
        store = Gtk.ListStore(int)
        for index in range(3):
            store.append([index])
        tree = Gtk.TreeView(model=store)
        selection = tree.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.select_path(Gtk.TreePath.new_from_indices([0]))
        view = SimpleNamespace(get_selection=lambda: selection)
        player = SimpleNamespace(queue=songs, queue_store=store, play_history=[],
                                 queue_pointer_drag={'indices': [0, 2], 'x': 0, 'y': 0,
                                                     'active': False},
                                 show_song_drag_ghost=Mock(), queue_pointer_destination=Mock())
        self.assertTrue(Player.queue_pointer_motion(
            player, view, SimpleNamespace(x=20, y=20, state=Gdk.ModifierType.BUTTON1_MASK)))
        self.assertEqual([path.get_indices()[0] for path in selection.get_selected_rows()[1]], [0, 2])

    def test_all_library_views_use_pointer_drag(self):
        calls = []
        view = SimpleNamespace(
            unset_rows_drag_source=lambda: calls.append('pointer'),
            enable_model_drag_source=lambda *_args: calls.append('native'))
        player = SimpleNamespace(song_view=view, song_native_drag_enabled=True,
                                 song_drag_targets=[], playlist_pointer_mode=lambda: True)
        Player.update_song_drag_mode(player)
        Player.update_song_drag_mode(player)
        self.assertEqual(calls, ['pointer'])
        player.playlist_pointer_mode = lambda: False
        Player.update_song_drag_mode(player)
        self.assertEqual(calls, ['pointer'])

    def test_smart_playlist_tracks_drag_to_regular_playlist(self):
        tracks = [Item('/library/metadata/1', 'One'), Item('/library/metadata/2', 'Two')]
        store = Gtk.ListStore(str)
        for track in tracks:
            store.append([track.title])
        tree = Gtk.TreeView(model=store)
        selected = tree.get_selection()
        selected.set_mode(Gtk.SelectionMode.MULTIPLE)
        paths = [Gtk.TreePath.new_from_indices([index]) for index in range(2)]
        for path in paths:
            selected.select_path(path)
        view = SimpleNamespace(get_selection=lambda: selected,
                               get_path_at_pos=lambda *_: (paths[0], object(), 0, 0),
                               set_drag_dest_row=Mock())
        destination = Item('/playlists/8/items', 'Destination')
        row = Gtk.ListBoxRow()
        row.playlist = destination
        listing = SimpleNamespace(get_row_at_y=lambda _y: row)
        queue_button = object()
        player = SimpleNamespace(
            songs=tracks, active_smart_playlist={'id': 'smart'}, song_columns={},
            playlist_pointer_mode=lambda: False, playlist_reorder_allowed=lambda: False,
            playlist_list=listing, queue_nav=queue_button,
            show_song_drag_ghost=Mock(), hide_song_drag_ghost=Mock(),
            hide_song_drop_line=Mock(), add_tracks_to_playlist=Mock(),
            pointer_position_in=lambda widget, _event: (5, 10) if widget is listing else None)
        self.assertFalse(Player.library_artist_pressed(
            player, view, SimpleNamespace(button=1, x=5, y=5, state=0)))
        self.assertEqual(player.song_pointer_drag['indices'], [0, 1])
        Player.song_pointer_motion(player, view, SimpleNamespace(
            x=20, y=20, state=Gdk.ModifierType.BUTTON1_MASK))
        self.assertTrue(row.get_style_context().has_class('playlist-drag-target'))
        self.assertTrue(Player.song_pointer_release(player, view, SimpleNamespace(button=1)))
        self.assertFalse(row.get_style_context().has_class('playlist-drag-target'))
        player.add_tracks_to_playlist.assert_called_once_with(destination, tracks)

    def test_pointer_drag_preview_uses_the_rendered_track_row(self):
        window = Gtk.OffscreenWindow()
        store = Gtk.ListStore(str, str)
        store.append(['Song', 'Artist'])
        view = Gtk.TreeView(model=store)
        for index in range(2):
            view.append_column(Gtk.TreeViewColumn(str(index), Gtk.CellRendererText(), text=index))
        window.add(view)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        path = Gtk.TreePath.new_from_indices([0])
        area = view.get_background_area(path, None)
        player = SimpleNamespace(song_drag_row_ghost=Gtk.Image(), song_drag_ghost=Gtk.Label())
        try:
            Player.prepare_song_drag_ghost(player, view, {'x': 5, 'y': area.y + area.height // 2})
            self.assertTrue(player.song_drag_row_ghost.get_visible())
            self.assertEqual(player.song_drag_row_ghost.get_storage_type(), Gtk.ImageType.SURFACE)
            self.assertFalse(player.song_drag_ghost.get_visible())
        finally:
            window.destroy()

    def test_playlist_pointer_release_uses_insertion_position(self):
        movements = []
        view = SimpleNamespace(set_drag_dest_row=lambda *_args: None)
        queue_icon = object()
        playlist_list = object()
        player = SimpleNamespace(
            song_pointer_drag={'indices': [1, 2], 'active': True},
            hide_song_drag_ghost=lambda: None,
            hide_song_drop_line=lambda: None,
            queue_nav=queue_icon, playlist_list=playlist_list,
            pointer_position_in=lambda widget, _event: (5, 5) if widget is view else None,
            playlist_reorder_allowed=lambda: True,
            song_drop_position=lambda _x, _y: 4,
            move_playlist_rows=lambda indices, destination:
                movements.append((indices, destination)) or True)
        self.assertTrue(Player.song_pointer_release(
            player, view, SimpleNamespace(button=1, x=10, y=20)))
        self.assertEqual(movements, [([1, 2], 4)])

    def test_queue_selection_callback_accepts_gtk_arguments(self):
        model = Gtk.ListStore(int)
        model.append([-1])
        model.append([0])
        model.append([1])
        view = Gtk.TreeView(model=model)
        selection = view.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.set_select_function(Player.queue_row_selectable)
        selection.select_path(Gtk.TreePath.new_from_indices([0]))
        selection.select_path(Gtk.TreePath.new_from_indices([1]))
        selection.select_path(Gtk.TreePath.new_from_indices([2]))
        _, paths = selection.get_selected_rows()
        self.assertEqual([path.get_indices()[0] for path in paths], [0, 1, 2])

    def test_similar_songs_adds_ten_unique_tracks_after_seed(self):
        seed = Item('/library/metadata/1', 'Seed')
        nearby = [seed] + [Item(f'/library/metadata/{number}', f'Song {number}')
                           for number in range(2, 14)]
        nearby.insert(3, nearby[2])
        added = []
        status = []
        player = SimpleNamespace(
            client=SimpleNamespace(nearest_tracks=lambda song, limit: nearby,
                                   metadata_similar_tracks=lambda song, section, limit: []),
            library=SimpleNamespace(get_active_id=lambda: '2'),
            status=SimpleNamespace(set_text=status.append),
            async_work=lambda work, done, valid: done(work()) if valid() else None,
            enqueue_tracks=added.append,
        )
        Player.enqueue_similar_songs(player, seed)
        self.assertEqual(len(added[0]), 10)
        self.assertEqual([track.key for track in added[0]],
                         [f'/library/metadata/{number}' for number in range(2, 12)])
        self.assertIn('Added 10 similar songs to queue', status)

    def test_similar_songs_reports_unavailable_sonic_results(self):
        messages = []
        player = SimpleNamespace(
            client=SimpleNamespace(nearest_tracks=lambda song, limit: [],
                                   metadata_similar_tracks=lambda song, section, limit: []),
            library=SimpleNamespace(get_active_id=lambda: '2'),
            status=SimpleNamespace(set_text=messages.append),
            async_work=lambda work, done, valid: done(work()) if valid() else None,
            enqueue_tracks=lambda tracks: self.fail('Unexpected queue change'),
        )
        Player.enqueue_similar_songs(player, Item('/library/metadata/1', 'Seed'))
        self.assertIn('no sonic matches or tracks with matching genre or artist', messages[-1])

    def test_similar_songs_fills_from_plex_genre_when_sonic_unavailable(self):
        seed = Item('/library/metadata/1', 'Seed', genre='Jazz')
        fallback = [Item(f'/library/metadata/{number}', f'Song {number}', genre='Jazz')
                    for number in range(2, 14)]
        added = []
        player = SimpleNamespace(
            client=SimpleNamespace(nearest_tracks=lambda song, limit: [],
                                   metadata_similar_tracks=lambda song, section, limit: fallback),
            library=SimpleNamespace(get_active_id=lambda: '2'),
            status=SimpleNamespace(set_text=lambda _message: None),
            async_work=lambda work, done, valid: done(work()) if valid() else None,
            enqueue_tracks=added.append,
        )
        Player.enqueue_similar_songs(player, seed)
        self.assertEqual(added, [fallback[:10]])

    def test_insert_next_and_append_keep_current_track(self):
        queue = ['current', 'later']
        next_queue, index, position = insert_items(queue, 0, ['next-a', 'next-b'], True)
        self.assertEqual(next_queue, ['current', 'next-a', 'next-b', 'later'])
        self.assertEqual((index, position), (0, 1))
        appended, index, position = insert_items(queue, 0, ['last'])
        self.assertEqual((appended, index, position), (['current', 'later', 'last'], 0, 2))
        self.assertEqual(queue, ['current', 'later'])

    def test_reorder_tracks_current_index_and_rejects_invalid_order(self):
        queue, index = reorder_items(['one', 'two', 'three'], 1, [2, 0, 1])
        self.assertEqual((queue, index), (['three', 'one', 'two'], 2))
        with self.assertRaises(ValueError):
            reorder_items(['one', 'two'], 0, [0, 0])

    def test_move_selected_rows_as_block_preserves_current_track(self):
        moved, index = move_items(['a', 'b', 'c', 'd', 'e'], 2, [1, 3], 5)
        self.assertEqual(moved, ['a', 'c', 'e', 'b', 'd'])
        self.assertEqual(index, 1)
        with self.assertRaises(ValueError):
            move_items(['a', 'b'], 0, [9], 1)

    def test_dragging_history_copies_it_into_queue_and_keeps_current_track(self):
        queue = ['current', 'next', 'last']
        history = ['older', 'recent']
        moved, index = move_queue_or_history(queue, 0, history, [-2, 2], 1)
        self.assertEqual(moved, ['current', 'recent', 'last', 'next'])
        self.assertEqual(index, 0)
        self.assertEqual(history, ['older', 'recent'])
        with self.assertRaises(ValueError):
            move_queue_or_history(queue, 0, history, [-9], 1)

    def test_dragging_history_into_empty_queue_starts_the_track(self):
        started = []
        client = object()
        player = SimpleNamespace(
            queue=[], index=-1, play_history=['played'], client=client,
            queue_album=None, stream_open=False, remote_opening=False,
            clear_remote_queue=Mock(), pulse_queue_icon=Mock(),
            shuffle=SimpleNamespace(get_active=lambda: False),
            start_track=lambda: started.append(True))
        self.assertTrue(Player.move_queue_indices(player, [-1], 0))
        self.assertEqual((player.queue, player.index, player.queue_client),
                         (['played'], 0, client))
        self.assertEqual(started, [True])

    def test_remove_selected_rows_tracks_current_or_next_index(self):
        remaining, index, removed_current = remove_items(
            ['a', 'b', 'c', 'd'], 2, [0, 1])
        self.assertEqual((remaining, index, removed_current), (['c', 'd'], 0, False))
        remaining, index, removed_current = remove_items(
            ['a', 'b', 'c', 'd'], 2, [1, 2])
        self.assertEqual((remaining, index, removed_current), (['a', 'd'], 1, True))
        self.assertEqual(remove_items(['a'], 0, [0]), ([], -1, True))

    def test_similar_selection_avoids_album_and_artist_runs(self):
        seed = Item('/library/metadata/1', 'Seed')
        clustered = [Item(f'/library/metadata/{index}', f'Cluster {index}',
                          artist='One Artist', album='One Album')
                     for index in range(2, 12)]
        varied = [Item(f'/library/metadata/{index}', f'Varied {index}',
                       artist=f'Artist {index}', album=f'Album {index}')
                  for index in range(12, 24)]
        chosen = select_similar_tracks(seed, clustered + varied)
        self.assertEqual(len(chosen), 10)
        self.assertEqual(len({(song.artist, song.album) for song in chosen}), 10)
        self.assertEqual(len({song.artist for song in chosen}), 10)

    def test_backspace_removes_selected_queue_rows(self):
        removed = []
        player = SimpleNamespace(selected_queue_indices=lambda: [1, 2],
                                 remove_queue_indices=removed.append)
        self.assertTrue(Player.queue_key_pressed(player, None,
                                                  SimpleNamespace(keyval=Gdk.KEY_BackSpace)))
        self.assertEqual(removed, [[1, 2]])

    def test_removing_current_track_advances_without_resuming_pause(self):
        tracks = [Item(f'/library/metadata/{index}', str(index)) for index in range(3)]
        started = []
        player = SimpleNamespace(
            queue=tracks, index=1, stream_open=True, remote_opening=False,
            playing=False, remote_container='old', remote_queue_id='7',
            remote_queue_version='1', remote_item_ids=('1',),
            start_track=lambda **options: started.append(options),
            status=SimpleNamespace(set_text=lambda _text: None),
        )
        Player.remove_queue_indices(player, [1])
        self.assertEqual([track.title for track in player.queue], ['0', '2'])
        self.assertEqual(player.index, 1)
        self.assertEqual(started, [{'resume_paused': True}])
        self.assertEqual(player.remote_queue_id, '')

    def test_enqueue_next_does_not_restart_current_stream(self):
        current = Item('/library/metadata/1', 'Current', album='Album')
        added = Item('/library/metadata/2', 'Next', album='Other')
        calls = []
        client = object()
        player = SimpleNamespace(
            client=client, queue_client=client, queue=[current], index=0,
            queue_album=Item('/library/metadata/10', 'Album'), stream_open=True,
            remote_opening=False,
            shuffle=SimpleNamespace(get_active=lambda: False),
            remote_container='old', remote_queue_id='7', remote_queue_version='1',
            remote_item_ids=('1',),
            refresh_queue_view=lambda: calls.append('refresh'),
            pulse_queue_icon=lambda: calls.append('pulse'),
            mpris=SimpleNamespace(changed=lambda: calls.append('mpris')),
            persist_session=lambda **_kw: calls.append('save'),
            start_track=lambda: calls.append('restart'),
            status=SimpleNamespace(set_text=lambda _text: None),
        )
        Player.enqueue_tracks(player, [added], play_next=True)
        self.assertEqual(player.queue, [current, added])
        self.assertEqual(player.index, 0)
        self.assertIsNone(player.queue_album)
        self.assertEqual(player.remote_queue_id, '')
        self.assertEqual(calls, ['pulse', 'refresh', 'mpris', 'save'])
        player.stream_open = False
        player.remote_opening = True
        Player.enqueue_tracks(player, [Item('/library/metadata/3', 'Later')])
        self.assertNotIn('restart', calls)

    def test_queue_right_click_uses_song_menu_and_keeps_selected_row(self):
        song = Item('/library/metadata/1', 'Song')
        selected = []
        selection = SimpleNamespace(path_is_selected=lambda _path: True,
                                    unselect_all=lambda: selected.append('clear'),
                                    select_path=lambda _path: selected.append('select'))
        view = SimpleNamespace(get_path_at_pos=lambda _x, _y: ('row', None, None, None),
                               get_selection=lambda: selection)
        menu_calls = []
        player = SimpleNamespace(queue=[song], queue_store={'row': [0]},
                                 show_song_context_menu=lambda *args: menu_calls.append(args),
                                 play_queue_track=lambda _index: None)
        event = SimpleNamespace(button=3, x=5, y=7)
        self.assertTrue(Player.queue_song_pressed(player, view, event))
        self.assertEqual(selected, [])
        self.assertEqual(menu_calls[0][:3], (event, song, 0))

    def test_sidebar_drop_accepts_only_loaded_current_server_media(self):
        track = Item('/library/metadata/2', 'Song')
        other = Item('/library/metadata/3', 'Other Song')
        album = Item('/library/metadata/10', 'Album')
        added = []
        player = SimpleNamespace(
            client=object(), albums=[album],
            resolve_loaded_tracks=lambda keys: ([{track.key: track, other.key: other}[key]
                                                  for key in keys]
                                                 if all(key in (track.key, other.key) for key in keys)
                                                 else []),
            enqueue_tracks=lambda tracks: added.append(('tracks', tracks)),
            enqueue_album=lambda item: added.append(('album', item)),
        )
        def drop(key, kind):
            selection = SimpleNamespace(get_data=lambda: key.encode())
            Player.queue_drop_received(player, None, None, 0, 0, selection, kind, 1)
        with patch('player.Gtk.drag_finish') as finish:
            drop(track.key + '\n' + other.key, 0)
            drop(album.key, 1)
            drop('/library/metadata/999', 1)
            drop('https://other.example/song', 0)
        self.assertEqual(added, [('tracks', [track, other]), ('album', album)])
        self.assertEqual([call.args[1] for call in finish.call_args_list],
                         [True, True, False, False])

    def test_queue_pointer_press_keeps_multi_selection_for_reorder(self):
        selection = SimpleNamespace(path_is_selected=lambda _path: True)
        view = SimpleNamespace(get_path_at_pos=lambda _x, _y: ('row', None, None, None),
                               get_selection=lambda: selection)
        player = SimpleNamespace(queue_store={'row': [1]},
                                 selected_queue_drag_indices=lambda: [1, 3])
        event = SimpleNamespace(button=1, x=8, y=12, state=0)
        self.assertFalse(Player.queue_song_pressed(player, view, event))
        self.assertEqual(player.queue_pointer_drag['indices'], [1, 3])

    def test_queue_pointer_can_start_dragging_a_history_row(self):
        selection = SimpleNamespace(path_is_selected=lambda _path: True)
        view = SimpleNamespace(get_path_at_pos=lambda _x, _y: ('row', None, None, None),
                               get_selection=lambda: selection)
        player = SimpleNamespace(queue_store={'row': [-1]},
                                 selected_queue_drag_indices=lambda: [-1])
        event = SimpleNamespace(button=1, x=8, y=12, state=0)
        self.assertFalse(Player.queue_song_pressed(player, view, event))
        self.assertEqual(player.queue_pointer_drag['indices'], [-1])

    def test_queue_checkbox_is_above_floating_player_bar(self):
        margins = []
        bar = SimpleNamespace(get_allocated_height=lambda: 140, get_visible=lambda: True)
        player = SimpleNamespace(keep_style_playing=SimpleNamespace(set_margin_bottom=margins.append),
                                 player_bar=bar, frosted_player_bar=True)
        Player.update_queue_bottom_inset(player)
        player.frosted_player_bar = False
        Player.update_queue_bottom_inset(player)
        self.assertEqual(margins, [156, 16])

    def test_settings_slider_scroll_is_forwarded_to_its_scroller(self):
        scroller = object()
        scale = SimpleNamespace(get_ancestor=lambda _kind: scroller)
        event = object()
        with patch('player.Gtk.propagate_event') as propagate:
            self.assertTrue(Player.ignore_settings_scale_scroll(scale, event))
        propagate.assert_called_once_with(scroller, event)

    def test_queue_pointer_reorders_selected_rows_together(self):
        tracks = [Item(f'/library/metadata/{index}', str(index)) for index in range(5)]
        changed = []
        markers = []
        view = SimpleNamespace(set_drag_dest_row=lambda *args: markers.append(args))
        player = SimpleNamespace(
            queue=tracks, index=2, queue_pointer_drag={
                'indices': [1, 3], 'x': 5, 'y': 5, 'active': False},
            queue_pointer_destination=lambda _view, _x, _y, show_marker=False: 5,
            show_song_drag_ghost=lambda *_args: None,
            hide_song_drag_ghost=lambda: None,
            hide_song_drop_line=lambda: None,
            clear_remote_queue=lambda: changed.append('clear'),
            shuffle=SimpleNamespace(get_active=lambda: False),
            refresh_queue_view=lambda: changed.append('refresh'),
            mpris=SimpleNamespace(changed=lambda: changed.append('mpris')),
            persist_session=lambda **_kwargs: changed.append('save'),
        )
        motion = SimpleNamespace(x=20, y=30, state=Gdk.ModifierType.BUTTON1_MASK)
        self.assertTrue(Player.queue_pointer_motion(player, view, motion))
        self.assertTrue(player.queue_pointer_drag['active'])
        self.assertTrue(Player.queue_pointer_release(
            player, view, SimpleNamespace(button=1, x=20, y=30)))
        self.assertEqual([track.title for track in player.queue], ['0', '2', '4', '1', '3'])
        self.assertEqual(player.index, 1)
        self.assertEqual(markers, [(None, Gtk.TreeViewDropPosition.BEFORE)])
        self.assertEqual(changed, ['clear', 'refresh', 'mpris', 'save'])

    def test_queue_pointer_destination_uses_queue_index_after_history(self):
        marks = []
        lines = []
        view = SimpleNamespace(
            get_path_at_pos=lambda _x, _y: ('next', None, None, None),
            get_background_area=lambda _path, _column: SimpleNamespace(y=20, height=20),
            set_drag_dest_row=lambda *args: marks.append(args))
        player = SimpleNamespace(queue_store={'next': [4]}, queue=[object()] * 5,
                                 index=2, play_history=[object()] * 2,
                                 show_song_drop_line=lambda _view, y: lines.append(y))
        self.assertEqual(Player.queue_pointer_destination(
            player, view, 12, 35, show_marker=True), 5)
        self.assertEqual(marks, [('next', Gtk.TreeViewDropPosition.AFTER)])
        self.assertEqual(lines, [40])

    def test_playlist_pointer_destination_draws_line_between_rows(self):
        marks = []
        lines = []
        path = Gtk.TreePath.new_from_indices([1])
        view = SimpleNamespace(
            get_path_at_pos=lambda _x, _y: (path, None, None, None),
            get_background_area=lambda _path, _column: SimpleNamespace(y=30, height=20),
            set_drag_dest_row=lambda *args: marks.append(args))
        player = SimpleNamespace(song_view=view, songs=[object()] * 3,
                                 show_song_drop_line=lambda _view, y: lines.append(y))
        self.assertEqual(Player.song_drop_position(player, 5, 45, True), 2)
        self.assertEqual(marks, [(path, Gtk.TreeViewDropPosition.AFTER)])
        self.assertEqual(lines, [50])

    def test_playlist_drop_adds_every_selected_track(self):
        tracks = [Item('/library/metadata/1', 'One'),
                  Item('/library/metadata/2', 'Two')]
        added = []
        client = SimpleNamespace(add_playlist_item=lambda playlist, track: added.append(track.key))
        player = SimpleNamespace(
            client=client, active_playlist=None, song_view_cache={},
            resolve_loaded_tracks=lambda keys: ([next(track for track in tracks if track.key == key)
                                                  for key in keys]
                                                 if all(any(track.key == key for track in tracks)
                                                        for key in keys) else []),
            song_count=SimpleNamespace(set_text=lambda _message: None),
            async_work=lambda work, done, valid, failed: done(work()) if valid() else None,
        )
        row = SimpleNamespace(playlist=SimpleNamespace(title='Mix'))
        selection = SimpleNamespace(get_data=lambda: b'/library/metadata/1\n/library/metadata/2')
        with patch('player.Gtk.drag_finish') as finish:
            Player.playlist_drop_received(player, row, None, 0, 0, selection, 0, 1)
        self.assertEqual(added, [track.key for track in tracks])
        self.assertTrue(finish.call_args.args[1])

    def test_playlist_tracks_can_be_copied_to_another_playlist(self):
        tracks = [Item('/library/metadata/1', 'One'),
                  Item('/library/metadata/2', 'Two')]
        destination = Item('/playlists/8/items', 'Destination')
        listing = SimpleNamespace(get_row_at_y=lambda _y: SimpleNamespace(playlist=destination))
        queue_button = object()
        player = SimpleNamespace(song_pointer_drag={'active': True, 'indices': [0, 1]},
                                 songs=tracks, playlist_list=listing, queue_nav=queue_button,
                                 hide_song_drag_ghost=Mock(), hide_song_drop_line=Mock(),
                                 add_tracks_to_playlist=Mock(),
                                 pointer_position_in=lambda widget, _event:
                                     (5, 10) if widget is listing else None)
        view = Mock()
        self.assertTrue(Player.song_pointer_release(player, view,
                                                     SimpleNamespace(button=1)))
        player.add_tracks_to_playlist.assert_called_once_with(destination, tracks)

    def test_queue_tracks_can_be_copied_to_a_playlist(self):
        song = Item('/library/metadata/1', 'One')
        destination = Item('/playlists/8/items', 'Destination')
        listing = SimpleNamespace(get_row_at_y=lambda _y: SimpleNamespace(playlist=destination))
        player = SimpleNamespace(queue_pointer_drag={'active': True, 'indices': [0]},
                                 queue=[song], play_history=[], playlist_list=listing,
                                 hide_song_drag_ghost=Mock(), hide_song_drop_line=Mock(),
                                 add_tracks_to_playlist=Mock(),
                                 pointer_position_in=lambda _widget, _event: (5, 10))
        self.assertTrue(Player.queue_pointer_release(player, Mock(), SimpleNamespace(button=1)))
        player.add_tracks_to_playlist.assert_called_once_with(destination, [song])
