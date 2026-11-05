import unittest
from collections import OrderedDict, deque
import weakref
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi
gi.require_version('Gst', '1.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gst, Gtk

from player import PAUSE_MARKER, Player
from album_card import FlipCard
import appearance
from plex_client import Item
from music_facets import MusicFacet
from test_smart_playlists import definition as smart_definition


class PlayerControlTests(unittest.TestCase):
    def test_queue_end_uses_same_style_only_when_enabled(self):
        calls = []
        player = SimpleNamespace(
            queue=[Item('/library/metadata/1', 'Current')], index=0,
            shuffle=SimpleNamespace(get_active=lambda: False),
            repeat=SimpleNamespace(get_active=lambda: False),
            keep_style_playing_enabled=True,
            style_autoplay_exhausted=False, style_autoplay_pending=False,
            style_autoplay_waiting=False,
            extend_queue_same_style=lambda: calls.append('extend'),
            start_track=lambda: calls.append('start'),
            stop=lambda: calls.append('stop'),
            status=SimpleNamespace(set_text=lambda _value: None))
        Player.advance(player)
        self.assertEqual(calls, ['extend'])
        self.assertTrue(player.style_autoplay_waiting)
        player.keep_style_playing_enabled = False
        Player.advance(player)
        self.assertEqual(calls[-1], 'stop')

    def test_same_mood_continuation_prefetches_without_skipping_current_song(self):
        current = Item('/library/metadata/1', 'Current')
        next_song = Item('/library/metadata/2', 'Next')
        facet = MusicFacet('mood', 'Calm', (('album.mood', 12),))
        client = SimpleNamespace(
            more_tracks_same_mood=lambda *_args, **_kwargs: (facet, [next_song]))
        calls = []
        player = SimpleNamespace(
            client=client, queue_client=client,
            library=SimpleNamespace(get_active_id=lambda: '2'),
            queue=[current], index=0, play_history=[], play_generation=0,
            style_autoplay_pending=False, style_autoplay_waiting=False,
            style_autoplay_exhausted=False, style_autoplay_generation=0,
            keep_style_playing_enabled=True,
            auto_style_facet=None, auto_style_keys=set(), queue_album=object(),
            remote_queue_id='old', remote_container='old', remote_queue_version='old',
            remote_item_ids=('old',),
            async_work=lambda work, done, valid, _failed: done(work()) if valid() else None,
            pulse_queue_icon=lambda: calls.append('pulse'),
            refresh_queue_view=lambda: calls.append('refresh'),
            mpris=SimpleNamespace(changed=lambda: calls.append('mpris')),
            persist_session=lambda **_kwargs: calls.append('save'),
            start_track=lambda: calls.append('start'),
            stop=lambda: calls.append('stop'),
            status=SimpleNamespace(set_text=lambda _value: None))
        cache = SimpleNamespace(read_music_facets=lambda _section: (facet,))
        with patch('player.LocalCache', return_value=cache):
            Player.extend_queue_same_style(player)
        self.assertEqual(player.queue, [current, next_song])
        self.assertEqual(player.index, 0)
        self.assertIsNone(player.queue_album)
        self.assertEqual(player.remote_queue_id, '')
        self.assertEqual(player.auto_style_facet, facet)
        self.assertEqual(calls, ['pulse', 'refresh', 'mpris', 'save'])
        player.queue = [current]
        player.style_autoplay_waiting = True
        player.auto_style_facet = None
        player.auto_style_keys.clear()
        with patch('player.LocalCache', return_value=cache):
            Player.extend_queue_same_style(player)
        self.assertEqual(player.index, 1)
        self.assertEqual(calls[-1], 'start')

    def test_last_song_start_triggers_prefetch_before_track_end(self):
        calls = []
        player = SimpleNamespace(
            queue=['first', 'last'], index=0, playing=True,
            keep_style_playing_enabled=True,
            repeat=SimpleNamespace(get_active=lambda: False),
            shuffle=SimpleNamespace(get_active=lambda: False),
            style_autoplay_pending=False, style_autoplay_exhausted=False,
            extend_queue_same_style=lambda: calls.append('prefetch'))
        Player.maybe_prefetch_same_style(player)
        self.assertEqual(calls, [])
        player.index = 1
        Player.maybe_prefetch_same_style(player)
        self.assertEqual(calls, ['prefetch'])

    def test_disabling_pending_prefetch_does_not_stop_playing_song(self):
        calls = []
        player = SimpleNamespace(
            keep_style_playing_enabled=True,
            auto_style_facet=object(), auto_style_keys={'song'},
            style_autoplay_generation=3, style_autoplay_pending=True,
            style_autoplay_waiting=False, style_autoplay_exhausted=False,
            stop=lambda: calls.append('stop'),
            status=SimpleNamespace(set_text=lambda _message: None))
        with patch('player.save_keep_style_playing_enabled'):
            Player.keep_style_playing_changed(
                player, SimpleNamespace(get_active=lambda: False))
        self.assertFalse(player.style_autoplay_pending)
        self.assertEqual(player.style_autoplay_generation, 4)
        self.assertEqual(calls, [])

    def test_filling_category_queue_preserves_current_and_history(self):
        facet = MusicFacet('mood', 'Calm', (('track.mood', 30),))
        history = Item('/library/metadata/1', 'Previous')
        current = Item('/library/metadata/2', 'Playing')
        old_next = Item('/library/metadata/3', 'Old next')
        new_songs = [Item(f'/library/metadata/{index}', f'New {index}')
                     for index in range(4, 29)]
        requests = []
        client = SimpleNamespace(music_facet_random_tracks=lambda section, selected,
                                 limit, excluded: (requests.append(
                                     (section, selected, limit, excluded)) or new_songs))
        changed = []
        player = SimpleNamespace(
            library=SimpleNamespace(get_active_id=lambda: '2'), client=client,
            style_queue_generation=0, play_generation=0, play_history=[history],
            async_work=lambda work, done, *_args: done(work()),
            queue=[history, current, old_next], index=1, stream_open=True,
            remote_opening=False, remote_queue_id='old',
            queue_client=client, queue_album=object(),
            pulse_queue_icon=lambda: changed.append('pulse'),
            refresh_queue_view=lambda: changed.append('refresh'),
            mpris=SimpleNamespace(changed=lambda: changed.append('mpris')),
            persist_session=lambda **_kwargs: changed.append('save'),
            start_track=lambda: changed.append('start'),
            status=SimpleNamespace(set_text=lambda value: changed.append(value)))
        Player.fill_style_queue(player, facet)
        self.assertEqual(player.queue, [history, current] + new_songs)
        self.assertEqual(player.index, 1)
        self.assertEqual(player.remote_queue_id, '')
        self.assertEqual(requests[0][:3], ('2', facet, 25))
        self.assertEqual(requests[0][3], {history.key, current.key})
        self.assertNotIn('start', changed)
        self.assertIn('refresh', changed)
        player.stream_open = False
        player.remote_opening = False
        Player.fill_style_queue(player, facet)
        self.assertEqual(player.queue, new_songs)
        self.assertEqual(player.index, 0)
        self.assertIn('start', changed)

    def test_skip_buttons_follow_queue_bounds_and_repeat(self):
        previous = Gtk.Button()
        next_button = Gtk.Button()
        player = SimpleNamespace(previous_button=previous, next_button=next_button,
                                 queue=[object(), object()], index=0,
                                 repeat=SimpleNamespace(get_active=lambda: False),
                                 shuffle=SimpleNamespace(get_active=lambda: False))
        Player.update_skip_buttons(player)
        self.assertFalse(previous.get_sensitive())
        self.assertTrue(next_button.get_sensitive())
        player.index = 1
        Player.update_skip_buttons(player)
        self.assertTrue(previous.get_sensitive())
        self.assertFalse(next_button.get_sensitive())
        player.repeat.get_active = lambda: True
        Player.update_skip_buttons(player)
        self.assertTrue(next_button.get_sensitive())
        player.queue = []
        Player.update_skip_buttons(player)
        self.assertFalse(previous.get_sensitive())
        self.assertFalse(next_button.get_sensitive())

    def test_sorted_library_header_has_highlight_and_direction_triangle(self):
        columns = {}
        for field in ('title', 'artist', 'added_at'):
            column = Gtk.TreeViewColumn(field)
            column.sort_arrow = Gtk.Label()
            column.sort_header = Gtk.EventBox()
            column.header_button = Gtk.Button()
            columns[field] = column
        player = SimpleNamespace(song_columns=columns, column_sort=('artist', False))
        Player.update_song_sort_headers(player)
        self.assertEqual(columns['artist'].sort_arrow.get_text(), '▲')
        self.assertTrue(columns['artist'].sort_arrow.get_visible())
        self.assertTrue(columns['artist'].header_button.get_style_context().has_class('sorted'))
        self.assertFalse(columns['title'].sort_arrow.get_visible())
        player.column_sort = 'artist', True
        Player.update_song_sort_headers(player)
        self.assertEqual(columns['artist'].sort_arrow.get_text(), '▼')
        player.column_sort = None
        Player.update_song_sort_headers(player)
        self.assertFalse(columns['artist'].sort_arrow.get_visible())
        self.assertFalse(columns['artist'].header_button.get_style_context().has_class('sorted'))
        player.song_sort = 'addedAt:desc'
        Player.update_song_sort_headers(player)
        self.assertEqual(columns['added_at'].sort_arrow.get_text(), '▼')
        self.assertTrue(columns['added_at'].header_button.get_style_context().has_class('sorted'))

    def test_sort_highlight_tracks_accent_and_queue_history_button_stays_clear(self):
        accent_provider = Gtk.CssProvider()
        sort_provider = Gtk.CssProvider()
        errors = []
        sort_provider.connect('parsing-error', lambda _provider, _section, error:
                              errors.append(error.message))
        player = SimpleNamespace(accent_provider=accent_provider,
                                 sort_provider=sort_provider,
                                 art_accent_enabled=False,
                                 current_art_bright=None,
                                 accent_color='#e7a641')
        Player.apply_accent(player)
        css = sort_provider.to_string()
        self.assertIn('rgba(231,166,65,0.22)', css)
        self.assertIn('rgba(231,166,65,0.78)', css)
        self.assertIn('#queue-history-more', css)
        self.assertIn('background-color: rgba(0,0,0,0)', css)
        player.art_accent_enabled = True
        player.current_art_bright = '#abcdef'
        Player.apply_accent(player)
        self.assertIn('rgba(171,205,239,0.22)', sort_provider.to_string())
        self.assertEqual(errors, [])

    def test_album_back_is_rendered_before_first_flip_without_changing_side(self):
        calls = []
        stack = SimpleNamespace(
            set_visible_child_name=lambda side: calls.append(('side', side)),
            get_visible_child=lambda: 'back widget',
            get_allocation=lambda: 'card allocation',
            size_allocate=lambda allocation: calls.append(('allocate', allocation)))
        card = SimpleNamespace(prepared=False, animating=False, side='front',
                               get_mapped=lambda: True, stack=stack,
                               snapshot=lambda widget: calls.append(('render', widget)))
        FlipCard.prepare(card)
        self.assertEqual(calls, [('side', 'back'), ('allocate', 'card allocation'),
                                 ('render', 'back widget'),
                                 ('side', 'front')])
        self.assertTrue(card.prepared)
        FlipCard.prepare(card)
        self.assertEqual(len(calls), 4)

    def test_track_widgets_wait_until_album_flip_finishes(self):
        tracks = [Item('/library/metadata/1', 'Track')]
        callbacks = []
        rendered = []
        client = object()
        card = SimpleNamespace(tracks=None, tracks_loading=False,
                               album=Item('/library/metadata/2', 'Album'),
                               flip_card=SimpleNamespace(animating=True),
                               pending_tracks=None, pending_tracks_error=False)
        player = SimpleNamespace(client=client, art_epoch=0,
                                 async_work=lambda _work, done, _valid, _error:
                                 callbacks.append(done),
                                 single_flip_enabled=False, last_flipped_tile=None,
                                 pending_flipped_tile=card,
                                 show_card_tracks=lambda _card, songs: rendered.append(songs))
        Player.load_card_tracks(player, card)
        callbacks[0](tracks)
        self.assertEqual(rendered, [])
        self.assertEqual(card.pending_tracks, tracks)
        card.flip_card.animating = False
        Player.album_side_shown(player, card, 'back')
        self.assertEqual(rendered, [tracks])
        self.assertIsNone(card.pending_tracks)

    def test_window_controls_follow_option_with_title_bar_visible(self):
        controls = Gtk.Box()
        buttons = [Gtk.Button(label=label) for label in ('−', '□', '×')]
        for button in buttons:
            controls.pack_start(button, False, False, 0)
        controls.set_no_show_all(True)
        controls.show_all()
        self.assertFalse(any(button.get_visible() for button in buttons))
        margins = []
        player = SimpleNamespace(window_buttons_enabled=True, hide_title_bar=False,
                                 window_controls=controls,
                                 busy_spinner=SimpleNamespace(set_margin_end=margins.append))
        Player.update_window_controls(player)
        self.assertTrue(controls.get_visible())
        self.assertTrue(all(button.get_visible() for button in buttons))
        self.assertEqual(margins, [90])
        player.window_buttons_enabled = False
        Player.update_window_controls(player)
        self.assertFalse(controls.get_visible())
        player.window_buttons_enabled = True
        Player.update_window_controls(player)
        self.assertTrue(all(button.get_visible() for button in buttons))

    def test_queue_shows_five_prior_tracks_in_dim_text_before_current(self):
        history = deque((Item(f'/library/metadata/{index}', f'Played {index}')
                         for index in range(6)), maxlen=5)
        queue = [Item('/library/metadata/20', 'Older queue item'),
                 Item('/library/metadata/21', 'Current'),
                 Item('/library/metadata/22', 'Next')]
        store = Gtk.ListStore(int, str, str, str, str, str, str, str, str, bool, str, str)
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
        player.playing = False
        Player.refresh_queue_view(player)
        self.assertEqual(store[5][1], PAUSE_MARKER)

    def test_queue_history_expands_and_numbers_from_current_track(self):
        history = deque((Item(f'/library/metadata/{index}', f'Played {index}')
                         for index in range(30)), maxlen=200)
        queue = [Item(f'/library/metadata/{index}', f'Queued {index}')
                 for index in range(4)]
        store = Gtk.ListStore(int, str, str, str, str, str, str, str, str, bool, str, str)
        visibility = []
        player = SimpleNamespace(
            queue_store=store, play_history=history, queue=queue, index=1,
            queue_history_visible=5, theme='dark', stream_open=True,
            remote_opening=False, playing=True,
            content_views=SimpleNamespace(get_visible_child_name=lambda: 'queue'),
            queue_count=SimpleNamespace(set_text=lambda _text: None),
            queue_history_button=SimpleNamespace(set_visible=visibility.append))
        Player.refresh_queue_view(player)
        rows = list(store)
        self.assertEqual([row[2] for row in rows[:5]],
                         [f'Played {index}' for index in range(25, 30)])
        self.assertEqual([row[1] for row in rows[5:]], ['▶', '2', '3'])
        self.assertEqual(visibility[-1], True)
        Player.show_more_previous_tracks(player, None)
        self.assertEqual([row[2] for row in list(store)[:25]],
                         [f'Played {index}' for index in range(5, 30)])
        self.assertEqual(store[0][0], -6)
        self.assertEqual(visibility[-1], True)
        Player.show_more_previous_tracks(player, None)
        self.assertEqual(len(store), 33)
        self.assertEqual(visibility[-1], False)

    def test_background_click_does_not_move_window_until_drag_threshold(self):
        moves = []
        player = SimpleNamespace(
            window_drag_start=None, can_drag_window_from=lambda _widget: True,
            begin_move_drag=lambda *args: moves.append(args))
        def event(x, y, state=Gdk.ModifierType.BUTTON1_MASK):
            return SimpleNamespace(button=1, x_root=x, y_root=y, time=123, state=state)
        with patch('player.Gtk.get_event_widget', return_value=object()):
            Player.background_drag_pressed(player, None, event(100, 100))
        self.assertEqual(moves, [])
        Player.background_drag_motion(player, None, event(104, 104))
        self.assertEqual(moves, [])
        Player.background_drag_released(player, None, event(104, 104))
        self.assertIsNone(player.window_drag_start)
        with patch('player.Gtk.get_event_widget', return_value=object()):
            Player.background_drag_pressed(player, None, event(100, 100))
        Player.background_drag_motion(player, None, event(108, 108))
        self.assertEqual(moves, [(1, 108, 108, 123)])

    def test_bottom_right_grip_starts_native_resize_instead_of_window_move(self):
        resize_calls = []
        player = SimpleNamespace(
            window_drag_start=(10, 10), is_maximized=lambda: False,
            begin_resize_drag=lambda *args: resize_calls.append(args))
        event = SimpleNamespace(button=1, x_root=400.8, y_root=300.2, time=123)
        self.assertTrue(Player.resize_grip_pressed(player, None, event))
        self.assertIsNone(player.window_drag_start)
        self.assertEqual(resize_calls, [
            (Gdk.WindowEdge.SOUTH_EAST, 1, 400, 300, 123)])
        player.is_maximized = lambda: True
        Player.resize_grip_pressed(player, None, event)
        self.assertEqual(len(resize_calls), 1)

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
            update_song_drag_mode=lambda: None,
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
        self.assertGreater(len(rows), 0)
        self.assertLessEqual(len(rows), 200)
        while scheduled[0]():
            pass
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
            update_song_drag_mode=lambda: None,
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
        key = (client, 'music', None, None, None, '', None)
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
            update_song_drag_mode=lambda: None,
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
        while scheduled[0]():
            pass
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
            order = ['queue', 'now', 'albums', 'styles', 'lyrics', 'settings', 'library']
            appearance.save_sidebar_order(order)
            self.assertEqual(appearance.load_sidebar_order(), order)
            with self.assertRaises(ValueError):
                appearance.save_sidebar_order(['now'] * 6)
            self.assertEqual(appearance.load_sidebar_order(), order)

    def test_sidebar_volume_scroll_clamps_and_reveals_level(self):
        values = []
        player = SimpleNamespace(volume=SimpleNamespace(get_value=lambda: .98),
                                 set_volume=values.append, show_sidebar_volume=Mock())
        self.assertTrue(Player.sidebar_volume_scroll(
            player, None, SimpleNamespace(direction=Gdk.ScrollDirection.UP)))
        self.assertEqual(values, [1])
        player.show_sidebar_volume.assert_called_once()
        smooth = SimpleNamespace(direction=Gdk.ScrollDirection.SMOOTH,
                                 get_scroll_deltas=lambda: (True, 0, .5))
        self.assertTrue(Player.sidebar_volume_scroll(player, None, smooth))
        self.assertAlmostEqual(values[-1], .955)

    def test_sidebar_volume_click_mutes_and_restores(self):
        value = [.6]
        player = SimpleNamespace(volume=SimpleNamespace(get_value=lambda: value[0]),
                                 set_volume=lambda v: value.__setitem__(0, v),
                                 sidebar_volume_restore=.8, show_sidebar_volume=Mock())
        Player.sidebar_volume_clicked(player)
        self.assertEqual(value[0], 0)
        Player.sidebar_volume_clicked(player)
        self.assertEqual(value[0], .6)
        self.assertEqual(player.show_sidebar_volume.call_count, 2)

    def test_sidebar_volume_indicator_uses_accent_and_level(self):
        context = Mock()
        widget = SimpleNamespace(get_allocated_width=lambda: 80,
                                 get_allocated_height=lambda: 200)
        player = SimpleNamespace(sidebar_volume_visible=True, sidebar_volume_opacity=1.0,
                                 volume=SimpleNamespace(get_value=lambda: .75),
                                 art_accent_enabled=False, accent_color='#ff8000')
        self.assertFalse(Player.draw_sidebar_volume(player, widget, context))
        context.rectangle.assert_called_once_with(0, 50, 80, 150)
        context.set_source_rgba.assert_called_once_with(1, 128 / 255, 0, .16)

    def test_sidebar_volume_fades_smoothly_and_stops(self):
        draws = Mock()
        player = SimpleNamespace(sidebar_volume_fade_start=None, sidebar_volume_opacity=1,
                                 sidebar_volume_visible=True, sidebar_volume_tick=42,
                                 sidebar_volume_indicator=SimpleNamespace(queue_draw=draws))
        clock = SimpleNamespace(get_frame_time=lambda: 1_000_000)
        self.assertTrue(Player.fade_sidebar_volume(player, None, clock))
        clock.get_frame_time = lambda: 1_250_000
        self.assertTrue(Player.fade_sidebar_volume(player, None, clock))
        self.assertAlmostEqual(player.sidebar_volume_opacity, .5)
        clock.get_frame_time = lambda: 1_500_000
        self.assertFalse(Player.fade_sidebar_volume(player, None, clock))
        self.assertFalse(player.sidebar_volume_visible)
        self.assertEqual(player.sidebar_volume_tick, 0)
        self.assertEqual(draws.call_count, 3)

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
                                 position_sidebar_volume=Mock(),
                                 nav_drop_root_y=lambda _widget, _x, _y: 500)
        with patch('player.save_sidebar_order') as save, \
                patch('player.Gtk.drag_finish') as finish:
            Player.nav_drag_data_received(player, object(), object(), 0, 0,
                                          SimpleNamespace(get_data=lambda: b'settings'), 2, 0)
        self.assertEqual(player.sidebar_order, ['now', 'settings', 'albums', 'library', 'queue'])
        self.assertEqual(moved[1], (buttons['settings'], 1))
        save.assert_called_once_with(player.sidebar_order)
        player.position_sidebar_volume.assert_called_once()
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
                              set_reveal_child=reveal, show=lambda: None)
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

    def test_search_shortcut_opens_and_respects_text_entry(self):
        entry = Gtk.Entry()
        player = SimpleNamespace(
            startup_loading=False, search_shortcut='Tab', get_focus=lambda: None,
            content_views=SimpleNamespace(get_visible_child_name=lambda: 'albums'),
            album_search_revealer=SimpleNamespace(get_reveal_child=lambda: False),
            toggle_album_search=Mock(), space_held=False)
        event = SimpleNamespace(keyval=Gdk.KEY_Tab, state=0)
        self.assertTrue(Player.global_key_pressed(player, None, event))
        player.toggle_album_search.assert_called_once()
        player.get_focus = lambda: entry
        self.assertFalse(Player.global_key_pressed(player, None, event))
        self.assertEqual(player.toggle_album_search.call_count, 1)
        player.get_focus = lambda: None
        player.search_shortcut = '<Control>f'
        self.assertFalse(Player.global_key_pressed(player, None, event))
        self.assertTrue(Player.global_key_pressed(
            player, None, SimpleNamespace(keyval=Gdk.KEY_f, state=Gdk.ModifierType.CONTROL_MASK)))
        self.assertEqual(player.toggle_album_search.call_count, 2)

    def test_search_shortcut_persists_and_recovers_from_invalid_settings(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(appearance, 'SETTINGS_PATH', Path(directory) / 'settings.json'):
            self.assertEqual(appearance.load_search_shortcut(), 'Tab')
            appearance.save_search_shortcut('<Control>f')
            self.assertEqual(appearance.load_search_shortcut(), '<Control>f')
            with self.assertRaises(ValueError):
                appearance.save_search_shortcut('not a key name')

    def test_album_search_slides_open_and_focuses_then_closes(self):
        state = [False]
        reveal = SimpleNamespace(get_reveal_child=lambda: state[0],
                                 set_reveal_child=lambda value: state.__setitem__(0, value))
        player = SimpleNamespace(content_views=SimpleNamespace(get_visible_child_name=lambda: 'albums'),
                                 album_search_revealer=reveal,
                                 views=SimpleNamespace(set_visible_child_name=Mock()),
                                 search=SimpleNamespace(grab_focus=Mock()),
                                 search_button=SimpleNamespace(grab_focus=Mock()))
        Player.toggle_album_search(player)
        self.assertTrue(state[0])
        player.search.grab_focus.assert_called_once()
        Player.toggle_album_search(player)
        self.assertFalse(state[0])
        player.search_button.grab_focus.assert_called_once()

    def test_album_header_reserves_search_height_without_extra_artist_gap(self):
        header = SimpleNamespace(get_visible=lambda: True, set_margin_start=Mock(),
                                 set_margin_top=Mock())
        surface = SimpleNamespace(get_margin_top=lambda: 36, set_margin_top=Mock())
        scrollbar = SimpleNamespace(set_margin_top=Mock())
        wall = SimpleNamespace(get_margin_top=lambda: 0, set_margin_top=Mock())
        player = SimpleNamespace(album_top=SimpleNamespace(get_allocated_height=lambda: 84),
                                 album_margin=40, album_wall=wall,
                                 gpu_wall=SimpleNamespace(render_surface=surface,
                                                          scrollbar=scrollbar),
                                 gpu_filter_header=header)
        Player.album_top_allocated(player)
        wall.set_margin_top.assert_called_once_with(124)
        header.set_margin_top.assert_called_once_with(88)
        surface.set_margin_top.assert_called_once_with(0)
        scrollbar.set_margin_top.assert_called_once_with(0)

    def test_now_album_click_opens_album_search_in_grid(self):
        actions = []
        player = SimpleNamespace(
            client=object(), index=0,
            queue=[Item('/library/metadata/2', 'Song', album='Blue Train')],
            queue_album=None, artist_filter='Old Artist', artist_catalog=[object()],
            search=SimpleNamespace(set_text=lambda value: actions.append(('search', value))),
            album_search_revealer=SimpleNamespace(
                set_reveal_child=lambda _value: actions.append('hide')),
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
        view = SimpleNamespace(get_path_at_pos=lambda *_: (row, artist_column, 0, 0),
                               get_selection=lambda: SimpleNamespace(
                                   path_is_selected=lambda _path: False))
        event = SimpleNamespace(button=1, x=10, y=10)
        player = SimpleNamespace(playlist_pointer_mode=lambda: False, songs=[object()])
        self.assertFalse(Player.library_artist_pressed(player, view, event))
        self.assertEqual(player.song_drag_candidate_indices, [0])

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

    def test_arrow_shortcuts_seek_with_bounds_and_skip_tracks(self):
        actions = []
        seek = SimpleNamespace(get_sensitive=lambda: True, get_value=lambda: 3,
                               get_adjustment=lambda: SimpleNamespace(get_upper=lambda: 6))
        player = SimpleNamespace(get_focus=lambda: None, seek=seek,
                                 seek_to=lambda _scale, _scroll, value: actions.append(value),
                                 previous=lambda: actions.append('previous'),
                                 advance=lambda: actions.append('next'))
        for key, state in ((Gdk.KEY_Left, 0), (Gdk.KEY_Right, 0),
                           (Gdk.KEY_Left, Gdk.ModifierType.CONTROL_MASK),
                           (Gdk.KEY_Right, Gdk.ModifierType.CONTROL_MASK)):
            self.assertTrue(Player.global_key_pressed(player, None,
                            SimpleNamespace(keyval=key, state=state)))
        self.assertEqual(actions, [0, 6, 'previous', 'next'])
        with patch('player.is_text_editing', return_value=True):
            self.assertFalse(Player.global_key_pressed(player, None,
                             SimpleNamespace(keyval=Gdk.KEY_Right, state=0)))
        self.assertEqual(actions, [0, 6, 'previous', 'next'])

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
        saved = []
        player = SimpleNamespace(
            stream_open=True, playing=True,
            pipeline=SimpleNamespace(set_state=states.append,
                                     get_state=lambda _timeout: (None, Gst.State.NULL, None),
                                     query_position=lambda _format: (True, 42500 * Gst.MSECOND)),
            set_play_button_state=lambda playing: None,
            refresh_live_waveform=lambda: None,
            mpris=SimpleNamespace(changed=lambda: None),
            refresh_playing_highlight=lambda: None,
            refresh_queue_view=lambda: None,
            song_view=SimpleNamespace(queue_draw=lambda: None),
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
