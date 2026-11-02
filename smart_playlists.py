"""Local smart playlist definitions and evaluation over the cached music catalog."""

import hashlib
import json
import os
import random
import tempfile
from pathlib import Path

from gi.repository import GLib


PATH = Path(GLib.get_user_config_dir()) / 'plex-music-prototype' / 'smart-playlists.json'
FIELDS = {
    'genre': 'text', 'artist': 'text', 'album': 'text', 'title': 'text',
    'mood': 'text', 'year': 'number', 'user_rating': 'number',
    'play_count': 'number',
}
FIELD_LABELS = (
    ('genre', 'Genre'), ('artist', 'Artist'), ('album', 'Album'),
    ('title', 'Title'), ('mood', 'Mood'), ('year', 'Year'),
    ('user_rating', 'Rating'), ('play_count', 'Play Count'),
)
TEXT_OPERATORS = (
    ('contains', 'Contains'), ('not_contains', 'Does not contain'),
    ('is', 'Is'), ('is_not', 'Is not'), ('starts_with', 'Starts with'),
    ('ends_with', 'Ends with'),
)
NUMBER_OPERATORS = (
    ('is', 'Is'), ('is_not', 'Is not'), ('greater', 'Is greater than'),
    ('less', 'Is less than'), ('at_least', 'Is at least'),
    ('at_most', 'Is at most'), ('range', 'Is in the range'),
)
SELECTIONS = (
    ('random', 'Random'), ('recent', 'Recently added'),
    ('oldest', 'Oldest added'), ('title', 'Title'), ('artist', 'Artist'),
    ('rating', 'Highest rated'), ('plays', 'Most played'),
)
LIMIT_UNITS = (('songs', 'songs'), ('minutes', 'minutes'), ('hours', 'hours'))


def scope_key(machine, address, section):
    identity = machine or address
    return hashlib.sha256(f'{identity}\0{section}'.encode('utf-8')).hexdigest()


def validate_definition(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid smart playlist')
    name = data.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError('Enter a smart playlist name (up to 80 characters).')
    identifier = data.get('id')
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 80:
        raise ValueError('Invalid smart playlist identifier.')
    match = data.get('match', 'all')
    if match not in ('all', 'any'):
        raise ValueError('Choose whether all or any rules must match.')
    rules_enabled = data.get('rules_enabled', True)
    checked_only = data.get('checked_only', False)
    limit_enabled = data.get('limit_enabled', False)
    if any(type(value) is not bool for value in
           (rules_enabled, checked_only, limit_enabled)):
        raise ValueError('Invalid smart playlist options.')
    raw_rules = data.get('rules', [])
    if not isinstance(raw_rules, list) or len(raw_rules) > 32 or (rules_enabled and not raw_rules):
        raise ValueError('Add at least one rule, or disable rule filtering.')
    rules = []
    for rule in raw_rules:
        if not isinstance(rule, dict):
            raise ValueError('Invalid smart playlist rule.')
        field = rule.get('field')
        if field not in FIELDS:
            raise ValueError('Choose a supported rule field.')
        operator = rule.get('operator')
        allowed = TEXT_OPERATORS if FIELDS[field] == 'text' else NUMBER_OPERATORS
        if operator not in {item[0] for item in allowed}:
            raise ValueError('Choose a comparison for this field.')
        value = rule.get('value')
        if FIELDS[field] == 'text':
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError('Enter text for each rule.')
            normalized = {'field': field, 'operator': operator, 'value': value.strip()}
        else:
            try:
                value = float(value)
                end = float(rule.get('end')) if operator == 'range' else None
            except (TypeError, ValueError):
                raise ValueError('Enter a number for each numeric rule.') from None
            if not (-1000000000 <= value <= 1000000000) or (
                    end is not None and not value <= end <= 1000000000):
                raise ValueError('Enter a valid numeric range.')
            normalized = {'field': field, 'operator': operator, 'value': value}
            if end is not None:
                normalized['end'] = end
        rules.append(normalized)
    amount = data.get('limit_amount', 25)
    if type(amount) is not int or not 1 <= amount <= 100000:
        raise ValueError('Choose a limit between 1 and 100000.')
    unit = data.get('limit_unit', 'songs')
    selected_by = data.get('selected_by', 'random')
    if unit not in {item[0] for item in LIMIT_UNITS} or selected_by not in {
            item[0] for item in SELECTIONS}:
        raise ValueError('Choose a supported limit and selection method.')
    return {'id': identifier, 'name': name.strip(), 'rules_enabled': rules_enabled,
            'match': match, 'rules': rules, 'checked_only': checked_only,
            'limit_enabled': limit_enabled, 'limit_amount': amount,
            'limit_unit': unit, 'selected_by': selected_by}


def _matches(song, rule):
    field, operator, value = rule['field'], rule['operator'], rule['value']
    actual = getattr(song, field, '' if FIELDS[field] == 'text' else 0)
    if FIELDS[field] == 'text':
        actual, value = str(actual).casefold(), value.casefold()
        return {
            'contains': lambda: value in actual,
            'not_contains': lambda: value not in actual,
            'is': lambda: actual == value,
            'is_not': lambda: actual != value,
            'starts_with': lambda: actual.startswith(value),
            'ends_with': lambda: actual.endswith(value),
        }[operator]()
    try:
        actual = float(actual)
    except (TypeError, ValueError):
        return False
    if field == 'user_rating':
        actual /= 2  # Plex stores 0–10; the dialog uses 0–5 stars.
    return {
        'is': lambda: actual == value,
        'is_not': lambda: actual != value,
        'greater': lambda: actual > value,
        'less': lambda: actual < value,
        'at_least': lambda: actual >= value,
        'at_most': lambda: actual <= value,
        'range': lambda: value <= actual <= rule.get('end', value),
    }[operator]()


def apply_definition(songs, definition, checked_keys=(), rng=None):
    """Filter first, then select/order and cap. Range endpoints are inclusive."""
    definition = validate_definition(definition)
    checked_keys = set(checked_keys)
    rules = definition['rules'] if definition['rules_enabled'] else []
    match = all if definition['match'] == 'all' else any
    result = [song for song in songs
              if (not rules or match(_matches(song, rule) for rule in rules))
              and (not definition['checked_only'] or song.key in checked_keys)]
    if not definition['limit_enabled']:
        return result
    selected_by = definition['selected_by']
    if selected_by == 'random':
        result = list(result)
        (rng or random).shuffle(result)
    elif selected_by == 'recent':
        result.sort(key=lambda song: song.added_at, reverse=True)
    elif selected_by == 'oldest':
        result.sort(key=lambda song: song.added_at)
    elif selected_by == 'title':
        result.sort(key=lambda song: (song.title.casefold(), song.artist.casefold()))
    elif selected_by == 'artist':
        result.sort(key=lambda song: (song.artist.casefold(), song.title.casefold()))
    elif selected_by == 'rating':
        result.sort(key=lambda song: song.user_rating, reverse=True)
    elif selected_by == 'plays':
        result.sort(key=lambda song: song.play_count, reverse=True)
    amount = definition['limit_amount']
    unit = definition['limit_unit']
    if unit == 'songs':
        return result[:amount]
    budget = amount * (60000 if unit == 'minutes' else 3600000)
    chosen = []
    for song in result:
        duration = max(0, song.duration)
        if duration <= budget:
            chosen.append(song)
            budget -= duration
    return chosen


def load_for_scope(machine, address, section, path=PATH):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get('version') != 1:
        return []
    scopes = data.get('scopes', {})
    entries = scopes.get(scope_key(machine, address, section), []) if isinstance(scopes, dict) else []
    if not isinstance(entries, list):
        return []
    result = []
    for entry in entries[:200]:
        try:
            result.append(validate_definition(entry))
        except ValueError:
            pass
    return result


def save_for_scope(machine, address, section, definitions, path=PATH):
    validated = [validate_definition(entry) for entry in definitions]
    if len(validated) > 200 or len({entry['id'] for entry in validated}) != len(validated):
        raise ValueError('Too many smart playlists or duplicate identifiers.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    scopes = data.get('scopes', {}) if isinstance(data, dict) else {}
    if not isinstance(scopes, dict):
        scopes = {}
    scopes[scope_key(machine, address, section)] = validated
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.smart-playlists-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump({'version': 1, 'scopes': scopes}, output, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
