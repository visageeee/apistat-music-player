import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from id3_tags import MAX_ID3_BYTES, read_id3_tags

try:
    from mutagen.id3 import ID3, TIT2, TXXX, COMM
except ImportError:
    ID3 = None


@unittest.skipIf(ID3 is None, 'python3-mutagen is not installed')
class EmbeddedID3Tests(unittest.TestCase):
    def client_for(self, payload):
        def open_range(request, timeout):
            range_header = request.get_header('Range')
            start, end = (int(value) for value in range_header.removeprefix('bytes=').split('-'))
            response = io.BytesIO(payload[start:end + 1])
            response.status = 206
            return response
        return SimpleNamespace(token='secret', identifier='test', timeout=5,
                               url=lambda path: 'http://plex' + path,
                               opener=SimpleNamespace(open=Mock(side_effect=open_range)))

    def test_reads_text_custom_and_comment_frames_from_bounded_ranges(self):
        tags = ID3()
        tags.add(TIT2(encoding=3, text=['Track title']))
        tags.add(TXXX(encoding=3, desc='custom', text=['custom value']))
        tags.add(COMM(encoding=3, lang='eng', desc='note', text=['comment']))
        buffer = io.BytesIO()
        tags.save(buffer)
        client = self.client_for(buffer.getvalue())
        frames, status = read_id3_tags(client, '/library/parts/7/42/file.mp3')
        self.assertEqual(status, '')
        self.assertIn(('TIT2', 'Track title'), frames)
        self.assertIn(('TXXX:custom', 'custom value'), frames)
        self.assertIn(('COMM:note:eng', 'comment'), frames)
        self.assertEqual(client.opener.open.call_count, 2)
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.get_header('X-plex-token'), 'secret')
        self.assertNotIn('secret', request.full_url)

    def test_reads_id3v1_tags_from_end_of_file(self):
        tail = (b'TAG' + b'Title'.ljust(30, b'\x00') + b'Artist'.ljust(30, b'\x00') +
                b'Album'.ljust(30, b'\x00') + b'1999' + b'Comment'.ljust(30, b'\x00') + b'\x00')
        payload = b'audio' * 30 + tail
        client = self.client_for(payload)
        frames, status = read_id3_tags(client, '/library/parts/7/file.mp3', len(payload))
        self.assertEqual(status, '')
        self.assertIn(('TIT2', 'Title'), frames)
        self.assertIn(('TPE1', 'Artist'), frames)

    def test_invalid_path_and_oversized_header_are_rejected(self):
        client = self.client_for(b'')
        self.assertTrue(read_id3_tags(client, 'https://bad.example/file')[1])
        client.opener.open.assert_not_called()
        size = MAX_ID3_BYTES
        encoded = bytes((size >> shift) & 0x7f for shift in (21, 14, 7, 0))
        client = self.client_for(b'ID3\x04\x00\x00' + encoded)
        self.assertIn('limit', read_id3_tags(client, '/library/parts/7/file.mp3')[1])
        self.assertEqual(client.opener.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
