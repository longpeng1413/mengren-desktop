"""Windows global hotkey integration."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer, Qt
from PySide6.QtGui import QKeySequence


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("w_param", wintypes.WPARAM),
        ("l_param", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("point", _Point),
        ("private", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class _Binding:
    """One parsed Windows shortcut registration."""

    sequence: str
    modifiers: int
    virtual_key: int


class GlobalHotkey(QAbstractNativeEventFilter):
    """Registers application-level capture, desktop, and system shortcuts."""

    _MOD_ALT = 0x0001
    _MOD_CONTROL = 0x0002
    _MOD_SHIFT = 0x0004
    _MOD_WIN = 0x0008
    _MOD_NOREPEAT = 0x4000
    _WM_HOTKEY = 0x0312
    _NORMAL_ID = 101
    _LONG_ID = 102
    _PRESENTATION_ID = 105
    _REMINDER_ID = 106
    _CALCULATOR_ID = 107
    _SLEEP_ID = 108
    _FEATURE_IDS = {
        "normal": _NORMAL_ID,
        "long": _LONG_ID,
        "presentation": _PRESENTATION_ID,
        "reminder": _REMINDER_ID,
        "calculator": _CALCULATOR_ID,
        "sleep": _SLEEP_ID,
    }

    def __init__(
        self,
        capture_callback: Callable[[], None],
        long_capture_callback: Callable[[], None],
        presentation_callback: Callable[[], None],
        normal_shortcut: str = "F1",
        long_shortcut: str = "F2",
        presentation_shortcut: str = "F4",
        reminder_callback: Callable[[], None] | None = None,
        reminder_shortcut: str = "F3",
        calculator_callback: Callable[[], None] | None = None,
        calculator_shortcut: str = "Shift+Q",
        sleep_callback: Callable[[], None] | None = None,
        sleep_shortcut: str = "Shift+F12",
    ) -> None:
        super().__init__()
        self._callbacks = {
            self._NORMAL_ID: capture_callback,
            self._LONG_ID: long_capture_callback,
            self._PRESENTATION_ID: presentation_callback,
            self._REMINDER_ID: reminder_callback or (lambda: None),
            self._CALCULATOR_ID: calculator_callback or (lambda: None),
            self._SLEEP_ID: sleep_callback or (lambda: None),
        }
        self._registered_ids: set[int] = set()
        self._suspended = False
        self._bindings = self._parse_bindings(
            normal_shortcut,
            long_shortcut,
            presentation_shortcut,
            reminder_shortcut,
            calculator_shortcut,
            sleep_shortcut,
        )
        self._registration = dict.fromkeys(self._FEATURE_IDS, False)

    @property
    def registration(self) -> dict[str, bool]:
        """Return the latest registration state for both configured shortcuts."""
        return dict(self._registration)

    @property
    def shortcuts(self) -> tuple[str, str, str, str, str, str]:
        """Return all global shortcuts in display order."""
        normal = self._bindings[self._NORMAL_ID].sequence
        long_capture = self._bindings[self._LONG_ID].sequence
        presentation = self._bindings[self._PRESENTATION_ID].sequence
        reminder = self._bindings[self._REMINDER_ID].sequence
        calculator = self._bindings[self._CALCULATOR_ID].sequence
        sleep = self._bindings[self._SLEEP_ID].sequence
        return (
            normal,
            long_capture,
            presentation,
            reminder,
            calculator,
            sleep,
        )

    def register(self) -> dict[str, bool]:
        """Register all configured shortcuts for the current Windows thread."""
        if self._suspended:
            self._registration = dict.fromkeys(self._FEATURE_IDS, False)
            return self.registration
        if sys.platform != "win32":
            self._registration = dict.fromkeys(self._FEATURE_IDS, False)
            return self.registration
        self._registration = {
            name: (
                self._register(hotkey_id)
                if self._bindings[hotkey_id].sequence
                else False
            )
            for name, hotkey_id in self._FEATURE_IDS.items()
        }
        return self.registration

    def reconfigure(
        self,
        normal_shortcut: str,
        long_shortcut: str,
        presentation_shortcut: str,
        reminder_shortcut: str = "F3",
        calculator_shortcut: str = "Shift+Q",
        sleep_shortcut: str = "Shift+F12",
    ) -> bool:
        """Apply all shortcuts, restoring the old set if one is unavailable."""
        try:
            new_bindings = self._parse_bindings(
                normal_shortcut,
                long_shortcut,
                presentation_shortcut,
                reminder_shortcut,
                calculator_shortcut,
                sleep_shortcut,
            )
        except ValueError:
            return False

        old_bindings = self._bindings
        self.unregister()
        self._bindings = new_bindings
        results = self.register()
        if all(
            not self._bindings[hotkey_id].sequence or results[name]
            for name, hotkey_id in self._FEATURE_IDS.items()
        ):
            return True

        self.unregister()
        self._bindings = old_bindings
        self.register()
        return False

    def unregister(self) -> None:
        """Release every global shortcut registered by this object."""
        if sys.platform == "win32":
            for hotkey_id in self._registered_ids:
                ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self._registered_ids.clear()
        self._registration = dict.fromkeys(self._FEATURE_IDS, False)

    def suspend(self) -> None:
        """Temporarily release shortcuts while the user records replacement keys."""
        if self._suspended:
            return
        self._suspended = True
        self.unregister()

    def resume(self) -> dict[str, bool]:
        """Restore shortcuts after the shortcut editor has closed."""
        if not self._suspended:
            return self.registration
        self._suspended = False
        return self.register()

    def nativeEventFilter(self, event_type, message) -> bool:
        """Forward Windows WM_HOTKEY notifications to the matching callback."""
        if self._suspended:
            return False
        if bytes(event_type) != b"windows_generic_MSG":
            return False
        native_message = _Msg.from_address(int(message))
        if native_message.message != self._WM_HOTKEY:
            return False
        callback = self._callbacks.get(native_message.w_param)
        if callback is not None:
            QTimer.singleShot(0, callback)
            return True
        return False

    def _register(self, hotkey_id: int) -> bool:
        """Register one previously parsed binding with the Windows API."""
        binding = self._bindings[hotkey_id]
        if ctypes.windll.user32.RegisterHotKey(
            None,
            hotkey_id,
            binding.modifiers | self._MOD_NOREPEAT,
            binding.virtual_key,
        ):
            self._registered_ids.add(hotkey_id)
            return True
        return False

    @classmethod
    def _parse_bindings(
        cls,
        normal_shortcut: str,
        long_shortcut: str,
        presentation_shortcut: str,
        reminder_shortcut: str = "",
        calculator_shortcut: str = "",
        sleep_shortcut: str = "",
    ) -> dict[int, _Binding]:
        """Validate all shortcut strings and translate them to Windows virtual keys."""
        normal = cls._parse_sequence(normal_shortcut)
        long_capture = cls._parse_sequence(long_shortcut)
        presentation = cls._parse_sequence(
            presentation_shortcut,
            allow_empty=True,
        )
        reminder = cls._parse_sequence(reminder_shortcut, allow_empty=True)
        calculator = cls._parse_sequence(calculator_shortcut, allow_empty=True)
        sleep = cls._parse_sequence(sleep_shortcut, allow_empty=True)
        bindings = {
            cls._NORMAL_ID: normal,
            cls._LONG_ID: long_capture,
            cls._PRESENTATION_ID: presentation,
            cls._REMINDER_ID: reminder,
            cls._CALCULATOR_ID: calculator,
            cls._SLEEP_ID: sleep,
        }
        active_bindings = [binding for binding in bindings.values() if binding.sequence]
        signatures = {
            (binding.modifiers, binding.virtual_key)
            for binding in active_bindings
        }
        if len(signatures) != len(active_bindings):
            raise ValueError("duplicate shortcuts")
        return bindings

    @classmethod
    def _parse_sequence(cls, text: str, allow_empty: bool = False) -> _Binding:
        """Convert one single-step Qt key sequence into a Windows registration binding."""
        if not text.strip():
            if allow_empty:
                return _Binding("", 0, 0)
            raise ValueError("invalid shortcut")
        sequence = QKeySequence(text)
        if sequence.isEmpty() or sequence.count() != 1:
            raise ValueError("invalid shortcut")
        combination = sequence[0]
        key = combination.key()
        virtual_key = cls._to_virtual_key(key)
        if virtual_key is None:
            raise ValueError("unsupported shortcut")
        modifiers = combination.keyboardModifiers()
        windows_modifiers = 0
        if modifiers & Qt.KeyboardModifier.AltModifier:
            windows_modifiers |= cls._MOD_ALT
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            windows_modifiers |= cls._MOD_CONTROL
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            windows_modifiers |= cls._MOD_SHIFT
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            windows_modifiers |= cls._MOD_WIN
        portable = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        return _Binding(portable, windows_modifiers, virtual_key)

    @staticmethod
    def _to_virtual_key(key: Qt.Key) -> int | None:
        """Map supported Qt keys to the virtual-key values required by RegisterHotKey."""
        value = int(key)
        if int(Qt.Key.Key_F1) <= value <= int(Qt.Key.Key_F24):
            return 0x70 + value - int(Qt.Key.Key_F1)
        if int(Qt.Key.Key_0) <= value <= int(Qt.Key.Key_9):
            return value
        if int(Qt.Key.Key_A) <= value <= int(Qt.Key.Key_Z):
            return value
        special_keys = {
            Qt.Key.Key_Space: 0x20,
            Qt.Key.Key_Escape: 0x1B,
            Qt.Key.Key_Insert: 0x2D,
            Qt.Key.Key_Delete: 0x2E,
            Qt.Key.Key_Home: 0x24,
            Qt.Key.Key_End: 0x23,
            Qt.Key.Key_PageUp: 0x21,
            Qt.Key.Key_PageDown: 0x22,
        }
        return special_keys.get(key)
