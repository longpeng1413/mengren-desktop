"""Desktop-layer stickers, timers, alarms, and topmost due alerts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
import math
from pathlib import Path

from PySide6.QtCore import QDateTime, QEvent, QPoint, QRect, QSize, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DISPLAY_NAME
from app.desktop_visibility import send_window_to_bottom
from app.reminder_preferences import (
    AUDIO_EXTENSIONS,
    DesktopToolSettings,
    IMAGE_EXTENSIONS,
    ReminderSettings,
    ensure_default_alarm_sound,
    import_reminder_asset,
    load_desktop_tool_settings,
    load_reminders,
    new_reminder,
    save_desktop_tool_settings,
    save_reminders,
)
from app.system_actions import open_calculator, put_computer_to_sleep
from ui import theme
from ui.color_picker import pick_color
from ui.translator_window import TranslatorWindow


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _format_remaining(seconds: int) -> str:
    seconds = max(0, seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}天 {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class ReminderLauncher(QWidget):
    """Compact toolbar for choosing one independent desktop function."""

    action_requested = Signal(str)
    display_mode_toggle_requested = Signal()

    _ACTIONS = (
        ("贴文字", "text"),
        ("贴图片", "image"),
        ("翻译", "translate"),
        ("闹钟", "alarm"),
        ("计时器", "stopwatch"),
        ("倒计时", "countdown"),
        ("睡眠", "sleep"),
        ("计算器", "calculator"),
    )

    def __init__(self) -> None:
        super().__init__()
        self._dragging = False
        self._drag_offset = QPoint()
        self._user_position: QPoint | None = None
        self.setWindowTitle("桌面工具")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setObjectName("reminderLauncher")
        self.setStyleSheet(
            theme.toolbar_style("reminderLauncher", 13)
            + """
            #reminderLauncher QPushButton {
                min-width: 48px; max-width: 48px;
                min-height: 32px; max-height: 32px;
            }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        self.drag_handle = QPushButton("移动")
        self.drag_handle.setObjectName("dragHandle")
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.setToolTip("按住并拖动桌面工具栏")
        self.drag_handle.installEventFilter(self)
        layout.addWidget(self.drag_handle)
        self.display_mode_button = QPushButton("桌面")
        self.display_mode_button.setToolTip("切换桌面挂件的桌面/置顶显示模式")
        self.display_mode_button.clicked.connect(
            self.display_mode_toggle_requested.emit
        )
        layout.addWidget(self.display_mode_button)
        self.buttons: dict[str, QPushButton] = {}
        for label, kind in self._ACTIONS:
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, selected=kind: self._choose(selected)
            )
            layout.addWidget(button)
            self.buttons[kind] = button
        self.exit_button = QPushButton("退出")
        self.exit_button.setObjectName("dangerButton")
        self.exit_button.setToolTip("关闭桌面工具栏（不关闭已创建的挂件）")
        self.exit_button.clicked.connect(self.hide)
        layout.addWidget(self.exit_button)

    def showEvent(self, event) -> None:
        """Round the toolbar's corners like the main window's cards."""
        super().showEvent(event)
        theme.round_corners(self)

    def set_always_on_top_mode(self, enabled: bool) -> None:
        """Show the current shared reminder display mode on the toggle button."""
        self.display_mode_button.setText("置顶" if enabled else "桌面")

    def show_launcher(self) -> None:
        self.adjustSize()
        if self._user_position is not None:
            self.move(self._user_position)
        else:
            screen = QApplication.screenAt(QCursor.pos())
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is not None:
                bounds = screen.availableGeometry()
                self.move(
                    bounds.center().x() - self.width() // 2,
                    bounds.top() + 70,
                )
        self.show()
        self.raise_()
        self.activateWindow()

    def eventFilter(self, watched, event) -> bool:
        if watched is not self.drag_handle:
            return super().eventFilter(watched, event)
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._dragging = True
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return True
        if event.type() == QEvent.Type.MouseMove and self._dragging:
            position = event.globalPosition().toPoint() - self._drag_offset
            self.move(position)
            self._user_position = QPoint(position)
            event.accept()
            return True
        if event.type() == QEvent.Type.MouseButtonRelease and self._dragging:
            self._dragging = False
            self._user_position = QPoint(self.pos())
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def _choose(self, kind: str) -> None:
        self.hide()
        self.action_requested.emit(kind)


class ReminderAlertDialog(QDialog):
    """A separate topmost window shown when an alarm or countdown becomes due."""

    dismiss_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("桌面提醒")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumWidth(420)
        self.setStyleSheet(
            """
            QDialog { background: #242a31; }
            QLabel { color: #f7f9fb; }
            QPushButton {
                color: white; background: #1677c8; border: 0;
                border-radius: 6px; min-height: 38px;
                padding: 0 24px; font-size: 16px; font-weight: 700;
            }
            QPushButton:hover { background: #248bdc; }
            """
        )
        self._title_label = QLabel()
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            "color: #ffcf4a; font-size: 25px; font-weight: 800;"
        )
        self._message_label = QLabel()
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.setStyleSheet("font-size: 19px;")
        stop_button = QPushButton("停止响铃并关闭")
        stop_button.clicked.connect(self.dismiss_requested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(20)
        layout.addWidget(self._title_label)
        layout.addWidget(self._message_label)
        layout.addWidget(stop_button, 0, Qt.AlignmentFlag.AlignCenter)

    def show_reminder(self, reminder: ReminderSettings) -> None:
        titles = {"alarm": "⏰ 闹钟提醒", "countdown": "⏰ 倒计时结束"}
        self._title_label.setText(titles.get(reminder.kind, "⏰ 提醒时间到"))
        self._message_label.setText(reminder.text.strip() or "设定的提醒时间已经到了。")
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            bounds = screen.availableGeometry()
            self.move(
                bounds.center().x() - self.width() // 2,
                bounds.center().y() - self.height() // 2,
            )
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        self.dismiss_requested.emit()
        super().closeEvent(event)


class _ResizeHandle(QWidget):
    """Small bottom-right handle that reports pointer movement to its item."""

    drag_started = Signal()
    drag_moved = Signal(QPoint)
    drag_finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._origin: QPoint | None = None
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("拖动这里自由缩放")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f2b84b"))
        painter.setPen(QPen(QColor("#5d481b"), 2))
        for offset in (4, 8, 12):
            painter.drawLine(
                self.width() - offset,
                self.height() - 2,
                self.width() - 2,
                self.height() - offset,
            )
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self.drag_started.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.drag_moved.emit(event.globalPosition().toPoint() - self._origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._origin = None
            self.drag_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _ResizableReminderItem(QWidget):
    """A text or image box resized directly from its visible corner handle."""

    resized = Signal(QSize)

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._resize_start = QSize()
        self._pixmap = QPixmap()
        self._text_color = "#fff4d6"
        self._selected = False
        self._requested_text_height = 90
        self._derived_font_size = 30
        self.setObjectName("resizableReminderItem")
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(kind == "text")
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._handle = _ResizeHandle(self)
        self._handle.drag_started.connect(self._begin_resize)
        self._handle.drag_moved.connect(self._resize_by)
        self._handle.drag_finished.connect(self._finish_resize)
        self._handle.hide()
        self._minimum_item_size = QSize(
            140 if kind == "text" else 120,
            48 if kind == "text" else 90,
        )
        self.setStyleSheet(
            "#resizableReminderItem {"
            " border: none; background: transparent;"
            "}"
        )

    def set_item_size(self, width: int, height: int) -> None:
        maximum = self.maximum_item_size()
        requested = QSize(
            max(self._minimum_item_size.width(), min(maximum.width(), width)),
            max(self._minimum_item_size.height(), min(maximum.height(), height)),
        )
        if self._kind == "text":
            self._requested_text_height = requested.height()
            self._derived_font_size = max(
                10,
                min(96, round(self._requested_text_height / 3)),
            )
            requested.setHeight(self._tight_text_height(requested.width(), maximum.height()))
        elif not self._pixmap.isNull():
            requested = self._tight_image_size(requested, maximum)
        self.setFixedSize(requested)
        self._refresh_content()

    def set_text_content(self, text: str, color: str) -> None:
        self._text_color = color
        self.label.setText(text)
        self.set_item_size(self.width(), self._requested_text_height)
        self._refresh_content()

    def set_image_content(self, pixmap: QPixmap) -> None:
        self._pixmap = QPixmap(pixmap)
        self.set_item_size(self.width(), self.height())
        self._refresh_content()

    @property
    def derived_font_size(self) -> int:
        return self._derived_font_size

    def maximum_item_size(self) -> QSize:
        """Use almost the full monitor containing this desktop sticker."""
        center = self.window().frameGeometry().center()
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QSize(1920, 1000)
        bounds = screen.availableGeometry()
        return QSize(
            max(self._minimum_item_size.width(), bounds.width() - 40),
            max(self._minimum_item_size.height(), bounds.height() - 90),
        )

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._handle.setVisible(selected)
        self.update()

    def _begin_resize(self) -> None:
        self._resize_start = QSize(
            self.width(),
            self._requested_text_height if self._kind == "text" else self.height(),
        )

    def _resize_by(self, delta: QPoint) -> None:
        self.set_item_size(
            self._resize_start.width() + delta.x(),
            self._resize_start.height() + delta.y(),
        )
        self.window().adjustSize()

    def _finish_resize(self) -> None:
        if self._kind == "text":
            self.resized.emit(QSize(self.width(), self._requested_text_height))
        else:
            self.resized.emit(self.size())

    def _tight_text_height(self, width: int, maximum_height: int) -> int:
        font = QFont(self.label.font())
        font.setPixelSize(self._derived_font_size)
        font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        text = self.label.text() or "文字"
        bounds = metrics.boundingRect(
            QRect(0, 0, max(1, width - 10), maximum_height),
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            text,
        )
        return max(
            self._minimum_item_size.height(),
            min(maximum_height, bounds.height() + 10),
        )

    def _tight_image_size(self, requested: QSize, maximum: QSize) -> QSize:
        content_limit = QSize(
            max(1, requested.width() - 10),
            max(1, requested.height() - 10),
        )
        fitted = self._pixmap.size().scaled(
            content_limit,
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        tight = QSize(fitted.width() + 10, fitted.height() + 10)
        if (
            tight.width() < self._minimum_item_size.width()
            or tight.height() < self._minimum_item_size.height()
        ):
            minimum_content = QSize(
                max(1, self._minimum_item_size.width() - 10),
                max(1, self._minimum_item_size.height() - 10),
            )
            fitted = self._pixmap.size().scaled(
                minimum_content,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            )
            tight = QSize(fitted.width() + 10, fitted.height() + 10)
        return QSize(
            min(maximum.width(), tight.width()),
            min(maximum.height(), tight.height()),
        )

    def _refresh_content(self) -> None:
        if self._kind == "text":
            self.label.setStyleSheet(
                f"border: none; color: {self._text_color};"
                f" font-size: {self.derived_font_size}px; font-weight: 600;"
            )
        elif not self._pixmap.isNull():
            self.label.setPixmap(
                self._pixmap.scaled(
                    max(1, self.width() - 14),
                    max(1, self.height() - 14),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def resizeEvent(self, event) -> None:
        self.label.setGeometry(5, 5, max(1, self.width() - 10), max(1, self.height() - 10))
        self._handle.move(self.width() - self._handle.width(), self.height() - self._handle.height())
        self._handle.raise_()
        self._refresh_content()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._selected:
            return
        painter = QPainter(self)
        painter.setPen(
            QPen(
                QColor(242, 184, 75, 210),
                1,
                Qt.PenStyle.DashLine,
            )
        )
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        owner = self.window()
        if event.button() == Qt.MouseButton.LeftButton and hasattr(owner, "_begin_drag"):
            if hasattr(owner, "_select_item"):
                owner._select_item(self)
            owner._begin_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        owner = self.window()
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(owner, "_continue_drag"):
            owner._continue_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        owner = self.window()
        if event.button() == Qt.MouseButton.LeftButton and hasattr(owner, "_end_drag"):
            owner._end_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        owner = self.window()
        if event.button() == Qt.MouseButton.LeftButton and hasattr(owner, "edit_requested"):
            owner.edit_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        owner = self.window()
        if hasattr(owner, "_open_context_menu"):
            owner._open_context_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)


class ReminderEditorDialog(QDialog):
    """Create or edit a reminder card and its optional audible schedule."""

    def __init__(self, settings: ReminderSettings, parent=None) -> None:
        super().__init__(parent)
        self._original = settings
        self._kind = settings.kind
        self._image_source = settings.image_path
        self._sound_source = settings.sound_path
        self.result_settings = settings
        titles = {
            "text": "文字贴图",
            "image": "图片贴图",
            "alarm": "闹钟",
            "countdown": "倒计时",
        }
        self.setWindowTitle(titles.get(settings.kind, "桌面工具"))
        self.setMinimumWidth(560)

        self._text_edit = QTextEdit(settings.text)
        self._text_edit.setPlaceholderText("输入重要事件、待办事项或其他提醒文字……")
        self._text_edit.setMinimumHeight(105)

        self._image_preview = QLabel("未选择图片")
        self._image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_preview.setFixedSize(260, 135)
        self._image_preview.setStyleSheet(
            "border: 1px dashed #9aa4af; border-radius: 5px; color: #66717d;"
        )
        choose_image = QPushButton("加载图片")
        remove_image = QPushButton("移除图片")
        choose_image.clicked.connect(self._choose_image)
        remove_image.clicked.connect(self._remove_image)
        image_buttons = QHBoxLayout()
        image_buttons.addWidget(choose_image)
        image_buttons.addWidget(remove_image)
        image_buttons.addStretch()
        image_buttons_widget = QWidget()
        image_buttons_widget.setLayout(image_buttons)

        self._text_color = QColor(settings.text_color)
        self._color_button = QPushButton()
        self._color_button.clicked.connect(self._choose_color)
        self._update_color_button()

        self._show_status = QCheckBox("显示未完成/已完成标识")
        self._show_status.setChecked(settings.show_status)
        self._status = QComboBox()
        self._status.addItem("未完成", False)
        self._status.addItem("已完成", True)
        self._status.setCurrentIndex(1 if settings.completed else 0)
        self._status.setEnabled(settings.show_status)
        self._show_status.toggled.connect(self._status.setEnabled)

        appearance_form = QFormLayout()
        appearance_form.addRow("文字颜色：", self._color_button)
        appearance_form.addRow(self._show_status, self._status)
        appearance_widget = QWidget()
        appearance_widget.setLayout(appearance_form)

        self._schedule_mode = QComboBox()
        self._schedule_mode.addItem("不响铃", "none")
        self._schedule_mode.addItem("指定日期和时间", "alarm")
        self._schedule_mode.addItem("倒计时", "countdown")
        schedule_index = max(0, self._schedule_mode.findData(settings.schedule_mode))
        self._schedule_mode.setCurrentIndex(schedule_index)

        self._alarm_at = QDateTimeEdit()
        self._alarm_at.setCalendarPopup(True)
        self._alarm_at.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        alarm_at = _parse_datetime(settings.alarm_at)
        self._alarm_at.setDateTime(
            QDateTime(alarm_at)
            if alarm_at is not None
            else QDateTime.currentDateTime().addSecs(3600)
        )

        self._countdown_hours = QSpinBox()
        self._countdown_hours.setRange(0, 999)
        self._countdown_hours.setSuffix(" 小时")
        self._countdown_minutes = QSpinBox()
        self._countdown_minutes.setRange(0, 59)
        self._countdown_minutes.setSuffix(" 分")
        self._countdown_seconds = QSpinBox()
        self._countdown_seconds.setRange(0, 59)
        self._countdown_seconds.setSuffix(" 秒")
        countdown = max(0, settings.countdown_seconds)
        hours, remainder = divmod(countdown, 3600)
        minutes, seconds = divmod(remainder, 60)
        self._countdown_hours.setValue(hours)
        self._countdown_minutes.setValue(minutes)
        self._countdown_seconds.setValue(seconds)
        countdown_layout = QHBoxLayout()
        countdown_layout.setContentsMargins(0, 0, 0, 0)
        countdown_layout.addWidget(self._countdown_hours)
        countdown_layout.addWidget(self._countdown_minutes)
        countdown_layout.addWidget(self._countdown_seconds)
        countdown_widget = QWidget()
        countdown_widget.setLayout(countdown_layout)

        self._sound_mode = QComboBox()
        self._sound_mode.addItem("内置提醒音", "default")
        self._sound_mode.addItem("自选音乐", "custom")
        self._sound_mode.setCurrentIndex(1 if settings.sound_path else 0)
        self._sound_label = QLabel(
            Path(settings.sound_path).name
            if settings.sound_path
            else "使用内置提醒音"
        )
        self._sound_label.setWordWrap(True)
        choose_sound = QPushButton("选择音乐")
        choose_sound.clicked.connect(self._choose_sound)
        sound_row = QHBoxLayout()
        sound_row.setContentsMargins(0, 0, 0, 0)
        sound_row.addWidget(choose_sound)
        sound_row.addWidget(self._sound_label, 1)
        sound_widget = QWidget()
        sound_widget.setLayout(sound_row)

        schedule_group = QGroupBox("闹钟与计时器")
        schedule_form = QFormLayout(schedule_group)
        schedule_form.addRow("提醒方式：", self._schedule_mode)
        schedule_form.addRow("响铃时间：", self._alarm_at)
        schedule_form.addRow("倒计时长度：", countdown_widget)
        schedule_form.addRow("提示音乐：", self._sound_mode)
        schedule_form.addRow("", sound_widget)
        self._schedule_mode.currentIndexChanged.connect(self._update_schedule_controls)
        self._sound_mode.currentIndexChanged.connect(self._update_schedule_controls)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        text_heading = QLabel(
            "文字内容：" if settings.kind == "text" else "名称（可选）："
        )
        image_heading = QLabel("选择图片：")
        layout.addWidget(text_heading)
        layout.addWidget(self._text_edit)
        layout.addWidget(image_heading)
        layout.addWidget(self._image_preview, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(image_buttons_widget)
        layout.addWidget(appearance_widget)
        layout.addWidget(schedule_group)
        layout.addWidget(buttons)
        text_visible = settings.kind in {"text", "alarm", "countdown"}
        image_visible = settings.kind == "image"
        sticker = settings.kind in {"text", "image"}
        scheduled = settings.kind in {"alarm", "countdown"}
        text_heading.setVisible(text_visible)
        self._text_edit.setVisible(text_visible)
        image_heading.setVisible(image_visible)
        self._image_preview.setVisible(image_visible)
        image_buttons_widget.setVisible(image_visible)
        appearance_widget.setVisible(sticker)
        if settings.kind == "image":
            color_label = appearance_form.labelForField(self._color_button)
            if color_label is not None:
                color_label.hide()
            self._color_button.hide()
        schedule_group.setVisible(scheduled)
        if scheduled:
            fixed_mode = settings.kind
            self._schedule_mode.setCurrentIndex(
                self._schedule_mode.findData(fixed_mode)
            )
            mode_label = schedule_form.labelForField(self._schedule_mode)
            if mode_label is not None:
                mode_label.hide()
            self._schedule_mode.hide()
        self._update_image_preview()
        self._update_schedule_controls()

    def _choose_image(self) -> None:
        extensions = " ".join(f"*{suffix}" for suffix in sorted(IMAGE_EXTENSIONS))
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择提醒图片",
            "",
            f"图片文件 ({extensions});;所有文件 (*)",
        )
        if path:
            self._image_source = path
            self._update_image_preview()

    def _remove_image(self) -> None:
        self._image_source = ""
        self._update_image_preview()

    def _update_image_preview(self) -> None:
        pixmap = QPixmap(self._image_source) if self._image_source else QPixmap()
        if pixmap.isNull():
            self._image_preview.setPixmap(QPixmap())
            self._image_preview.setText("未选择图片")
            return
        self._image_preview.setText("")
        self._image_preview.setPixmap(
            pixmap.scaled(
                self._image_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _choose_color(self) -> None:
        color = pick_color(self._text_color, self._color_button, "选择提醒文字颜色")
        if color.isValid():
            self._text_color = color
            self._update_color_button()

    def _update_color_button(self) -> None:
        self._color_button.setText(self._text_color.name().upper())
        foreground = "#101418" if self._text_color.lightness() > 150 else "#ffffff"
        self._color_button.setStyleSheet(
            f"background: {self._text_color.name()}; color: {foreground};"
        )

    def _choose_sound(self) -> None:
        extensions = " ".join(f"*{suffix}" for suffix in sorted(AUDIO_EXTENSIONS))
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择提示音乐",
            "",
            f"音频文件 ({extensions});;所有文件 (*)",
        )
        if path:
            self._sound_source = path
            self._sound_mode.setCurrentIndex(self._sound_mode.findData("custom"))
            self._sound_label.setText(Path(path).name)

    def _update_schedule_controls(self) -> None:
        mode = self._schedule_mode.currentData()
        self._alarm_at.setEnabled(mode == "alarm")
        for control in (
            self._countdown_hours,
            self._countdown_minutes,
            self._countdown_seconds,
        ):
            control.setEnabled(mode == "countdown")
        custom = self._sound_mode.currentData() == "custom"
        self._sound_label.setEnabled(custom)

    def _save(self) -> None:
        text = self._text_edit.toPlainText().strip()
        mode = self._kind if self._kind in {"alarm", "countdown"} else "none"
        if self._kind == "text" and not text:
            QMessageBox.warning(
                self,
                APP_DISPLAY_NAME,
                "请输入文字贴图内容。",
            )
            return
        if self._kind == "image" and not self._image_source:
            QMessageBox.warning(self, APP_DISPLAY_NAME, "请选择一张图片。")
            return
        countdown = (
            self._countdown_hours.value() * 3600
            + self._countdown_minutes.value() * 60
            + self._countdown_seconds.value()
        )
        unchanged_countdown = (
            mode == "countdown"
            and self._original.schedule_mode == "countdown"
            and countdown == self._original.countdown_seconds
            and not self._original.alarm_fired
            and (
                (
                    self._original.countdown_running
                    and (_parse_datetime(self._original.target_at) or datetime.min)
                    > datetime.now()
                )
                or (
                    not self._original.countdown_running
                    and self._original.countdown_remaining > 0
                )
            )
        )
        if mode == "countdown" and countdown <= 0:
            QMessageBox.warning(self, APP_DISPLAY_NAME, "倒计时时间必须大于 0 秒。")
            return
        alarm_at = self._alarm_at.dateTime().toPython().replace(microsecond=0)
        unchanged_alarm = (
            mode == "alarm"
            and self._original.schedule_mode == "alarm"
            and alarm_at == _parse_datetime(self._original.alarm_at)
            and bool(self._original.target_at)
        )
        if mode == "alarm" and alarm_at <= datetime.now() and not unchanged_alarm:
            QMessageBox.warning(self, APP_DISPLAY_NAME, "闹钟时间必须晚于当前时间。")
            return
        try:
            image_path = (
                import_reminder_asset(self._image_source, "image")
                if self._kind == "image" and self._image_source
                else ""
            )
            sound_path = (
                import_reminder_asset(self._sound_source, "audio")
                if mode in {"alarm", "countdown"}
                and self._sound_mode.currentData() == "custom"
                else ""
            )
        except (OSError, ValueError):
            QMessageBox.warning(
                self,
                APP_DISPLAY_NAME,
                "图片或音乐无法读取，请重新选择一个本机文件。",
            )
            return
        target = ""
        alarm_value = ""
        alarm_fired = False
        countdown_remaining = 0
        countdown_running = False
        if mode == "alarm":
            alarm_value = alarm_at.isoformat()
            target = self._original.target_at if unchanged_alarm else alarm_value
            alarm_fired = self._original.alarm_fired if unchanged_alarm else False
        elif mode == "countdown":
            if unchanged_countdown:
                target = self._original.target_at
                alarm_fired = self._original.alarm_fired
                countdown_remaining = self._original.countdown_remaining
                countdown_running = self._original.countdown_running
            else:
                countdown_remaining = countdown
        self.result_settings = ReminderSettings(
            reminder_id=self._original.reminder_id,
            kind=self._kind,
            enabled=True,
            text=text if self._kind != "image" else "",
            image_path=image_path,
            font_size=self._original.font_size,
            text_width=self._original.text_width,
            text_height=self._original.text_height,
            image_width=self._original.image_width,
            image_height=self._original.image_height,
            text_color=self._text_color.name(),
            show_status=(
                self._show_status.isChecked()
                if self._kind in {"text", "image"}
                else False
            ),
            completed=(
                bool(self._status.currentData())
                if self._kind in {"text", "image"}
                else False
            ),
            x=self._original.x,
            y=self._original.y,
            schedule_mode=mode,
            alarm_at=alarm_value,
            countdown_seconds=countdown if mode == "countdown" else 0,
            countdown_remaining=countdown_remaining,
            countdown_running=countdown_running,
            target_at=target,
            sound_path=sound_path,
            alarm_fired=alarm_fired,
            stopwatch_elapsed=self._original.stopwatch_elapsed,
            stopwatch_started_at=self._original.stopwatch_started_at,
            stopwatch_running=self._original.stopwatch_running,
        )
        self.accept()


class DesktopReminderWidget(QWidget):
    """A draggable card kept below ordinary windows and above the desktop."""

    edit_requested = Signal()
    delete_requested = Signal()
    status_toggle_requested = Signal()
    stop_alarm_requested = Signal()
    position_saved = Signal(QPoint)
    text_size_changed = Signal(QSize)
    image_size_changed = Signal(QSize)
    alarm_due = Signal()
    stopwatch_start_requested = Signal()
    stopwatch_toggle_requested = Signal()
    stopwatch_reset_requested = Signal()
    countdown_start_requested = Signal()
    countdown_toggle_requested = Signal()
    countdown_reset_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = ReminderSettings()
        self._drag_offset: QPoint | None = None
        self._due_emitted = False
        self.setObjectName("desktopReminder")
        self.setWindowTitle("桌面提醒")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setStyleSheet(
            """
            #desktopReminder {
                background-color: rgba(31, 36, 42, 238);
                border: 2px solid #f2b84b;
                border-radius: 12px;
            }
            QLabel { background: transparent; }
            """
        )

        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label = QLabel()
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet(
            "color: #fff4d6; font-size: 22px; font-weight: 700;"
        )
        self._image_item = _ResizableReminderItem("image", self)
        self._text_item = _ResizableReminderItem("text", self)
        self._image_item.resized.connect(self.image_size_changed)
        self._text_item.resized.connect(self.text_size_changed)
        self._image_label = self._image_item.label
        self._text_label = self._text_item.label
        self._timer_label = QLabel()
        self._timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._control_bar = QWidget()
        control_layout = QHBoxLayout(self._control_bar)
        control_layout.setContentsMargins(0, 2, 0, 0)
        control_layout.setSpacing(7)
        self._stopwatch_start_button = QPushButton("开始")
        self._stopwatch_toggle_button = QPushButton("暂停")
        self._stopwatch_reset_button = QPushButton("重置")
        self._stopwatch_cancel_button = QPushButton("取消")
        self._countdown_edit_button = QPushButton("修改")
        for button in (
            self._stopwatch_start_button,
            self._stopwatch_toggle_button,
            self._stopwatch_reset_button,
            self._stopwatch_cancel_button,
            self._countdown_edit_button,
        ):
            button.setStyleSheet(
                "color: #f7f9fb; background: #3a4652; border: 1px solid #788592;"
                "border-radius: 5px; min-height: 30px; padding: 0 10px;"
                "font-size: 14px; font-weight: 700;"
            )
            control_layout.addWidget(button)
        self._stopwatch_start_button.clicked.connect(
            self._request_timer_start
        )
        self._stopwatch_toggle_button.clicked.connect(
            self._request_timer_toggle
        )
        self._stopwatch_reset_button.clicked.connect(
            self._request_timer_reset
        )
        self._stopwatch_cancel_button.clicked.connect(self.delete_requested.emit)
        self._countdown_edit_button.clicked.connect(self.edit_requested.emit)
        for label in (
            self._status_label,
            self._title_label,
            self._timer_label,
        ):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        layout.addWidget(self._status_label)
        layout.addWidget(self._title_label)
        layout.addWidget(self._image_item, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._text_item, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._timer_label)
        layout.addWidget(self._control_bar, 0, Qt.AlignmentFlag.AlignCenter)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_time)
        self._timer.start()

    def set_always_on_top(self, enabled: bool) -> None:
        """Apply one shared display mode without changing the card position."""
        flag = Qt.WindowType.WindowStaysOnTopHint
        if bool(self.windowFlags() & flag) == enabled:
            return
        was_visible = self.isVisible()
        position = QPoint(self.pos())
        self.setWindowFlag(flag, enabled)
        self.move(position)
        if was_visible:
            self.show()
            if enabled:
                self.raise_()

    def set_settings(self, settings: ReminderSettings) -> None:
        self._settings = settings
        self._due_emitted = settings.alarm_fired
        self._select_item(None)
        sticker = settings.kind in {"text", "image"}
        if settings.show_status and sticker:
            if settings.completed:
                self._status_label.setText("✓ 已完成")
                self._status_label.setStyleSheet(
                    "color: #72e38d; font-size: 17px; font-weight: 700;"
                )
            else:
                self._status_label.setText("● 未完成")
                self._status_label.setStyleSheet(
                    "color: #ff704d; font-size: 17px; font-weight: 700;"
                )
            self._status_label.show()
        else:
            self._status_label.hide()

        self._text_item.set_item_size(settings.text_width, settings.text_height)
        self._text_item.set_text_content(settings.text, settings.text_color)
        self._text_item.setVisible(settings.kind == "text" and bool(settings.text))

        pixmap = QPixmap(settings.image_path) if settings.image_path else QPixmap()
        if pixmap.isNull() or settings.kind != "image":
            self._image_item.hide()
        else:
            self._image_item.set_item_size(settings.image_width, settings.image_height)
            self._image_item.set_image_content(pixmap)
            self._image_item.show()
        if settings.kind in {"alarm", "countdown", "stopwatch"}:
            default_titles = {
                "alarm": "闹钟",
                "countdown": "倒计时",
                "stopwatch": "计时器",
            }
            self._title_label.setText(settings.text or default_titles[settings.kind])
            self._title_label.show()
        else:
            self._title_label.hide()
        timer_kind = settings.kind in {"stopwatch", "countdown"}
        for button in (
            self._stopwatch_start_button,
            self._stopwatch_toggle_button,
            self._stopwatch_reset_button,
            self._stopwatch_cancel_button,
        ):
            button.setVisible(timer_kind)
        self._countdown_edit_button.setVisible(settings.kind == "countdown")
        self._control_bar.setVisible(timer_kind)
        if timer_kind:
            running = (
                settings.stopwatch_running
                if settings.kind == "stopwatch"
                else settings.countdown_running
            )
            progressed = (
                settings.stopwatch_elapsed > 0
                if settings.kind == "stopwatch"
                else 0 < settings.countdown_remaining < settings.countdown_seconds
            )
            self._stopwatch_start_button.setEnabled(not running)
            self._stopwatch_toggle_button.setText(
                "暂停" if running else "继续"
            )
            self._stopwatch_toggle_button.setEnabled(
                running or progressed
            )
        self._update_time()
        self.adjustSize()

    def _update_time(self) -> None:
        if self._settings.kind == "stopwatch":
            elapsed = self._settings.stopwatch_elapsed
            started = _parse_datetime(self._settings.stopwatch_started_at)
            if self._settings.stopwatch_running and started is not None:
                elapsed += max(0, int((datetime.now() - started).total_seconds()))
            state = "运行中" if self._settings.stopwatch_running else "已暂停"
            self._timer_label.setText(
                f"正计时：{_format_remaining(elapsed)}  {state}"
            )
            self._timer_label.setStyleSheet(
                "color: #8fd6ff; font-size: 24px; font-weight: 800;"
            )
            self._timer_label.show()
            return
        if self._settings.kind == "countdown":
            target = _parse_datetime(self._settings.target_at)
            remaining = self._settings.countdown_remaining
            if self._settings.countdown_running and target is not None:
                remaining = max(
                    0,
                    math.ceil((target - datetime.now()).total_seconds()),
                )
            if self._settings.alarm_fired and remaining <= 0:
                self._timer_label.setText("⏰ 倒计时结束")
                self._timer_label.setStyleSheet(
                    "color: #ffcf4a; font-size: 20px; font-weight: 800;"
                )
            else:
                state = "运行中" if self._settings.countdown_running else "已暂停"
                self._timer_label.setText(
                    f"倒计时：{_format_remaining(remaining)}  {state}"
                )
                self._timer_label.setStyleSheet(
                    "color: #8fd6ff; font-size: 18px; font-weight: 700;"
                )
            self._timer_label.show()
            if remaining <= 0 and not self._due_emitted:
                self._due_emitted = True
                self.alarm_due.emit()
            return
        mode = self._settings.schedule_mode
        target = _parse_datetime(self._settings.target_at)
        if mode == "none" or target is None:
            self._timer_label.hide()
            return
        remaining = int((target - datetime.now()).total_seconds())
        if remaining <= 0:
            self._timer_label.setText("⏰ 提醒时间到！")
            self._timer_label.setStyleSheet(
                "color: #ffcf4a; font-size: 20px; font-weight: 800;"
            )
            self._timer_label.show()
            if not self._due_emitted:
                self._due_emitted = True
                self.alarm_due.emit()
            return
        if mode == "countdown":
            text = f"倒计时：{_format_remaining(remaining)}"
        else:
            text = f"闹钟：{target.strftime('%Y-%m-%d %H:%M:%S')}"
        self._timer_label.setText(text)
        self._timer_label.setStyleSheet(
            "color: #8fd6ff; font-size: 18px; font-weight: 700;"
        )
        self._timer_label.show()

    def _request_timer_start(self) -> None:
        if self._settings.kind == "countdown":
            self.countdown_start_requested.emit()
        else:
            self.stopwatch_start_requested.emit()

    def _request_timer_toggle(self) -> None:
        if self._settings.kind == "countdown":
            self.countdown_toggle_requested.emit()
        else:
            self.stopwatch_toggle_requested.emit()

    def _request_timer_reset(self) -> None:
        if self._settings.kind == "countdown":
            self.countdown_reset_requested.emit()
        else:
            self.stopwatch_reset_requested.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._select_item(None)
            self._begin_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self._continue_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._end_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.edit_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event) -> None:
        self._select_item(None)
        super().focusOutEvent(event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate:
            self._select_item(None)
        return super().event(event)

    def _select_item(self, selected: _ResizableReminderItem | None) -> None:
        self._text_item.set_selected(selected is self._text_item)
        self._image_item.set_selected(selected is self._image_item)

    def _begin_drag(self, global_position: QPoint) -> None:
        self._drag_offset = global_position - self.frameGeometry().topLeft()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _continue_drag(self, global_position: QPoint) -> None:
        if self._drag_offset is not None:
            self.move(global_position - self._drag_offset)

    def _end_drag(self) -> None:
        if self._drag_offset is None:
            return
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.position_saved.emit(self.pos())

    @property
    def is_dragging(self) -> bool:
        return self._drag_offset is not None

    def contextMenuEvent(self, event) -> None:
        self._open_context_menu(event.globalPos())

    def _open_context_menu(self, global_position: QPoint) -> None:
        menu = QMenu(self)
        edit_action = (
            menu.addAction("修改")
            if self._settings.kind != "stopwatch"
            else None
        )
        status_action = None
        if self._settings.show_status and self._settings.kind in {"text", "image"}:
            status_action = menu.addAction(
                "标记为未完成" if self._settings.completed else "标记为已完成"
            )
        stopwatch_toggle_action = None
        stopwatch_reset_action = None
        if self._settings.kind == "stopwatch":
            stopwatch_toggle_action = menu.addAction(
                "暂停" if self._settings.stopwatch_running else "继续"
            )
            stopwatch_reset_action = menu.addAction("重置")
        stop_action = (
            menu.addAction("停止响铃")
            if self._settings.kind in {"alarm", "countdown"}
            else None
        )
        menu.addSeparator()
        delete_action = menu.addAction("删除提醒")
        selected = menu.exec(global_position)
        if edit_action is not None and selected == edit_action:
            self.edit_requested.emit()
        elif status_action is not None and selected == status_action:
            self.status_toggle_requested.emit()
        elif stopwatch_toggle_action is not None and selected == stopwatch_toggle_action:
            self.stopwatch_toggle_requested.emit()
        elif stopwatch_reset_action is not None and selected == stopwatch_reset_action:
            self.stopwatch_reset_requested.emit()
        elif stop_action is not None and selected == stop_action:
            self.stop_alarm_requested.emit()
        elif selected == delete_action:
            self.delete_requested.emit()


class DesktopReminderManager:
    """Own independent desktop stickers, alarms, stopwatch, and countdown windows."""

    def __init__(
        self,
        parent=None,
        bottom_window_handler: Callable[[int], bool] = send_window_to_bottom,
        sleep_handler: Callable[[], bool] = put_computer_to_sleep,
        calculator_handler: Callable[[], bool] = open_calculator,
    ) -> None:
        self._parent = parent
        self._bottom_window_handler = bottom_window_handler
        self._sleep_handler = sleep_handler
        self._calculator_handler = calculator_handler
        self._tool_settings = load_desktop_tool_settings()
        self._reminders = {
            item.reminder_id: item
            for item in load_reminders()
        }
        self._widgets: dict[str, DesktopReminderWidget] = {}
        self._translator: TranslatorWindow | None = None
        self._launcher = ReminderLauncher()
        self._launcher.action_requested.connect(self._create_action)
        self._launcher.display_mode_toggle_requested.connect(
            self._toggle_display_mode
        )
        self._launcher.set_always_on_top_mode(self._tool_settings.always_on_top)
        self._alert = ReminderAlertDialog(parent)
        self._alert.dismiss_requested.connect(self._dismiss_alert)

        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(0.85)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.errorOccurred.connect(self._media_error)
        self._fallback_timer = QTimer()
        self._fallback_timer.setInterval(1200)
        self._fallback_timer.timeout.connect(QApplication.beep)
        self._alarm_playing = False
        self._ringing_id = ""
        self._desktop_layer_timer = QTimer()
        self._desktop_layer_timer.setInterval(750)
        self._desktop_layer_timer.timeout.connect(self._refresh_desktop_layer)
        self._desktop_layer_timer.start()

    @property
    def settings(self) -> ReminderSettings:
        return next(iter(self._reminders.values()), ReminderSettings())

    @property
    def widget(self) -> DesktopReminderWidget | None:
        return next(iter(self._widgets.values()), None)

    @property
    def launcher(self) -> ReminderLauncher:
        return self._launcher

    def restore(self) -> None:
        for reminder in list(self._reminders.values()):
            self._show_widget(reminder)

    def open_launcher(self) -> None:
        if self._launcher.isVisible():
            self._launcher.hide()
            return
        self._launcher.show_launcher()

    def open_translator(self) -> None:
        """Show the text translator, created on first use."""
        if self._translator is None:
            self._translator = TranslatorWindow()
        self._translator.open()

    def open_editor(self) -> None:
        """Backward-compatible name used by older launcher wiring."""
        self.open_launcher()

    def _create_action(self, kind: str) -> None:
        if kind == "translate":
            self.open_translator()
            return
        if kind == "calculator":
            if not self._calculator_handler():
                QMessageBox.warning(self._parent, APP_DISPLAY_NAME, "无法打开计算器。")
            return
        if kind == "sleep":
            answer = QMessageBox.question(
                self._parent,
                APP_DISPLAY_NAME,
                "确定让电脑立即进入睡眠吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes and not self._sleep_handler():
                QMessageBox.warning(
                    self._parent,
                    APP_DISPLAY_NAME,
                    "电脑未能进入睡眠，请检查 Windows 电源设置。",
                )
            return
        reminder = new_reminder(kind)
        if kind == "stopwatch":
            reminder = replace(
                reminder,
                text="计时器",
                stopwatch_started_at="",
                stopwatch_running=False,
            )
            self._reminders[reminder.reminder_id] = reminder
            self._persist()
            self._show_widget(reminder)
            return
        dialog = ReminderEditorDialog(reminder, self._parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reminder = dialog.result_settings
        self._reminders[reminder.reminder_id] = reminder
        self._persist()
        self._show_widget(reminder)

    def _edit(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None or reminder.kind == "stopwatch":
            return
        dialog = ReminderEditorDialog(reminder, self._parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.result_settings
        self._reminders[reminder_id] = updated
        self._persist()
        self._show_widget(updated)

    def _widget_for(self, reminder_id: str) -> DesktopReminderWidget:
        widget = self._widgets.get(reminder_id)
        if widget is not None:
            return widget
        widget = DesktopReminderWidget()
        widget.set_always_on_top(self._tool_settings.always_on_top)
        widget.edit_requested.connect(lambda rid=reminder_id: self._edit(rid))
        widget.delete_requested.connect(lambda rid=reminder_id: self._delete(rid))
        widget.status_toggle_requested.connect(
            lambda rid=reminder_id: self._toggle_completed(rid)
        )
        widget.stop_alarm_requested.connect(lambda rid=reminder_id: self.stop_alarm(rid))
        widget.position_saved.connect(
            lambda position, rid=reminder_id: self._save_position(rid, position)
        )
        widget.text_size_changed.connect(
            lambda size, rid=reminder_id: self._save_text_size(rid, size)
        )
        widget.image_size_changed.connect(
            lambda size, rid=reminder_id: self._save_image_size(rid, size)
        )
        widget.alarm_due.connect(lambda rid=reminder_id: self._alarm_due(rid))
        widget.stopwatch_start_requested.connect(
            lambda rid=reminder_id: self._start_stopwatch(rid)
        )
        widget.stopwatch_toggle_requested.connect(
            lambda rid=reminder_id: self._toggle_stopwatch(rid)
        )
        widget.stopwatch_reset_requested.connect(
            lambda rid=reminder_id: self._reset_stopwatch(rid)
        )
        widget.countdown_start_requested.connect(
            lambda rid=reminder_id: self._start_countdown(rid)
        )
        widget.countdown_toggle_requested.connect(
            lambda rid=reminder_id: self._toggle_countdown(rid)
        )
        widget.countdown_reset_requested.connect(
            lambda rid=reminder_id: self._reset_countdown(rid)
        )
        self._widgets[reminder_id] = widget
        return widget

    def _show_widget(self, reminder: ReminderSettings) -> None:
        widget = self._widget_for(reminder.reminder_id)
        widget.set_settings(reminder)
        if reminder.x is None or reminder.y is None:
            screen = QApplication.primaryScreen()
            if screen is not None:
                bounds = screen.availableGeometry()
                offset = 24 * (len(self._widgets) - 1)
                widget.move(
                    bounds.right() - widget.width() - 32 - offset,
                    bounds.top() + 32 + offset,
                )
                self._save_position(reminder.reminder_id, widget.pos())
        else:
            widget.move(reminder.x, reminder.y)
            if not any(
                screen.availableGeometry().intersects(widget.frameGeometry())
                for screen in QApplication.screens()
            ):
                screen = QApplication.primaryScreen()
                if screen is not None:
                    bounds = screen.availableGeometry()
                    widget.move(bounds.right() - widget.width() - 32, bounds.top() + 32)
                    self._save_position(reminder.reminder_id, widget.pos())
        self._refresh_desktop_layer()

    def _refresh_desktop_layer(self) -> None:
        for widget in self._widgets.values():
            if not widget.isVisible():
                widget.show()
            if self._tool_settings.always_on_top:
                continue
            if not widget.is_dragging:
                widget.lower()
                self._bottom_window_handler(int(widget.winId()))

    def _toggle_display_mode(self) -> None:
        enabled = not self._tool_settings.always_on_top
        self._tool_settings = DesktopToolSettings(always_on_top=enabled)
        self._launcher.set_always_on_top_mode(enabled)
        try:
            save_desktop_tool_settings(self._tool_settings)
        except OSError:
            pass
        for widget in self._widgets.values():
            widget.set_always_on_top(enabled)
        self._refresh_desktop_layer()

    def _replace(self, reminder_id: str, **changes) -> ReminderSettings | None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return None
        updated = replace(reminder, **changes)
        self._reminders[reminder_id] = updated
        self._persist()
        return updated

    def _toggle_completed(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return
        updated = self._replace(reminder_id, completed=not reminder.completed)
        if updated is not None:
            self._widget_for(reminder_id).set_settings(updated)

    def _save_position(self, reminder_id: str, position: QPoint) -> None:
        self._replace(reminder_id, x=position.x(), y=position.y())

    def _save_text_size(self, reminder_id: str, size: QSize) -> None:
        self._replace(
            reminder_id,
            font_size=max(10, min(96, round(size.height() / 3))),
            text_width=size.width(),
            text_height=size.height(),
        )

    def _save_image_size(self, reminder_id: str, size: QSize) -> None:
        self._replace(
            reminder_id,
            image_width=size.width(),
            image_height=size.height(),
        )

    def _start_stopwatch(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if (
            reminder is None
            or reminder.kind != "stopwatch"
            or reminder.stopwatch_running
        ):
            return
        updated = self._replace(
            reminder_id,
            stopwatch_started_at=datetime.now().replace(microsecond=0).isoformat(),
            stopwatch_running=True,
        )
        if updated is not None:
            self._widget_for(reminder_id).set_settings(updated)

    def _toggle_stopwatch(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None or reminder.kind != "stopwatch":
            return
        if reminder.stopwatch_running:
            started = _parse_datetime(reminder.stopwatch_started_at)
            added = max(0, int((datetime.now() - started).total_seconds())) if started else 0
            updated = self._replace(
                reminder_id,
                stopwatch_elapsed=reminder.stopwatch_elapsed + added,
                stopwatch_started_at="",
                stopwatch_running=False,
            )
        else:
            updated = self._replace(
                reminder_id,
                stopwatch_started_at=datetime.now().replace(microsecond=0).isoformat(),
                stopwatch_running=True,
            )
        if updated is not None:
            self._widget_for(reminder_id).set_settings(updated)

    def _reset_stopwatch(self, reminder_id: str) -> None:
        updated = self._replace(
            reminder_id,
            stopwatch_elapsed=0,
            stopwatch_started_at="",
            stopwatch_running=False,
        )
        if updated is not None:
            self._widget_for(reminder_id).set_settings(updated)

    def _start_countdown(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if (
            reminder is None
            or reminder.kind != "countdown"
            or reminder.countdown_running
        ):
            return
        remaining = reminder.countdown_remaining or reminder.countdown_seconds
        if remaining <= 0:
            return
        updated = self._replace(
            reminder_id,
            countdown_remaining=remaining,
            countdown_running=True,
            target_at=(datetime.now() + timedelta(seconds=remaining)).replace(
                microsecond=0
            ).isoformat(),
            alarm_fired=False,
        )
        if updated is not None:
            self._widget_for(reminder_id).set_settings(updated)

    def _toggle_countdown(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None or reminder.kind != "countdown":
            return
        if not reminder.countdown_running:
            self._start_countdown(reminder_id)
            return
        target = _parse_datetime(reminder.target_at)
        remaining = (
            max(0, math.ceil((target - datetime.now()).total_seconds()))
            if target is not None
            else reminder.countdown_remaining
        )
        updated = self._replace(
            reminder_id,
            countdown_remaining=remaining,
            countdown_running=False,
            target_at="",
        )
        if updated is not None:
            self._widget_for(reminder_id).set_settings(updated)

    def _reset_countdown(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None or reminder.kind != "countdown":
            return
        self.stop_alarm(reminder_id)
        updated = self._replace(
            reminder_id,
            countdown_remaining=reminder.countdown_seconds,
            countdown_running=False,
            target_at="",
            alarm_fired=False,
        )
        if updated is not None:
            self._widget_for(reminder_id).set_settings(updated)

    def _delete(self, reminder_id: str) -> None:
        widget = self._widgets.get(reminder_id)
        answer = QMessageBox.question(
            widget,
            APP_DISPLAY_NAME,
            "确定删除这个桌面项目吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._ringing_id == reminder_id:
            self.stop_alarm(reminder_id)
        if widget is not None:
            widget.close()
            widget.deleteLater()
            self._widgets.pop(reminder_id, None)
        self._reminders.pop(reminder_id, None)
        self._persist()

    def _alarm_due(self, reminder_id: str) -> None:
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return
        changes = {"alarm_fired": True}
        if reminder.kind == "countdown":
            changes.update(
                countdown_remaining=0,
                countdown_running=False,
                target_at="",
            )
        updated = self._replace(reminder_id, **changes)
        if updated is None:
            return
        self._widget_for(reminder_id).set_settings(updated)
        self._start_alarm(reminder_id)
        self._alert.show_reminder(updated)

    def _start_alarm(self, reminder_id: str) -> None:
        self.stop_alarm()
        reminder = self._reminders.get(reminder_id)
        if reminder is None:
            return
        source = reminder.sound_path
        if not source or not Path(source).is_file():
            try:
                source = ensure_default_alarm_sound()
            except OSError:
                source = ""
        self._alarm_playing = True
        self._ringing_id = reminder_id
        if source:
            self._player.setSource(QUrl.fromLocalFile(source))
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
            self._player.play()
        else:
            QApplication.beep()
            self._fallback_timer.start()

    def stop_alarm(self, reminder_id: str = "") -> None:
        if reminder_id and self._ringing_id and reminder_id != self._ringing_id:
            return
        self._alarm_playing = False
        self._ringing_id = ""
        self._player.stop()
        self._fallback_timer.stop()
        self._alert.hide()

    def _dismiss_alert(self) -> None:
        self.stop_alarm()

    def _media_error(self, _error, _message: str) -> None:
        if not self._alarm_playing or self._fallback_timer.isActive():
            return
        QApplication.beep()
        self._fallback_timer.start()

    def _persist(self) -> None:
        try:
            save_reminders(list(self._reminders.values()))
        except OSError:
            pass

    def shutdown(self) -> None:
        self._desktop_layer_timer.stop()
        self.stop_alarm()
        self._launcher.close()
        self._alert.close()
        for widget in self._widgets.values():
            widget.close()
