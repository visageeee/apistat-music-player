import unittest
import os
import sys
from unittest.mock import patch

import credentials


class CredentialTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'), 'Secret Service is Linux only')
    def test_linux_secret_service_backend(self):
        with patch.object(credentials, 'Secret') as secret:
            secret.COLLECTION_DEFAULT = 'default'
            secret.password_store_sync.return_value = True
            credentials._save_value('test-value')
            secret.password_lookup_sync.return_value = 'test-value'
            self.assertEqual(credentials._load_value(), 'test-value')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Secret Service is Linux only')
    def test_legacy_secret_is_copied_to_new_schema(self):
        with patch.object(credentials, 'Secret') as secret, \
                patch.object(credentials, '_save_value') as save:
            secret.password_lookup_sync.side_effect = [None, 'saved-login']
            self.assertEqual(credentials._load_value(), 'saved-login')
            self.assertEqual(secret.password_lookup_sync.call_args_list[1].args[0],
                             credentials.LEGACY_SCHEMA)
            save.assert_called_once_with('saved-login')

    def test_save_and_restore_connection(self):
        with patch.object(credentials, '_save_value') as save, \
             patch.object(credentials, '_load_value') as load:
            credentials.save_credentials('https://plex.example:32400', 'test-secret')
            saved = save.call_args.args[0]
            load.return_value = saved
            self.assertEqual(credentials.load_credentials(),
                             ('https://plex.example:32400', 'test-secret'))

    def test_missing_or_invalid_connection(self):
        with patch.object(credentials, '_load_value') as load:
            for value in (None, '', '{}', '{bad json}', '{"address": 5, "token": "x"}'):
                load.return_value = value
                self.assertIsNone(credentials.load_credentials())


if __name__ == '__main__':
    unittest.main()
