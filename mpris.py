"""MPRIS D-Bus controls for desktop media keys and media widgets."""

import os
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gio, GLib, Gst


NAME = 'org.mpris.MediaPlayer2.apistat'
PATH = '/org/mpris/MediaPlayer2'
PLAYER = 'org.mpris.MediaPlayer2.Player'
ROOT = 'org.mpris.MediaPlayer2'
XML = '''<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/><method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="Fullscreen" type="b" access="readwrite"/>
    <property name="CanSetFullscreen" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/><method name="Previous"/>
    <method name="Pause"/><method name="PlayPause"/>
    <method name="Stop"/><method name="Play"/>
    <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
    <method name="SetPosition">
      <arg name="TrackId" type="o" direction="in"/>
      <arg name="Position" type="x" direction="in"/>
    </method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>'''


class Mpris:
    def __init__(self, player):
        self.player = player
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        self.connection = None
        self.registrations = []
        self.owner = Gio.bus_own_name(Gio.BusType.SESSION, NAME,
                                      Gio.BusNameOwnerFlags.NONE,
                                      self._bus_acquired, None, None)

    def _bus_acquired(self, connection, _name):
        self.connection = connection
        for interface in self.node.interfaces:
            self.registrations.append(connection.register_object(
                PATH, interface, self._method, self._get, self._set))

    def close(self):
        if self.connection:
            for registration in self.registrations:
                self.connection.unregister_object(registration)
        self.registrations.clear()
        self.connection = None
        Gio.bus_unown_name(self.owner)

    def track_id(self):
        if self.player.queue and 0 <= self.player.index < len(self.player.queue):
            return f'/org/apistat/track/{os.getpid()}_{self.player.play_generation}'
        return '/org/mpris/MediaPlayer2/TrackList/NoTrack'

    def metadata(self):
        if not self.player.queue or not 0 <= self.player.index < len(self.player.queue):
            return {}
        track = self.player.queue[self.player.index]
        result = {'mpris:trackid': GLib.Variant('o', self.track_id()),
                  'xesam:title': GLib.Variant('s', track.title),
                  'xesam:artist': GLib.Variant('as', [track.artist]),
                  'mpris:length': GLib.Variant('x', int(track.duration * 1000))}
        if self.player.queue_album:
            result['xesam:album'] = GLib.Variant('s', self.player.queue_album.title)
        elif track.album:
            result['xesam:album'] = GLib.Variant('s', track.album)
        return result

    def position(self):
        ok, position = self.player.pipeline.query_position(Gst.Format.TIME)
        return max(0, position // 1000) if ok else 0

    def _get(self, _connection, _sender, _path, interface, name):
        player = self.player
        if interface == ROOT:
            values = {
                'CanQuit': ('b', True), 'CanRaise': ('b', True),
                'Fullscreen': ('b', False), 'CanSetFullscreen': ('b', False),
                'HasTrackList': ('b', False), 'Identity': ('s', 'Apistat'),
                'SupportedUriSchemes': ('as', []),
                'SupportedMimeTypes': ('as', []),
            }
        else:
            has_track = bool(player.queue and 0 <= player.index < len(player.queue))
            values = {
                'PlaybackStatus': ('s', 'Playing' if player.playing else
                                   'Paused' if has_track and player.stream_open else 'Stopped'),
                'LoopStatus': ('s', 'Playlist' if player.repeat.get_active() else 'None'),
                'Rate': ('d', 1.0), 'Shuffle': ('b', player.shuffle.get_active()),
                'Metadata': ('a{sv}', self.metadata()),
                'Volume': ('d', player.pipeline.get_property('volume')),
                'Position': ('x', self.position()),
                'MinimumRate': ('d', 1.0), 'MaximumRate': ('d', 1.0),
                'CanGoNext': ('b', has_track and (player.index + 1 < len(player.queue) or player.repeat.get_active() or player.shuffle.get_active())),
                'CanGoPrevious': ('b', has_track),
                'CanPlay': ('b', has_track or bool(player.tracks) or bool(player.songs)),
                'CanPause': ('b', has_track),
                'CanSeek': ('b', has_track and player.seek.get_sensitive()),
                'CanControl': ('b', True),
            }
        signature, value = values[name]
        return GLib.Variant(signature, value)

    def _set(self, _connection, _sender, _path, interface, name, value):
        if interface != PLAYER:
            return False
        value = value.unpack()
        if name == 'LoopStatus':
            self.player.repeat.set_active(value == 'Playlist')
        elif name == 'Shuffle':
            self.player.shuffle.set_active(value)
        elif name == 'Volume':
            self.player.set_volume(max(0.0, value))
        elif name == 'Rate':
            if value == 0:
                self.player.pause()
            elif value != 1.0:
                return False
        else:
            return False
        self.changed()
        return True

    def _method(self, _connection, _sender, _path, interface, method, parameters, invocation):
        player = self.player
        if interface == ROOT:
            if method == 'Raise':
                player.present()
            elif method == 'Quit':
                invocation.return_value(None)
                GLib.idle_add(player.destroy)
                return
        elif method == 'Next':
            player.advance()
        elif method == 'Previous':
            player.previous()
        elif method == 'Pause':
            player.pause()
        elif method == 'PlayPause':
            player.toggle()
        elif method == 'Stop':
            player.stop()
        elif method == 'Play':
            player.play()
        elif method == 'Seek':
            player.seek_mpris(self.position() + parameters.unpack()[0])
        elif method == 'SetPosition':
            track_id, position = parameters.unpack()
            track = player.queue[player.index] if player.queue and 0 <= player.index < len(player.queue) else None
            if (track and track_id == self.track_id() and position >= 0
                    and (not track.duration or position <= track.duration * 1000)):
                player.seek_mpris(position)
        invocation.return_value(None)

    def changed(self):
        if not self.connection:
            return
        names = ('PlaybackStatus', 'LoopStatus', 'Shuffle', 'Metadata', 'Volume',
                 'CanGoNext', 'CanGoPrevious', 'CanPlay', 'CanPause', 'CanSeek')
        values = {name: self._get(None, None, None, PLAYER, name) for name in names}
        self.connection.emit_signal(None, PATH, 'org.freedesktop.DBus.Properties',
                                    'PropertiesChanged', GLib.Variant('(sa{sv}as)',
                                                                     (PLAYER, values, [])))

    def seeked(self, position):
        if self.connection:
            self.connection.emit_signal(None, PATH, PLAYER, 'Seeked',
                                        GLib.Variant('(x)', (position,)))
