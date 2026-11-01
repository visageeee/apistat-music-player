import unittest
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
from plex_client import Item


class PlayerControlTests(unittest.TestCase):
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
