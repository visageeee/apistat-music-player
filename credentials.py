"""Store the Plex connection in the desktop Secret Service keyring."""

import json

import gi

gi.require_version('Secret', '1')
from gi.repository import Secret


SCHEMA = Secret.Schema.new('org.plexmusicprototype.connection',
                           Secret.SchemaFlags.NONE,
                           {'application': Secret.SchemaAttributeType.STRING})
ATTRIBUTES = {'application': 'plex-music-prototype'}


def load_credentials():
    value = Secret.password_lookup_sync(SCHEMA, ATTRIBUTES, None)
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
    if not Secret.password_store_sync(SCHEMA, ATTRIBUTES, Secret.COLLECTION_DEFAULT,
                                      'Plex Music server', value, None):
        raise RuntimeError('Could not save the connection in the desktop keyring.')
