import os
import unittest
import uuid

import windows_vault


class WindowsVaultTests(unittest.TestCase):
    def test_rejects_invalid_target_and_oversized_value(self):
        with self.assertRaises(ValueError):
            windows_vault.write_secret('OtherApp/Server', 'secret')
        with self.assertRaises(ValueError):
            windows_vault.write_secret('Apistat/Test', 'x' * (windows_vault.MAX_BLOB_BYTES + 1))

    @unittest.skipUnless(os.name == 'nt', 'Windows Credential Manager test')
    def test_generic_credential_round_trip_and_delete(self):
        target = f'Apistat/Test/{uuid.uuid4()}'
        try:
            self.assertIsNone(windows_vault.read_secret(target))
            windows_vault.write_secret(target, 'temporary test value')
            self.assertEqual(windows_vault.read_secret(target), 'temporary test value')
        finally:
            windows_vault.delete_secret(target)
        self.assertIsNone(windows_vault.read_secret(target))


if __name__ == '__main__':
    unittest.main()
