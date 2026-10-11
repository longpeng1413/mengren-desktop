"""Tests for the official release: metadata, launcher window and shortcut dialog."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from app.branding import APP_DISPLAY_NAME, APP_VERSION
from app.preferences import HotkeySettings
from ui.hotkey_dialog import HotkeyDialog
from ui import main_window as main_window_module
from ui.main_window import MainWindow


def test_release_uses_current_version_metadata() -> None:
    assert APP_VERSION == "18.19"
    assert APP_DISPLAY_NAME == "猛人桌面助手v18.19"


def test_hotkey_dialog_edits_capture_teacher_and_reminder() -> None:
    _app = QApplication.instance() or QApplication([])
    dialog = HotkeyDialog(HotkeySettings())

    assert set(dialog._global_edits) == {
        "normal_capture",
        "long_capture",
        "presentation_mode",
        "reminder",
        "calculator",
        "sleep",
    }
    dialog.deleteLater()


def test_main_window_has_no_horizontal_or_recording_actions() -> None:
    _app = QApplication.instance() or QApplication([])

    class _Service(QObject):
        capture_failed = Signal(str)

        def start_capture(self):
            pass

        def start_long_capture(self):
            pass

        def toggle_presentation(self):
            pass

    window = MainWindow(_Service(), lambda _settings: True)
    labels = {button.text() for button in window.findChildren(QPushButton)}

    assert "普通截图" in labels
    assert "长截图" in labels
    assert "教鞭模式" in labels
    assert "桌面提醒" in labels
    assert "横向长截图" not in labels
    assert "录屏" not in labels
    assert "录屏设置" not in labels
    window.deleteLater()


def test_main_window_teacher_help_uses_configured_shortcut() -> None:
    _app = QApplication.instance() or QApplication([])

    class _Service(QObject):
        capture_failed = Signal(str)

        def start_capture(self):
            pass

        def start_long_capture(self):
            pass

        def toggle_presentation(self):
            pass

    window = MainWindow(_Service(), lambda _settings: True)
    settings = HotkeySettings(presentation_mode="F3")
    window.set_hotkey_status(
        settings,
        {"normal": True, "long": True, "presentation": True},
    )
    label_texts = {label.text() for label in window.findChildren(QLabel)}
    help_text = next(text for text in label_texts if text.startswith("教鞭说明："))

    assert "按 F3 进入" in help_text
    assert "再次按 F3" in help_text
    assert "F5" not in help_text
    window.deleteLater()


def test_hotkey_dialog_always_suspends_and_resumes_global_shortcuts(
    monkeypatch,
) -> None:
    _app = QApplication.instance() or QApplication([])

    class _Service(QObject):
        capture_failed = Signal(str)

        def start_capture(self):
            pass

        def start_long_capture(self):
            pass

        def toggle_presentation(self):
            pass

    calls: list[str] = []

    class _CancelledDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, settings, *_args, **_kwargs):
            self.settings = settings

        def exec(self):
            calls.append("dialog")
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(main_window_module, "HotkeyDialog", _CancelledDialog)
    window = MainWindow(
        _Service(),
        lambda _settings: True,
        hotkey_suspend_handler=lambda: calls.append("suspend"),
        hotkey_resume_handler=lambda: (
            calls.append("resume")
            or {"normal": True, "long": True, "presentation": True, "reminder": True}
        ),
    )

    window.open_hotkey_dialog()

    assert calls == ["suspend", "dialog", "resume"]
    window.deleteLater()
