"""Tests for reminder card appearance, countdown, and completion state."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from app.reminder_preferences import DesktopToolSettings, ReminderSettings, new_reminder
from ui import reminder_widget
from ui.reminder_widget import (
    DesktopReminderManager,
    DesktopReminderWidget,
    ReminderAlertDialog,
    ReminderEditorDialog,
    ReminderLauncher,
    _format_remaining,
)


def test_countdown_formatter_supports_hours_and_days() -> None:
    assert _format_remaining(65) == "00:01:05"
    assert _format_remaining(90061) == "1天 01:01:01"


def test_text_sticker_shows_text_and_status_without_image(tmp_path) -> None:
    _application = QApplication.instance() or QApplication([])
    image = tmp_path / "tiny.png"
    from PySide6.QtGui import QImage

    QImage(20, 10, QImage.Format.Format_ARGB32).save(str(image))
    widget = DesktopReminderWidget()
    widget.set_settings(
            ReminderSettings(
                kind="text",
                enabled=True,
            text="重要会议",
            image_path=str(image),
            text_width=400,
            text_height=108,
            image_width=320,
            image_height=180,
            text_color="#22aa55",
            show_status=True,
            completed=False,
            )
    )

    assert widget._status_label.text() == "● 未完成"
    assert widget._text_label.text() == "重要会议"
    assert "font-size: 36px" in widget._text_label.styleSheet()
    assert widget._text_item.size().width() == 400
    assert widget._image_item.isHidden()
    widget.close()


def test_image_sticker_is_independent_from_text(tmp_path) -> None:
    _application = QApplication.instance() or QApplication([])
    image = tmp_path / "tiny.png"
    from PySide6.QtGui import QImage

    QImage(20, 10, QImage.Format.Format_ARGB32).save(str(image))
    widget = DesktopReminderWidget()
    widget.set_settings(
        ReminderSettings(
            kind="image",
            enabled=True,
            image_path=str(image),
            image_width=320,
            image_height=180,
        )
    )

    assert not widget._image_label.pixmap().isNull()
    assert widget._image_item.size() == QSize(320, 165)
    assert (widget._image_item.width() - 10) == 2 * (widget._image_item.height() - 10)
    assert widget._text_item.isHidden()
    widget.close()


def test_resize_box_is_hidden_until_sticker_is_selected() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    widget.set_settings(ReminderSettings(kind="text", enabled=True, text="无需边框"))

    assert not widget._text_item.selected
    assert not widget._text_item._handle.isVisible()

    widget._select_item(widget._text_item)
    assert widget._text_item.selected
    assert not widget._text_item._handle.isHidden()

    QApplication.sendEvent(widget, QEvent(QEvent.Type.WindowDeactivate))
    assert not widget._text_item.selected
    assert widget._text_item._handle.isHidden()
    widget.close()


def test_desktop_launcher_matches_f1_button_size_and_uses_larger_font() -> None:
    _application = QApplication.instance() or QApplication([])
    launcher = ReminderLauncher()

    assert set(launcher.buttons) == {
        "text",
        "image",
        "alarm",
        "stopwatch",
        "countdown",
        "sleep",
        "calculator",
    }
    assert [button.text() for button in launcher.buttons.values()] == [
        "贴文字",
        "贴图片",
        "闹钟",
        "计时器",
        "倒计时",
        "睡眠",
        "计算器",
    ]
    assert launcher.drag_handle.text() == "移动"
    assert launcher.display_mode_button.text() == "桌面"
    assert launcher.exit_button.text() == "退出"
    assert "min-width: 48px" in launcher.styleSheet()
    assert "min-height: 32px" in launcher.styleSheet()
    assert "font-size: 13px" in launcher.styleSheet()
    launcher.close()


def test_desktop_launcher_display_mode_label_tracks_current_mode() -> None:
    _application = QApplication.instance() or QApplication([])
    launcher = ReminderLauncher()

    launcher.set_always_on_top_mode(True)
    assert launcher.display_mode_button.text() == "置顶"
    launcher.set_always_on_top_mode(False)
    assert launcher.display_mode_button.text() == "桌面"
    launcher.close()


def test_desktop_launcher_closes_with_escape() -> None:
    application = QApplication.instance() or QApplication([])
    launcher = ReminderLauncher()
    launcher.show_launcher()
    application.processEvents()

    QTest.keyClick(launcher, Qt.Key.Key_Escape)
    application.processEvents()

    assert not launcher.isVisible()
    launcher.close()


def test_desktop_launcher_exit_button_only_closes_launcher() -> None:
    application = QApplication.instance() or QApplication([])
    launcher = ReminderLauncher()
    launcher.show_launcher()
    application.processEvents()

    launcher.exit_button.click()
    application.processEvents()

    assert not launcher.isVisible()
    launcher.close()


def test_desktop_shortcut_toggles_launcher(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda _items: None)
    manager = DesktopReminderManager()

    manager.open_launcher()
    application.processEvents()
    assert manager.launcher.isVisible()

    manager.open_launcher()
    application.processEvents()
    assert not manager.launcher.isVisible()
    manager.shutdown()


def test_desktop_launcher_drag_handle_moves_and_remembers_position() -> None:
    application = QApplication.instance() or QApplication([])
    launcher = ReminderLauncher()
    launcher.show_launcher()
    application.processEvents()
    initial = QPoint(launcher.pos())
    handle = launcher.drag_handle

    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=QPoint(12, 12))
    QTest.mouseMove(handle, QPoint(82, 52))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=QPoint(82, 52))
    application.processEvents()

    moved = QPoint(launcher.pos())
    assert moved != initial
    launcher.hide()
    launcher.show_launcher()
    application.processEvents()
    assert launcher.pos() == moved
    launcher.close()


def test_stopwatch_counts_up_separately_from_countdown() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    widget.set_settings(
        ReminderSettings(
            kind="stopwatch",
            enabled=True,
            stopwatch_elapsed=65,
            stopwatch_running=False,
        )
    )

    assert widget._timer_label.text() == "正计时：00:01:05  已暂停"
    assert widget._title_label.text() == "计时器"
    widget.close()


def test_stopwatch_window_has_start_pause_reset_and_cancel_buttons() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    start_spy = QSignalSpy(widget.stopwatch_start_requested)
    toggle_spy = QSignalSpy(widget.stopwatch_toggle_requested)
    reset_spy = QSignalSpy(widget.stopwatch_reset_requested)
    cancel_spy = QSignalSpy(widget.delete_requested)
    widget.set_settings(
        ReminderSettings(kind="stopwatch", stopwatch_running=False)
    )

    assert widget._stopwatch_start_button.text() == "开始"
    assert widget._stopwatch_toggle_button.text() == "继续"
    assert widget._stopwatch_reset_button.text() == "重置"
    assert widget._stopwatch_cancel_button.text() == "取消"
    widget._stopwatch_start_button.click()
    widget.set_settings(
        ReminderSettings(kind="stopwatch", stopwatch_running=True)
    )
    widget._stopwatch_toggle_button.click()
    widget._stopwatch_reset_button.click()
    widget._stopwatch_cancel_button.click()

    assert start_spy.count() == 1
    assert toggle_spy.count() == 1
    assert reset_spy.count() == 1
    assert cancel_spy.count() == 1
    widget.close()


def test_countdown_has_timer_controls_plus_modify_button() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    edit_spy = QSignalSpy(widget.edit_requested)
    start_spy = QSignalSpy(widget.countdown_start_requested)
    toggle_spy = QSignalSpy(widget.countdown_toggle_requested)
    reset_spy = QSignalSpy(widget.countdown_reset_requested)
    cancel_spy = QSignalSpy(widget.delete_requested)
    widget.set_settings(
        ReminderSettings(
            kind="countdown",
            schedule_mode="countdown",
            countdown_seconds=60,
            countdown_remaining=60,
            countdown_running=False,
        )
    )

    assert not widget._stopwatch_start_button.isHidden()
    assert not widget._stopwatch_toggle_button.isHidden()
    assert not widget._stopwatch_reset_button.isHidden()
    assert not widget._stopwatch_cancel_button.isHidden()
    assert not widget._countdown_edit_button.isHidden()
    widget._stopwatch_start_button.click()
    widget.set_settings(
        ReminderSettings(
            kind="countdown",
            schedule_mode="countdown",
            countdown_seconds=60,
            countdown_remaining=59,
            countdown_running=True,
            target_at=(datetime.now() + timedelta(seconds=59)).isoformat(),
        )
    )
    widget._stopwatch_toggle_button.click()
    widget._stopwatch_reset_button.click()
    widget._stopwatch_cancel_button.click()
    widget._countdown_edit_button.click()
    assert start_spy.count() == 1
    assert toggle_spy.count() == 1
    assert reset_spy.count() == 1
    assert cancel_spy.count() == 1
    assert edit_spy.count() == 1
    widget.close()


def test_new_countdown_waits_for_start_button() -> None:
    _application = QApplication.instance() or QApplication([])
    dialog = ReminderEditorDialog(new_reminder("countdown"))
    dialog._countdown_seconds.setValue(30)

    dialog._save()

    settings = dialog.result_settings
    assert settings.countdown_seconds == 30
    assert settings.countdown_remaining == 30
    assert not settings.countdown_running
    assert not settings.target_at


def test_desktop_card_is_not_always_on_top() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()

    assert not widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    widget.close()


def test_manager_keeps_cards_visible_at_desktop_bottom_layer(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda _items: None)
    lowered: list[int] = []
    manager = DesktopReminderManager(
        bottom_window_handler=lambda handle: not lowered.append(handle),
    )
    settings = ReminderSettings(
        reminder_id="desktop-only-test",
        kind="text",
        enabled=True,
        text="只在桌面显示",
    )
    manager._reminders[settings.reminder_id] = settings
    manager._show_widget(settings)
    application.processEvents()
    widget = manager._widgets[settings.reminder_id]

    assert widget.isVisible()
    assert lowered
    manager._refresh_desktop_layer()
    assert widget.isVisible()
    manager.shutdown()


def test_manager_toggles_all_cards_to_topmost_and_persists(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(
        reminder_widget,
        "load_desktop_tool_settings",
        lambda: DesktopToolSettings(always_on_top=False),
    )
    saved: list[DesktopToolSettings] = []
    monkeypatch.setattr(
        reminder_widget,
        "save_desktop_tool_settings",
        saved.append,
    )
    manager = DesktopReminderManager()
    settings = ReminderSettings(
        reminder_id="topmost-test",
        kind="text",
        enabled=True,
        text="始终显示",
    )
    manager._reminders[settings.reminder_id] = settings
    manager._show_widget(settings)
    application.processEvents()

    manager._toggle_display_mode()

    widget = manager._widgets[settings.reminder_id]
    assert widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert manager.launcher.display_mode_button.text() == "置顶"
    assert saved == [DesktopToolSettings(always_on_top=True)]

    manager._toggle_display_mode()
    assert not widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert manager.launcher.display_mode_button.text() == "桌面"
    manager.shutdown()


def test_launcher_calculator_action_uses_injected_handler(monkeypatch) -> None:
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    calls: list[str] = []
    manager = DesktopReminderManager(
        calculator_handler=lambda: not calls.append("calculator")
    )

    manager._create_action("calculator")

    assert calls == ["calculator"]
    manager.shutdown()


def test_launcher_sleep_action_requires_confirmation(monkeypatch) -> None:
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(
        reminder_widget.QMessageBox,
        "question",
        lambda *args, **kwargs: reminder_widget.QMessageBox.StandardButton.Yes,
    )
    calls: list[str] = []
    manager = DesktopReminderManager(
        sleep_handler=lambda: not calls.append("sleep")
    )

    manager._create_action("sleep")

    assert calls == ["sleep"]
    manager.shutdown()


def test_due_alert_uses_a_separate_topmost_window() -> None:
    _application = QApplication.instance() or QApplication([])
    alert = ReminderAlertDialog()
    alert.show_reminder(
        ReminderSettings(kind="countdown", text="休息一下")
    )

    assert alert.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert alert._title_label.text() == "⏰ 倒计时结束"
    assert alert._message_label.text() == "休息一下"
    alert.close()


def test_manager_stopwatch_start_pause_and_reset_are_persisted(monkeypatch) -> None:
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda _items: None)
    manager = DesktopReminderManager()
    settings = ReminderSettings(
        reminder_id="stopwatch-control-test",
        kind="stopwatch",
        enabled=True,
    )
    manager._reminders[settings.reminder_id] = settings

    manager._start_stopwatch(settings.reminder_id)
    assert manager._reminders[settings.reminder_id].stopwatch_running
    manager._toggle_stopwatch(settings.reminder_id)
    assert not manager._reminders[settings.reminder_id].stopwatch_running
    manager._reset_stopwatch(settings.reminder_id)
    reset = manager._reminders[settings.reminder_id]
    assert reset.stopwatch_elapsed == 0
    assert not reset.stopwatch_running
    manager.shutdown()


def test_manager_keeps_card_at_bottom_when_topmost_alert_appears(
    monkeypatch,
) -> None:
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda _items: None)
    manager = DesktopReminderManager()
    settings = ReminderSettings(
        reminder_id="alert-layer-test",
        kind="countdown",
        enabled=True,
        text="倒计时完成",
        schedule_mode="countdown",
        countdown_seconds=60,
        countdown_remaining=60,
    )
    manager._reminders[settings.reminder_id] = settings
    manager._show_widget(settings)
    monkeypatch.setattr(manager, "_start_alarm", lambda _reminder_id: None)

    manager._alarm_due(settings.reminder_id)

    assert manager._widgets[settings.reminder_id].isVisible()
    assert manager._alert.isVisible()
    assert manager._alert.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    manager.shutdown()


def test_manager_countdown_start_pause_reset_are_persisted(monkeypatch) -> None:
    _application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda _items: None)
    manager = DesktopReminderManager()
    settings = ReminderSettings(
        reminder_id="countdown-control-test",
        kind="countdown",
        enabled=True,
        schedule_mode="countdown",
        countdown_seconds=120,
        countdown_remaining=120,
    )
    manager._reminders[settings.reminder_id] = settings

    manager._start_countdown(settings.reminder_id)
    running = manager._reminders[settings.reminder_id]
    assert running.countdown_running
    assert running.target_at
    manager._toggle_countdown(settings.reminder_id)
    paused = manager._reminders[settings.reminder_id]
    assert not paused.countdown_running
    assert paused.countdown_remaining > 0
    assert not paused.target_at
    manager._reset_countdown(settings.reminder_id)
    reset = manager._reminders[settings.reminder_id]
    assert reset.countdown_remaining == 120
    assert not reset.countdown_running
    manager.shutdown()


def test_drag_resizing_text_box_changes_real_font_size() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    widget.set_settings(ReminderSettings(enabled=True, text="缩放文字"))

    widget._text_item.set_item_size(440, 180)

    assert widget._text_item.derived_font_size == 60
    assert "font-size: 60px" in widget._text_label.styleSheet()
    widget.close()


def test_resize_handle_emits_new_persistable_box_size() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    widget.set_settings(ReminderSettings(enabled=True, text="拖动缩放"))
    spy = QSignalSpy(widget.text_size_changed)

    widget._text_item._begin_resize()
    widget._text_item._resize_by(QPoint(50, 30))
    widget._text_item._handle.drag_finished.emit()

    assert widget._text_item.size().width() == 410
    assert widget._text_item.size().height() < 120
    assert widget._text_item.derived_font_size == 40
    assert spy.count() == 1
    assert spy.at(0)[0] == QSize(410, 120)
    widget.close()


def test_image_resize_can_use_almost_a_complete_monitor(monkeypatch) -> None:
    _application = QApplication.instance() or QApplication([])
    from PySide6.QtGui import QPixmap

    widget = DesktopReminderWidget()
    item = widget._image_item
    monkeypatch.setattr(item, "maximum_item_size", lambda: QSize(1880, 990))
    pixmap = QPixmap(1600, 900)
    pixmap.fill(Qt.GlobalColor.blue)
    item.set_image_content(pixmap)

    item.set_item_size(1880, 990)

    assert item.width() > 1700
    assert item.height() > 950
    assert item.width() <= 1880
    assert item.height() <= 990
    widget.close()


def test_text_frame_tracks_rendered_text_instead_of_scale_height() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    widget.set_settings(
        ReminderSettings(
            kind="text",
            enabled=True,
            text="紧贴文字",
            text_width=500,
            text_height=180,
        )
    )

    assert widget._text_item.derived_font_size == 60
    assert widget._text_item.height() < 100
    assert widget._text_item.height() >= widget._text_label.fontMetrics().height()
    widget.close()


def test_due_reminder_emits_alarm_only_once() -> None:
    _application = QApplication.instance() or QApplication([])
    widget = DesktopReminderWidget()
    spy = QSignalSpy(widget.alarm_due)
    widget.set_settings(
        ReminderSettings(
            kind="alarm",
            enabled=True,
            text="时间到",
            schedule_mode="alarm",
            target_at=(datetime.now() - timedelta(seconds=1)).isoformat(),
        )
    )

    widget._update_time()
    widget._update_time()

    assert spy.count() == 1
    assert "提醒时间到" in widget._timer_label.text()
    widget.close()
