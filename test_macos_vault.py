import socket
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import companion
import companion_account
import credentials
import macos_vault


class MacOSVaultTests(unittest.TestCase):
    def test_keychain_targets_and_round_trip(self):
        backend = Mock()
        backend.get_password.return_value = 'saved'
        with patch.object(macos_vault, '_backend', return_value=backend):
            macos_vault.write_secret('Apistat/PlexServer', 'secret')
            backend.set_password.assert_called_once_with('org.apistat.Apistat',
                                                         'Apistat/PlexServer', 'secret')
            self.assertEqual(macos_vault.read_secret('Apistat/PlexServer'), 'saved')
            macos_vault.delete_secret('Apistat/PlexServer')
            backend.delete_password.assert_called_once_with('org.apistat.Apistat',
                                                            'Apistat/PlexServer')
            with self.assertRaises(ValueError):
                macos_vault.write_secret('OtherApp/Server', 'secret')
            with self.assertRaises(ValueError):
                macos_vault.write_secret('Apistat/PlexServer', '')

    def test_missing_keychain_entry_is_not_deleted(self):
        backend = Mock()
        backend.get_password.return_value = None
        with patch.object(macos_vault, '_backend', return_value=backend):
            macos_vault.delete_secret('Apistat/Companion/id')
        backend.delete_password.assert_not_called()

    def test_macos_server_and_account_tokens_use_keychain(self):
        with patch.object(credentials.sys, 'platform', 'darwin'), \
             patch.object(credentials, 'write_secret', create=True) as save, \
             patch.object(credentials, 'read_secret', return_value='saved', create=True) as load:
            credentials._save_value('secret')
            self.assertEqual(credentials._load_value(), 'saved')
            save.assert_called_once_with('Apistat/PlexServer', 'secret')
            load.assert_called_once_with('Apistat/PlexServer')
        with patch.object(companion_account.sys, 'platform', 'darwin'), \
             patch.object(companion_account, 'write_secret', create=True) as save, \
             patch.object(companion_account, 'delete_secret', create=True) as delete:
            companion_account.save_device_token('id', 'token')
            companion_account.clear_device_token('id')
            save.assert_called_once_with('Apistat/Companion/id', 'token')
            delete.assert_called_once_with('Apistat/Companion/id')

    def test_macos_uses_real_interface_mask_to_restrict_lan(self):
        entry = SimpleNamespace(family=socket.AF_INET, address='192.168.42.4',
                                netmask='255.255.255.0')
        psutil = SimpleNamespace(net_if_addrs=lambda: {'en0': [entry]})
        with patch.object(companion.sys, 'platform', 'darwin'), \
             patch.object(companion, 'local_ip', return_value='192.168.42.4'), \
             patch.object(companion, 'psutil', psutil, create=True):
            self.assertTrue(companion.same_lan_peer('192.168.42.100'))
            self.assertFalse(companion.same_lan_peer('192.168.43.100'))
            self.assertFalse(companion.same_lan_peer('8.8.8.8'))


if __name__ == '__main__':
    unittest.main()
