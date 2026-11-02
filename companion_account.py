"""Opt-in plex.tv PIN linking and device connection publication.

The device token lives in Secret Service on Linux and Credential Manager on
Windows. There is no plaintext token fallback.
"""

import json
import os
import platform
import re
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener

if os.name == 'nt':
    from windows_vault import read_secret, write_secret, delete_secret
    Secret = None
else:
    import gi

    gi.require_version('Secret', '1')
    from gi.repository import Secret

from plex_client import NoRedirect
from plex_resources import parse_resources


PLEX_TV = 'https://plex.tv'
PLEX_CLIENTS = 'https://clients.plex.tv'
SCHEMA = (Secret.Schema.new('org.plexmusicprototype.companion', Secret.SchemaFlags.NONE,
                            {'identifier': Secret.SchemaAttributeType.STRING})
          if Secret is not None else None)


def _windows_target(identifier):
    return f'Apistat/Companion/{identifier}'


class AccountError(Exception):
    pass


class PlexAccount:
    def __init__(self, identifier, name, opener=None, base=PLEX_TV):
        self.identifier, self.name = identifier, name
        self.base = base.rstrip('/')
        self.opener = opener or build_opener(NoRedirect())

    @property
    def headers(self):
        return {'Accept': 'application/json', 'X-Plex-Client-Identifier': self.identifier,
                'X-Plex-Product': 'Apistat', 'X-Plex-Version': '1.0.0',
                'X-Plex-Platform': platform.system(),
                'X-Plex-Device': 'Windows PC' if os.name == 'nt' else 'Linux PC',
                'X-Plex-Device-Name': self.name,
                'X-Plex-Model': 'standalone',
                'X-Plex-Provides': 'client,player,pubsub-player'}

    def request(self, method, path, token=None, data=None, accept='application/json',
                base=None):
        headers = dict(self.headers, Accept=accept)
        if token:
            headers['X-Plex-Token'] = token
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        req = Request((base or self.base) + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=15) as response:
                return response.read()
        except HTTPError as exc:
            raise AccountError(f'plex.tv returned HTTP {exc.code}') from None

    def create_pin(self):
        data = json.loads(self.request('POST', '/api/v2/pins', data=b'strong=false'))
        if type(data.get('id')) is not int or not isinstance(data.get('code'), str):
            raise AccountError('Plex returned an invalid link code.')
        return data['id'], data['code']

    def check_pin(self, pin_id):
        if type(pin_id) is not int or pin_id < 1:
            raise ValueError('Invalid PIN ID')
        data = json.loads(self.request('GET', f'/api/v2/pins/{pin_id}'))
        return data.get('authToken') or None

    def user_id(self, token):
        data = json.loads(self.request('GET', '/api/v2/user', token=token))
        user_id = data.get('id')
        if not isinstance(user_id, (int, str)) or not str(user_id):
            raise AccountError('Plex returned no account ID.')
        return str(user_id)

    def resources(self, token):
        body = self.request('GET',
                            '/api/v2/resources?includeHttps=1&includeRelay=1&includeIPv6=1',
                            token=token, base=PLEX_CLIENTS)
        return parse_resources(body)

    def device_id(self, token):
        root = ET.fromstring(self.request('GET', '/devices.xml', token=token,
                                          accept='application/xml'))
        for device in root.iter('Device'):
            if device.get('clientIdentifier') == self.identifier:
                value = device.get('id', '')
                if value.isdigit():
                    return value
        return None

    def publish(self, token, uri):
        if not re.fullmatch(r'http://(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}', uri):
            raise ValueError('Expected a local HTTP address')
        identifier = self.device_id(token)
        if not identifier:
            raise AccountError('Linked Plex device is not registered yet.')
        path = f'/devices/{identifier}?Connection%5B%5D%5Buri%5D={quote(uri, safe="")}'
        self.request('PUT', path, token=token)

    def unlink(self, token):
        identifier = self.device_id(token)
        if identifier:
            self.request('DELETE', f'/devices/{identifier}.xml', token=token)


def load_device_token(identifier):
    if os.name == 'nt':
        return read_secret(_windows_target(identifier))
    return Secret.password_lookup_sync(SCHEMA, {'identifier': identifier}, None)


def save_device_token(identifier, token):
    if os.name == 'nt':
        write_secret(_windows_target(identifier), token)
        return
    if not Secret.password_store_sync(SCHEMA, {'identifier': identifier},
                                      Secret.COLLECTION_DEFAULT, 'Apistat remote control',
                                      token, None):
        raise AccountError('Desktop keyring could not save the device link.')


def clear_device_token(identifier):
    if os.name == 'nt':
        delete_secret(_windows_target(identifier))
        return
    Secret.password_clear_sync(SCHEMA, {'identifier': identifier}, None)
