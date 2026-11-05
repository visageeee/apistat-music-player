import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from player import Player


class SourceSelectorTests(unittest.TestCase):
    def make_player(self, client=None):
        source = {'id': 'a' * 32, 'name': 'Music', 'path': '/music'}
        server = SimpleNamespace(identifier='server-id', name='Server')
        player = SimpleNamespace(_updating_source_selector=False,
                                 source_config={'active': '', 'local': [source]},
                                 account_servers=[server], client=client,
                                 remote_server_machine='', connect_local_source=Mock(),
                                 connect_account_server=Mock(), restore_connection=Mock())
        return player, source, server

    def test_selecting_local_source_uses_its_saved_folder(self):
        player, source, _server = self.make_player()
        Player.source_selected(player, SimpleNamespace(get_active_id=lambda: 'local:' + source['id']))
        player.connect_local_source.assert_called_once_with(source)

    def test_selecting_account_server_uses_discovered_server(self):
        player, _source, server = self.make_player()
        Player.source_selected(player, SimpleNamespace(get_active_id=lambda: 'plex:server-id'))
        player.connect_account_server.assert_called_once_with(server)

    def test_switching_back_to_current_plex_does_not_restore_local_source(self):
        player, source, _server = self.make_player(SimpleNamespace(is_local=True, source={'id': 'a' * 32}))
        player.source_config['active'] = 'local:' + source['id']
        Player.source_selected(player, SimpleNamespace(get_active_id=lambda: 'plex:current'))
        self.assertEqual(player.source_config['active'], '')
        player.restore_connection.assert_called_once()

    def test_rebuilding_selector_does_not_change_source(self):
        player, source, _server = self.make_player()
        player._updating_source_selector = True
        Player.source_selected(player, SimpleNamespace(get_active_id=lambda: 'local:' + source['id']))
        player.connect_local_source.assert_not_called()


if __name__ == '__main__':
    unittest.main()
