"""Windows system-tray integration for the background AIShot application."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QMainWindow, QMenu, QStyle, QSystemTrayIcon

from app.branding import APP_DISPLAY_NAME
from app.preferences import HotkeySettings

class ApplicationTray(QSystemTrayIcon):
    """Keeps AIShot available in the Windows notification area."""

    def __init__(
        self,
        window: QMainWindow,
        quit_callback: Callable[[], None],
        edit_hotkeys_callback: Callable[[], None],
        edit_translation_callback: Callable[[], None],
        autostart_enabled: bool,
        set_autostart_enabled: Callable[[bool], bool],
        reminder_callback: Callable[[], None] | None = None,
    ) -> None:
        icon = window.windowIcon()
        if icon.isNull():
            icon = window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        super().__init__(icon, window)
        self._window = window
        self._set_autostart_enabled = set_autostart_enabled

        menu = QMenu(window)
        show_action = menu.addAction(f"显示 {APP_DISPLAY_NAME}")
        show_action.triggered.connect(self._show_window)
        hotkey_action = menu.addAction("修改快捷键")
        hotkey_action.triggered.connect(edit_hotkeys_callback)
        if reminder_callback is not None:
            reminder_action = menu.addAction("桌面提醒")
            reminder_action.triggered.connect(reminder_callback)
        translation_action = menu.addAction("翻译 API 设置")
        translation_action.triggered.connect(edit_translation_callback)
        self._autostart_action = menu.addAction("开机自启动")
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(autostart_enabled)
        self._autostart_action.toggled.connect(self._change_autostart)
        menu.addSeparator()
        exit_action = menu.addAction("退出")
        exit_action.triggered.connect(quit_callback)
        self.setContextMenu(menu)
        self.activated.connect(self._handle_activation)
        self.setToolTip(APP_DISPLAY_NAME)

    def show_ready_message(
        self,
        settings: HotkeySettings,
        hotkeys: dict[str, bool],
    ) -> None:
        """Confirm background readiness without opening a normal window."""
        normal = "已就绪" if hotkeys.get("normal") else "注册失败"
        long_capture = "已就绪" if hotkeys.get("long") else "注册失败"
        presentation = (
            "已就绪"
            if hotkeys.get("presentation")
            else "未设置"
            if not settings.presentation_mode
            else "注册失败"
        )
        reminder = "已就绪" if hotkeys.get("reminder") else "注册失败"
        calculator = (
            "已就绪"
            if hotkeys.get("calculator")
            else "未设置"
            if not settings.calculator
            else "注册失败"
        )
        sleep = (
            "已就绪"
            if hotkeys.get("sleep")
            else "未设置"
            if not settings.sleep
            else "注册失败"
        )
        details = (
            f"{settings.normal_capture} 截图：{normal}\n"
            f"{settings.long_capture} 纵向长截图：{long_capture}\n"
            f"{settings.presentation_mode or '未设置'} 教鞭模式：{presentation}\n"
            f"{settings.reminder} 桌面提醒：{reminder}\n"
            f"{settings.calculator or '未设置'} 计算器开关：{calculator}\n"
            f"{settings.sleep or '未设置'} 计算机睡眠：{sleep}"
        )
        self.showMessage(
            f"{APP_DISPLAY_NAME} 已在后台运行",
            details,
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def show_warning(self, message: str) -> None:
        """Show a non-blocking warning that cannot be covered by desktop overlays."""
        self.showMessage(
            APP_DISPLAY_NAME,
            message,
            QSystemTrayIcon.MessageIcon.Warning,
            6000,
        )

    def _handle_activation(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Open the optional status window on a tray-icon click."""
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._show_window()

    def _show_window(self) -> None:
        """Restore the small status window when requested from the tray."""
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _change_autostart(self, enabled: bool) -> None:
        """Persist the tray's startup choice and restore it if Windows rejects the change."""
        if self._set_autostart_enabled(enabled):
            return
        self._autostart_action.blockSignals(True)
        self._autostart_action.setChecked(not enabled)
        self._autostart_action.blockSignals(False)
        self.showMessage(
            APP_DISPLAY_NAME,
            "无法修改开机自启动设置。",
            QSystemTrayIcon.MessageIcon.Warning,
            4000,
        )
