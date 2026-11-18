"""Read desktop item identities through the Windows Shell folder view."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import uuid


class ShellError(Exception):
    pass


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("reserved1", ctypes.c_ushort),
                ("reserved2", ctypes.c_ushort), ("reserved3", ctypes.c_ushort),
                ("value", ctypes.c_longlong), ("extra", ctypes.c_longlong)]


def _call(obj, index, argtypes, *args):
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    function = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
    result = function(obj, *args)
    if result < 0:
        raise ShellError(f"Shell HRESULT 0x{result & 0xffffffff:08X}")
    return result


def _release(obj):
    if obj.value:
        _call(obj, 2, [])


def desktop_identities():
    """Return Shell parsing names and positions in desktop view order."""
    ole = ctypes.WinDLL("ole32")
    shell = ctypes.WinDLL("shlwapi")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    shell.StrRetToBufW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.LPWSTR, wintypes.UINT]
    shell.StrRetToBufW.restype = ctypes.c_long
    status = ole.CoInitializeEx(None, 2)
    if status < 0 and status != -2147417850:  # RPC_E_CHANGED_MODE: already initialized
        raise ShellError("COM initialization failed")
    objects = [ctypes.c_void_p() for _ in range(6)]
    windows, dispatch, provider, browser, view, folder_view = objects
    folder = ctypes.c_void_p()
    try:
        clsid = GUID("9BA05972-F6A8-11CF-A442-00A0C90A8F39")
        iid_windows = GUID("85CB6900-4D95-11CF-960C-0080C7F4EE85")
        if ole.CoCreateInstance(ctypes.byref(clsid), None, 4, ctypes.byref(iid_windows), ctypes.byref(windows)) < 0:
            raise ShellError("Unable to open Shell windows")
        location, empty, hwnd = VARIANT(), VARIANT(), wintypes.LONG()
        location.vt = 3  # VT_I4; CSIDL_DESKTOP is zero
        _call(windows, 15, [ctypes.POINTER(VARIANT), ctypes.POINTER(VARIANT), ctypes.c_int,
                            ctypes.POINTER(wintypes.LONG), ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
              ctypes.byref(location), ctypes.byref(empty), 8, ctypes.byref(hwnd), 1, ctypes.byref(dispatch))
        if not dispatch.value:
            raise ShellError("Desktop Shell view is unavailable")
        iid_provider = GUID("6D5140C1-7436-11CE-8034-00AA006009FA")
        _call(dispatch, 0, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(iid_provider), ctypes.byref(provider))
        iid_browser = GUID("000214E2-0000-0000-C000-000000000046")
        _call(provider, 3, [ctypes.POINTER(GUID), ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
              ctypes.byref(iid_browser), ctypes.byref(iid_browser), ctypes.byref(browser))
        _call(browser, 15, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(view))
        iid_view = GUID("CDE725B0-CCC9-4519-917E-325D72FAB4CE")
        _call(view, 0, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(iid_view), ctypes.byref(folder_view))
        iid_folder = GUID("000214E6-0000-0000-C000-000000000046")
        _call(folder_view, 5, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(iid_folder), ctypes.byref(folder))
        count = ctypes.c_int()
        _call(folder_view, 7, [wintypes.UINT, ctypes.POINTER(ctypes.c_int)], 0, ctypes.byref(count))
        identities = []
        for index in range(count.value):
            pidl = ctypes.c_void_p()
            _call(folder_view, 6, [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], index, ctypes.byref(pidl))
            try:
                # STRRET contains an aligned union; 272 bytes covers the native structure.
                result = ctypes.create_string_buffer(272)
                _call(folder, 11, [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p], pidl, 0x8000, result)
                name = ctypes.create_unicode_buffer(32768)
                if shell.StrRetToBufW(result, pidl, name, len(name)) < 0 or not name.value:
                    raise ShellError("Unable to identify desktop item")
                position = wintypes.POINT()
                _call(folder_view, 11, [ctypes.c_void_p, ctypes.POINTER(wintypes.POINT)], pidl, ctypes.byref(position))
                identities.append((name.value, [position.x, position.y]))
            finally:
                ole.CoTaskMemFree(pidl)
        if len({name for name, _ in identities}) != len(identities):
            raise ShellError("Desktop item identities are not unique")
        return identities
    finally:
        _release(folder)
        for obj in reversed(objects):
            _release(obj)
        if status >= 0:
            ole.CoUninitialize()
