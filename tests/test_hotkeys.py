"""Tests for all configurable global and presentation shortcuts."""

import ctypes
from app import hotkeys as hotkeys_module
from app.hotkeys import GlobalHotkey
import json
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.application import _repair_startup_settings
from app import preferences
from app import presentation_hotkeys as presentation_hotkeys_module
from app.preferences import HotkeySettings, PresentationShortcutSettings
from app.presentation_hotkeys import PresentationHotkeys


def test_global_shortcuts_are_parsed() -> None:
    bindings = GlobalHotkey._parse_bindings("F1", "F2", "F4", "F3")

    assert len(bindings) == 6


def test_duplicate_shortcuts_are_rejected() -> None:
    try:
        GlobalHotkey._parse_bindings("F1", "F2", "F4", "F4")
    except ValueError:
        return
    raise AssertionError("duplicate shortcuts must be rejected")


def test_optional_global_shortcuts_may_be_empty() -> None:
    bindings = GlobalHotkey._parse_bindings("F1", "F2", "")

    assert bindings[GlobalHotkey._PRESENTATION_ID].sequence == ""
    assert bindings[GlobalHotkey._REMINDER_ID].sequence == ""
    assert bindings[GlobalHotkey._CALCULATOR_ID].sequence == ""
    assert bindings[GlobalHotkey._SLEEP_ID].sequence == ""


def test_system_action_shortcuts_are_parsed_and_check_duplicates() -> None:
    bindings = GlobalHotkey._parse_bindings(
        "F1",
        "F2",
        "F4",
        "F3",
        "Shift+Q",
        "Shift+F12",
    )

    assert bindings[GlobalHotkey._CALCULATOR_ID].sequence == "Shift+Q"
    assert bindings[GlobalHotkey._SLEEP_ID].sequence == "Shift+F12"

    try:
        GlobalHotkey._parse_bindings(
            "F1",
            "F2",
            "F4",
            "F3",
            "Shift+Q",
            "Shift+Q",
        )
    except ValueError:
        return
    raise AssertionError("duplicate system-action shortcuts must be rejected")


def test_reminder_shortcut_participates_in_duplicate_validation() -> None:
    try:
        GlobalHotkey._parse_bindings(
            "F1",
            "F2",
            "",
            "F1",
        )
    except ValueError:
        return
    raise AssertionError("duplicate reminder shortcut must be rejected")


def test_duplicate_saved_global_shortcuts_are_repaired_before_startup() -> None:
    invalid = HotkeySettings(reminder="F1")

    assert _repair_startup_settings(invalid) == HotkeySettings()


def test_defaults_use_f1_through_f4() -> None:
    settings = HotkeySettings()

    assert settings.normal_capture == "F1"
    assert settings.long_capture == "F2"
    assert settings.reminder == "F3"
    assert settings.presentation_mode == "F4"
    assert settings.calculator == "Shift+Q"
    assert settings.sleep == "Shift+F12"


def test_global_and_presentation_shortcut_conflict_is_repaired() -> None:
    invalid = HotkeySettings(
        presentation_tools=PresentationShortcutSettings(brush="F1")
    )

    assert _repair_startup_settings(invalid) == HotkeySettings()


def test_presentation_shortcuts_are_distinct_and_parsed() -> None:
    parsed = PresentationHotkeys._parse_settings(PresentationShortcutSettings())

    assert parsed == {}


def test_duplicate_presentation_shortcuts_are_rejected() -> None:
    settings = PresentationShortcutSettings(
        brush="Ctrl+Alt+B",
        line="Ctrl+Alt+B",
    )
    try:
        PresentationHotkeys._parse_settings(settings)
    except ValueError:
        return
    raise AssertionError("duplicate presentation shortcuts must be rejected")


def test_legacy_reserved_clear_shortcut_is_migrated(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "normal_capture": "F1",
                "long_capture": "F2",
                "presentation_tools": {"clear": "Ctrl+Alt+Delete"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preferences, "_settings_file", lambda: settings_path)

    loaded = preferences.load_hotkey_settings()

    assert loaded.presentation_tools.clear == ""


def test_legacy_optional_shortcuts_are_cleared_once(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "normal_capture": "F1",
                "long_capture": "F2",
                "horizontal_capture": "F3",
                "record_capture": "F4",
                "presentation_mode": "F5",
                "presentation_tools": {"brush": "Ctrl+Alt+B"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preferences, "_settings_file", lambda: settings_path)

    loaded = preferences.load_hotkey_settings()

    assert loaded.presentation_mode == "F4"
    assert all(not value for value in loaded.presentation_tools.as_action_map().values())
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["shortcut_defaults_version"] == 4
    assert "horizontal_capture" not in saved
    assert "record_capture" not in saved
    assert loaded.reminder == "F3"


def test_version_2_shortcuts_migrate_desktop_and_teacher_defaults(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "normal_capture": "F1",
                "long_capture": "F2",
                "horizontal_capture": "F3",
                "record_capture": "",
                "presentation_mode": "",
                "reminder": "F4",
                "shortcut_defaults_version": 2,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preferences, "_settings_file", lambda: settings_path)

    loaded = preferences.load_hotkey_settings()

    assert loaded.presentation_mode == "F4"
    assert loaded.reminder == "F3"
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["shortcut_defaults_version"] == 4


def test_version_3_settings_receive_system_action_defaults(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "normal_capture": "F1",
                "long_capture": "F2",
                "horizontal_capture": "Ctrl+F3",
                "record_capture": "",
                "presentation_mode": "F4",
                "reminder": "F3",
                "shortcut_defaults_version": 3,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(preferences, "_settings_file", lambda: settings_path)

    loaded = preferences.load_hotkey_settings()

    assert loaded.calculator == "Shift+Q"
    assert loaded.sleep == "Shift+F12"
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["calculator"] == "Shift+Q"
    assert saved["sleep"] == "Shift+F12"
    assert saved["shortcut_defaults_version"] == 4


def test_system_action_hotkeys_dispatch_to_their_callbacks() -> None:
    application = QApplication.instance() or QApplication([])
    actions: list[str] = []
    hotkeys = GlobalHotkey(
        lambda: None,
        lambda: None,
        lambda: None,
        calculator_callback=lambda: actions.append("calculator"),
        sleep_callback=lambda: actions.append("sleep"),
    )

    for hotkey_id in (GlobalHotkey._CALCULATOR_ID, GlobalHotkey._SLEEP_ID):
        message = hotkeys_module._Msg()
        message.message = GlobalHotkey._WM_HOTKEY
        message.w_param = hotkey_id
        assert hotkeys.nativeEventFilter(
            b"windows_generic_MSG",
            ctypes.addressof(message),
        )
    QTimer.singleShot(0, application.quit)
    application.exec()

    assert actions == ["calculator", "sleep"]


def test_global_hotkeys_suspend_and_resume_around_shortcut_recording(
    monkeypatch,
) -> None:
    hotkeys = GlobalHotkey(
        lambda: None,
        lambda: None,
        lambda: None,
    )
    calls: list[str] = []
    monkeypatch.setattr(hotkeys, "unregister", lambda: calls.append("unregister"))

    def register() -> dict[str, bool]:
        calls.append("register")
        return {name: True for name in hotkeys._FEATURE_IDS}

    monkeypatch.setattr(hotkeys, "register", register)

    hotkeys.suspend()

    assert hotkeys._suspended
    assert calls == ["unregister"]
    assert not hotkeys.nativeEventFilter(b"windows_generic_MSG", 0)

    assert hotkeys.resume()["normal"]
    assert not hotkeys._suspended
    assert calls == ["unregister", "register"]


def test_partial_presentation_registration_remains_active(monkeypatch) -> None:
    hotkeys = PresentationHotkeys(lambda _action: None)
    monkeypatch.setattr(hotkeys, "_register_all", lambda: False)

    assert not hotkeys.set_active(True)
    assert hotkeys.active


def test_presentation_registration_reports_every_failed_action(monkeypatch) -> None:
    hotkeys = PresentationHotkeys(lambda _action: None)
    assert hotkeys.configure(
        PresentationShortcutSettings(
            pointer_brush_toggle="F6",
            brush="F8",
            line="F7",
        )
    )
    rejected_ids = {201, 203}
    fake_user32 = SimpleNamespace(
        RegisterHotKey=lambda _window, hotkey_id, _modifiers, _key: hotkey_id not in rejected_ids
    )
    monkeypatch.setattr(presentation_hotkeys_module.sys, "platform", "win32")
    monkeypatch.setattr(
        presentation_hotkeys_module.ctypes,
        "windll",
        SimpleNamespace(user32=fake_user32),
    )

    assert not hotkeys._register_all()
    assert hotkeys.failed_actions == ("pointer_brush_toggle", "line")
    assert len(hotkeys._registered_ids) == 1


def test_independent_native_filter_dispatches_presentation_shortcuts(
    monkeypatch,
) -> None:
    application = QApplication.instance() or QApplication([])
    actions: list[str] = []
    presentation = PresentationHotkeys(actions.append)
    assert presentation.configure(
        PresentationShortcutSettings(pointer_brush_toggle="F6")
    )
    monkeypatch.setattr(presentation_hotkeys_module.sys, "platform", "linux")
    assert presentation.set_active(True)
    presentation._registered_ids.add(PresentationHotkeys._FIRST_ID)

    message = presentation_hotkeys_module._Msg()
    message.message = GlobalHotkey._WM_HOTKEY
    message.w_param = PresentationHotkeys._FIRST_ID

    handled = presentation.nativeEventFilter(
        b"windows_generic_MSG",
        ctypes.addressof(message),
    )
    QTimer.singleShot(0, application.quit)
    application.exec()

    assert handled
    assert actions == ["pointer_brush_toggle"]
