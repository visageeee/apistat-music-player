"""Store app secrets in the current Windows user's Credential Manager vault."""

import ctypes
import os
from ctypes import wintypes


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_BLOB_BYTES = 5 * 512


class Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]


CredentialPointer = ctypes.POINTER(Credential)


def _api():
    if os.name != 'nt':
        raise OSError('Windows Credential Manager is unavailable on this system.')
    library = ctypes.WinDLL('advapi32', use_last_error=True)
    library.CredWriteW.argtypes = (CredentialPointer, wintypes.DWORD)
    library.CredWriteW.restype = wintypes.BOOL
    library.CredReadW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(CredentialPointer))
    library.CredReadW.restype = wintypes.BOOL
    library.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
    library.CredDeleteW.restype = wintypes.BOOL
    library.CredFree.argtypes = (ctypes.c_void_p,)
    library.CredFree.restype = None
    return library


def _target(name):
    if not isinstance(name, str) or not name.startswith('Apistat/') or len(name) > 256:
        raise ValueError('Invalid credential target.')
    return name


def read_secret(name):
    api = _api()
    pointer = CredentialPointer()
    if not api.CredReadW(_target(name), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        credential = pointer.contents
        blob = ctypes.string_at(credential.CredentialBlob,
                                credential.CredentialBlobSize)
        return blob.decode('utf-8')
    finally:
        api.CredFree(pointer)


def write_secret(name, value):
    if not isinstance(value, str):
        raise TypeError('Credential value must be text.')
    blob = value.encode('utf-8')
    if not blob or len(blob) > MAX_BLOB_BYTES:
        raise ValueError('Credential value exceeds the Windows vault limit.')
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = Credential()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = _target(name)
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = 'Apistat'
    if not _api().CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def delete_secret(name):
    if not _api().CredDeleteW(_target(name), CRED_TYPE_GENERIC, 0):
        if ctypes.get_last_error() != ERROR_NOT_FOUND:
            raise ctypes.WinError(ctypes.get_last_error())
