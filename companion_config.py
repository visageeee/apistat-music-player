"""Persistent, non-secret Plex Companion player preferences."""

import json
import os
import tempfile
import uuid
from pathlib import Path

from gi.repository import GLib


CONFIG_PATH = Path(GLib.get_user_config_dir()) / 'apistat' / 'companion.json'


def load_config(path=CONFIG_PATH):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    identifier = data.get('identifier')
    try:
        identifier = str(uuid.UUID(identifier))
    except (ValueError, TypeError, AttributeError):
        identifier = str(uuid.uuid4())
    name = data.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        name = 'Apistat'
    elif name == 'Plex Music on Linux':
        name = 'Apistat'
    result = {'identifier': identifier, 'name': name.strip(),
              'enabled': data.get('enabled') is True}
    if result != data:
        save_config(result, path)
    return result


def save_config(data, path=CONFIG_PATH):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.companion-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as target:
            json.dump(data, target, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
