import unittest
import xml.etree.ElementTree as ET

from music_facets import MusicFacet, category_id, merge_categories


class MusicFacetTests(unittest.TestCase):
    def test_merges_server_categories_across_music_types(self):
        artist = ET.fromstring('<MediaContainer><Directory key="12" title="Dream Pop"/></MediaContainer>')
        album = ET.fromstring('<MediaContainer><Directory key="12" title="dream pop"/></MediaContainer>')
        mood = ET.fromstring('<MediaContainer><Directory key="30" title="Calm"/></MediaContainer>')
        facets = merge_categories([('style', 8, 'artist.style', artist),
                                   ('style', 9, 'album.style', album),
                                   ('mood', 10, 'track.mood', mood)])
        self.assertEqual(facets, (
            MusicFacet('mood', 'Calm', (('track.mood', 30),)),
            MusicFacet('style', 'Dream Pop', (('album.style', 12), ('artist.style', 12)))))

    def test_category_id_reads_valid_filter_path_but_rejects_external_url(self):
        node = ET.Element('Directory', {'fastKey': '/library/sections/2/all?album.style=42'})
        self.assertEqual(category_id(node, 'style'), 42)
        node.set('fastKey', 'https://example.com/?style=42')
        self.assertIsNone(category_id(node, 'style'))
        with self.assertRaises(ValueError):
            MusicFacet('style', 'Rock', (('https://example.com', 42),))
