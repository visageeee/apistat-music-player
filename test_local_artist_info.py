import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_artist_info
from local_library import LocalLibrary, create_source


class ArtistLookupTests(unittest.TestCase):
    def test_musicbrainz_match_and_wikipedia_extract(self):
        replies = [
            {'artists': [{'name': 'Example Artist', 'id': '12345678-1234-1234-1234-123456789abc'}]},
            {'relations': [{'type': 'wikipedia', 'url': {'resource': 'https://en.wikipedia.org/wiki/Example_Artist'}}]},
            {'query': {'pages': {'42': {'title': 'Example Artist', 'extract': 'An artist.'}}}},
        ]
        with patch.object(local_artist_info, '_json', side_effect=replies) as request:
            self.assertEqual(local_artist_info.lookup_artist('Example Artist'),
                             ('An artist.', 'https://en.wikipedia.org/wiki/Example_Artist'))
        self.assertEqual(request.call_count, 3)
        self.assertIn('musicbrainz.org', request.call_args_list[0].args[0])
        self.assertIn('en.wikipedia.org/w/api.php', request.call_args_list[2].args[0])

    def test_ambiguous_names_and_untrusted_links_are_not_used(self):
        with patch.object(local_artist_info, '_json', return_value={'artists': [
                {'name': 'Shared'}, {'name': 'Shared'}]}) as request:
            self.assertIsNone(local_artist_info.lookup_artist('Shared'))
            self.assertEqual(request.call_count, 1)
        replies = [{'artists': [{'name': 'Shared', 'id': '12345678-1234-1234-1234-123456789abc'}]},
                   {'relations': [{'type': 'wikipedia', 'url': {'resource': 'https://evil.example/wiki/Shared'}}]}]
        with patch.object(local_artist_info, '_json', side_effect=replies) as request:
            self.assertIsNone(local_artist_info.lookup_artist('Shared'))
            self.assertEqual(request.call_count, 2)

    def test_wikidata_sitelink_is_used_for_wikipedia(self):
        replies = [
            {'artists': [{'name': 'Example', 'id': '12345678-1234-1234-1234-123456789abc'}]},
            {'relations': [{'type': 'wikidata', 'url': {'resource': 'https://www.wikidata.org/wiki/Q42'}}]},
            {'entities': {'Q42': {'sitelinks': {'enwiki': {'title': 'Example (musician)'}}}}},
            {'query': {'pages': {'1': {'title': 'Example (musician)', 'extract': 'Biography.'}}}},
        ]
        with patch.object(local_artist_info, '_json', side_effect=replies) as request:
            result = local_artist_info.lookup_artist('Example')
        self.assertEqual(result, ('Biography.', 'https://en.wikipedia.org/wiki/Example_(musician)'))
        self.assertIn('wikidata.org/w/api.php', request.call_args_list[2].args[0])

    def test_album_artist_credits_disambiguate_shared_names(self):
        first, second = '12345678-1234-1234-1234-123456789abc', 'abcdefab-1234-1234-1234-123456789abc'
        replies = [
            {'artists': [{'name': 'Shared', 'id': first}, {'name': 'Shared', 'id': second}]},
            {'releases': [{'title': 'Record', 'artist-credit': [{'artist': {'id': second}}]}]},
            {'relations': [{'type': 'wikipedia', 'url': {'resource': 'https://en.wikipedia.org/wiki/Shared'}}]},
            {'query': {'pages': {'1': {'title': 'Shared', 'extract': 'Right artist.'}}}},
        ]
        with patch.object(local_artist_info, '_json', side_effect=replies) as request:
            self.assertEqual(local_artist_info.lookup_artist('Shared', 'Record')[0], 'Right artist.')
        self.assertIn(second, request.call_args_list[2].args[0])

    def test_old_cached_misses_do_not_block_new_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music = root / 'music'; music.mkdir()
            library = LocalLibrary(create_source(music), root / 'database')
            with library.connect() as db:
                db.execute('INSERT INTO artist_info VALUES (?, ?, ?, ?)', ('artist', '', '', 9999999999))
            with patch.object(local_artist_info, 'lookup_artist', return_value=('Bio', 'url')) as lookup:
                self.assertEqual(library.artist_description('Artist', 'Album'), ('Bio', 'url'))
                lookup.assert_called_once_with('Artist', 'Album')

    def test_cache_persists_and_failures_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music = root / 'music'; music.mkdir()
            source = create_source(music)
            library = LocalLibrary(source, root / 'database')
            with patch.object(local_artist_info, 'lookup_artist', return_value=('Bio', 'https://en.wikipedia.org/wiki/Artist')) as lookup:
                self.assertEqual(library.artist_description('Artist')[0], 'Bio')
                reopened = LocalLibrary(source, root / 'database')
                self.assertEqual(reopened.artist_description('artist')[0], 'Bio')
                lookup.assert_called_once()
            with patch.object(local_artist_info, 'lookup_artist', side_effect=[RuntimeError('offline'), ('Later', 'url')]) as lookup:
                with self.assertRaises(RuntimeError):
                    library.artist_description('Other')
                self.assertEqual(library.artist_description('Other')[0], 'Later')
                self.assertEqual(lookup.call_count, 2)


if __name__ == '__main__':
    unittest.main()
