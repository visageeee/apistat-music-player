"""Store the Plex connection in the operating system's credential vault."""

import json
import os
import sys

if os.name == 'nt':
    from windows_vault import read_secret, write_secret
    Secret = None
elif sys.platform == 'darwin':
    from macos_vault import read_secret, write_secret
    Secret = None
else:
    import gi

    gi.require_version('Secret', '1')
    from gi.repository import Secret


SCHEMA = (Secret.Schema.new('org.plexmusicprototype.connection',
                            Secret.SchemaFlags.NONE,
                            {'application': Secret.SchemaAttributeType.STRING})
          if Secret is not None else None)
ATTRIBUTES = {'application': 'plex-music-prototype'}
WINDOWS_TARGET = 'Apistat/PlexServer'


def _load_value():
    if os.name == 'nt' or sys.platform == 'darwin':
        return read_secret(WINDOWS_TARGET)
    return Secret.password_lookup_sync(SCHEMA, ATTRIBUTES, None)


def _save_value(value):
    if os.name == 'nt' or sys.platform == 'darwin':
        write_secret(WINDOWS_TARGET, value)
    elif not Secret.password_store_sync(SCHEMA, ATTRIBUTES, Secret.COLLECTION_DEFAULT,
                                        'Apistat server', value, None):
        raise RuntimeError('Could not save the connection in the desktop keyring.')


def load_credentials():
    value = _load_value()
    if not value:
        return None
    try:
        saved = json.loads(value)
        address, token = saved['address'], saved['token']
        if not isinstance(address, str) or not isinstance(token, str):
            return None
        return address, token
    except (ValueError, KeyError, TypeError):
        return None


def save_credentials(address, token):
    value = json.dumps({'address': address, 'token': token})
    _save_value(value)
