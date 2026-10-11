"""Small non-sensitive local preferences for AIShot."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PresentationShortcutSettings:
    """Shortcuts active only while desktop presentation mode is enabled."""

    pointer_brush_toggle: str = ""
    brush: str = ""
    line: str = ""
    rectangle: str = ""
    ellipse: str = ""
    arrow: str = ""
    text: str = ""
    eraser: str = ""
    clear: str = ""
    undo: str = ""
    redo: str = ""

    def as_action_map(self) -> dict[str, str]:
        """Return action names paired with their persisted key sequences."""
        return {
            "pointer_brush_toggle": self.pointer_brush_toggle,
            "brush": self.brush,
            "line": self.line,
            "rectangle": self.rectangle,
            "ellipse": self.ellipse,
            "arrow": self.arrow,
            "text": self.text,
            "eraser": self.eraser,
            "clear": self.clear,
            "undo": self.undo,
            "redo": self.redo,
        }


@dataclass(frozen=True, slots=True)
class HotkeySettings:
    """Persisted global shortcut choices."""

    normal_capture: str = "F1"
    long_capture: str = "F2"
    presentation_mode: str = "F4"
    presentation_tools: PresentationShortcutSettings = field(
        default_factory=PresentationShortcutSettings
    )
    reminder: str = "F3"
    calculator: str = "Shift+Q"
    sleep: str = "Shift+F12"


def _settings_file() -> Path:
    """Return a user-writable settings path outside the project source tree."""
    root = Path(os.environ.get("APPDATA", Path.home())) / "AIShot"
    return root / "settings.json"


def load_hotkey_settings() -> HotkeySettings:
    """Load shortcuts and migrate optional actions to opt-in bindings."""
    path = _settings_file()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        normal = str(values.get("normal_capture", "")).strip()
        long_capture = str(values.get("long_capture", "")).strip()
        defaults_version = int(values.get("shortcut_defaults_version", 0))
        migrate_optional_shortcuts = defaults_version < 2
        migrate_f3_f4_defaults = defaults_version < 3
        migrate_system_action_shortcuts = defaults_version < 4
        presentation = str(values.get("presentation_mode", "")).strip()
        reminder = str(values.get("reminder", "F4")).strip() or "F4"
        calculator = str(values.get("calculator", "Shift+Q")).strip()
        sleep = str(values.get("sleep", "Shift+F12")).strip()
        stored_tools = values.get("presentation_tools", {})
        if not isinstance(stored_tools, dict):
            stored_tools = {}
        defaults = PresentationShortcutSettings()
        tool_values = {
            name: str(stored_tools.get(name, default)).strip()
            for name, default in defaults.as_action_map().items()
        }
        if migrate_optional_shortcuts:
            presentation = ""
            tool_values = defaults.as_action_map()
        if migrate_f3_f4_defaults:
            if not presentation and reminder.casefold() == "f4":
                reminder = "F3"
                presentation = "F4"
        if tool_values["clear"].casefold().replace(" ", "") in {
            "ctrl+alt+delete",
            "ctrl+alt+del",
        }:
            tool_values["clear"] = defaults.clear
        tools = PresentationShortcutSettings(**tool_values)
        if normal and long_capture:
            settings = HotkeySettings(
                normal_capture=normal,
                long_capture=long_capture,
                presentation_mode=presentation,
                presentation_tools=tools,
                reminder=reminder,
                calculator=calculator,
                sleep=sleep,
            )
            if (
                migrate_optional_shortcuts
                or migrate_f3_f4_defaults
                or migrate_system_action_shortcuts
            ):
                try:
                    save_hotkey_settings(settings)
                except OSError:
                    pass
            return settings
    except (OSError, ValueError, TypeError):
        pass
    return HotkeySettings()


def save_hotkey_settings(settings: HotkeySettings) -> None:
    """Persist shortcut choices in the current Windows user's application data."""
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    values = asdict(settings)
    values["shortcut_defaults_version"] = 4
    path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
