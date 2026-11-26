"""Regression coverage for the F3 clock alarm list and scheduling."""

from array import array
from dataclasses import replace
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import wave

from PySide6.QtCore import QTime, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QDialog, QFrame, QLabel, QMenu, QMessageBox, QPushButton, QToolTip, QWidget

from app.clock_alarms import ClockAlarm, clock_alarm_sound, load_clock_alarms, new_clock_alarm, save_clock_alarms
from app.reminder_preferences import (
    ensure_default_alarm_sound,
    new_reminder,
    save_reminders,
    settings_directory,
)
from ui.clock_alarm_manager import ClockAlarmManager
from ui.clock_alarm_window import AlarmPlayback, ClockAlarmEditor, ClockAlarmWindow
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
        editor._duration.setCurrentText("30m")
        editor._snooze.setCurrentText("1h")
        editor._delete_after.setChecked(True)
        editor._save()
        return editor.result()

    monkeypatch.setattr(ClockAlarmEditor, "exec", configure)
    window.findChild(QPushButton, "alarmAdd").click()
    alarm, = load_clock_alarms()
    assert (alarm.at, alarm.label, alarm.weekdays) == (time(6, 35), "晨练", (0, 2))
    assert (alarm.sound, alarm.ring_seconds, alarm.snooze_minutes) == ("gentle", 1800, 60)
    assert alarm.delete_after_ring
    assert alarm.next_at == datetime(2026, 11, 25, 6, 35)

    _app.processEvents()
    time_label = window.findChild(QLabel, "listTime")
    name_label = window.findChild(QLabel, "alarmName")
    repeat_label = window.findChild(QLabel, "repeatLabel")
    assert time_label.text() == "06:35"
    assert name_label.text() == "晨练"
    assert repeat_label.text() == "· 周一、周三"
    assert time_label.x() < name_label.x() < repeat_label.x()
    assert abs(time_label.geometry().center().y() - repeat_label.geometry().center().y()) <= 1
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


def test_duration_menus_offer_requested_values_and_keep_existing_custom_values() -> None:
    _app = QApplication.instance() or QApplication([])
    editor = ClockAlarmEditor(ClockAlarm("new", time(8)), False)
    assert [editor._duration.itemText(i) for i in range(editor._duration.count())] == [
        "30s", "1m", "2m", "3m", "5m", "10m", "15m", "30m",
    ]
    assert [editor._snooze.itemText(i) for i in range(editor._snooze.count())] == [
        "5m", "10m", "15m", "30m", "1h",
    ]
    assert (editor._duration.currentData(), editor._snooze.currentData()) == (30, 5)
    editor.deleteLater()

    previous = ClockAlarm("previous", time(9), ring_seconds=65, snooze_minutes=0)
    editor = ClockAlarmEditor(previous, True)
    editor._save()
    assert editor.result_alarm == previous
    editor.deleteLater()


def test_save_as_default_prefills_future_alarms_without_changing_the_current_alarm(tmp_path, monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    original = ClockAlarm("existing", time(8), label="原闹钟").set_enabled(True, MONDAY)
    save_clock_alarms([original])
    source = tmp_path / "铃声.wav"
    source.write_bytes(Path(ensure_default_alarm_sound("gentle")).read_bytes())
    monkeypatch.setattr("ui.clock_alarm_window.QFileDialog.getOpenFileName", lambda *_: (str(source), ""))
    monkeypatch.setattr(QToolTip, "showText", lambda *_: None)
    manager = ClockAlarmManager(now=lambda: MONDAY)
    manager.open_list()

    def save_defaults(editor):
        editor._at.setTime(QTime(22, 45))
        editor._label.setText("晨练")
        editor._repeat.setCurrentText("自选星期")
        editor._days[0].click()
        editor._days[2].click()
        editor._sound.setCurrentIndex(editor._sound.findData("custom"))
        editor._choose.click()
        editor._duration.setCurrentText("30m")
        editor._snooze.setCurrentText("1h")
        editor._delete_after.setChecked(True)
        editor.findChild(QPushButton, "saveAlarmDefault").click()
        assert editor.result_alarm == original
        editor.reject()
        return editor.result()

    monkeypatch.setattr(ClockAlarmEditor, "exec", save_defaults)
    manager._window.findChild(QPushButton, "editRow").click()
    assert load_clock_alarms() == [original]
    path = settings_directory() / "clock_alarm_defaults.json"
    values = json.loads(path.read_text(encoding="utf-8"))
    assert {"alarm_id", "at", "next_at", "snoozed_until"}.isdisjoint(values)
    manager.shutdown()
    source.unlink()

    reopened = ClockAlarmManager(now=lambda: MONDAY + timedelta(minutes=23))
    reopened.open_list()

    def use_defaults(editor):
        draft = editor.result_alarm
        assert draft.alarm_id != original.alarm_id
        assert draft.at == time(7, 24) and not draft.enabled
        assert editor._at.time() == QTime(7, 24)
        assert editor._label.text() == "晨练"
        assert editor._repeat.currentText() == "自选星期"
        assert [day for day, button in enumerate(editor._days) if button.isChecked()] == [0, 2]
        assert editor._sound.currentData() == "custom"
        assert editor._file_label.text() == "铃声.wav"
        assert Path(draft.sound_path).is_file()
        assert (editor._duration.currentData(), editor._snooze.currentData()) == (1800, 60)
        assert editor._delete_after.isChecked()
        editor._save()
        return editor.result()

    monkeypatch.setattr(ClockAlarmEditor, "exec", use_defaults)
    reopened._window.findChild(QPushButton, "alarmAdd").click()
    old, added = load_clock_alarms()
    assert old == original and added.label == "晨练"
    assert added.next_at == datetime(2026, 11, 23, 7, 24)
    reopened.shutdown()


def test_unreadable_default_options_leave_new_alarm_available() -> None:
    path = settings_directory() / "clock_alarm_defaults.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"ring_seconds": []}', encoding="utf-8")

    draft = new_clock_alarm(MONDAY)
    assert draft.at == time(7, 1)
    assert (draft.label, draft.weekdays, draft.ring_seconds, draft.snooze_minutes) == ("", (), 30, 5)


def test_list_rows_stay_fixed_at_different_sizes_and_header_buttons_match() -> None:
    app = QApplication.instance() or QApplication([])
    window = ClockAlarmWindow(now=lambda: MONDAY)
    one = ClockAlarm("one", time(8))
    two = ClockAlarm("two", time(9))
    window.set_alarms([one])
    window.open_list()
    for width, height in ((410, 342), (520, 600), (365, 230)):
        window.resize(width, height)
        app.processEvents()
        row = window.findChild(QFrame, "alarmRow")
        assert row.height() == row.minimumHeight() == row.maximumHeight() == 40
    add = window.findChild(QPushButton, "alarmAdd")
    help_button = window.findChild(QPushButton, "alarmHelp")
    assert add.size() == help_button.size()
    assert add.y() == help_button.y()

    window.set_alarms([one, two])
    app.processEvents()
    rows = [row for row in window.findChildren(QFrame, "alarmRow") if row.isVisible()]
    assert [row.height() for row in rows] == [40, 40]
    assert rows[1].y() - rows[0].y() == 45
    window.close()
    window.deleteLater()


def test_countdown_updates_only_for_enabled_single_alarms() -> None:
    app = QApplication.instance() or QApplication([])
    now = MONDAY
    window = ClockAlarmWindow(now=lambda: now)
    enabled = ClockAlarm("enabled", time(9, 35)).set_enabled(True, now)
    disabled = ClockAlarm("disabled", time(10))
    repeating = ClockAlarm("repeating", time(11), weekdays=(0, 2)).set_enabled(True, now)
    window.set_alarms([enabled, disabled, repeating])
    window.open_list()
    app.processEvents()
    rows = window.findChildren(QFrame, "alarmRow")
    labels = [row.findChild(QLabel, "repeatLabel") for row in rows]
    assert [label.text() for label in labels] == [
        "· 仅一次 · 2小时35分后响铃", "· 仅一次", "· 周一、周三",
    ]
    now += timedelta(hours=1, minutes=25)
    window._countdown_timer.timeout.emit()
    app.processEvents()
    assert labels[0].text() == "· 仅一次 · 1小时10分后响铃"
    window.close()
    assert not window._countdown_timer.isActive()
    window.deleteLater()


def test_list_context_menu_deletes_only_its_row_and_help_opens(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    first = ClockAlarm("first", time(8), label="很长的测试名称" * 7, weekdays=(0, 1, 2, 4, 5, 6))
    second = ClockAlarm("second", time(9))
    save_clock_alarms([first, second])
    manager = ClockAlarmManager(now=lambda: MONDAY)
    manager.open_list()
    window = manager._window
    window.resize(window.minimumWidth(), window.height())
    app.processEvents()
    first_row, _ = window.findChildren(QFrame, "alarmRow")
    assert first_row.findChild(QLabel, "alarmName").text().startswith("很长")
    assert first_row.findChild(QLabel, "repeatLabel").text().startswith("· 周一")

    second_row_button = next(
        button for button in window.findChildren(QPushButton, "editRow")
        if button.property("alarmId") == second.alarm_id
    )
    point = second_row_button.rect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, second_row_button.mapToGlobal(point)
    )
    app.sendEvent(second_row_button, event)
    app.processEvents()
    menu = window.findChild(QMenu)
    assert menu.isVisible()
    action, = menu.actions()
    assert action.text() == "删除闹钟"
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    assert load_clock_alarms() == [first]

    help_text = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: help_text.append(text))
    window.findChild(QPushButton, "alarmHelp").click()
    assert "右键菜单可删除" in help_text[0]
    assert "Windows 当前的声音输出和音量" in help_text[0]
    manager.shutdown()


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


def test_all_four_embedded_songs_are_selectable_and_resolve_to_local_files() -> None:
    _app = QApplication.instance() or QApplication([])
    editor = ClockAlarmEditor(ClockAlarm("songs", time(7)), False)
    assert editor._sound.currentData() == "default"
    for key, title, filename in (
        ("default", "默认 · 我听人说思念像风一样", "missing_like_wind.mp3"),
        ("road_answer", "答案在路上", "road_answer.mp3"),
        ("cello_volcano", "岩滩火山（大提琴纯音乐）", "cello_volcano.mp3"),
        ("your_answer", "你的答案", "your_answer.mp3"),
    ):
        index = editor._sound.findData(key)
        assert index >= 0
        assert editor._sound.itemText(index) == title
        path = Path(clock_alarm_sound(key))
        assert path.name == filename
        assert path.stat().st_size > 1000
    editor._sound.setCurrentIndex(editor._sound.findData("your_answer"))
    editor._save()
    save_clock_alarms([editor.result_alarm])
    assert load_clock_alarms()[0].sound == "your_answer"
    editor.deleteLater()


def test_alarm_playback_follows_the_current_windows_output(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    parent = QWidget()
    playback = AlarmPlayback(parent)
    first_output = object()
    headset = object()
    current_output = first_output
    routed = []
    monkeypatch.setattr(playback._devices, "defaultAudioOutput", lambda: current_output)
    monkeypatch.setattr(playback._output, "setDevice", routed.append)
    monkeypatch.setattr(playback._player, "setSource", lambda _source: None)
    monkeypatch.setattr(playback._player, "play", lambda: None)

    playback.play("default", "")
    assert playback._output.volume() == 1.0
    assert routed == [first_output]
    current_output = headset
    playback._devices.audioOutputsChanged.emit()
    assert routed == [first_output, headset]
    playback.stop()

    current_output = first_output
    playback._devices.audioOutputsChanged.emit()
    assert routed == [first_output, headset]
    playback.play("default", "")
    assert routed == [first_output, headset, first_output]
    playback.stop()
    parent.deleteLater()


def test_generated_clock_tone_is_stronger_than_the_reminder_tone() -> None:
    def peak(path: str) -> int:
        samples = array("h")
        with wave.open(path, "rb") as sound:
            samples.frombytes(sound.readframes(sound.getnframes()))
        return max(abs(sample) for sample in samples)

    reminder = ensure_default_alarm_sound("gentle")
    clock = ensure_default_alarm_sound("gentle", loud=True)
    assert 1.8 * peak(reminder) < peak(clock) < 32767


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
