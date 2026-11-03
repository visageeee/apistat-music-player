import unittest
from xml.etree import ElementTree as ET
from unittest.mock import Mock

from artist_info import file_info_lines, format_artist_description
from plex_client import Item, PlexClient


class ArtistInfoTests(unittest.TestCase):
    def test_artist_description_has_space_between_paragraphs(self):
        self.assertEqual(format_artist_description('First paragraph.\nSecond paragraph.\n\nThird.'),
                         'First paragraph.\n\nSecond paragraph.\n\nThird.')

    def test_plex_track_file_details_and_matching_artist_summary(self):
        client = PlexClient('http://localhost:32400', 'token')
        track = Item('/library/metadata/10', 'Song', artist='Artist')
        client.xml = Mock(side_effect=[
            ET.fromstring('<MediaContainer><Track grandparentKey="/library/metadata/2" '
                          'grandparentTitle="Artist"><Media audioCodec="flac" bitrate="950" '
                          'audioChannels="2" audioSampleRate="44100" audioBitDepth="16" '
                          'container="flac"><Part size="1200" file="/music/song.flac">'
                          '<Stream streamType="2" selected="1" samplingRate="48000" bitDepth="24"/>'
                          '</Part>'
                          '</Media></Track></MediaContainer>'),
            ET.fromstring('<MediaContainer><Directory summary="A biography"/></MediaContainer>')])
        details, biography = client.track_details(track)
        self.assertEqual(biography, 'A biography')
        self.assertEqual(details['codec'], 'flac')
        self.assertEqual(details['sample_rate'], '48000')
        self.assertEqual(details['bit_depth'], '24')
        self.assertEqual(details['file'], '/music/song.flac')
        self.assertIn(('Bitrate', '950 kbps'), file_info_lines(details))
        self.assertEqual(client.xml.call_count, 2)

    def test_plex_artist_lookup_rejects_untrusted_path_and_mismatched_artist(self):
        client = PlexClient('http://localhost:32400', 'token')
        client.xml = Mock(return_value=ET.fromstring(
            '<MediaContainer><Track grandparentKey="https://elsewhere" '
            'grandparentTitle="Someone else"/></MediaContainer>'))
        self.assertEqual(client.track_details(Item('/library/metadata/10', 'Song', artist='Artist')),
                         ({'album_artist': 'Someone else'}, ''))
        client.xml.assert_called_once()
        with self.assertRaises(ValueError):
            client.track_details(Item('https://elsewhere', 'Song'))


if __name__ == '__main__':
    unittest.main()
