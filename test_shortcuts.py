import unittest
from unittest.mock import patch

import shortcuts


class ShortcutTests(unittest.TestCase):
    def test_reads_existing_player_bindings(self):
        command = shortcuts.command_for('PlayPause')
        listing = (f'/commands/custom/XF86AudioPlay   {command}\n'
                   '/commands/custom/<Alt>F1   another-command\n')
        with patch.object(shortcuts, '_xfconf', return_value=listing):
            bindings = shortcuts.bindings()
        self.assertEqual(bindings['PlayPause'], ['XF86AudioPlay'])
        self.assertEqual(bindings['Next'], [])

    def test_rebind_preserves_other_commands(self):
        command = shortcuts.command_for('PlayPause')
        current = {'/commands/custom/XF86AudioPlay': command}
        with patch.object(shortcuts, 'all_shortcuts', return_value=current), \
             patch.object(shortcuts, '_xfconf') as xfconf:
            shortcuts.set_binding('PlayPause', '<Primary><Alt>p')
        self.assertEqual(xfconf.call_count, 2)
        self.assertEqual(xfconf.call_args_list[0].args[-1], command)
        self.assertEqual(xfconf.call_args_list[1].args,
                         ('-p', '/commands/custom/XF86AudioPlay', '-r'))

    def test_conflict_does_not_change_existing_shortcut(self):
        current = {'/commands/custom/<Primary><Alt>p': 'another-command'}
        with patch.object(shortcuts, 'all_shortcuts', return_value=current), \
             patch.object(shortcuts, '_xfconf') as xfconf:
            with self.assertRaises(shortcuts.ShortcutConflict):
                shortcuts.set_binding('PlayPause', '<Primary><Alt>p')
        xfconf.assert_not_called()

    def test_clear_removes_only_own_binding(self):
        command = shortcuts.command_for('Pause')
        current = {'/commands/custom/XF86AudioPause': command,
                   '/commands/custom/<Alt>F1': 'another-command'}
        with patch.object(shortcuts, 'all_shortcuts', return_value=current), \
             patch.object(shortcuts, '_xfconf') as xfconf:
            shortcuts.clear_bindings('Pause')
        xfconf.assert_called_once_with('-p', '/commands/custom/XF86AudioPause', '-r')


if __name__ == '__main__':
    unittest.main()
