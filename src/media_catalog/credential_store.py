"""Store a Gemini key in the current Windows user's Credential Manager."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

TARGET = 'MediaCatalogVideoDesktop/GeminiAPIKey'


class CredentialError(RuntimeError):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]


def _api():
    if os.name != 'nt':
        raise CredentialError('儲存 Key 需要 Windows Credential Manager')
    return ctypes.WinDLL('Advapi32', use_last_error=True)


def read_key(target: str = TARGET) -> str | None:
    api = _api()
    pointer = ctypes.POINTER(_Credential)()
    if not api.CredReadW(wintypes.LPCWSTR(target), 1, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == 1168:
            return None
        raise CredentialError(f'讀取 Gemini Key 失敗（Windows 錯誤 {error}）')
    try:
        credential = pointer.contents
        data = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return data.decode('utf-16-le')
    finally:
        api.CredFree(pointer)


def write_key(value: str, target: str = TARGET) -> None:
    key = value.strip()
    if not key:
        raise ValueError('Gemini Key 不可為空白')
    blob = key.encode('utf-16-le')
    if len(blob) > 2560:
        raise ValueError('Gemini Key 過長')
    backing = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _Credential(Type=1, TargetName=target, CredentialBlobSize=len(blob),
                             CredentialBlob=backing, Persist=2, UserName='MediaCatalogVideoDesktop')
    api = _api()
    if not api.CredWriteW(ctypes.byref(credential), 0):
        raise CredentialError(f'儲存 Gemini Key 失敗（Windows 錯誤 {ctypes.get_last_error()}）')


def delete_key(target: str = TARGET) -> None:
    api = _api()
    if not api.CredDeleteW(wintypes.LPCWSTR(target), 1, 0):
        error = ctypes.get_last_error()
        if error != 1168:
            raise CredentialError(f'移除 Gemini Key 失敗（Windows 錯誤 {error}）')
