import unittest
from collections import OrderedDict, deque
import weakref
import threading
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gst', '1.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gst, Gtk

from player import Player
import appearance
from plex_client import Item
from test_smart_playlists import definition as smart_definition


class PlayerControlTests(unittest.TestCase):
    def test_window_controls_follow_option_with_title_bar_visible(self):
        shown = []
        margins = []
        player = SimpleNamespace(window_buttons_enabled=True, hide_title_bar=False,
                                 window_controls=SimpleNamespace(set_visible=shown.append),
                                 busy_spinner=SimpleNamespace(set_margin_end=margins.append))
        Player.update_window_controls(player)
        self.assertEqual((shown, margins), ([True], [90]))

    def test_queue_shows_five_prior_tracks_in_dim_text_before_current(self):
        history = deque((Item(f'/library/metadata/{index}', f'Played {index}')
                         for index in range(6)), maxlen=5)
        queue = [Item('/library/metadata/20', 'Older queue item'),
                 Item('/library/metadata/21', 'Current'),
                 Item('/library/metadata/22', 'Next')]
        store = Gtk.ListStore(int, str, str, str, str, str, str, str, str, bool, str)
        labels = []
        player = SimpleNamespace(
            queue_store=store, play_history=history, queue=queue, index=1,
            theme='dark', stream_open=True, remote_opening=False,
            content_views=SimpleNamespace(get_visible_child_name=lambda: 'queue'),
            queue_count=SimpleNamespace(set_text=labels.append))
        Player.refresh_queue_view(player)
        rows = list(store)
        self.assertEqual(len(rows), 7)
        self.assertEqual([row[2] for row in rows[:5]],
                         [f'Played {index}' for index in range(1, 6)])
        self.assertTrue(all(row[9] and row[10] == '#7a7a7a' for row in rows[:5]))
        self.assertEqual([row[2] for row in rows[5:]], ['Current', 'Next'])
        self.assertIn('5 previously played', labels[-1])

    def test_smart_playlist_filters_catalog_before_library_display(self):
        client = object()
        songs = [Item('/library/metadata/1', 'Blue', genre='Jazz', user_rating=10),
                 Item('/library/metadata/2', 'Other', genre='Jazz', user_rating=0),
                 Item('/library/metadata/3', 'Rock', genre='Rock', user_rating=10)]
        shown = []
        player = SimpleNamespace(
            client=client, library=SimpleNamespace(get_active_id=lambda: 'music'),
            active_playlist=None, active_smart_playlist=smart_definition(checked_only=True),
            library_album_filter=None, library_search=SimpleNamespace(get_text=lambda: ''),
            song_generation=0, song_store=object(),
            song_view=SimpleNamespace(set_model=lambda _model: None),
            song_view_cache=OrderedDict(), song_view_key=None,
            song_catalog_source=(client, 'music', None, None), song_catalog=songs,
            effective_library_sort=lambda: None,
            display_song_page=lambda results, *_args: shown.extend(results))
        Player.load_songs(player)
        self.assertEqual([song.key for song in shown], ['/library/metadata/1'])

    def test_theme_styles_parse_and_cover_selection_and_hover_states(self):
        for theme in ('black', 'light'):
            provider = Gtk.CssProvider()
            errors = []
            provider.connect('parsing-error', lambda _provider, _section, error:
                             errors.append(error.message))
            Player.apply_theme(SimpleNamespace(theme=theme, theme_provider=provider))
            self.assertEqual(errors, [])
            css = provider.to_string()
            for selector in ('#song-view', '#queue-view', '#album-track-view'):
                self.assertTrue(f'{selector}:selected.view' in css or
                                f'{selector}.view:selected' in css)
        self.assertIn('#album-sort-bar button:hover', css)
        self.assertIn('#song-view header button:hover', css)
        self.assertIn('#settings-tabs header tab:hover', css)

    def test_escape_returns_from_album_search_and_library_filter(self):
        actions = []
        album_player = SimpleNamespace(
            content_views=SimpleNamespace(get_visible_child_name=lambda: 'albums'),
            views=SimpleNamespace(get_visible_child_name=lambda: 'wall'),
            artist_filter=None, search=SimpleNamespace(get_text=lambda: 'Blue'),
            show_all_albums=lambda: actions.append('albums'))
        self.assertTrue(Player.escape_search(album_player))
        library_player = SimpleNamespace(
            content_views=SimpleNamespace(get_visible_child_name=lambda: 'library'),
            library_album_filter=None,
            library_search=SimpleNamespace(get_text=lambda: 'Miles',
                                           set_text=lambda value: actions.append(('filter', value))))
        self.assertTrue(Player.escape_search(library_player))
        self.assertEqual(actions, ['albums', ('filter', '')])

    def test_large_song_list_appends_in_idle_batches(self):
        songs = [Item(f'/library/metadata/{index}', f'Song {index}') for index in range(450)]
        scheduled = []
        rows = []
        messages = []
        changed = []
        player = SimpleNamespace(song_generation=1, closed=False, songs=[], song_total=0,
                                 song_store=SimpleNamespace(append=rows.append),
                                 song_column_value=lambda song, _field: song.title,
                                 song_count=SimpleNamespace(set_text=messages.append),
                                 mpris=SimpleNamespace(changed=lambda: changed.append(True)),
                                 effective_library_sort=lambda: None)
        with patch('player.GLib.idle_add', side_effect=lambda callback: scheduled.append(callback)):
            Player.display_song_page(player, songs, len(songs), None, None, '')
        self.assertEqual(len(rows), 0)
        self.assertTrue(scheduled[0]())
        self.assertEqual(len(rows), 200)
        self.assertTrue(scheduled[0]())
        self.assertFalse(scheduled[0]())
        self.assertEqual(len(rows), 450)
        self.assertEqual(messages[-1], '450 of 450 songs')
        self.assertEqual(changed, [True])

    def test_stale_song_batch_stops_when_view_changes(self):
        scheduled = []
        rows = []
        player = SimpleNamespace(song_generation=1, closed=False, songs=[], song_total=0,
                                 song_store=SimpleNamespace(append=rows.append),
                                 song_column_value=lambda song, _field: song.title,
                                 song_count=SimpleNamespace(set_text=lambda _text: None),
                                 mpris=SimpleNamespace(changed=lambda: None))
        songs = [Item(f'/library/metadata/{index}', 'Song') for index in range(250)]
        with patch('player.GLib.idle_add', side_effect=lambda callback: scheduled.append(callback)):
            Player.display_song_page(player, songs, len(songs), None, None, '')
        player.song_generation = 2
        self.assertFalse(scheduled[0]())
        self.assertEqual(rows, [])

    def test_large_catalog_sorts_in_background(self):
        client = object()
        scheduled = []
        source = (client, 'music', None, None)
        player = SimpleNamespace(
            client=client, library=SimpleNamespace(get_active_id=lambda: 'music'),
            active_playlist=None, library_album_filter=None,
            library_search=SimpleNamespace(get_text=lambda: ''),
            song_generation=0, song_store=SimpleNamespace(clear=lambda: None),
            song_view=SimpleNamespace(set_model=lambda _model: None),
            song_view_cache=OrderedDict(), song_view_key=None,
            song_catalog_source=source,
            song_catalog=[Item(f'/library/metadata/{index}', 'Song') for index in range(2001)],
            effective_library_sort=lambda: None,
            song_count=SimpleNamespace(set_text=lambda _text: None),
            async_work=lambda work, done, valid: scheduled.append((work, done, valid)))
        Player.load_songs(player)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(player.songs, [])
        self.assertTrue(scheduled[0][2]())

    def test_returning_to_loaded_list_reuses_gtk_model(self):
        client = object()
        song = Item('/library/metadata/1', 'Cached')
        model = object()
        key = (client, 'music', None, None, '', None)
        displayed = []
        player = SimpleNamespace(
            client=client, library=SimpleNamespace(get_active_id=lambda: 'music'),
            active_playlist=None, library_album_filter=None,
            library_search=SimpleNamespace(get_text=lambda: ''),
            song_generation=0, song_view_cache=OrderedDict([(key, {
                'store': model, 'rows': [song], 'results': [song],
                'total': 1, 'message': '1 of 1 songs', 'built_at': float('inf')})]),
            song_store=object(),
            song_view=SimpleNamespace(set_model=displayed.append),
            song_catalog_source=None, song_catalog=None,
            effective_library_sort=lambda: None,
            song_count=SimpleNamespace(set_text=displayed.append),
            start_song_catalog=lambda *_args: self.fail('Requeried server'),
            async_work=lambda *_args: self.fail('Resorted list'))
        Player.load_songs(player)
        self.assertEqual(displayed, [model, '1 of 1 songs'])
        self.assertEqual(player.songs, [song])

    def test_returning_to_partial_list_resumes_existing_rows(self):
        songs = [Item(f'/library/metadata/{index}', 'Song') for index in range(450)]
        rows = [object() for _ in range(200)]
        scheduled = []
        player = SimpleNamespace(song_generation=2, closed=False, songs=list(songs[:200]),
                                 song_total=0, song_store=SimpleNamespace(append=rows.append),
                                 song_column_value=lambda song, _field: song.title,
                                 song_count=SimpleNamespace(set_text=lambda _text: None),
                                 mpris=SimpleNamespace(changed=lambda: None),
                                 song_view_cache={}, song_view_key=None,
                                 effective_library_sort=lambda: None)
        with patch('player.GLib.idle_add', side_effect=lambda callback: scheduled.append(callback)):
            Player.display_song_page(player, songs, len(songs), None, None, '')
        self.assertTrue(scheduled[0]())
        self.assertFalse(scheduled[0]())
        self.assertEqual(len(rows), 450)

    def test_number_keys_follow_sidebar_order(self):
        opened = []
        player = SimpleNamespace(get_focus=lambda: None,
                                 sidebar_order=['queue', 'now', 'albums', 'settings', 'library'],
                                 show_view=opened.append)
        for number in range(1, 6):
            event = SimpleNamespace(keyval=getattr(Gdk, f'KEY_{number}'), state=0)
            self.assertTrue(Player.global_key_pressed(player, None, event))
        self.assertEqual(opened, player.sidebar_order)

    def test_sidebar_order_persists_and_rejects_invalid_order(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            order = ['queue', 'now', 'albums', 'settings', 'library']
            appearance.save_sidebar_order(order)
            self.assertEqual(appearance.load_sidebar_order(), order)
            with self.assertRaises(ValueError):
                appearance.save_sidebar_order(['now'] * 5)
            self.assertEqual(appearance.load_sidebar_order(), order)

    def test_sidebar_drop_reorders_even_on_empty_surface(self):
        order = ['now', 'albums', 'library', 'queue', 'settings']
        moved = []
        buttons = {name: object() for name in order}
        player = SimpleNamespace(nav_buttons=buttons, sidebar_order=order,
                                 nav_drag_source='settings', nav_drag_insert=1,
                                 nav_drag_completed=False,
                                 sidebar_spacer=object(),
                                 nav_drop_gap=SimpleNamespace(set_reveal_child=lambda _value: None),
                                 sidebar=SimpleNamespace(reorder_child=lambda button, index:
                                                         moved.append((button, index))),
                                 status=SimpleNamespace(set_text=lambda _text: None),
                                 update_nav_drag=lambda _y: None,
                                 nav_drop_root_y=lambda _widget, _x, _y: 500)
        with patch('player.save_sidebar_order') as save, \
                patch('player.Gtk.drag_finish') as finish:
            Player.nav_drag_data_received(player, object(), object(), 0, 0,
                                          SimpleNamespace(get_data=lambda: b'settings'), 2, 0)
        self.assertEqual(player.sidebar_order, ['now', 'settings', 'albums', 'library', 'queue'])
        self.assertEqual(moved[1], (buttons['settings'], 1))
        save.assert_called_once_with(player.sidebar_order)
        finish.assert_called_once()

    def test_sidebar_drag_uses_vertical_root_coordinates(self):
        order = ['now', 'albums', 'library', 'queue', 'settings']
        buttons = {name: SimpleNamespace(
            translate_coordinates=lambda _parent, _x, _y, index=index:
                (True, 12, 40 + index * 60),
            get_allocated_height=lambda: 40)
            for index, name in enumerate(order)}
        buttons['now'].get_image = lambda: SimpleNamespace(
            get_icon_name=lambda: ('media-playback-start-symbolic', None))
        buttons['now'].set_opacity = lambda _opacity: None
        player = SimpleNamespace(sidebar_order=order, nav_buttons=buttons,
                                 nav_drag_insert=None,
                                 get_window=lambda: SimpleNamespace(get_origin=lambda: (1, 50, 100)))
        player.nav_drop_root_y = lambda widget, x, y: Player.nav_drop_root_y(player, widget, x, y)
        with patch('player.Gtk.drag_set_icon_name'):
            Player.nav_drag_begin(player, buttons['now'], object(), 'now')
        self.assertEqual(player.nav_drag_centers, [200, 260, 320, 380])

    def test_sidebar_coordinates_accept_two_value_pygobject_tuple(self):
        player = SimpleNamespace(get_window=lambda: SimpleNamespace(
            get_origin=lambda: (50, 100)))
        widget = SimpleNamespace(translate_coordinates=lambda *_args: (12, 80))
        self.assertEqual(Player.nav_drop_root_y(player, widget, 0, 20), 180)

    def test_hide_shortcut_hides_sidebar_overlay(self):
        changed = []
        player = SimpleNamespace(get_focus=lambda: None,
                                 sidebar_drop_surface=SimpleNamespace(get_visible=lambda: True,
                                                                      set_visible=lambda visible:
                                                                      changed.append(('sidebar', visible))),
                                 player_bar=SimpleNamespace(set_visible=lambda visible:
                                                            changed.append(('bar', visible))))
        self.assertTrue(Player.global_key_pressed(
            player, None, SimpleNamespace(keyval=Gdk.KEY_f, state=0)))
        self.assertEqual(changed, [('sidebar', False), ('bar', False)])

    def test_sidebar_drag_updates_gap_while_pointer_is_between_buttons(self):
        order = ['now', 'albums', 'library', 'queue', 'settings']
        buttons = {name: object() for name in order}
        changes = []
        revealed = [False]
        def reveal(visible):
            revealed[0] = visible
            changes.append(('gap', visible))
        gap = SimpleNamespace(get_reveal_child=lambda: revealed[0],
                              set_reveal_child=reveal)
        children = list(buttons.values()) + [gap]
        def reorder(child, index):
            children.remove(child)
            children.insert(index, child)
            changes.append(('move', child, index))
        player = SimpleNamespace(
            nav_drag_source='settings', nav_drag_insert=None,
            nav_drag_centers=[100, 160, 220, 280], sidebar_order=order,
            nav_buttons=buttons, nav_drop_gap=gap,
            sidebar=SimpleNamespace(get_children=lambda: list(children),
                                    reorder_child=reorder),
            get_window=lambda: SimpleNamespace(get_origin=lambda: (1, 0, 0)))
        Player.update_nav_drag(player, 190)
        Player.update_nav_drag(player, 190)
        self.assertEqual(player.nav_drag_insert, 2)
        self.assertEqual(changes, [('move', gap, 2), ('gap', True)])

    def test_scrubbing_updates_visible_fill_before_seeking(self):
        events = []
        scale = SimpleNamespace(set_value=lambda value: events.append(('fill', value)))
        player = SimpleNamespace(seek_mpris=lambda value: events.append(('seek', value)),
                                 timeline_seek_source=0, pending_timeline_seek=None,
                                 flush_timeline_seek=lambda: None)
        with patch('player.GLib.timeout_add', return_value=42):
            self.assertTrue(Player.seek_to(player, scale, None, 42.5))
        self.assertEqual(events, [('fill', 42.5)])
        self.assertEqual(player.pending_timeline_seek, 42.5)
        self.assertFalse(Player.flush_timeline_seek(player))
        self.assertEqual(events, [('fill', 42.5), ('seek', 42500000)])

    def test_waveform_timeline_click_maps_to_song_position(self):
        values = []
        scale = SimpleNamespace(get_sensitive=lambda: True,
                                get_adjustment=lambda: SimpleNamespace(get_upper=lambda: 120.0))
        player = SimpleNamespace(seek=scale,
                                 seek_to=lambda _scale, _scroll, value: values.append(value))
        widget = SimpleNamespace(get_allocated_width=lambda: 400)
        Player.wave_timeline_scrub(player, widget, 100)
        self.assertEqual(values, [30.0])

    def test_timeline_hover_clamps_marker_and_clears_on_leave(self):
        classes = set()
        redraws = []
        style = SimpleNamespace(add_class=classes.add, remove_class=classes.discard)
        widget = SimpleNamespace(get_allocated_width=lambda: 100,
                                 get_style_context=lambda: style)
        widget.queue_draw = lambda: redraws.append(True)
        player = SimpleNamespace(timeline_hover_x=None)
        Player.timeline_motion(player, widget, SimpleNamespace(x=180))
        self.assertEqual(player.timeline_hover_x, 99)
        self.assertIn('hovering', classes)
        Player.timeline_leave(player, widget, None)
        self.assertIsNone(player.timeline_hover_x)
        self.assertNotIn('hovering', classes)
        self.assertEqual(len(redraws), 2)

    def test_now_album_click_opens_album_search_in_grid(self):
        actions = []
        player = SimpleNamespace(
            client=object(), index=0,
            queue=[Item('/library/metadata/2', 'Song', album='Blue Train')],
            queue_album=None, artist_filter='Old Artist', artist_catalog=[object()],
            search=SimpleNamespace(set_text=lambda value: actions.append(('search', value))),
            album_toolbar=SimpleNamespace(hide=lambda: actions.append('hide')),
            show_view=lambda view: actions.append(('view', view)),
            load_albums=lambda: actions.append('load'))
        self.assertTrue(Player.now_album_pressed(player, None, SimpleNamespace(button=1)))
        self.assertEqual(actions, [('search', 'Blue Train'), 'hide', ('view', 'albums'), 'load'])
        self.assertIsNone(player.artist_filter)

    def test_album_scroll_loads_next_page_once_near_bottom(self):
        calls = []
        position = [700]
        adjustment = SimpleNamespace(get_upper=lambda: 1000,
                                     get_value=lambda: position[0],
                                     get_page_size=lambda: 200)
        player = SimpleNamespace(
            loading_albums=False, albums=[object()] * 100, total=250,
            content_views=SimpleNamespace(get_visible_child_name=lambda: 'albums'),
            views=SimpleNamespace(get_visible_child_name=lambda: 'wall'),
            wall_scroll=SimpleNamespace(get_vadjustment=lambda: adjustment),
            load_albums=lambda more: calls.append(more))
        Player.maybe_load_more_albums(player)
        self.assertEqual(calls, [])
        position[0] = 705
        Player.maybe_load_more_albums(player)
        self.assertEqual(calls, [True])
        player.loading_albums = True
        Player.maybe_load_more_albums(player)
        self.assertEqual(calls, [True])
        player.loading_albums = False
        player.total = len(player.albums)
        Player.maybe_load_more_albums(player)
        self.assertEqual(calls, [True])

    def test_library_artist_left_click_keeps_current_view(self):
        row = Gtk.TreePath.new_from_indices([0])
        artist_column = Gtk.TreeViewColumn('Artist')
        view = SimpleNamespace(get_path_at_pos=lambda *_: (row, artist_column, 0, 0))
        event = SimpleNamespace(button=1, x=10, y=10)
        self.assertFalse(Player.library_artist_pressed(SimpleNamespace(), view, event))

    def test_hidden_tooltips_stay_hidden_when_dynamic_text_changes(self):
        root = Gtk.Box()
        button = Gtk.Button()
        root.add(button)
        root.tooltip_texts = weakref.WeakKeyDictionary()
        root.desktop_tooltips_enabled = True
        root.tooltips_hidden = False
        settings = Gtk.Settings.get_default()
        previous = settings.get_property('gtk-enable-tooltips')
        try:
            Player.set_tooltip(root, button, 'Play')
            self.assertTrue(button.get_has_tooltip())
            root.tooltips_hidden = True
            Player.apply_tooltip_setting(root)
            self.assertFalse(button.get_has_tooltip())
            Player.set_tooltip(root, button, 'Pause')
            self.assertFalse(button.get_has_tooltip())
            root.tooltips_hidden = False
            Player.apply_tooltip_setting(root)
            self.assertEqual(button.get_tooltip_text(), 'Pause')
            self.assertTrue(button.get_has_tooltip())
        finally:
            settings.set_property('gtk-enable-tooltips', previous)

    def test_compact_artist_action_opens_that_artist(self):
        opened = []
        player = SimpleNamespace(index=0,
                                 queue=[Item('/library/metadata/1', 'Song', artist='Coltrane')],
                                 show_artist_albums=opened.append)
        Player.show_current_artist_albums(player)
        self.assertEqual(opened, ['Coltrane'])

    def test_timeline_interpolates_between_pipeline_samples(self):
        values = []
        player = SimpleNamespace(closed=False, stream_open=True, playing=True,
                                 timeline_duration=120.0, timeline_dragging=False,
                                 timeline_base_position=10.0, timeline_base_time=100.0,
                                 seek=SimpleNamespace(set_value=values.append))
        with patch('player.time.monotonic', return_value=100.125):
            self.assertTrue(Player.animate_timeline(player))
        self.assertAlmostEqual(values[0], 10.125)

    def test_space_toggles_once_per_key_press_even_with_search_focus(self):
        toggles = []
        player = SimpleNamespace(space_held=False, toggle=lambda: toggles.append(True),
                                 get_focus=lambda: object())
        event = SimpleNamespace(keyval=Gdk.KEY_space, state=0)
        self.assertTrue(Player.global_key_pressed(player, None, event))
        self.assertTrue(Player.global_key_pressed(player, None, event))
        self.assertEqual(toggles, [True])
        self.assertTrue(Player.global_key_released(player, None, event))
        self.assertTrue(Player.global_key_pressed(player, None, event))
        self.assertEqual(toggles, [True, True])

    def test_previous_card_waits_until_next_card_finishes_flipping(self):
        calls = []
        first_flip = SimpleNamespace(show_side=lambda side: calls.append(('first', side)))
        second_flip = SimpleNamespace(side='front', animating=False,
                                      show_side=lambda side: calls.append(('second', side)))
        first = SimpleNamespace(flip_card=first_flip)
        second = SimpleNamespace(flip_card=second_flip)
        player = SimpleNamespace(single_flip_enabled=True, last_flipped_tile=first,
                                 pending_flipped_tile=None,
                                 grid=SimpleNamespace(get_children=lambda: [
                                     SimpleNamespace(get_child=lambda: first),
                                     SimpleNamespace(get_child=lambda: second)]),
                                 load_card_tracks=lambda tile: None)

        Player.flip_album_card(player, second)
        self.assertEqual(calls, [('second', 'back')])
        self.assertIs(player.last_flipped_tile, first)
        Player.album_side_shown(player, second, 'back')
        self.assertEqual(calls, [('second', 'back'), ('first', 'front')])
        self.assertIs(player.last_flipped_tile, second)

    def test_clicking_card_track_plays_it_in_album_order(self):
        album = Item('/library/metadata/10', 'Album')
        tracks = [Item('/library/metadata/20', 'First'),
                  Item('/library/metadata/21', 'Second')]
        started = []
        client = object()
        player = SimpleNamespace(client=client, start_track=lambda: started.append(True))
        card = SimpleNamespace(album=album, tracks=tracks)

        Player.play_card_track(player, card, 1)

        self.assertEqual(player.queue, tracks)
        self.assertIs(player.queue_album, album)
        self.assertIs(player.queue_client, client)
        self.assertEqual(player.index, 1)
        self.assertEqual(started, [True])

    def test_pause_while_gstreamer_still_reports_null_does_not_restart(self):
        states = []
        restarts = []
        paused_waves = []
        saved = []
        player = SimpleNamespace(
            stream_open=True, playing=True,
            pipeline=SimpleNamespace(set_state=states.append,
                                     get_state=lambda _timeout: (None, Gst.State.NULL, None),
                                     query_position=lambda _format: (True, 42500 * Gst.MSECOND)),
            set_play_button_state=lambda playing: None,
            waveform=SimpleNamespace(pause=lambda: paused_waves.append(True)),
            mpris=SimpleNamespace(changed=lambda: None),
            persist_session=lambda **kwargs: saved.append(kwargs),
            queue=['track'],
            start_track=lambda: restarts.append(True),
            play_album=lambda _index: restarts.append(True),
        )
        player.toggle = lambda: Player.toggle(player)

        Player.pause(player)

        self.assertFalse(player.playing)
        self.assertEqual(states, [Gst.State.PAUSED])
        self.assertEqual(restarts, [])
        self.assertEqual(paused_waves, [True])
        self.assertEqual(player.playback_position_ms, 42500)
        self.assertEqual(saved, [{'force': True}])

    def test_remote_media_uses_same_queue_and_start_offset(self):
        tracks = [Item('/library/metadata/20', 'First'),
                  Item('/library/metadata/21', 'Second')]
        media = SimpleNamespace(tracks=tracks, index=1, offset=4300,
                                container_key='/playQueues/7', queue_id='7',
                                queue_version='2', item_ids=('10', '11'))
        client = object()
        starts = []
        player = SimpleNamespace(closed=False, remote_config={'enabled': True},
                                 client=client,
                                 remote_receiver=SimpleNamespace(server_client=client),
                                 start_track=lambda **kwargs: starts.append(kwargs),
                                 remote_snapshot=lambda: {'state': 'buffering'})
        with patch('player.GLib.idle_add', side_effect=lambda callback: callback()):
            result = Player.apply_remote_command(player, 'playMedia', {}, media)
        self.assertEqual(result['state'], 'buffering')
        self.assertEqual((player.queue, player.index, player.queue_client),
                         (tracks, 1, client))
        self.assertEqual((player.remote_queue_id, player.remote_item_ids),
                         ('7', ('10', '11')))
        self.assertEqual(starts, [{'resume_position_ms': 4300}])

    def test_remote_transport_seek_and_volume_use_local_controls(self):
        calls = []
        player = SimpleNamespace(closed=False, remote_config={'enabled': True},
                                 stream_open=False, queue=['track'],
                                 play=lambda: calls.append('play'),
                                 pause=lambda: calls.append('pause'),
                                 stop=lambda: calls.append('stop'),
                                 persist_session=lambda **_kwargs: None,
                                 advance=lambda: calls.append('next'),
                                 previous=lambda: calls.append('previous'),
                                 set_volume=lambda value: calls.append(('volume', value)),
                                 remote_snapshot=lambda: {'state': 'paused'})
        with patch('player.GLib.idle_add', side_effect=lambda callback: callback()):
            for action in ('play', 'pause', 'stop', 'skipNext', 'skipPrevious'):
                Player.apply_remote_command(player, action, {}, None)
            Player.apply_remote_command(player, 'seekTo', {'offset': 42000}, None)
            Player.apply_remote_command(player, 'setParameters', {'volume': 37}, None)
        self.assertEqual(calls, ['play', 'pause', 'stop', 'next', 'previous',
                                 ('volume', 0.37)])
        self.assertEqual((player.pending_resume_seek_ms, player.playback_position_ms),
                         (42000, 42000))

    def test_remote_token_can_be_authorized_by_configured_plex_server(self):
        player = SimpleNamespace(client=SimpleNamespace(address='http://plex.local:32400',
                                                        token='desktop-token'),
                                 remote_config={'identifier': 'player', 'name': 'Linux'},
                                 remote_link_user='owner', remote_token_cache={},
                                 remote_token_lock=threading.Lock())
        self.assertTrue(Player.verify_remote_token(player, 'desktop-token'))
        with patch('player.PlexClient') as client_class:
            client_class.return_value.sections.return_value = [('1', 'Music')]
            self.assertTrue(Player.verify_remote_token(player, 'phone-server-token'))
            client_class.assert_called_once_with('http://plex.local:32400',
                                                 'phone-server-token', 'player', 'Linux')


if __name__ == '__main__':
    unittest.main()
