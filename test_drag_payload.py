import unittest

from drag_payload import decode_track_keys, encode_track_keys


class DragPayloadTests(unittest.TestCase):
    def test_multiple_track_keys_round_trip_in_order(self):
        keys = ['/library/metadata/12', '/library/metadata/34']
        self.assertEqual(decode_track_keys(encode_track_keys(keys)), keys)

    def test_rejects_external_paths_and_mixed_invalid_payloads(self):
        self.assertEqual(decode_track_keys(b'/library/metadata/12\nhttps://other.example'), [])
        self.assertEqual(decode_track_keys(b'/library/metadata/12\n/other/path'), [])
        self.assertEqual(encode_track_keys(['/library/metadata/12', '/other/path']), b'')
