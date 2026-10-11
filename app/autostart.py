"""Current-user Windows startup registration for the packaged application."""

from __future__ import annotations

import sys
from pathlib import Path

from app.branding import APP_AUTOSTART_NAME, LEGACY_AUTOSTART_NAMES

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_enabled() -> bool:
    """Return whether Windows will start this application for the current user."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            for name in (APP_AUTOSTART_NAME, *LEGACY_AUTOSTART_NAMES):
                try:
                    winreg.QueryValueEx(key, name)
                    return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


def set_enabled(enabled: bool) -> bool:
    """Enable or disable current-user startup without requiring administrator rights."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(
                    key,
                    APP_AUTOSTART_NAME,
                    0,
                    winreg.REG_SZ,
                    startup_command(),
                )
            for name in LEGACY_AUTOSTART_NAMES:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            if not enabled:
                try:
                    winreg.DeleteValue(key, APP_AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        return False
    return True


def refresh_registration() -> bool:
    """Re-register a packaged EXE that already starts with Windows.

    After an upgrade or product rename this moves entries saved under an old
    name to the current one and points them at the EXE that is now running.
    Running from source never touches the registry.
    """
    if not getattr(sys, "frozen", False) or not is_enabled():
        return False
    return set_enabled(True)


def startup_command() -> str:
    """Return the correctly quoted command Windows should launch after sign-in."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    root = Path(__file__).resolve().parent.parent
    return f'"{Path(sys.executable).resolve()}" "{root / "main.py"}"'
