"""Tests for restoring all shortcut defaults from the settings dialog."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app.preferences import HotkeySettings, PresentationShortcutSettings
from ui.hotkey_dialog import HotkeyDialog


def test_restore_defaults_applies_and_accepts_dialog() -> None:
    _application = QApplication.instance() or QApplication([])
    customized = HotkeySettings(
        normal_capture="Ctrl+F1",
        presentation_tools=PresentationShortcutSettings(
            pointer_brush_toggle="F6",
            clear="F7",
        ),
    )
    dialog = HotkeyDialog(customized)

    dialog._restore_defaults()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.settings == HotkeySettings()


def test_bare_escape_closes_dialog_without_recording_escape() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = HotkeyDialog(HotkeySettings())
    edit = dialog._global_edits["normal_capture"]
    dialog.show()
    edit.setFocus()

    QTest.keyClick(edit, Qt.Key.Key_Escape)
    application.processEvents()

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert edit.keySequence().toString() == "F1"


def test_system_action_shortcuts_can_be_changed_or_cleared() -> None:
    _application = QApplication.instance() or QApplication([])
    dialog = HotkeyDialog(HotkeySettings())
    dialog._global_edits["calculator"].setKeySequence("Ctrl+Alt+C")
    dialog._global_edits["sleep"].clear()

    dialog._save()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.settings.calculator == "Ctrl+Alt+C"
    assert dialog.settings.sleep == ""
