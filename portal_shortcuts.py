"""Global shortcut sessions through the XDG desktop portal when supported."""

import uuid
from pathlib import Path

from gi.repository import Gio, GLib

from shortcuts import ACTIONS


BUS_NAME = 'org.freedesktop.portal.Desktop'
APP_ID = 'org.apistat.Apistat'
OBJECT_PATH = '/org/freedesktop/portal/desktop'
INTERFACE = 'org.freedesktop.portal.GlobalShortcuts'
REQUEST_INTERFACE = 'org.freedesktop.portal.Request'
SESSION_INTERFACE = 'org.freedesktop.portal.Session'
ACTION_METHODS = {'PlayPause': 'toggle', 'Play': 'play', 'Pause': 'pause',
                  'Next': 'advance', 'Previous': 'previous', 'Stop': 'stop'}


def result_value(results, key):
    value = results.get(key)
    return value.unpack() if isinstance(value, GLib.Variant) else value


class PortalShortcuts:
    def __init__(self, player, changed):
        self.player = player
        self.changed = changed
        self.connection = None
        self.session_handle = None
        self.version = 0
        self.shortcuts = {}
        self.bound_once = False
        self.closed = False
        self.pending = {}
        self.early = {}
        self.signal_ids = []
        self.request_prefix = None

    @property
    def available(self):
        return bool(self.session_handle and not self.closed)

    def start(self):
        Gio.bus_get(Gio.BusType.SESSION, None, self._bus_ready)

    def _bus_ready(self, _source, result):
        if self.closed:
            return
        try:
            self.connection = Gio.bus_get_finish(result)
        except GLib.Error:
            return
        sender = self.connection.get_unique_name().lstrip(':').replace('.', '_')
        self.request_prefix = f'{OBJECT_PATH}/request/{sender}/'
        self.signal_ids = [
            self.connection.signal_subscribe(BUS_NAME, REQUEST_INTERFACE, 'Response',
                                             None, None, Gio.DBusSignalFlags.NONE,
                                             self._request_response),
            self.connection.signal_subscribe(BUS_NAME, INTERFACE, 'Activated',
                                             OBJECT_PATH, None, Gio.DBusSignalFlags.NONE,
                                             self._activated),
            self.connection.signal_subscribe(BUS_NAME, INTERFACE, 'ShortcutsChanged',
                                             OBJECT_PATH, None, Gio.DBusSignalFlags.NONE,
                                             self._shortcuts_changed)]
        if Path('/.flatpak-info').exists():
            self._check_version()
        else:
            self._call(OBJECT_PATH, 'org.freedesktop.host.portal.Registry', 'Register',
                       GLib.Variant('(sa{sv})', (APP_ID, {})), '()',
                       lambda _reply: self._check_version())

    def _check_version(self):
        self._call(OBJECT_PATH, 'org.freedesktop.DBus.Properties', 'Get',
                   GLib.Variant('(ss)', (INTERFACE, 'version')), '(v)',
                   self._version_ready)

    def _call(self, path, interface, method, parameters, reply_type, done):
        if self.closed or self.connection is None:
            return
        def finished(connection, result, _user_data=None):
            if self.closed:
                return
            try:
                reply = connection.call_finish(result)
            except GLib.Error:
                done(None)
            else:
                done(reply)
        self.connection.call(BUS_NAME, path, interface, method, parameters,
                             GLib.VariantType.new(reply_type) if reply_type else None,
                             Gio.DBusCallFlags.NONE, 10000, None, finished, None)

    def _version_ready(self, reply):
        if reply is None:
            self.changed()
            return
        value = reply.unpack()[0]
        self.version = value.unpack() if isinstance(value, GLib.Variant) else value
        self._new_session()

    def _request(self, method, parameters, done):
        self._call(OBJECT_PATH, INTERFACE, method, parameters, '(o)',
                   lambda reply: self._request_handle(reply, done))

    def _request_handle(self, reply, done):
        if reply is None:
            done(None)
            return
        path = reply.unpack()[0]
        if path in self.early:
            done(self.early.pop(path))
        else:
            self.pending[path] = done

    def _request_response(self, _connection, _sender, path, _interface,
                          _signal, parameters):
        if self.request_prefix and not path.startswith(self.request_prefix):
            return
        response = parameters.unpack()
        callback = self.pending.pop(path, None)
        if callback:
            callback(response)
        else:
            self.early[path] = response

    def _new_session(self, bind_after=False):
        if self.session_handle:
            self._call(self.session_handle, SESSION_INTERFACE, 'Close', None, None,
                       lambda _reply: None)
            self.session_handle = None
        options = {'handle_token': GLib.Variant('s', 'apistat_' + uuid.uuid4().hex),
                   'session_handle_token': GLib.Variant('s', 'apistat_' + uuid.uuid4().hex)}
        self._request('CreateSession', GLib.Variant('(a{sv})', (options,)),
                      lambda response: self._session_created(response, bind_after))

    def _session_created(self, response, bind_after):
        if not response or response[0] != 0:
            self.changed()
            return
        self.session_handle = result_value(response[1], 'session_handle')
        self.bound_once = False
        self.shortcuts = {}
        self.changed()
        if bind_after:
            self.enable()
        else:
            self._request('ListShortcuts', GLib.Variant('(oa{sv})',
                                                       (self.session_handle, {})),
                          self._listed)

    def _listed(self, response):
        if response and response[0] == 0:
            self._update_shortcuts(result_value(response[1], 'shortcuts') or [])

    def _update_shortcuts(self, rows):
        self.shortcuts = {key: result_value(options, 'trigger_description') or 'Assigned'
                          for key, options in rows if key in ACTION_METHODS}
        self.changed()

    def enable(self):
        if not self.available:
            return
        if self.bound_once:
            self._new_session(bind_after=True)
            return
        self.bound_once = True
        rows = [(method, {'description': GLib.Variant('s', label)})
                for label, method in ACTIONS]
        arguments = GLib.Variant('(oa(sa{sv})sa{sv})',
                                 (self.session_handle, rows, '', {}))
        self._request('BindShortcuts', arguments, self._bound)

    def _bound(self, response):
        if response and response[0] == 0:
            self._update_shortcuts(result_value(response[1], 'shortcuts') or [])
        else:
            self.changed()

    def configure(self):
        if not self.available:
            return
        if not self.shortcuts or self.version < 2:
            self.enable()
            return
        self._call(OBJECT_PATH, INTERFACE, 'ConfigureShortcuts',
                   GLib.Variant('(osa{sv})', (self.session_handle, '', {})),
                   '()', lambda _reply: None)

    def _shortcuts_changed(self, _connection, _sender, _path, _interface,
                           _signal, parameters):
        session, rows = parameters.unpack()
        if session == self.session_handle:
            self._update_shortcuts(rows)

    def _activated(self, _connection, _sender, _path, _interface, _signal, parameters):
        session, action, _timestamp, _options = parameters.unpack()
        if self.closed or session != self.session_handle or action not in ACTION_METHODS:
            return
        if getattr(self.player, 'closed', False):
            return
        getattr(self.player, ACTION_METHODS[action])()

    def close(self):
        self.closed = True
        if self.connection:
            for signal_id in self.signal_ids:
                self.connection.signal_unsubscribe(signal_id)
            if self.session_handle:
                self.connection.call(BUS_NAME, self.session_handle, SESSION_INTERFACE,
                                     'Close', None, None, Gio.DBusCallFlags.NONE,
                                     1000, None, None, None)
        self.signal_ids = []
        self.session_handle = None
        self.pending.clear()
        self.early.clear()
