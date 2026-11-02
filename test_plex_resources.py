import json
import unittest
from unittest.mock import patch

from plex_resources import AccountServer, ServerConnection, parse_resources, reachable_music_server


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self, _limit):
        return self.body


class ResourcesTests(unittest.TestCase):
    def test_filters_devices_urls_and_orders_local_direct_relay(self):
        body = json.dumps([
            {'provides': 'player', 'accessToken': 'other', 'clientIdentifier': 'player'},
            {'provides': 'server', 'name': 'Music', 'clientIdentifier': 'machine',
             'accessToken': 'server-token', 'owned': True, 'connections': [
                 {'uri': 'https://relay.plex.tv:443', 'local': False, 'relay': True},
                 {'uri': 'http://203.0.113.5:32400', 'local': False, 'relay': False},
                 {'uri': 'https://remote.example:32400', 'local': False, 'relay': False},
                 {'uri': 'http://192.168.1.4:32400', 'local': True, 'relay': False},
                 {'uri': 'https://192-168-1-4.machine.plex.direct:32400',
                  'local': True, 'relay': False},
                 {'uri': 'https://name:password@evil.example', 'local': False},
                 {'uri': 'https://evil.example/path', 'local': False},
             ]},
        ]).encode()
        servers = parse_resources(body)
        self.assertEqual(len(servers), 1)
        self.assertEqual((servers[0].name, servers[0].identifier,
                          servers[0].token, servers[0].owned),
                         ('Music', 'machine', 'server-token', True))
        self.assertEqual([item.uri for item in servers[0].connections], [
            'https://192-168-1-4.machine.plex.direct:32400',
            'http://192.168.1.4:32400',
            'https://remote.example:32400',
            'https://relay.plex.tv:443',
        ])

    def test_rejects_invalid_resource_data_and_missing_server_token(self):
        with self.assertRaises(ValueError):
            parse_resources(b'not-json')
        with self.assertRaises(ValueError):
            parse_resources(b'{"MediaContainer":null}')
        self.assertEqual(parse_resources(json.dumps([
            {'provides': 'server', 'clientIdentifier': 'machine',
             'connections': [{'uri': 'https://remote.example'}]},
        ]).encode()), [])
        self.assertEqual(parse_resources(json.dumps([
            {'provides': 'server', 'clientIdentifier': 'machine', 'accessToken': 'token',
             'connections': None},
        ]).encode()), [])

    def test_rejects_public_plain_http_even_if_marked_local(self):
        resources = parse_resources(json.dumps([
            {'provides': 'server', 'clientIdentifier': 'machine', 'accessToken': 'token',
             'connections': [{'uri': 'http://203.0.113.5:32400', 'local': True}]},
        ]).encode())
        self.assertEqual(resources, [])

    def test_identity_mismatch_never_sends_token_then_falls_back(self):
        server = AccountServer('Music', 'expected', 'secret', True, (
            ServerConnection('https://wrong.example', True, False),
            ServerConnection('https://right.example', False, False),
        ))
        identity_requests = []

        class Opener:
            def open(self, request, timeout):
                identity_requests.append((request.full_url, request.get_header('X-plex-token'),
                                          timeout))
                identifier = 'wrong' if 'wrong.example' in request.full_url else 'expected'
                return Response(f'<MediaContainer machineIdentifier="{identifier}"/>'.encode())

        with patch('plex_resources.PlexClient') as client:
            client.return_value.sections.return_value = [('2', 'Music')]
            result = reachable_music_server(server, 'player', 'Apistat', Opener())
        self.assertEqual(result, ('https://right.example', 'secret'))
        self.assertEqual([request[1] for request in identity_requests], [None, None])
        client.assert_called_once_with('https://right.example', 'secret', 'player',
                                       'Apistat', timeout=4)

    def test_rejects_server_without_music_library(self):
        server = AccountServer('Movies', 'machine', 'token', True,
                               (ServerConnection('https://server.example', False, False),))

        class Opener:
            def open(self, _request, timeout):
                return Response(b'<MediaContainer machineIdentifier="machine"/>')

        with patch('plex_resources.PlexClient') as client:
            client.return_value.sections.return_value = []
            self.assertIsNone(reachable_music_server(server, 'player', 'Apistat', Opener()))


if __name__ == '__main__':
    unittest.main()
