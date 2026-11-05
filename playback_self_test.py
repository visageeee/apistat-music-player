"""Exercise packaged playback with generated local and HTTP audio fixtures."""
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst

from ribbon_audio import RibbonAudioTap


FIXTURES = ('tone.flac', 'tone.mp3', 'tone.m4a')


def verify_playback(directory):
    fixtures = {name: (Path(directory) / name).read_bytes() for name in FIXTURES}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            name = self.path.lstrip('/')
            if name not in fixtures:
                self.send_error(404)
                return
            requests.append((name, self.headers.get('X-Plex-Token')))
            data = fixtures[name]
            start, end = 0, len(data) - 1
            range_header = self.headers.get('Range')
            if range_header:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', range_header)
                if not match or int(match.group(1)) >= len(data):
                    self.send_error(416)
                    return
                start = int(match.group(1))
                if match.group(2):
                    end = min(end, int(match.group(2)))
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
            else:
                self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            self.end_headers()
            try:
                self.wfile.write(data[start:end + 1])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for name in FIXTURES:
            for uri in ((Path(directory) / name).resolve().as_uri(),
                        f'http://127.0.0.1:{server.server_port}/{name}'):
                playbin = Gst.ElementFactory.make('playbin')
                if playbin is None:
                    raise RuntimeError('Missing GStreamer playbin')
                tap = RibbonAudioTap('fakesink name=selftest_sink sync=false signal-handoffs=true')
                sink = tap.sink_bin.get_by_name('selftest_sink')
                if sink is None:
                    raise RuntimeError('Could not create the test audio sink')
                count = [0]
                sink.set_property('signal-handoffs', True)
                sink.set_property('sync', False)
                sink.connect('handoff', lambda *_args: count.__setitem__(0, count[0] + 1))
                playbin.set_property('audio-sink', tap.sink_bin)
                playbin.set_property('flags', 2)
                def configure_source(_playbin, source):
                    if source.find_property('extra-headers'):
                        headers = Gst.Structure.new_empty('headers')
                        headers.set_value('X-Plex-Token', 'apistat-self-test')
                        source.set_property('extra-headers', headers)
                playbin.connect('source-setup', configure_source)
                playbin.set_property('uri', uri)
                try:
                    playbin.set_state(Gst.State.PLAYING)
                    message = playbin.get_bus().timed_pop_filtered(
                        15 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
                    if message is None:
                        raise RuntimeError(f'Playback timed out for {name}')
                    if message.type == Gst.MessageType.ERROR:
                        error, _debug = message.parse_error()
                        raise RuntimeError(f'Playback failed for {name}: {error.message}')
                    if count[0] == 0:
                        raise RuntimeError(f'No audio decoded for {name}')
                finally:
                    playbin.set_state(Gst.State.NULL)
            if (name, 'apistat-self-test') not in requests:
                raise RuntimeError(f'HTTP authentication header missing for {name}')
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
