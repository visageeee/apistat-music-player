import unittest
from pathlib import Path

import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst

from playback_self_test import verify_playback

Gst.init(None)


class PlaybackSelfTests(unittest.TestCase):
    def test_decodes_local_and_authenticated_http_audio(self):
        required = ('playbin', 'fakesink', 'spectrum', 'souphttpsrc', 'flacdec',
                    'mpg123audiodec', 'faad', 'qtdemux')
        if not all(Gst.ElementFactory.find(name) for name in required):
            self.skipTest('Audio test plugins unavailable')
        verify_playback(Path(__file__).parent / 'test_fixtures' / 'audio')


if __name__ == '__main__':
    unittest.main()
