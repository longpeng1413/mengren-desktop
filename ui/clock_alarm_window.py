"""Phone-style alarm list, editor, and ringing prompt."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, QTime, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedLayout,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DISPLAY_NAME
from app.clock_alarms import (
    BUILTIN_SOUNDS,
    DEFAULT_RINGTONE_TITLE,
    REPEAT_PRESETS,
    WEEKDAY_NAMES,
    ClockAlarm,
    clock_alarm_sound,
)
from app.reminder_preferences import (
    AUDIO_EXTENSIONS,
    import_reminder_asset,
)
from ui import theme


_STYLE = f"""
QDialog, QScrollArea, QWidget#alarmRows {{ background: {theme.BACKGROUND}; }}
QDialog {{
    color: {theme.TEXT}; font-family: {theme.FONT}; font-size: 14px;
}}
QLabel, QCheckBox {{ color: {theme.TEXT}; }}
QLabel#heading {{ font-size: 27px; font-weight: 700; }}
QLabel#muted {{ color: {theme.MUTED}; }}
QFrame#alarmRow {{ background: {theme.PANEL}; border-radius: 8px; }}
QLabel#listTime {{ font-size: 19px; font-weight: 700; }}
QLabel#alarmName, QLabel#repeatLabel {{ font-size: 14px; }}
QLabel#repeatLabel {{ color: {theme.MUTED}; }}
QLabel#alarmTime, QTimeEdit#alarmTime {{ font-size: 42px; }}
QLabel:disabled {{ color: {theme.MUTED}; }}
QPushButton, QLineEdit, QTimeEdit, QComboBox, QSpinBox {{
    color: {theme.TEXT}; background: {theme.RAISED}; border: 1px solid {theme.LINE};
    border-radius: 8px; padding: 5px 10px; min-height: 26px;
}}
QComboBox QAbstractItemView {{
    background: {theme.RAISED}; color: {theme.TEXT};
    selection-background-color: {theme.ACCENT}; selection-color: {theme.ACCENT_INK};
}}
QPushButton:hover {{ background: {theme.HOVER}; }}
QPushButton:focus, QLineEdit:focus, QTimeEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {theme.ACCENT};
}}
QPushButton:checked, QPushButton#primaryButton {{
    color: {theme.ACCENT_INK}; background: {theme.ACCENT}; font-weight: 600;
}}
QPushButton#dangerButton {{ color: {theme.DANGER}; }}
QPushButton:disabled, QSpinBox:disabled {{ color: {theme.DISABLED}; }}
QPushButton#alarmAdd {{ font-size: 24px; padding: 0; }}
QPushButton#alarmHelp {{ font-size: 15px; padding: 0; }}
QPushButton#editRow {{ background: transparent; border: 1px solid transparent; padding: 0; }}
QPushButton#editRow:hover {{ border-color: {theme.LINE}; }}
QPushButton#editRow:focus {{ border-color: {theme.ACCENT}; }}
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 28px; }}
QTimeEdit::up-arrow, QTimeEdit::down-arrow {{ width: 14px; height: 9px; }}
""" + theme.MENU_STYLE


def _button(text: str, role: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(role)
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _place_window(widget: QWidget, screen) -> None:
    if screen is not None:
        widget.move(screen.availableGeometry().center() - widget.rect().center())
    theme.dark_title_bar(widget)


class _AlarmSwitch(QAbstractButton):
    def __init__(self, alarm: ClockAlarm) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setChecked(alarm.enabled)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{alarm.at:%H:%M} {alarm.label or '闹钟'}开关")
        self.setToolTip("已开启，点击关闭" if alarm.enabled else "已关闭，点击开启")
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(44, 28)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.ACCENT if on else theme.PRESSED))
        painter.drawRoundedRect(QRectF(2, 3, 40, 22), 11, 11)
        painter.setBrush(QColor(theme.ACCENT_INK if on else theme.TEXT))
        painter.drawEllipse(QPointF(31 if on else 13, 14), 8, 8)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.ACCENT)))
            painter.drawRoundedRect(QRectF(0.5, 1.5, 43, 25), 12, 12)
        painter.end()


class _AlarmText(QLabel):
    """Keep room for both fields when an alarm has a long name or repeat summary."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(name)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._name), metrics.height())

    def minimumSizeHint(self) -> QSize:
        hint = self.sizeHint()
        return QSize(min(60, hint.width()), hint.height())

    def resizeEvent(self, event) -> None:
        self.setText(self.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideRight, self.width()))
        super().resizeEvent(event)


class ClockAlarmWindow(QDialog):
    add_requested = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    enabled_changed = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("闹钟")
        self.setMinimumSize(390, 365)
        self.resize(458, 432)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(16)

        header = QHBoxLayout()
        heading = QLabel("闹钟")
        heading.setObjectName("heading")
        header.addWidget(heading)
        header.addStretch()
        help_button = _button("?", "alarmHelp")
        help_button.setFixedSize(28, 28)
        help_button.setAccessibleName("闹钟使用说明")
        help_button.setToolTip("闹钟使用说明")
        help_button.clicked.connect(self._show_help)
        header.addWidget(help_button)
        add = _button("+", "alarmAdd")
        add.setFixedSize(42, 42)
        add.setAccessibleName("添加闹钟")
        add.setToolTip("添加闹钟")
        add.clicked.connect(self.add_requested.emit)
        header.addWidget(add)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows = QWidget()
        self._rows.setObjectName("alarmRows")
        self._row_layout = QVBoxLayout(self._rows)
        self._row_layout.setContentsMargins(0, 0, 4, 0)
        self._row_layout.setSpacing(5)
        scroll.setWidget(self._rows)
        layout.addWidget(scroll, 1)

    def open_list(self) -> None:
        if not self.isVisible():
            _place_window(self, QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen())
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def set_alarms(self, alarms: list[ClockAlarm], ringing_id: str = "") -> None:
        focused = QApplication.focusWidget()
        had_focus = focused is not None and self._rows.isAncestorOf(focused)
        focus_name = focused.objectName() if had_focus else ""
        focus_alarm = focused.property("alarmId") if had_focus else None
        while self._row_layout.count():
            item = self._row_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for alarm in sorted(alarms, key=lambda item: (item.at, item.label)):
            row = self._make_row(alarm, alarm.alarm_id == ringing_id)
            self._row_layout.addWidget(row)
            row.show()
            for button in row.findChildren(QAbstractButton):
                if focus_alarm == alarm.alarm_id and button.objectName() == focus_name:
                    button.setFocus(Qt.FocusReason.OtherFocusReason)
        if not alarms:
            empty = QLabel("还没有闹钟\n点击右上角的 ＋ 添加")
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._row_layout.addWidget(empty, 1)
        else:
            self._row_layout.addStretch()

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "闹钟使用说明",
            "点「＋」添加闹钟，点击时间或名称进行编辑。右侧开关可以启停，右键菜单可删除该条闹钟。\n\n"
            "编辑时可设置重复、响铃时长和稍后提醒，也可选择和试听铃声。"
            f"默认铃声为《{DEFAULT_RINGTONE_TITLE}》。"
            "试听和响铃都使用 Windows 当前的声音输出和音量。\n\n"
            "到点后可停止或稍后提醒。关闭闹钟列表后，只要桌面助手仍在托盘运行，闹钟就会继续提醒。",
        )

    def _show_row_menu(self, position: QPoint, alarm_id: str) -> None:
        menu = QMenu(self)
        delete = menu.addAction("删除闹钟")
        delete.triggered.connect(lambda: self.delete_requested.emit(alarm_id))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(position)

    def _make_row(self, alarm: ClockAlarm, ringing: bool) -> QFrame:
        row = QFrame()
        row.setObjectName("alarmRow")
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda point: self._show_row_menu(row.mapToGlobal(point), alarm.alarm_id)
        )
        line = QHBoxLayout(row)
        line.setContentsMargins(8, 4, 10, 4)
        line.setSpacing(8)

        title = alarm.label or "闹钟"
        edit = _button("", "editRow")
        edit.setProperty("alarmId", alarm.alarm_id)
        edit.setAccessibleName(f"编辑 {alarm.at:%H:%M} {title}")
        edit.clicked.connect(lambda: self.edit_requested.emit(alarm.alarm_id))
        card = QWidget()
        stack = QStackedLayout(card)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        display = QWidget()
        content = QHBoxLayout(display)
        content.setContentsMargins(7, 0, 5, 0)
        content.setSpacing(8)
        time_label = QLabel(f"{alarm.at:%H:%M}")
        time_label.setObjectName("listTime")
        time_label.setMinimumWidth(58)
        time_label.setEnabled(alarm.enabled)
        details = f"· {alarm.repeat_label}"
        if ringing:
            details += " · 正在响铃"
        elif alarm.snoozed_until is not None:
            next_time = datetime.fromtimestamp(alarm.snoozed_until)
            details += f" · {next_time:%H:%M} 再提醒"
        tooltip = f"{title} {details}"
        if alarm.next_at is not None and not ringing:
            tooltip += f"\n下次响铃 {alarm.next_at:%m-%d %H:%M}"
        edit.setToolTip(tooltip)
        name = _AlarmText(title)
        name.setObjectName("alarmName")
        subtitle = _AlarmText(details)
        subtitle.setObjectName("repeatLabel")
        content.addWidget(time_label)
        content.addWidget(name)
        content.addWidget(subtitle)
        content.addStretch()
        stack.addWidget(display)
        stack.addWidget(edit)
        stack.setCurrentWidget(edit)
        line.addWidget(card, 1)
        switch = _AlarmSwitch(alarm)
        switch.setObjectName("alarmSwitch")
        switch.setProperty("alarmId", alarm.alarm_id)
        switch.toggled.connect(lambda enabled: self.enabled_changed.emit(alarm.alarm_id, enabled))
        line.addWidget(switch)
        return row


class AlarmPlayback:
    """Loop an alarm and use the system beep when audio playback fails."""

    def __init__(self, parent: QWidget) -> None:
        self._player = QMediaPlayer(parent)
        self._output = QAudioOutput(parent)
        # Leave attenuation to the Windows endpoint and volume mixer.
        self._output.setVolume(1.0)
        self._devices = QMediaDevices(parent)
        self._devices.audioOutputsChanged.connect(self._sync_default_output)
        self._player.setAudioOutput(self._output)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.errorOccurred.connect(self._fallback)
        self._beep_timer = QTimer(parent)
        self._beep_timer.setInterval(1200)
        self._beep_timer.timeout.connect(QApplication.beep)
        self._active = False

    def play(self, sound: str, path: str) -> None:
        self.stop()
        self._active = True
        self._sync_default_output()
        try:
            if sound != "custom" or not path or not Path(path).is_file():
                path = clock_alarm_sound(sound)
        except OSError:
            self._fallback()
            return
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def stop(self) -> None:
        self._active = False
        self._player.stop()
        self._beep_timer.stop()

    def _sync_default_output(self) -> None:
        if self._active:
            self._output.setDevice(self._devices.defaultAudioOutput())

    def _fallback(self, *_error) -> None:
        if self._active and not self._beep_timer.isActive():
            QApplication.beep()
            self._beep_timer.start()


class ClockAlarmEditor(QDialog):
    def __init__(self, alarm: ClockAlarm, existing: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑闹钟" if existing else "添加闹钟")
        self.setMinimumWidth(410)
        self.setStyleSheet(_STYLE)
        self.result_alarm = alarm
        self.delete_requested = False
        self._sound_path = alarm.sound_path
        self._sound_name = alarm.sound_name
        self._preview = AlarmPlayback(self)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._stop_preview)
        self.finished.connect(self._stop_preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)
        self._at = QTimeEdit(QTime(alarm.at.hour, alarm.at.minute))
        self._at.setObjectName("alarmTime")
        self._at.setAccessibleName("闹钟时间")
        self._at.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._at.setDisplayFormat("HH:mm")
        layout.addWidget(self._at)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self._label = QLineEdit(alarm.label)
        self._label.setMaxLength(60)
        self._label.setPlaceholderText("闹钟")
        form.addRow("名称", self._label)

        self._repeat = QComboBox()
        for label, days in REPEAT_PRESETS:
            self._repeat.addItem(label, days)
        self._repeat.addItem("自选星期", None)
        preset = next((i for i, (_, days) in enumerate(REPEAT_PRESETS) if days == alarm.weekdays), -1)
        self._repeat.setCurrentIndex(preset if preset >= 0 else len(REPEAT_PRESETS))
        form.addRow("重复", self._repeat)
        weekdays = QWidget()
        weekday_row = QHBoxLayout(weekdays)
        weekday_row.setContentsMargins(0, 0, 0, 0)
        weekday_row.setSpacing(4)
        self._days = []
        for day, label in enumerate(WEEKDAY_NAMES):
            button = _button(label[-1])
            button.setAccessibleName(label)
            button.setToolTip(label)
            button.setCheckable(True)
            button.setChecked(day in alarm.weekdays)
            button.setFixedWidth(36)
            weekday_row.addWidget(button)
            self._days.append(button)
        weekday_row.addStretch()
        form.addRow("", weekdays)
        self._repeat.currentIndexChanged.connect(
            lambda: form.setRowVisible(weekdays, self._repeat.currentData() is None)
        )
        form.setRowVisible(weekdays, self._repeat.currentData() is None)

        sound_options = QWidget()
        sound_row = QHBoxLayout(sound_options)
        sound_row.setContentsMargins(0, 0, 0, 0)
        self._sound = QComboBox()
        for label, value in BUILTIN_SOUNDS:
            self._sound.addItem(label, value)
        self._sound.addItem("本机音频", "custom")
        self._sound.setCurrentIndex(self._sound.findData(alarm.sound))
        self._choose = _button("选择文件")
        self._choose.clicked.connect(self._choose_sound)
        self._preview_button = _button("试听")
        self._preview_button.clicked.connect(self._toggle_preview)
        sound_row.addWidget(self._sound, 1)
        sound_row.addWidget(self._choose)
        sound_row.addWidget(self._preview_button)
        form.addRow("铃声", sound_options)
        self._file_label = QLabel(self._sound_name)
        self._file_label.setObjectName("muted")
        self._file_label.setTextFormat(Qt.TextFormat.PlainText)
        self._file_label.setWordWrap(True)
        form.addRow("", self._file_label)

        def update_sound() -> None:
            self._stop_preview()
            custom = self._sound.currentData() == "custom"
            self._choose.setVisible(custom)
            form.setRowVisible(self._file_label, custom and bool(self._sound_path))
            self._preview_button.setEnabled(not custom or bool(self._sound_path))

        self._sound.currentIndexChanged.connect(update_sound)
        self._update_sound = update_sound
        update_sound()

        self._duration = QSpinBox()
        self._duration.setRange(5, 300)
        self._duration.setSuffix(" 秒")
        self._duration.setValue(alarm.ring_seconds)
        form.addRow("响铃时长", self._duration)
        self._snooze = QSpinBox()
        self._snooze.setRange(0, 60)
        self._snooze.setSpecialValueText("关闭")
        self._snooze.setSuffix(" 分钟")
        self._snooze.setValue(alarm.snooze_minutes)
        form.addRow("稍后提醒", self._snooze)
        self._delete_after = QCheckBox("本轮停止响铃后自动删除")
        self._delete_after.setChecked(alarm.delete_after_ring)
        form.addRow("", self._delete_after)
        layout.addLayout(form)

        actions = QHBoxLayout()
        if existing:
            delete = _button("删除闹钟", "dangerButton")
            delete.clicked.connect(self._delete_alarm)
            actions.addWidget(delete)
        actions.addStretch()
        cancel = _button("取消")
        cancel.clicked.connect(self.reject)
        save = _button("保存", "primaryButton")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)
        self._at.setFocus()

    def _choose_sound(self) -> None:
        self._stop_preview()
        extensions = " ".join(f"*{suffix}" for suffix in sorted(AUDIO_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(self, "选择铃声", "", f"音频文件 ({extensions})")
        if path:
            self._sound_path = path
            self._sound_name = Path(path).name
            self._file_label.setText(self._sound_name)
            self._update_sound()

    def _toggle_preview(self) -> None:
        if self._preview_timer.isActive():
            self._stop_preview()
            return
        self._preview.play(self._sound.currentData(), self._sound_path)
        self._preview_button.setText("停止试听")
        self._preview_timer.start(4000)

    def _stop_preview(self) -> None:
        self._preview_timer.stop()
        self._preview.stop()
        self._preview_button.setText("试听")

    def _save(self) -> None:
        weekdays = self._repeat.currentData()
        if weekdays is None:
            weekdays = tuple(day for day, button in enumerate(self._days) if button.isChecked())
            if not weekdays:
                QMessageBox.warning(self, APP_DISPLAY_NAME, "请至少选择一天。")
                return
        sound = self._sound.currentData()
        sound_path = ""
        if sound == "custom":
            try:
                sound_path = import_reminder_asset(self._sound_path, "audio")
            except (OSError, ValueError):
                QMessageBox.warning(self, APP_DISPLAY_NAME, "无法读取铃声，请选择一个本机音频文件。")
                return
        self.result_alarm = replace(
            self.result_alarm,
            at=self._at.time().toPython(),
            label=self._label.text().strip(),
            weekdays=weekdays,
            delete_after_ring=self._delete_after.isChecked(),
            ring_seconds=self._duration.value(),
            snooze_minutes=self._snooze.value(),
            sound=sound,
            sound_path=sound_path,
            sound_name=self._sound_name if sound_path else "",
        )
        self.accept()

    def _delete_alarm(self) -> None:
        self.delete_requested = True
        self.accept()


class ClockAlarmAlert(QDialog):
    snooze_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("闹钟")
        self.setMinimumWidth(350)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(16)
        self._time = QLabel()
        self._time.setObjectName("alarmTime")
        self._time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel()
        self._label.setObjectName("heading")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._time)
        layout.addWidget(self._label)
        actions = QHBoxLayout()
        self.snooze_button = _button("稍后提醒")
        self.snooze_button.clicked.connect(self.snooze_requested.emit)
        stop = _button("停止", "primaryButton")
        stop.clicked.connect(self.stop_requested.emit)
        actions.addWidget(self.snooze_button, 1)
        actions.addWidget(stop, 1)
        layout.addLayout(actions)
        self.rejected.connect(self.stop_requested.emit)

    def ring(self, alarm: ClockAlarm, now: datetime) -> None:
        shown_time = now.time() if alarm.snoozed_until is not None else alarm.at
        self._time.setText(f"{shown_time:%H:%M}")
        self._label.setText(alarm.label or "闹钟")
        self.snooze_button.setText(f"{alarm.snooze_minutes} 分钟后提醒")
        self.snooze_button.setVisible(alarm.snooze_minutes > 0)
        self.adjustSize()
        _place_window(self, QApplication.primaryScreen())
        self.show()
        self.raise_()
        self.activateWindow()
