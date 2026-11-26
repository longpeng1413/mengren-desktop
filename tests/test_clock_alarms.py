"""Regression coverage for the F3 clock alarm list and scheduling."""

from dataclasses import replace
from datetime import datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QLabel, QPushButton

from app.clock_alarms import ClockAlarm, load_clock_alarms, save_clock_alarms
from app.reminder_preferences import (
    ensure_default_alarm_sound,
    new_reminder,
    save_reminders,
    settings_directory,
)
from ui.clock_alarm_manager import ClockAlarmManager
from ui.clock_alarm_window import AlarmPlayback, ClockAlarmEditor
from ui.reminder_widget import DesktopReminderManager


MONDAY = datetime(2026, 11, 23, 7)


def test_next_occurrence_respects_repeat_days_and_rearming() -> None:
    monday = ClockAlarm("monday", time(7), weekdays=(0,))
    weekend = ClockAlarm("weekend", time(7), weekdays=(5, 6))
    once = ClockAlarm("once", time(6))

    assert monday.set_enabled(True, MONDAY).next_at == MONDAY + timedelta(days=7)
    assert weekend.set_enabled(True, MONDAY).next_at == MONDAY + timedelta(days=5)
    assert once.set_enabled(True, MONDAY).next_at == MONDAY + timedelta(days=1, hours=-1)
    assert not once.advance(MONDAY).enabled


def test_persistence_keeps_disabled_and_snoozed_alarms_and_skips_bad_rows() -> None:
    once = ClockAlarm("once", time(8), label="晨练")
    repeating = ClockAlarm(
        "repeat", time(7), weekdays=(0, 2), ring_seconds=45,
        delete_after_ring=True, snooze_minutes=12, sound="gentle",
    ).snooze(MONDAY)
    save_clock_alarms([once, repeating])
    path = settings_directory() / "clock_alarms.json"
    original = path.read_text(encoding="utf-8")
    path.write_text('[{"alarm_id":"bad","at":"27:00"},null,' + original[1:], encoding="utf-8")

    assert load_clock_alarms() == [once, repeating]
    assert repeating.due_timestamp == (MONDAY + timedelta(minutes=12)).timestamp()


def test_list_add_edit_toggle_and_delete_save_across_restart(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    manager = ClockAlarmManager(now=lambda: MONDAY)
    manager.open_list()
    window = manager._window

    def configure(editor):
        editor._at.setTime(QTime(6, 35))
        editor._label.setText("晨练")
        editor._repeat.setCurrentText("自选星期")
        editor._days[0].click()
        editor._days[2].click()
        editor._sound.setCurrentIndex(editor._sound.findData("gentle"))
        editor._duration.setValue(65)
        editor._snooze.setValue(8)
        editor._delete_after.setChecked(True)
        editor._save()
        return editor.result()

    monkeypatch.setattr(ClockAlarmEditor, "exec", configure)
    window.findChild(QPushButton, "alarmAdd").click()
    alarm, = load_clock_alarms()
    assert (alarm.at, alarm.label, alarm.weekdays) == (time(6, 35), "晨练", (0, 2))
    assert (alarm.sound, alarm.ring_seconds, alarm.snooze_minutes) == ("gentle", 65, 8)
    assert alarm.delete_after_ring
    assert alarm.next_at == datetime(2026, 11, 25, 6, 35)

    _app.processEvents()
    time_label = window.findChild(QLabel, "alarmTime")
    assert time_label.height() >= time_label.fontMetrics().height()
    switch = next(button for button in window.findChildren(QAbstractButton, "alarmSwitch") if button.isVisible())
    switch.click()
    assert not load_clock_alarms()[0].enabled
    manager.shutdown()

    reopened = ClockAlarmManager(now=lambda: MONDAY)
    reopened.open_list()

    def remove(editor):
        assert editor.result_alarm.alarm_id == alarm.alarm_id
        editor.findChild(QPushButton, "dangerButton").click()
        return editor.result()

    monkeypatch.setattr(ClockAlarmEditor, "exec", remove)
    reopened._window.findChild(QPushButton, "editRow").click()
    assert not load_clock_alarms()
    reopened.shutdown()


def test_editor_imports_audio_and_provides_distinct_builtin_tones(tmp_path, monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    paths = [ensure_default_alarm_sound(tone) for tone in ("gentle", "bright")]
    assert Path(paths[0]).read_bytes() != Path(paths[1]).read_bytes()
    original = tmp_path / "晨间铃声.wav"
    original.write_bytes(Path(paths[0]).read_bytes())
    editor = ClockAlarmEditor(ClockAlarm("file", time(7)), False)
    editor._sound.setCurrentIndex(editor._sound.findData("custom"))
    monkeypatch.setattr(
        "ui.clock_alarm_window.QFileDialog.getOpenFileName", lambda *_: (str(original), "")
    )
    editor._choose.click()
    editor._save()

    assert editor.result() == QDialog.DialogCode.Accepted
    assert editor.result_alarm.sound_name == original.name
    original.unlink()
    assert Path(editor.result_alarm.sound_path).is_file()


def test_snooze_survives_restart_then_stops_and_deletes(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    current = MONDAY
    alarm = ClockAlarm(
        "test", time(7), delete_after_ring=True, ring_seconds=10, snooze_minutes=2,
    ).set_enabled(True, current - timedelta(minutes=1))
    save_clock_alarms([alarm])
    playback = []
    monkeypatch.setattr(AlarmPlayback, "play", lambda _self, sound, _path: playback.append(sound))
    manager = ClockAlarmManager(now=lambda: current)
    manager.start()

    assert manager._alert.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert manager._ring_timeout.interval() == 10000
    assert playback == ["default"]
    manager._alert.snooze_button.click()
    assert not manager._alert.isVisible()
    assert load_clock_alarms() == [alarm.snooze(current)]
    manager.shutdown()

    manager = ClockAlarmManager(now=lambda: current)
    current += timedelta(minutes=1)
    manager.start()
    assert manager._ringing is None
    current += timedelta(minutes=1)
    manager._check_due()
    assert manager._ringing is not None
    manager._ring_timeout.timeout.emit()
    assert not load_clock_alarms()
    assert not manager._alert.isVisible()
    assert playback == ["default", "default"]
    manager.shutdown()


def test_simultaneous_alarms_queue_and_can_be_removed_while_waiting(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    armed = ClockAlarm("first", time(7), snooze_minutes=0).set_enabled(
        True, MONDAY - timedelta(minutes=1)
    )
    save_clock_alarms([armed, replace(armed, alarm_id="remove"), replace(armed, alarm_id="third")])
    monkeypatch.setattr(AlarmPlayback, "play", lambda *_: None)
    manager = ClockAlarmManager(now=lambda: MONDAY)
    manager.start()

    assert manager._ringing.alarm_id == "first"
    assert manager._alert.snooze_button.isHidden()
    manager._save_user_change("remove", None)
    manager._alert.close()
    assert manager._ringing is None
    manager._check_due()
    assert manager._ringing.alarm_id == "third"
    manager._finish_ring()
    manager._check_due()
    assert manager._ringing is None
    assert [alarm.alarm_id for alarm in load_clock_alarms()] == ["first", "third"]
    assert not any(alarm.enabled for alarm in load_clock_alarms())
    manager.shutdown()


def test_missed_one_shot_is_disabled_and_recent_repeat_is_recovered(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    original = MONDAY - timedelta(days=3)
    once = ClockAlarm("missed", time(7), delete_after_ring=True)
    repeat = ClockAlarm("daily", time(7), weekdays=tuple(range(7)))
    save_clock_alarms([a.set_enabled(True, original) for a in (once, repeat)])
    monkeypatch.setattr(AlarmPlayback, "play", lambda *_: None)
    manager = ClockAlarmManager(now=lambda: MONDAY + timedelta(minutes=1))
    manager.start()

    assert manager._ringing.alarm_id == "daily"
    assert not manager._alarms["missed"].enabled
    manager._finish_ring()
    assert manager._alarms["daily"].next_at == MONDAY + timedelta(days=1)
    manager.shutdown()


def test_f3_separates_existing_dated_reminders_from_clock_alarms(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    existing = replace(
        new_reminder("alarm"), text="牙医",
        target_at=(datetime.now() + timedelta(days=2)).isoformat(),
    )
    save_reminders([existing])
    manager = DesktopReminderManager(bottom_window_handler=lambda _: True)
    manager.restore()
    assert manager._widgets[existing.reminder_id]._title_label.text() == "牙医"
    manager.launcher.buttons["alarm"].click()
    assert manager._clock_alarms._window.isVisible()
    assert not load_clock_alarms()
    edited = []

    def record_editor(dialog):
        edited.append((dialog.windowTitle(), dialog.result_settings.kind))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr("ui.reminder_widget.ReminderEditorDialog.exec", record_editor)
    manager.launcher.buttons["schedule"].click()
    assert edited == [("日程提醒", "alarm")]
    manager.shutdown()
