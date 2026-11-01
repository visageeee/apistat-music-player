import unittest
import weakref
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


if __name__ == '__main__':
    unittest.main()
