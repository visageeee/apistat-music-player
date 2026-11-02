"""Validate same-app track drag data before changing Plex playlists or playback."""

import re


TRACK_KEY = re.compile(r'/library/metadata/\d+\Z')


def encode_track_keys(keys):
    if not keys or len(keys) > 2000 or any(not TRACK_KEY.fullmatch(key) for key in keys):
        return b''
    return '\n'.join(keys).encode('ascii')


def decode_track_keys(data):
    try:
        keys = bytes(data or b'').decode('ascii').splitlines()
    except (UnicodeDecodeError, TypeError):
        return []
    if not keys or len(keys) > 2000 or any(not TRACK_KEY.fullmatch(key) for key in keys):
        return []
    return keys
