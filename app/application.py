"""Application startup and lifetime wiring."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from app import autostart
from app.branding import APP_DISPLAY_NAME
from app.hotkeys import GlobalHotkey
from app.icon import application_icon
from app.preferences import HotkeySettings, load_hotkey_settings, save_hotkey_settings
from app.presentation_hotkeys import PresentationHotkeys
from app.qt_translation import install_chinese_translation
from app.system_actions import put_computer_to_sleep, toggle_calculator
from app.tray import ApplicationTray
from core.capture.capture_service import CaptureService
from ui.main_window import MainWindow
from ui.reminder_widget import DesktopReminderManager


def _repair_startup_settings(settings: HotkeySettings) -> HotkeySettings:
    """Replace invalid persisted shortcuts before native filters are created."""
    try:
        global_bindings = GlobalHotkey._parse_bindings(
            settings.normal_capture,
            settings.long_capture,
            settings.presentation_mode,
            settings.reminder,
            settings.calculator,
            settings.sleep,
        )
        presentation_bindings = PresentationHotkeys._parse_settings(
            settings.presentation_tools
        )
    except ValueError:
        return HotkeySettings()

    global_signatures = {
        (binding.modifiers, binding.virtual_key)
        for binding in global_bindings.values()
        if binding.sequence
    }
    presentation_signatures = {
        (binding.modifiers, binding.virtual_key)
        for _action, binding in presentation_bindings.values()
    }
    if global_signatures & presentation_signatures:
        return HotkeySettings()
    return settings


def run() -> None:
    """Start the application with its tray icon and configurable global shortcuts."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setQuitOnLastWindowClosed(False)
    install_chinese_translation(app)
    icon = application_icon()
    app.setWindowIcon(icon)
    autostart.refresh_registration()

    loaded_settings = load_hotkey_settings()
    settings = _repair_startup_settings(loaded_settings)
    if settings != loaded_settings:
        try:
            save_hotkey_settings(settings)
        except OSError:
            pass
    current_settings = settings
    capture_service = CaptureService()
    reminder_manager = DesktopReminderManager()
    capture_service.configure_presentation_shortcuts(settings.presentation_tools)

    def toggle_calculator_from_hotkey() -> None:
        """Toggle Windows Calculator without blocking the native event filter."""
        if not toggle_calculator():
            tray.show_warning("无法打开或关闭计算器。")

    def sleep_from_hotkey() -> None:
        """Enter sleep immediately; the dedicated shortcut is an explicit action."""
        if not put_computer_to_sleep():
            tray.show_warning("电脑未能进入睡眠，请检查 Windows 电源设置。")

    hotkeys = GlobalHotkey(
        capture_service.start_capture,
        capture_service.start_long_capture,
        capture_service.toggle_presentation,
        settings.normal_capture,
        settings.long_capture,
        settings.presentation_mode,
        reminder_callback=reminder_manager.open_launcher,
        reminder_shortcut=settings.reminder,
        calculator_callback=toggle_calculator_from_hotkey,
        calculator_shortcut=settings.calculator,
        sleep_callback=sleep_from_hotkey,
        sleep_shortcut=settings.sleep,
    )
    presentation_hotkeys = PresentationHotkeys(
        capture_service.execute_presentation_shortcut
    )
    presentation_hotkeys.configure(settings.presentation_tools)

    def apply_hotkeys(updated: HotkeySettings) -> bool:
        """Register, persist, and display replacement screenshot shortcuts."""
        nonlocal current_settings
        if not hotkeys.reconfigure(
            updated.normal_capture,
            updated.long_capture,
            updated.presentation_mode,
            updated.reminder,
            updated.calculator,
            updated.sleep,
        ):
            return False
        if (
            not presentation_hotkeys.configure(updated.presentation_tools)
            or not presentation_hotkeys.check_availability()
        ):
            hotkeys.reconfigure(
                current_settings.normal_capture,
                current_settings.long_capture,
                current_settings.presentation_mode,
                current_settings.reminder,
                current_settings.calculator,
                current_settings.sleep,
            )
            presentation_hotkeys.configure(current_settings.presentation_tools)
            return False
        current_settings = updated
        capture_service.configure_presentation_shortcuts(updated.presentation_tools)
        save_hotkey_settings(updated)
        window.set_hotkey_status(updated, hotkeys.registration)
        tray.show_ready_message(
            updated,
            hotkeys.registration,
        )
        return True

    window = MainWindow(
        capture_service,
        apply_hotkeys,
        reminder_callback=reminder_manager.open_launcher,
        hotkey_suspend_handler=hotkeys.suspend,
        hotkey_resume_handler=hotkeys.resume,
    )
    window.setWindowIcon(icon)
    tray = ApplicationTray(
        window,
        app.quit,
        window.open_hotkey_dialog,
        window.open_translation_settings,
        autostart.is_enabled(),
        autostart.set_enabled,
        reminder_callback=reminder_manager.open_launcher,
    )
    app.installNativeEventFilter(hotkeys)
    app.installNativeEventFilter(presentation_hotkeys)

    presentation_hotkey_warning_shown = False
    presentation_action_names = {
        "pointer_brush_toggle": "鼠标/画笔切换",
        "brush": "画笔",
        "line": "直线",
        "rectangle": "方框",
        "ellipse": "圆形",
        "arrow": "箭头",
        "text": "文字",
        "eraser": "橡皮擦",
        "clear": "清除全部",
        "undo": "撤销",
        "redo": "恢复",
    }

    def set_presentation_hotkeys_active(active: bool) -> None:
        nonlocal presentation_hotkey_warning_shown
        if not active:
            presentation_hotkeys.set_active(False)
            presentation_hotkey_warning_shown = False
            return
        if (
            not presentation_hotkeys.set_active(True)
            and not presentation_hotkey_warning_shown
        ):
            presentation_hotkey_warning_shown = True
            unavailable = "、".join(
                presentation_action_names.get(action, action)
                for action in presentation_hotkeys.failed_actions
            )
            tray.show_warning(
                f"教鞭已启动，但这些工具快捷键暂不可用：{unavailable or '未知'}。"
                "仍可使用鼠标工具栏，或在“修改快捷键”中更换。"
            )
            QTimer.singleShot(0, capture_service.restore_presentation_toolbar)

    capture_service.presentation_active_changed.connect(
        set_presentation_hotkeys_active
    )

    registered = hotkeys.register()
    window.set_hotkey_status(settings, registered)
    reminder_manager.restore()

    app.aboutToQuit.connect(hotkeys.unregister)
    app.aboutToQuit.connect(presentation_hotkeys.unregister)
    app.aboutToQuit.connect(reminder_manager.shutdown)
    app.aboutToQuit.connect(lambda: app.removeNativeEventFilter(hotkeys))
    app.aboutToQuit.connect(lambda: app.removeNativeEventFilter(presentation_hotkeys))
    tray.show()
    tray.show_ready_message(
        settings,
        registered,
    )
    sys.exit(app.exec())
