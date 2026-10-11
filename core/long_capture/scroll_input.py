"""Windows mouse-wheel input used by automatic long capture."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


_INPUT_MOUSE = 0
_MOUSEEVENTF_WHEEL = 0x0800
_WHEEL_DELTA = 120
_SPI_GETWHEELSCROLLLINES = 0x0068
_WHEEL_PAGESCROLL = 0xFFFFFFFF
_BASELINE_SCROLL_LINES = 3
_MAX_NORMALIZED_WHEEL_DELTA = 15 * _WHEEL_DELTA


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("mi", _MouseInput),)


class _Input(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = (("type", wintypes.DWORD), ("payload", _InputUnion))


def _wheel_scroll_lines(user32) -> int:
    """Read the current user's vertical wheel setting, defaulting safely."""
    lines = ctypes.c_uint(_BASELINE_SCROLL_LINES)
    try:
        succeeded = user32.SystemParametersInfoW(
            _SPI_GETWHEELSCROLLLINES,
            0,
            ctypes.byref(lines),
            0,
        )
    except (AttributeError, OSError):
        return _BASELINE_SCROLL_LINES
    return int(lines.value) if succeeded else _BASELINE_SCROLL_LINES


def _normalized_wheel_delta(notches: int, scroll_lines: int) -> int:
    """Return a high-resolution wheel delta normalized to three lines."""
    if notches == 0:
        return 0
    direction = 1 if notches > 0 else -1
    if scroll_lines == _WHEEL_PAGESCROLL:
        return direction * _WHEEL_DELTA
    if scroll_lines <= 0:
        return notches * _WHEEL_DELTA
    numerator = abs(notches) * _WHEEL_DELTA * _BASELINE_SCROLL_LINES
    magnitude = (numerator + scroll_lines // 2) // scroll_lines
    magnitude = max(1, min(_MAX_NORMALIZED_WHEEL_DELTA, magnitude))
    return direction * magnitude


def _wheel_event_deltas(notches: int, scroll_lines: int) -> tuple[int, ...]:
    """Split a normalized movement into standard detents plus a small remainder."""
    total_delta = _normalized_wheel_delta(notches, scroll_lines)
    if total_delta == 0:
        return ()
    direction = 1 if total_delta > 0 else -1
    full_detents, remainder = divmod(abs(total_delta), _WHEEL_DELTA)
    deltas = [direction * _WHEEL_DELTA] * full_detents
    if remainder:
        deltas.append(direction * remainder)
    return tuple(deltas)


def send_vertical_wheel(x: int, y: int, notches: int) -> bool:
    """Move to the selected content and inject discrete wheel notches.

    Positive values scroll upward and negative values scroll downward.
    """
    if sys.platform != "win32" or notches == 0:
        return False
    user32 = ctypes.windll.user32
    if not user32.SetCursorPos(int(x), int(y)):
        return False
    deltas = _wheel_event_deltas(
        int(notches),
        _wheel_scroll_lines(user32),
    )
    if not deltas:
        return False
    for delta in deltas:
        event = _Input(
            type=_INPUT_MOUSE,
            mi=_MouseInput(
                mouseData=ctypes.c_uint32(delta).value,
                dwFlags=_MOUSEEVENTF_WHEEL,
            ),
        )
        inserted = user32.SendInput(
            1,
            ctypes.byref(event),
            ctypes.sizeof(event),
        )
        if inserted != 1:
            return False
    return True
