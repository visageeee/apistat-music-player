import unittest
from unittest.mock import patch

import credentials


class CredentialTests(unittest.TestCase):
    def test_save_and_restore_connection(self):
        with patch.object(credentials, 'Secret') as secret:
            secret.COLLECTION_DEFAULT = 'default'
            secret.password_store_sync.return_value = True
            credentials.save_credentials('https://plex.example:32400', 'test-secret')
            saved = secret.password_store_sync.call_args.args[4]
            secret.password_lookup_sync.return_value = saved
            self.assertEqual(credentials.load_credentials(),
                             ('https://plex.example:32400', 'test-secret'))

    def test_missing_or_invalid_connection(self):
        with patch.object(credentials, 'Secret') as secret:
            for value in (None, '', '{}', '{bad json}', '{"address": 5, "token": "x"}'):
                secret.password_lookup_sync.return_value = value
                self.assertIsNone(credentials.load_credentials())


if __name__ == '__main__':
    unittest.main()
