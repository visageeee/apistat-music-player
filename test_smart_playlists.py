import random
import tempfile
import unittest
from pathlib import Path

from plex_client import Item
from smart_playlists import (apply_definition, load_for_scope, save_for_scope,
                             validate_definition)


def definition(**changes):
    value = {'id': 'one', 'name': 'Favorites', 'rules_enabled': True, 'match': 'all',
             'rules': [{'field': 'genre', 'operator': 'contains', 'value': 'jazz'}],
             'checked_only': False, 'limit_enabled': False, 'limit_amount': 25,
             'limit_unit': 'songs', 'selected_by': 'random'}
    value.update(changes)
    return value


SONGS = [
    Item('/library/metadata/1', 'Blue One', 'Mira', genre='Jazz', year='2020',
         duration=60000, user_rating=10, play_count=5, added_at=10),
    Item('/library/metadata/2', 'Blue Two', 'Jo', genre='Jazz', year='2019',
         duration=90000, user_rating=6, play_count=12, added_at=30),
    Item('/library/metadata/3', 'Green', 'Mira', genre='Rock', year='2020',
         duration=30000, user_rating=10, play_count=20, added_at=20),
]


class SmartPlaylistTests(unittest.TestCase):
    def test_any_all_and_disabled_rules(self):
        rules = [
            {'field': 'genre', 'operator': 'contains', 'value': 'jazz'},
            {'field': 'artist', 'operator': 'is', 'value': 'Mira'},
        ]
        self.assertEqual([song.key for song in apply_definition(
            SONGS, definition(rules=rules))], ['/library/metadata/1'])
        self.assertEqual([song.key for song in apply_definition(
            SONGS, definition(rules=rules, match='any'))],
            ['/library/metadata/1', '/library/metadata/2', '/library/metadata/3'])
        self.assertEqual(len(apply_definition(SONGS, definition(rules_enabled=False))), 3)

    def test_numeric_ranges_and_rating_stars_are_inclusive(self):
        value = definition(rules=[{'field': 'year', 'operator': 'range',
                                   'value': 2019, 'end': 2020},
                                  {'field': 'user_rating', 'operator': 'at_least',
                                   'value': 5}])
        self.assertEqual([song.key for song in apply_definition(SONGS, value)],
                         ['/library/metadata/1', '/library/metadata/3'])
        value['rules'][0]['end'] = 2018
        with self.assertRaises(ValueError):
            validate_definition(value)

    def test_checked_filter_precedes_selection_and_limit(self):
        value = definition(rules_enabled=False, checked_only=True, limit_enabled=True,
                           selected_by='plays', limit_amount=1)
        selected = apply_definition(SONGS, value, checked_keys={'/library/metadata/1',
                                                                '/library/metadata/2'})
        self.assertEqual([song.key for song in selected], ['/library/metadata/2'])
        value['selected_by'] = 'random'
        selected = apply_definition(SONGS, value, checked_keys={'/library/metadata/1'},
                                    rng=random.Random(9))
        self.assertEqual([song.key for song in selected], ['/library/metadata/1'])

    def test_duration_limit_uses_selected_order(self):
        value = definition(rules_enabled=False, limit_enabled=True,
                           selected_by='recent', limit_amount=2, limit_unit='minutes')
        self.assertEqual([song.key for song in apply_definition(SONGS, value)],
                         ['/library/metadata/2', '/library/metadata/3'])

    def test_persistence_is_scoped_and_invalid_entries_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'smart.json'
            save_for_scope('server-a', 'https://a', '1', [definition()], path)
            self.assertEqual(load_for_scope('server-a', 'https://a', '1', path)[0]['name'],
                             'Favorites')
            self.assertEqual(load_for_scope('server-b', 'https://b', '1', path), [])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                save_for_scope('server-a', 'https://a', '1',
                               [definition(), definition()], path)


if __name__ == '__main__':
    unittest.main()
