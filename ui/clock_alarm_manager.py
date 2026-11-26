"""Keep clock alarms running while the list window is closed."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from app.branding import APP_DISPLAY_NAME
from app.clock_alarms import (
    MISSED_ALARM_GRACE_SECONDS,
    ClockAlarm,
    load_clock_alarms,
    new_clock_alarm,
    save_clock_alarms,
)
from ui.clock_alarm_window import ALARM_FADE_IN_MS, AlarmPlayback, ClockAlarmAlert, ClockAlarmEditor, ClockAlarmWindow


_logger = logging.getLogger(__name__)


class ClockAlarmManager(QObject):
    def __init__(self, parent=None, now: Callable[[], datetime] = datetime.now) -> None:
        super().__init__()
        self._parent = parent
        self._now = now
        self._alarms = {alarm.alarm_id: alarm for alarm in load_clock_alarms()}
        self._pending: dict[str, float] = {}
        self._ringing: ClockAlarm | None = None
        self._window: ClockAlarmWindow | None = None
        self._alert: ClockAlarmAlert | None = None
        self._audio: AlarmPlayback | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._check_due)
        self._ring_timeout = QTimer(self)
        self._ring_timeout.setSingleShot(True)
        self._ring_timeout.setTimerType(Qt.TimerType.PreciseTimer)
        self._ring_timeout.timeout.connect(self._finish_ring)

    def start(self) -> None:
        self._timer.start()
        self._check_due()

    def open_list(self) -> None:
        if self._window is None:
            self._window = ClockAlarmWindow(self._parent, now=self._now)
            self._window.add_requested.connect(self._edit)
            self._window.edit_requested.connect(self._edit)
            self._window.delete_requested.connect(self._delete)
            self._window.enabled_changed.connect(self._set_enabled)
        self._refresh_list()
        self._window.open_list()

    def _edit(self, alarm_id: str = "") -> None:
        original = self._alarms.get(alarm_id) if alarm_id else new_clock_alarm(self._now())
        if original is None:
            return
        editor = ClockAlarmEditor(original, bool(alarm_id), self._window)
        accepted = editor.exec() == QDialog.DialogCode.Accepted
        alarm = editor.result_alarm
        delete = editor.delete_requested
        editor.deleteLater()
        if not accepted:
            return
        if not alarm_id:
            self._save_user_change(alarm.alarm_id, alarm.set_enabled(True, self._now()))
            return
        current = self._alarms.get(alarm_id)
        if current is None:
            return
        if delete:
            self._delete(alarm_id)
            return
        if (alarm.at, alarm.weekdays) != (current.at, current.weekdays):
            alarm = alarm.set_enabled(current.enabled, self._now())
        else:
            alarm = replace(alarm, next_at=current.next_at, snoozed_until=current.snoozed_until)
        self._save_user_change(alarm_id, alarm)

    def _delete(self, alarm_id: str) -> None:
        if alarm_id in self._alarms:
            self._save_user_change(alarm_id, None)

    def _set_enabled(self, alarm_id: str, enabled: bool) -> None:
        alarm = self._alarms.get(alarm_id)
        if alarm is not None and alarm.enabled != enabled:
            self._save_user_change(alarm_id, alarm.set_enabled(enabled, self._now()))

    def _save_user_change(self, alarm_id: str, alarm: ClockAlarm | None) -> None:
        updated = self._alarms.copy()
        if alarm is None:
            updated.pop(alarm_id, None)
        else:
            updated[alarm_id] = alarm
        try:
            save_clock_alarms(list(updated.values()))
        except OSError:
            self._refresh_list()
            QMessageBox.warning(self._window, APP_DISPLAY_NAME, "无法保存闹钟，请检查设置文件夹。")
            return
        self._alarms = updated
        if alarm is None or alarm.due_timestamp != self._pending.get(alarm_id):
            self._pending.pop(alarm_id, None)
        if self._ringing is not None and self._ringing.alarm_id == alarm_id:
            if (
                alarm is None
                or (alarm.at, alarm.weekdays, alarm.due_timestamp)
                != (self._ringing.at, self._ringing.weekdays, self._ringing.due_timestamp)
            ):
                self._clear_ring()
        self._refresh_list()

    def _refresh_list(self) -> None:
        if self._window is not None:
            ringing_id = self._ringing.alarm_id if self._ringing else ""
            self._window.set_alarms(list(self._alarms.values()), ringing_id)

    def _check_due(self) -> None:
        now = self._now()
        timestamp = now.timestamp()
        cutoff = timestamp - MISSED_ALARM_GRACE_SECONDS
        changed = False
        ringing_id = self._ringing.alarm_id if self._ringing else ""
        for alarm_id, alarm in self._alarms.items():
            if alarm_id == ringing_id:
                continue
            due = alarm.due_timestamp
            if due is not None and due < cutoff and self._pending.get(alarm_id) != due:
                # Look for a more recent repeat when the app was closed for several days.
                start = datetime.fromtimestamp(cutoff) if alarm.next_at is not None else now
                alarm = alarm.advance(start)
                self._alarms[alarm_id] = alarm
                due = alarm.due_timestamp
                changed = True
            if due is not None and due <= timestamp:
                self._pending[alarm_id] = due
            else:
                self._pending.pop(alarm_id, None)
        if changed:
            self._save_runtime_state()
            self._refresh_list()
        if self._ringing is not None or not self._pending:
            return
        alarm_id = min(self._pending, key=self._pending.__getitem__)
        self._pending.pop(alarm_id)
        self._start_ring(self._alarms[alarm_id], now)

    def _start_ring(self, alarm: ClockAlarm, now: datetime) -> None:
        if self._alert is None:
            self._alert = ClockAlarmAlert(self._parent)
            self._alert.stop_requested.connect(self._finish_ring)
            self._alert.snooze_requested.connect(self._snooze)
            self._audio = AlarmPlayback(self._alert)
        self._ringing = alarm
        self._alert.ring(alarm, now)
        ring_ms = alarm.ring_seconds * 1000
        fade_ms = min(ALARM_FADE_IN_MS, ring_ms // 2) if alarm.fade_in else 0
        self._audio.play(alarm.sound, alarm.sound_path, fade_ms)
        self._ring_timeout.start(ring_ms)
        self._refresh_list()

    def _finish_ring(self) -> None:
        if self._ringing is None:
            return
        alarm = self._alarms[self._ringing.alarm_id]
        if alarm.delete_after_ring:
            del self._alarms[alarm.alarm_id]
        else:
            now = self._now()
            due = alarm.due_timestamp
            if due is not None and due > now.timestamp():
                now = datetime.fromtimestamp(due)
            self._alarms[alarm.alarm_id] = alarm.advance(now)
        self._clear_ring()
        self._save_runtime_state()
        self._refresh_list()

    def _snooze(self) -> None:
        if self._ringing is None or self._ringing.snooze_minutes == 0:
            return
        current = self._alarms[self._ringing.alarm_id]
        snoozed = self._ringing.snooze(self._now())
        self._alarms[current.alarm_id] = replace(
            current, next_at=None, snoozed_until=snoozed.snoozed_until
        )
        self._clear_ring()
        self._save_runtime_state()
        self._refresh_list()

    def _clear_ring(self) -> None:
        self._ringing = None
        self._ring_timeout.stop()
        if self._audio is not None:
            self._audio.stop()
        if self._alert is not None:
            self._alert.hide()

    def _save_runtime_state(self) -> None:
        try:
            save_clock_alarms(list(self._alarms.values()))
        except OSError:
            _logger.exception("无法保存闹钟的响铃状态")

    def shutdown(self) -> None:
        self._timer.stop()
        self._clear_ring()
        if self._window is not None:
            self._window.close()
            self._window.deleteLater()
            self._window = None
        if self._alert is not None:
            self._alert.deleteLater()
            self._alert = None
            self._audio = None
