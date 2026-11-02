"""Discover an account's music servers and safely choose a reachable address."""

import ipaddress
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from plex_client import NoRedirect, PlexClient


LAN_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
    '169.254.0.0/16', 'fc00::/7', 'fe80::/10'))


@dataclass(frozen=True)
class ServerConnection:
    uri: str
    local: bool
    relay: bool


@dataclass(frozen=True)
class AccountServer:
    name: str
    identifier: str
    token: str
    owned: bool
    connections: tuple[ServerConnection, ...]


def _flag(value):
    return value is True or value == 1 or value == '1' or value == 'true'


def _safe_uri(value, local):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            port == 0 or parsed.path not in ('', '/')):
        return None
    if parsed.scheme == 'http':
        try:
            host = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return None
        if not local or not (host.is_loopback or any(host in network for network in LAN_NETWORKS)):
            return None
    return value.rstrip('/')


def parse_resources(body):
    """Accept Plex's v2 JSON resource list, retaining only usable PMS entries."""
    try:
        devices = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise ValueError('Plex returned an invalid server list.') from exc
    if isinstance(devices, dict):
        container = devices.get('MediaContainer', {})
        devices = container.get('Device', []) if isinstance(container, dict) else None
    if not isinstance(devices, list):
        raise ValueError('Plex returned an invalid server list.')
    servers = []
    for device in devices:
        if not isinstance(device, dict) or 'server' not in str(device.get('provides', '')).split(','):
            continue
        identifier = device.get('clientIdentifier')
        token = device.get('accessToken')
        if not isinstance(identifier, str) or not identifier or not isinstance(token, str) or not token:
            continue
        connections = []
        raw_connections = device.get('connections', device.get('Connection', []))
        if not isinstance(raw_connections, list):
            continue
        for item in raw_connections:
            if not isinstance(item, dict):
                continue
            local, relay = _flag(item.get('local')), _flag(item.get('relay'))
            uri = _safe_uri(item.get('uri'), local)
            if uri:
                connection = ServerConnection(uri, local, relay)
                if connection not in connections:
                    connections.append(connection)
        if not connections:
            continue
        connections.sort(key=lambda item: (item.relay, not item.local,
                                            item.uri.startswith('http://')))
        name = device.get('name')
        servers.append(AccountServer(name.strip() if isinstance(name, str) and name.strip()
                                     else 'Unnamed Plex server', identifier, token,
                                     _flag(device.get('owned')), tuple(connections)))
    return servers


def reachable_music_server(server, client_identifier, device_name, opener=None,
                           timeout=4):
    """Probe a server's published URLs without sending its token to the wrong host."""
    opener = opener or build_opener(NoRedirect())
    for connection in server.connections:
        try:
            request = Request(connection.uri + '/identity',
                              headers={'Accept': 'application/xml'})
            with opener.open(request, timeout=timeout) as response:
                identity = ET.fromstring(response.read(65536))
            if identity.get('machineIdentifier') != server.identifier:
                continue
            client = PlexClient(connection.uri, server.token, client_identifier,
                                device_name, timeout=timeout)
            if client.sections():
                return connection.uri, server.token
        except (HTTPError, URLError, OSError, ET.ParseError, ValueError):
            continue
    return None
