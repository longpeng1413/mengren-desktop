"""Temporary Windows hotkeys used only while presentation mode is active."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

from app.hotkeys import GlobalHotkey, _Msg
from app.preferences import PresentationShortcutSettings


class PresentationHotkeys(QAbstractNativeEventFilter):
    """Register drawing-tool shortcuts only for the lifetime of F5 mode."""

    _FIRST_ID = 201

    def __init__(self, action_callback: Callable[[str], None]) -> None:
        super().__init__()
        self._action_callback = action_callback
        self._settings = PresentationShortcutSettings()
        self._bindings: dict[int, tuple[str, object]] = {}
        self._registered_ids: set[int] = set()
        self._failed_actions: list[str] = []
        self._active = False
        self.configure(self._settings)

    @property
    def active(self) -> bool:
        """Return whether temporary tool shortcuts should currently be registered."""
        return self._active

    @property
    def failed_actions(self) -> tuple[str, ...]:
        """Return tool actions whose configured shortcuts Windows rejected."""
        return tuple(self._failed_actions)

    def configure(self, settings: PresentationShortcutSettings) -> bool:
        """Validate and replace all presentation shortcuts atomically."""
        try:
            parsed = self._parse_settings(settings)
        except ValueError:
            return False
        old_settings = self._settings
        old_bindings = self._bindings
        was_active = self._active
        if was_active:
            self._unregister_all()
        self._settings = settings
        self._bindings = parsed
        if not was_active:
            return True
        if self._register_all():
            return True
        self._unregister_all()
        self._settings = old_settings
        self._bindings = old_bindings
        self._register_all()
        return False

    def set_active(self, active: bool) -> bool:
        """Enable or disable every temporary presentation shortcut."""
        if active == self._active:
            return True
        if not active:
            self._unregister_all()
            self._active = False
            return True
        self._active = True
        # Keep every shortcut that Windows accepted.  One unavailable binding
        # must not disable the remaining presentation tools or trigger another
        # registration attempt every time the active signal is repeated.
        return self._register_all()

    def check_availability(self) -> bool:
        """Temporarily verify that other applications do not own configured keys."""
        if self._active or sys.platform != "win32" or not self._bindings:
            return not self._failed_actions
        available = self._register_all()
        failed = list(self._failed_actions)
        self._unregister_all()
        self._failed_actions = failed
        return available

    def unregister(self) -> None:
        """Release temporary shortcuts during application shutdown."""
        self._unregister_all()
        self._active = False

    def nativeEventFilter(self, event_type, message) -> bool:
        """Dispatch WM_HOTKEY messages belonging to presentation actions."""
        if bytes(event_type) != b"windows_generic_MSG":
            return False
        native_message = _Msg.from_address(int(message))
        item = self._bindings.get(native_message.w_param)
        if native_message.message != GlobalHotkey._WM_HOTKEY or item is None:
            return False
        action, _binding = item
        QTimer.singleShot(0, lambda selected=action: self._action_callback(selected))
        return True

    @classmethod
    def _parse_settings(
        cls,
        settings: PresentationShortcutSettings,
    ) -> dict[int, tuple[str, object]]:
        parsed: dict[int, tuple[str, object]] = {}
        signatures: set[tuple[int, int]] = set()
        for offset, (action, sequence) in enumerate(settings.as_action_map().items()):
            if not sequence.strip():
                continue
            binding = GlobalHotkey._parse_sequence(sequence)
            signature = (binding.modifiers, binding.virtual_key)
            if signature in signatures:
                raise ValueError("duplicate presentation shortcuts")
            signatures.add(signature)
            parsed[cls._FIRST_ID + offset] = (action, binding)
        return parsed

    def _register_all(self) -> bool:
        self._failed_actions.clear()
        if sys.platform != "win32":
            return True
        all_registered = True
        for hotkey_id, (action, binding) in self._bindings.items():
            if not ctypes.windll.user32.RegisterHotKey(
                None,
                hotkey_id,
                binding.modifiers | GlobalHotkey._MOD_NOREPEAT,
                binding.virtual_key,
            ):
                self._failed_actions.append(action)
                all_registered = False
                continue
            self._registered_ids.add(hotkey_id)
        return all_registered

    def _unregister_all(self) -> None:
        if sys.platform == "win32":
            for hotkey_id in self._registered_ids:
                ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self._registered_ids.clear()
        self._failed_actions.clear()
