"""Plex Companion HTTP receiver and LAN GDM advertisement.

Protocol code is original and intentionally limited to music on the configured
Plex server. No controller-provided URL or token is used to fetch media.
"""

import ipaddress
import fcntl
import re
import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener

from plex_client import NoRedirect, PlexClient


CAPABILITIES = 'timeline,playback'
CONTROLS = 'volume,skipPrevious,skipNext,seekTo,stop,playPause'
COMMANDS = {'play', 'pause', 'stop', 'skipNext', 'skipPrevious', 'seekTo',
            'setParameters', 'playMedia'}
TRACK_PATH = re.compile(r'/library/metadata/\d+')
ALBUM_CHILDREN = re.compile(r'/library/metadata/\d+/children')
QUEUE_PATH = re.compile(r'/playQueues/(\d+)')
PLAYLIST_PATH = re.compile(r'/playlists/\d+/items')


class ProtocolError(ValueError):
    pass


@dataclass
class MediaQueue:
    tracks: list
    index: int
    offset: int
    container_key: str = ''
    queue_id: str = ''
    queue_version: str = ''
    item_ids: tuple = ()


def one(query, key, default=None):
    values = query.get(key)
    if not values:
        return default
    if len(values) != 1:
        raise ProtocolError(f'Duplicate {key}')
    return values[0]


def nonnegative(value, name, maximum=2_147_483_647):
    if not isinstance(value, str) or not value.isdigit() or len(value) > 11:
        raise ProtocolError(f'Invalid {name}')
    number = int(value)
    if number > maximum:
        raise ProtocolError(f'Invalid {name}')
    return number


def parse_command(path, target, identifier):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/player/playback/'):
        raise ProtocolError('Invalid command path')
    action = parsed.path.removeprefix('/player/playback/')
    if action not in COMMANDS:
        raise ProtocolError('Unsupported command')
    if target and target != identifier:
        raise ProtocolError('Wrong target player')
    query = parse_qs(parsed.query, keep_blank_values=True)
    command_id = nonnegative(one(query, 'commandID'), 'commandID')
    media_type = one(query, 'type', 'music')
    if media_type != 'music':
        raise ProtocolError('Only music is supported')
    args = {}
    if action == 'seekTo':
        args['offset'] = nonnegative(one(query, 'offset'), 'offset')
    elif action == 'setParameters':
        value = one(query, 'volume')
        if value is None:
            raise ProtocolError('Only volume can be set')
        args['volume'] = nonnegative(value, 'volume', 100)
        if set(query) - {'commandID', 'type', 'volume', 'X-Plex-Token',
                         'X-Plex-Client-Identifier', 'X-Plex-Target-Client-Identifier'}:
            raise ProtocolError('Unsupported parameter')
    elif action == 'playMedia':
        key = one(query, 'key')
        container = one(query, 'containerKey', '')
        if not key or not (TRACK_PATH.fullmatch(key) or ALBUM_CHILDREN.fullmatch(key)):
            raise ProtocolError('Invalid media key')
        if container:
            container_path = urlsplit(container)
            if container_path.scheme or container_path.netloc or not (
                    QUEUE_PATH.fullmatch(container_path.path) or
                    ALBUM_CHILDREN.fullmatch(container_path.path) or
                    PLAYLIST_PATH.fullmatch(container_path.path)):
                raise ProtocolError('Invalid container key')
        args['key'] = key
        args['container'] = container
        args['offset'] = nonnegative(one(query, 'offset', '0'), 'offset')
        args['machine'] = one(query, 'machineIdentifier')
    return action, command_id, args


def load_media(client, key, container, offset):
    """Load only metadata from the already authorised configured Plex server."""
    if container:
        path = urlsplit(container).path
    elif ALBUM_CHILDREN.fullmatch(key):
        path = key
    else:
        path = key
    is_queue = QUEUE_PATH.fullmatch(path)
    if is_queue:
        root = client.xml(path, own=1, window=200)
    else:
        root = client.xml(path)
    elements = root.findall('Track') + root.findall('Metadata')
    if is_queue:
        count_text = root.get('playQueueTotalCount') or root.get('totalSize') or ''
        total = min(int(count_text), 1000) if count_text.isdigit() else len(elements)
        seen = {item.get('playQueueItemID') for item in elements}
        for start in range(len(elements), total, 200):
            page = client.xml(path, own=1, window=200,
                              **{'X-Plex-Container-Start': start,
                                 'X-Plex-Container-Size': 200})
            next_items = page.findall('Track') + page.findall('Metadata')
            fresh = [item for item in next_items if item.get('playQueueItemID') not in seen]
            if not fresh:
                break
            elements.extend(fresh)
            seen.update(item.get('playQueueItemID') for item in fresh)
    if not elements and ALBUM_CHILDREN.fullmatch(key):
        raise ProtocolError('Album has no tracks')
    if not elements and TRACK_PATH.fullmatch(key):
        if root.find('Directory') is not None:
            root = client.xml(key + '/children')
            elements = root.findall('Track')
        if not elements:
            raise ProtocolError('Media has no playable tracks')
    if not elements:
        raise ProtocolError('Container has no tracks')
    track_elements = [item for item in elements if item.get('type', 'track') == 'track']
    tracks = [client.track_item(item) for item in track_elements]
    if not tracks or len(tracks) > 1000:
        raise ProtocolError('Unsupported queue length')
    index = next((n for n, item in enumerate(tracks) if item.key == key), None)
    if index is None and ALBUM_CHILDREN.fullmatch(key):
        index = 0
    if index is None and path == key + '/children':
        index = 0
    if index is None:
        selected = root.get('playQueueSelectedItemID')
        ids = [item.get('playQueueItemID') for item in track_elements]
        index = ids.index(selected) if selected in ids else None
    if index is None and is_queue:
        selected_offset = root.get('playQueueSelectedItemOffset', '')
        if selected_offset.isdigit() and int(selected_offset) < len(tracks):
            index = int(selected_offset)
    if index is None:
        raise ProtocolError('Requested track is not in the queue')
    match = QUEUE_PATH.fullmatch(path)
    return MediaQueue(tracks, index, offset, path if container else '',
                      match.group(1) if match else '', root.get('playQueueVersion', ''),
                      tuple(item.get('playQueueItemID', '') for item in track_elements))


def timeline_xml(state, command_id):
    root = ET.Element('MediaContainer', commandID=str(command_id))
    music = {'type': 'music', 'state': state.get('state', 'stopped'),
             'time': str(state.get('position', 0)),
             'volume': str(state.get('volume', 0)), 'controllable': CONTROLS}
    if state.get('key'):
        music.update(key=state['key'], ratingKey=state['key'].rsplit('/', 1)[-1],
                     duration=str(state.get('duration', 0)),
                     machineIdentifier=state.get('machine', ''),
                     address=state.get('address', ''), port=str(state.get('port', '')),
                     protocol=state.get('protocol', 'http'))
        if state.get('container'):
            music['containerKey'] = state['container']
        if state.get('queue_id'):
            music['playQueueID'] = state['queue_id']
            music['playQueueVersion'] = str(state.get('queue_version') or '1')
            if state.get('item_id'):
                music['playQueueItemID'] = str(state['item_id'])
    ET.SubElement(root, 'Timeline', music)
    ET.SubElement(root, 'Timeline', type='video', state='stopped')
    ET.SubElement(root, 'Timeline', type='photo', state='stopped')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def local_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(('192.0.2.1', 80))
            return sock.getsockname()[0]
        except OSError:
            try:
                address = socket.gethostbyname(socket.gethostname())
                return address if ipaddress.ip_address(address).is_private else '127.0.0.1'
            except (OSError, ValueError):
                return '127.0.0.1'


def same_lan_peer(address):
    """Permit tokenless control only on the advertised IPv4 interface's subnet."""
    try:
        peer = ipaddress.ip_address(address)
        published = ipaddress.ip_address(local_ip())
    except ValueError:
        return False
    if peer.is_loopback:
        return True
    if not isinstance(peer, ipaddress.IPv4Address) or published.is_loopback:
        return False
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _index, name in interfaces:
            request = struct.pack('256s', name.encode()[:15])
            try:
                address = ipaddress.ip_address(socket.inet_ntoa(
                    fcntl.ioctl(sock.fileno(), 0x8915, request)[20:24]))
                if address != published:
                    continue
                mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x891b,
                                                    request)[20:24])
                network = ipaddress.ip_network(f'{address}/{mask}', strict=False)
                return peer in network
            except (OSError, ValueError):
                continue
    return False


class GDM:
    def __init__(self, identifier, name, port):
        self.identifier, self.name, self.port = identifier, name, port
        self.running = False
        self.sock = None
        self.thread = None

    def message(self, verb):
        clean = self.name.replace('\r', ' ').replace('\n', ' ')
        lines = [verb, f'Name: {clean}', f'Port: {self.port}',
                 'Product: Apistat', 'Version: 1.0.0', 'Protocol: plex',
                 'Protocol-Version: 1', f'Protocol-Capabilities: {CAPABILITIES}',
                 'Device-Class: pc', f'Resource-Identifier: {self.identifier}',
                 'Content-Type: plex/media-player', 'Provides: client,player,pubsub-player', '', '']
        return '\r\n'.join(lines).encode('utf-8')

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        try:
            self.sock.bind(('0.0.0.0', 32412))
        except OSError:
            self.sock.close()
            self.sock = None
            raise
        try:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                 socket.inet_aton('239.0.0.250') + socket.inet_aton('0.0.0.0'))
        except OSError:
            pass
        self.sock.settimeout(1)
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def announce(self, verb='HELLO * HTTP/1.0'):
        data = self.message(verb)
        for address in [('239.0.0.250', 32413), ('255.255.255.255', 32414)]:
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                self.sock.sendto(data, address)
            except OSError:
                pass

    def run(self):
        next_hello = 0
        while self.running:
            if time.monotonic() >= next_hello:
                self.announce()
                next_hello = time.monotonic() + 30
            try:
                data, address = self.sock.recvfrom(2048)
                if data.startswith(b'M-SEARCH'):
                    self.sock.sendto(self.message('HTTP/1.0 200 OK'), address)
            except socket.timeout:
                pass
            except OSError:
                break

    def stop(self):
        if self.running:
            self.running = False
            self.announce('BYE * HTTP/1.0')
            self.sock.close()
            self.thread.join(timeout=2)


class CompanionReceiver:
    """Threaded HTTP receiver. GTK callbacks are supplied by the application."""

    def __init__(self, identifier, name, account, apply, verifier, port=32500):
        self.identifier, self.name, self.account = identifier, name, account
        self.apply, self.verifier = apply, verifier
        self.port = port
        self.server_client = None
        self.server_machine = ''
        self.server_address = ''
        self.link_token = None
        self.link_user_id = None
        self.state = {'state': 'stopped', 'volume': 80}
        self.version = 0
        self.condition = threading.Condition()
        self.command_ids = {}
        self.command_lock = threading.Lock()
        self.subscribers = {}
        self.subscriber_failures = {}
        self.http = None
        self.thread = None
        self.gdm = None
        self.push_thread = None
        self.running = False
        self.last_request = None

    def set_server(self, client, machine):
        self.server_client = client
        self.server_machine = machine
        self.server_address = client.address if client else ''

    def set_link(self, token, user_id):
        self.link_token, self.link_user_id = token, user_id

    def publish(self, state):
        with self.condition:
            if state != self.state:
                self.state = state
                self.version += 1
                self.condition.notify_all()

    def resources(self):
        address = local_ip()
        root = ET.Element('MediaContainer')
        player = ET.SubElement(root, 'Player', title=self.name, protocol='plex',
                               protocolVersion='1', protocolCapabilities=CAPABILITIES,
                               machineIdentifier=self.identifier,
                               product='Apistat', platform='Linux',
                               deviceClass='pc', state=self.state.get('state', 'stopped'),
                               address=address, port=str(self.port), version='1.0.0',
                               provides='client,player,pubsub-player')
        ET.SubElement(player, 'Connection', protocol='http', address=address,
                      port=str(self.port), uri=f'http://{address}:{self.port}', local='1')
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)

    def start(self):
        if self.running:
            return
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Never log URLs: Companion requests may contain tokens.

            def send_xml(self, body, code=200):
                receiver.last_request = (urlsplit(self.path).path[:80], code)
                self.send_response(code)
                self.send_header('Content-Type', 'application/xml; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Plex-Client-Identifier', receiver.identifier)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Expose-Headers', 'X-Plex-Client-Identifier')
                self.end_headers()
                self.wfile.write(body)

            def error(self, code, message):
                self.send_xml(ET.tostring(ET.Element('Response', status=message)), code)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'X-Plex-Token, X-Plex-Client-Identifier, X-Plex-Target-Client-Identifier, X-Plex-Device-Name')
                self.end_headers()

            def do_GET(self):
                try:
                    peer = ipaddress.ip_address(self.client_address[0])
                except ValueError:
                    return self.error(403, 'Local network only')
                if not (peer.is_private or peer.is_loopback or peer.is_link_local):
                    return self.error(403, 'Local network only')
                path = urlsplit(self.path)
                query = parse_qs(path.query, keep_blank_values=True)
                plex_fields = ('X-Plex-Target-Client-Identifier',
                               'X-Plex-Client-Identifier', 'X-Plex-Token')
                if any(len(query.get(field, ())) > 1 for field in plex_fields):
                    return self.error(400, 'Duplicate Plex header')
                def field(name):
                    return self.headers.get(name) or next(iter(query.get(name, ())), '')
                target = field('X-Plex-Target-Client-Identifier')
                if target and target != receiver.identifier:
                    return self.error(404, 'Wrong target player')
                if path.path in ('/', '/resources'):
                    return self.send_xml(receiver.resources())
                controller = field('X-Plex-Client-Identifier')
                token = field('X-Plex-Token')
                if not controller or len(controller) > 256 or len(token) > 1024:
                    return self.error(401, 'Unauthorized')
                linked_lan = bool(receiver.link_user_id and
                                  same_lan_peer(self.client_address[0]))
                if not linked_lan and (not token or not receiver.verifier(token)):
                    return self.error(401, 'Unauthorized')
                try:
                    command_id = nonnegative(one(query, 'commandID'), 'commandID')
                    if path.path == '/player/timeline/poll':
                        wait = one(query, 'wait', '0')
                        if wait not in ('0', '1'):
                            raise ProtocolError('Invalid wait')
                        with receiver.condition:
                            version = receiver.version
                            if wait == '1' and receiver.running:
                                receiver.condition.wait_for(
                                    lambda: receiver.version != version or not receiver.running,
                                    timeout=20)
                            state = dict(receiver.state)
                        return self.send_xml(timeline_xml(state,
                            receiver.command_ids.get(controller, command_id)))
                    if path.path == '/player/timeline/subscribe':
                        port = nonnegative(one(query, 'port'), 'port', 65535)
                        if not port or one(query, 'protocol', 'http') != 'http':
                            raise ProtocolError('Invalid subscriber address')
                        receiver.command_ids[controller] = command_id
                        receiver.subscribers[controller] = (self.client_address[0], port, time.monotonic())
                        receiver.subscriber_failures.pop(controller, None)
                        return self.send_xml(timeline_xml(receiver.state, command_id))
                    if path.path == '/player/timeline/unsubscribe':
                        receiver.subscribers.pop(controller, None)
                        receiver.subscriber_failures.pop(controller, None)
                        return self.send_xml(timeline_xml(receiver.state, command_id))
                    action, command_id, args = parse_command(self.path, target, receiver.identifier)
                    if action == 'playMedia':
                        if not receiver.server_client or not receiver.server_machine:
                            return self.error(503, 'Plex server is not connected')
                        if args['machine'] != receiver.server_machine:
                            return self.error(403, 'Media is from another Plex server')
                    with receiver.command_lock:
                        if command_id <= receiver.command_ids.get(controller, -1):
                            return self.send_xml(timeline_xml(receiver.state,
                                                               receiver.command_ids[controller]))
                        media = (load_media(receiver.server_client, args['key'], args['container'],
                                            args['offset']) if action == 'playMedia' else None)
                        state = receiver.apply(action, args, media)
                        receiver.command_ids[controller] = command_id
                        receiver.publish(state)
                    return self.send_xml(timeline_xml(state, command_id))
                except ProtocolError as exc:
                    return self.error(400, str(exc))
                except Exception:
                    return self.error(500, 'Command failed')

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        try:
            self.http = Server(('0.0.0.0', self.port), Handler)
        except OSError:
            self.http = Server(('0.0.0.0', 0), Handler)
        self.port = self.http.server_port
        self.running = True
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.push_thread = threading.Thread(target=self.push_timelines, daemon=True)
        self.push_thread.start()
        try:
            self.gdm = GDM(self.identifier, self.name, self.port)
            self.gdm.start()
        except OSError:
            self.gdm = None  # HTTP and plex.tv discovery can still work.

    def stop(self):
        if not self.running:
            return
        self.running = False
        with self.condition:
            self.condition.notify_all()
        if self.gdm:
            self.gdm.stop()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.push_thread.join(timeout=2)

    def push_timelines(self):
        """Notify subscribed controllers when GTK publishes a changed timeline."""
        opener = build_opener(NoRedirect())
        last_version = -1
        while self.running:
            with self.condition:
                self.condition.wait_for(lambda: self.version != last_version or
                                        not self.running, timeout=5)
                if not self.running:
                    return
                last_version = self.version
                state = dict(self.state)
            for controller, (address, port, _since) in list(self.subscribers.items()):
                body = timeline_xml(state, self.command_ids.get(controller, 0))
                url = f'http://{address}:{port}/:/timeline'
                request = Request(url, data=body, method='POST', headers={
                    'Content-Type': 'application/xml',
                    'X-Plex-Client-Identifier': self.identifier})
                try:
                    with opener.open(request, timeout=2) as response:
                        response.read(1024)
                    if controller in self.subscribers:
                        self.subscribers[controller] = address, port, time.monotonic()
                        self.subscriber_failures.pop(controller, None)
                except Exception:
                    if controller not in self.subscribers:
                        continue
                    failures = self.subscriber_failures.get(controller, 0) + 1
                    self.subscriber_failures[controller] = failures
                    if failures >= 3:
                        self.subscribers.pop(controller, None)
                        self.subscriber_failures.pop(controller, None)
