"""Manage this player's global media shortcuts in Xfce."""

import os
import shutil
import subprocess


ACTIONS = (
    ('Play / Pause', 'PlayPause'),
    ('Play', 'Play'),
    ('Pause', 'Pause'),
    ('Next track', 'Next'),
    ('Previous track', 'Previous'),
    ('Stop', 'Stop'),
)
CHANNEL = 'xfce4-keyboard-shortcuts'
CUSTOM_PREFIX = '/commands/custom/'
OTHER_PREFIXES = ('/commands/default/', '/xfwm4/custom/', '/xfwm4/default/')
DESTINATION = 'org.mpris.MediaPlayer2.plexmusicprototype'
OBJECT_PATH = '/org/mpris/MediaPlayer2'
INTERFACE = 'org.mpris.MediaPlayer2.Player'


class ShortcutError(Exception):
    pass


class ShortcutConflict(ShortcutError):
    pass


def available():
    return 'XFCE' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper() and bool(
        shutil.which('xfconf-query') and shutil.which('gdbus'))


def command_for(method):
    if method not in {action for _label, action in ACTIONS}:
        raise ValueError('Unsupported shortcut action')
    executable = shutil.which('gdbus')
    if not executable:
        raise ShortcutError('The gdbus command is unavailable.')
    return (f'{executable} call --session --dest {DESTINATION} '
            f'--object-path {OBJECT_PATH} --method {INTERFACE}.{method}')


def _xfconf(*arguments):
    try:
        return subprocess.run(['xfconf-query', '-c', CHANNEL, *arguments],
                              capture_output=True, text=True, check=True, timeout=5).stdout
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ShortcutError('Could not update Xfce keyboard shortcuts.') from exc


def all_shortcuts():
    entries = {}
    for line in _xfconf('-lv').splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            entries[parts[0]] = parts[1]
    return entries


def bindings(entries=None):
    entries = all_shortcuts() if entries is None else entries
    return {method: [path[len(CUSTOM_PREFIX):] for path, value in entries.items()
                     if path.startswith(CUSTOM_PREFIX) and value == command_for(method)]
            for _label, method in ACTIONS}


def set_binding(method, accelerator):
    command = command_for(method)
    if not accelerator or '/' in accelerator or any(character.isspace() for character in accelerator):
        raise ValueError('Invalid keyboard shortcut')
    entries = all_shortcuts()
    new_path = CUSTOM_PREFIX + accelerator
    for path, value in entries.items():
        if path == new_path and value != command:
            raise ShortcutConflict('That shortcut is already used by another Xfce command.')
        if path.startswith(OTHER_PREFIXES) and path.rsplit('/', 1)[-1] == accelerator:
            raise ShortcutConflict('That shortcut is already used by Xfce.')
    old_paths = [path for path, value in entries.items()
                 if path.startswith(CUSTOM_PREFIX) and value == command and path != new_path]
    if new_path not in entries:
        _xfconf('-p', new_path, '-n', '-t', 'string', '-s', command)
    for path in old_paths:
        _xfconf('-p', path, '-r')


def clear_bindings(method):
    command = command_for(method)
    for path, value in all_shortcuts().items():
        if path.startswith(CUSTOM_PREFIX) and value == command:
            _xfconf('-p', path, '-r')
