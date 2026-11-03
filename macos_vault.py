"""Store Apistat secrets in macOS Keychain without a plaintext fallback."""

import sys

SERVICE = 'org.apistat.Apistat'


def _target(name):
    if not isinstance(name, str) or not name.startswith('Apistat/') or len(name) > 256:
        raise ValueError('Invalid credential target.')
    return name


def _backend():
    if sys.platform != 'darwin':
        raise OSError('macOS Keychain is unavailable on this system.')
    # Select Keychain explicitly instead of accepting a configured fallback backend.
    from keyring.backends.macOS import Keyring
    return Keyring()


def read_secret(name):
    return _backend().get_password(SERVICE, _target(name))


def write_secret(name, value):
    name = _target(name)
    if not isinstance(value, str) or not value:
        raise ValueError('Credential value must be nonempty text.')
    _backend().set_password(SERVICE, name, value)


def delete_secret(name):
    name = _target(name)
    backend = _backend()
    if backend.get_password(SERVICE, name) is not None:
        backend.delete_password(SERVICE, name)
