"""Windows helpers for keeping reminder cards on the desktop layer."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


_HWND_BOTTOM = 1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_NOOWNERZORDER = 0x0200


def _user32():
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    return user32


def send_window_to_bottom(handle: int) -> bool:
    """Place a reminder card at the bottom of the normal top-level window stack."""
    if sys.platform != "win32" or not handle:
        return True
    try:
        return bool(
            _user32().SetWindowPos(
                wintypes.HWND(handle),
                wintypes.HWND(_HWND_BOTTOM),
                0,
                0,
                0,
                0,
                _SWP_NOSIZE
                | _SWP_NOMOVE
                | _SWP_NOACTIVATE
                | _SWP_NOOWNERZORDER,
            )
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False
