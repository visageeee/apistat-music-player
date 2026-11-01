import os
import threading
import unittest
from types import SimpleNamespace

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gio, GLib, Gst

from mpris import Mpris, NAME, PATH, PLAYER


class FakeControl:
    def __init__(self, value=False):
        self.value = value

    def get_active(self):
        return self.value

    def set_active(self, value):
        self.value = value

    def get_sensitive(self):
        return True


class FakePipeline:
    def query_position(self, _format):
        return True, 0

    def get_property(self, _name):
        return 0.8

    def get_state(self, _timeout):
        return None, Gst.State.NULL, None


class FakePlayer:
    def __init__(self):
        self.queue = [SimpleNamespace(title='Song', artist='Artist', duration=125000)]
        self.queue_album = SimpleNamespace(title='Album')
        self.index = 0
        self.play_generation = 1
        self.playing = True
        self.stream_open = True
        self.tracks = self.queue
        self.pipeline = FakePipeline()
        self.repeat = FakeControl()
        self.shuffle = FakeControl()
        self.seek = FakeControl()
        self.actions = []

    def toggle(self):
        self.actions.append('PlayPause')

    def present(self):
        self.actions.append('Raise')


class MprisTests(unittest.TestCase):
    def test_metadata_and_controls_on_session_bus(self):
        if not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
            self.skipTest('Run under dbus-run-session')
        player = FakePlayer()
        service = Mpris(player)
        loop = GLib.MainLoop()
        result = []

        def client():
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                props = bus.call_sync(NAME, PATH, 'org.freedesktop.DBus.Properties',
                                      'Get', GLib.Variant('(ss)', (PLAYER, 'Metadata')),
                                      GLib.VariantType('(v)'), Gio.DBusCallFlags.NONE,
                                      2000, None)
                metadata = props.unpack()[0]
                result.append(metadata['xesam:title'])
                status = bus.call_sync(NAME, PATH, 'org.freedesktop.DBus.Properties',
                                       'Get', GLib.Variant('(ss)', (PLAYER, 'PlaybackStatus')),
                                       GLib.VariantType('(v)'), Gio.DBusCallFlags.NONE,
                                       2000, None)
                result.append(status.unpack()[0])
                bus.call_sync(NAME, PATH, PLAYER, 'PlayPause', None, None,
                              Gio.DBusCallFlags.NONE, 2000, None)
                result.append(player.actions[-1])
            except Exception as exc:
                result.append(exc)
            finally:
                GLib.idle_add(loop.quit)

        def start():
            if not service.connection:
                return True
            threading.Thread(target=client, daemon=True).start()
            return False

        GLib.timeout_add(10, start)
        GLib.timeout_add_seconds(4, loop.quit)
        loop.run()
        service.close()
        self.assertEqual(result, ['Song', 'Playing', 'PlayPause'])


if __name__ == '__main__':
    unittest.main()
