import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from player import Player


class OnboardingTests(unittest.TestCase):
    def test_missing_first_run_credentials_starts_account_setup(self):
        actions = []
        player = SimpleNamespace(
            first_run_setup=True,
            finish_startup_loading=lambda: actions.append('ready'),
            status=SimpleNamespace(set_text=lambda _text: None),
            async_work=lambda _work, done, **_kwargs: done(None),
            begin_first_run_setup=lambda: actions.append('account'),
            connect_dialog=lambda: actions.append('manual'))
        Player.restore_connection(player)
        self.assertEqual(actions, ['ready', 'account'])

    def test_first_account_connection_asks_for_music_library(self):
        class Dialog:
            def __init__(self, **_kwargs):
                self.box = Gtk.Box()

            def add_button(self, *_args):
                pass

            def set_default_response(self, *_args):
                pass

            def get_content_area(self):
                return self.box

            def show_all(self):
                pass

            def run(self):
                choices = next(child for child in self.box.get_children()
                               if isinstance(child, Gtk.ComboBoxText))
                choices.set_active_id('music-2')
                return Gtk.ResponseType.OK

            def destroy(self):
                pass

        player = SimpleNamespace(first_run_setup=True)
        with patch('player.Gtk.Dialog', Dialog):
            selected = Player.choose_initial_library(
                player, [('music-1', 'First library'), ('music-2', 'Second library')])
        self.assertEqual(selected, 'music-2')
        self.assertFalse(player.first_run_setup)


if __name__ == '__main__':
    unittest.main()
