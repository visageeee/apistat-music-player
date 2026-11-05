import tempfile
import os
import sys
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from companion import (CompanionReceiver, GDM, ProtocolError, load_media, parse_command,
                       same_lan_peer, local_ip, timeline_xml)
import companion_account
from companion_account import PlexAccount
from companion_config import load_config, save_config
from plex_client import PlexClient


class FakePlex:
    address = 'http://127.0.0.1:32400'

    def xml(self, path, **_params):
        if path == '/playQueues/7':
            return ET.fromstring('''<MediaContainer playQueueVersion="3"
              playQueueSelectedItemID="22">
              <Track key="/library/metadata/10" title="First" duration="100000" playQueueItemID="21"/>
              <Track key="/library/metadata/11" title="Second" duration="110000" playQueueItemID="22"/>
            </MediaContainer>''')
        if path == '/library/metadata/40':
            return ET.fromstring('<MediaContainer><Directory key="/library/metadata/40"/></MediaContainer>')
        if path == '/library/metadata/40/children':
            return ET.fromstring('''<MediaContainer><Track key="/library/metadata/10"
              title="First" duration="100000"/></MediaContainer>''')
        if path == '/library/metadata/10':
            return ET.fromstring('''<MediaContainer><Track key="/library/metadata/10"
              title="First" duration="100000"/></MediaContainer>''')
        if path == '/playlists/9/items':
            return ET.fromstring('''<MediaContainer>
              <Track key="/library/metadata/10" title="First"/>
              <Track key="/library/metadata/11" title="Second"/>
            </MediaContainer>''')
        raise AssertionError('Unexpected metadata path')

    track_item = staticmethod(PlexClient.track_item)


class CompanionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows interface lookup test')
    def test_windows_lan_lookup_uses_active_interface_mask(self):
        address = local_ip()
        if address.startswith('127.'):
            self.skipTest('No active LAN interface on this runner')
        self.assertTrue(same_lan_peer(address))
        self.assertFalse(same_lan_peer('8.8.8.8'))

    def test_identity_is_stable_and_remote_starts_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'companion.json'
            first = load_config(path)
            self.assertFalse(first['enabled'])
            self.assertEqual(first['identifier'], load_config(path)['identifier'])
            first['enabled'] = True
            first['name'] = 'Living room Linux'
            save_config(first, path)
            self.assertEqual(load_config(path), first)

    def test_default_name_migrates_without_changing_player_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'companion.json'
            config = load_config(path)
            self.assertEqual(config['name'], 'Apistat')
            identifier = config['identifier']
            config['name'] = 'Plex Music on Linux'
            save_config(config, path)
            migrated = load_config(path)
            self.assertEqual((migrated['identifier'], migrated['name']),
                             (identifier, 'Apistat'))
            config['name'] = 'Living room Linux'
            save_config(config, path)
            self.assertEqual(load_config(path)['name'], 'Living room Linux')

    def test_gdm_advertises_same_receiver_identity_and_working_capabilities(self):
        message = GDM('stable-player-id', 'Living room', 32500).message('HELLO * HTTP/1.0')
        self.assertIn(b'Resource-Identifier: stable-player-id', message)
        self.assertIn(b'Port: 32500', message)
        self.assertIn(b'Product: Apistat', message)
        self.assertIn(b'Protocol-Capabilities: timeline,playback', message)
        self.assertNotIn(b'playqueues-creation', message)

    def test_parse_rejects_bad_target_command_and_media(self):
        with self.assertRaises(ProtocolError):
            parse_command('/player/playback/play?commandID=1', 'other', 'player')
        with self.assertRaises(ProtocolError):
            parse_command('/player/playback/seekTo?commandID=1&offset=-1', 'player', 'player')
        with self.assertRaises(ProtocolError):
            parse_command('/player/playback/playMedia?commandID=2&key=http://evil.test/song',
                          'player', 'player')
        with self.assertRaises(ProtocolError):
            parse_command('/player/playback/playMedia?commandID=2&key=%2Flibrary%2Fmetadata%2F10&containerKey=http://evil.test/',
                          'player', 'player')
        self.assertEqual(parse_command('/player/playback/setParameters?commandID=4&volume=37',
                                       'player', 'player'),
                         ('setParameters', 4, {'volume': 37}))

    def test_loads_requested_queue_item_and_album(self):
        queue = load_media(FakePlex(), '/library/metadata/11', '/playQueues/7', 4500)
        self.assertEqual((queue.index, queue.offset, queue.queue_id, queue.queue_version),
                         (1, 4500, '7', '3'))
        self.assertEqual(queue.item_ids, ('21', '22'))
        album = load_media(FakePlex(), '/library/metadata/40', '', 0)
        self.assertEqual(album.tracks[0].title, 'First')
        album_context = load_media(FakePlex(), '/library/metadata/40',
                                   '/library/metadata/40/children', 0)
        self.assertEqual(album_context.index, 0)
        self.assertEqual(load_media(FakePlex(), '/library/metadata/10', '', 0).index, 0)
        self.assertEqual(load_media(FakePlex(), '/library/metadata/11',
                                    '/playlists/9/items', 0).index, 1)

    def test_play_queue_fetches_selected_track_beyond_first_window(self):
        class PagingPlex(FakePlex):
            def xml(self, path, **params):
                start = params.get('X-Plex-Container-Start', 0)
                root = ET.Element('MediaContainer', totalSize='250')
                for number in range(start, min(start + 200, 250)):
                    ET.SubElement(root, 'Track', key=f'/library/metadata/{number + 1}',
                                  title=f'Track {number + 1}',
                                  playQueueItemID=str(number + 1))
                return root
        queue = load_media(PagingPlex(), '/library/metadata/230', '/playQueues/9', 0)
        self.assertEqual((queue.index, len(queue.tracks)), (229, 250))

    def test_timeline_includes_queue_and_current_state(self):
        body = timeline_xml({'state': 'playing', 'key': '/library/metadata/11',
                             'position': 4500, 'duration': 110000, 'volume': 37,
                             'machine': 'machine', 'address': '127.0.0.1',
                             'port': 32400, 'protocol': 'http',
                             'container': '/playQueues/7', 'queue_id': '7',
                             'queue_version': '3', 'item_id': '22'}, 9)
        root = ET.fromstring(body)
        music = root.find("Timeline[@type='music']")
        self.assertEqual(root.get('commandID'), '9')
        self.assertEqual((music.get('time'), music.get('playQueueItemID'),
                          music.get('state'), music.get('volume')),
                         ('4500', '22', 'playing', '37'))

    def test_http_auth_order_and_queue_playback(self):
        calls = []
        def apply(action, args, media):
            calls.append((action, args, media))
            return {'state': 'playing', 'key': '/library/metadata/11',
                    'duration': 110000, 'position': 4500, 'volume': 37,
                    'machine': 'machine', 'address': '127.0.0.1', 'port': 32400}
        receiver = CompanionReceiver('player', 'Test Player', None, apply,
                                     lambda token: token == 'allowed', port=0)
        receiver.set_server(FakePlex(), 'machine')
        with patch('companion.GDM.start'):
            receiver.start()
            try:
                base = f'http://127.0.0.1:{receiver.port}'
                def get(path, token='allowed', target='player'):
                    request = Request(base + path, headers={
                        'X-Plex-Token': token, 'X-Plex-Client-Identifier': 'phone',
                        'X-Plex-Target-Client-Identifier': target})
                    with urlopen(request, timeout=3) as response:
                        return response.status, ET.fromstring(response.read())
                with self.assertRaises(HTTPError) as error:
                    get('/player/playback/play?commandID=1', token='wrong')
                self.assertEqual(error.exception.code, 401)
                with self.assertRaises(HTTPError) as error:
                    get('/player/playback/play?commandID=1', target='other')
                self.assertEqual(error.exception.code, 404)
                query = urlencode({'commandID': 2, 'key': '/library/metadata/11',
                                   'containerKey': '/playQueues/7', 'offset': 4500,
                                   'machineIdentifier': 'machine',
                                   'address': 'evil.test', 'port': '443',
                                   'protocol': 'https', 'token': 'ignored'})
                status, body = get('/player/playback/playMedia?' + query)
                self.assertEqual(status, 200)
                self.assertEqual(calls[-1][2].index, 1)
                self.assertEqual(body.get('commandID'), '2')
                get('/player/playback/playMedia?' + query)
                self.assertEqual(len(calls), 1)  # repeated command ID is idempotent
                with self.assertRaises(HTTPError) as error:
                    get('/player/playback/playMedia?' + query.replace('machine', 'other'))
                self.assertEqual(error.exception.code, 403)
                _status, body = get('/player/timeline/poll?commandID=2')
                self.assertEqual(body.find("Timeline[@type='music']").get('key'),
                                 '/library/metadata/11')
                self.assertEqual(receiver.last_request, ('/player/timeline/poll', 200))
                query_auth = urlencode({'commandID': 2, 'X-Plex-Token': 'allowed',
                                        'X-Plex-Client-Identifier': 'phone'})
                with urlopen(base + '/player/timeline/poll?' + query_auth, timeout=3) as response:
                    self.assertEqual(response.status, 200)
            finally:
                receiver.stop()

    def test_subscription_receives_local_timeline_change(self):
        updated = threading.Event()
        class Controller(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                music = ET.fromstring(body).find("Timeline[@type='music']")
                if music.get('state') == 'playing' and music.get('time') == '1200':
                    updated.set()
                self.send_response(200)
                self.end_headers()
        controller = ThreadingHTTPServer(('127.0.0.1', 0), Controller)
        controller_thread = threading.Thread(target=controller.serve_forever, daemon=True)
        controller_thread.start()
        receiver = CompanionReceiver('player', 'Test', None,
                                     lambda *_: {'state': 'stopped'},
                                     lambda token: token == 'allowed', port=0)
        try:
            with patch('companion.GDM.start'):
                receiver.start()
                request = Request(
                    f'http://127.0.0.1:{receiver.port}/player/timeline/subscribe?commandID=5&port={controller.server_port}',
                    headers={'X-Plex-Token': 'allowed',
                             'X-Plex-Client-Identifier': 'phone'})
                with urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                receiver.publish({'state': 'playing', 'time': 1200,
                                  'position': 1200, 'volume': 50})
                self.assertTrue(updated.wait(3))
        finally:
            receiver.stop()
            controller.shutdown()
            controller.server_close()
            controller_thread.join(timeout=2)

    def test_linked_lan_controller_can_poll_without_valid_plex_token(self):
        receiver = CompanionReceiver('player', 'Test', None,
                                     lambda *_: {'state': 'stopped'},
                                     lambda token: token == 'allowed', port=0)
        with patch('companion.GDM.start'):
            receiver.start()
            try:
                base = f'http://127.0.0.1:{receiver.port}/player/timeline/poll?commandID=1'
                def poll(token=None, controller='phone'):
                    headers = {'X-Plex-Client-Identifier': controller,
                               'X-Plex-Target-Client-Identifier': 'player'}
                    if token is not None:
                        headers['X-Plex-Token'] = token
                    with urlopen(Request(base, headers=headers), timeout=3) as response:
                        return response.status
                with self.assertRaises(HTTPError) as error:
                    poll()
                self.assertEqual(error.exception.code, 401)
                receiver.set_link('device-token', 'owner')
                with patch('companion.same_lan_peer', return_value=True):
                    self.assertEqual(poll(), 200)
                    self.assertEqual(poll('unrecognized-phone-token'), 200)
                    command = Request(
                        f'http://127.0.0.1:{receiver.port}/player/playback/pause?commandID=2',
                        headers={'X-Plex-Client-Identifier': 'phone',
                                 'X-Plex-Target-Client-Identifier': 'player'})
                    with urlopen(command, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    with self.assertRaises(HTTPError) as error:
                        poll(controller='')
                    self.assertEqual(error.exception.code, 401)
                with patch('companion.same_lan_peer', return_value=False):
                    with self.assertRaises(HTTPError) as error:
                        poll('unrecognized-phone-token')
                    self.assertEqual(error.exception.code, 401)
                    self.assertEqual(poll('allowed'), 200)
                receiver.set_link(None, None)
                with patch('companion.same_lan_peer', return_value=True):
                    with self.assertRaises(HTTPError) as error:
                        poll()
                    self.assertEqual(error.exception.code, 401)
            finally:
                receiver.stop()


class AccountTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'), 'Secret Service is Linux only')
    def test_legacy_device_token_is_migrated_and_unlink_clears_both(self):
        with patch.object(companion_account, 'Secret') as secret, \
                patch.object(companion_account, 'save_device_token') as save:
            secret.password_lookup_sync.side_effect = [None, 'linked-token']
            self.assertEqual(companion_account.load_device_token('id'), 'linked-token')
            save.assert_called_once_with('id', 'linked-token')
            companion_account.clear_device_token('id')
            self.assertEqual([call.args[0] for call in secret.password_clear_sync.call_args_list],
                             [companion_account.SCHEMA, companion_account.LEGACY_SCHEMA])


    def test_pin_and_connection_publication(self):
        class Response:
            def __init__(self, data):
                self.data = data
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return self.data
        class Opener:
            def __init__(self):
                self.requests = []
            def open(self, request, timeout):
                self.requests.append(request)
                path = request.full_url
                if path.endswith('/api/v2/pins'):
                    return Response(b'{"id":123,"code":"ABCD"}')
                if path.endswith('/api/v2/pins/123'):
                    return Response(b'{"authToken":"device-token"}')
                if path.endswith('/devices.xml'):
                    return Response(b'<MediaContainer><Device id="55" clientIdentifier="player"/></MediaContainer>')
                if '/api/v2/resources?' in path:
                    return Response(b'[{'
                                    b'"provides":"server","name":"Music","clientIdentifier":"server-id",'
                                    b'"accessToken":"server-token","connections":['
                                    b'{"uri":"https://server.example:32400","local":false,"relay":false}]}]')
                return Response(b'{}')
        opener = Opener()
        account = PlexAccount('player', 'Test Player', opener, base='https://plex.test')
        self.assertEqual(account.create_pin(), (123, 'ABCD'))
        self.assertEqual(account.check_pin(123), 'device-token')
        servers = account.resources('device-token')
        self.assertEqual((servers[0].name, servers[0].token), ('Music', 'server-token'))
        self.assertIn('includeHttps=1&includeRelay=1&includeIPv6=1', opener.requests[-1].full_url)
        self.assertTrue(opener.requests[-1].full_url.startswith('https://clients.plex.tv/'))
        self.assertEqual(opener.requests[-1].get_header('X-plex-token'), 'device-token')
        account.publish('device-token', 'http://192.168.1.10:32500')
        uri = opener.requests[-1].full_url
        self.assertIn('Connection%5B%5D%5Buri%5D=http%3A%2F%2F192.168.1.10%3A32500', uri)
        self.assertEqual(opener.requests[-1].get_header('X-plex-token'), 'device-token')


if __name__ == '__main__':
    unittest.main()
