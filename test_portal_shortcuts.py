import unittest
from types import SimpleNamespace

from gi.repository import GLib

from portal_shortcuts import PortalShortcuts


SESSION = '/org/freedesktop/portal/desktop/session/test/apistat'


class PortalShortcutTests(unittest.TestCase):
    def test_activation_uses_local_playback_and_ignores_other_sessions(self):
        calls = []
        player = SimpleNamespace(closed=False, toggle=lambda: calls.append('toggle'),
                                 advance=lambda: calls.append('next'))
        portal = PortalShortcuts(player, lambda: None)
        portal.session_handle = SESSION
        for session, action in ((SESSION, 'PlayPause'), (SESSION, 'Next'),
                                ('/another/session', 'Next'), (SESSION, 'Unknown')):
            portal._activated(None, None, None, None, None,
                              GLib.Variant('(osta{sv})', (session, action, 0, {})))
        self.assertEqual(calls, ['toggle', 'next'])

    def test_bind_requests_all_playback_actions_once(self):
        portal = PortalShortcuts(SimpleNamespace(), lambda: None)
        portal.session_handle = SESSION
        requests = []
        portal._request = lambda method, args, done: requests.append((method, args))
        portal.enable()
        portal.enable()
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0][0], 'BindShortcuts')
        session, actions, parent, options = requests[0][1].unpack()
        self.assertEqual(session, SESSION)
        self.assertEqual({name for name, _metadata in actions},
                         {'PlayPause', 'Play', 'Pause', 'Next', 'Previous', 'Stop'})
        self.assertEqual(parent, '')
        self.assertEqual(options, {})
        self.assertEqual(requests[1][0], 'CreateSession')

    def test_response_can_arrive_before_method_handle(self):
        portal = PortalShortcuts(SimpleNamespace(), lambda: None)
        path = '/org/freedesktop/portal/desktop/request/test/apistat'
        answers = []
        portal._request_response(None, None, path, None, None,
                                 GLib.Variant('(ua{sv})', (0, {'session_handle':
                                                    GLib.Variant('s', SESSION)})))
        portal._request_handle(GLib.Variant('(o)', (path,)), answers.append)
        self.assertEqual(answers[0][0], 0)
        self.assertEqual(portal.early, {})

    def test_shortcut_descriptions_from_desktop(self):
        updates = []
        portal = PortalShortcuts(SimpleNamespace(), lambda: updates.append(True))
        portal._update_shortcuts([('PlayPause', {'trigger_description':
                                               GLib.Variant('s', 'Ctrl+Alt+P')})])
        self.assertEqual(portal.shortcuts, {'PlayPause': 'Ctrl+Alt+P'})
        self.assertEqual(updates, [True])


if __name__ == '__main__':
    unittest.main()
