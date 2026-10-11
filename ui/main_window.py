"""AIShot's small launcher window."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app.branding import APP_DISPLAY_NAME, PRODUCT_NAME
from app.display_diagnostics import collect_display_diagnostics
from app.preferences import HotkeySettings
from core.capture.capture_service import CaptureService
from ui.hotkey_dialog import HotkeyDialog
from ui.translation_settings_dialog import TranslationSettingsDialog
from ui.window_position import center_on_cursor_screen


class MainWindow(QMainWindow):
    """Provides a visible launcher while global shortcuts remain active."""

    def __init__(
        self,
        capture_service: CaptureService,
        hotkey_change_handler: Callable[[HotkeySettings], bool],
        reminder_callback: Callable[[], None] | None = None,
        hotkey_suspend_handler: Callable[[], None] | None = None,
        hotkey_resume_handler: Callable[[], dict[str, bool]] | None = None,
    ) -> None:
        super().__init__()
        self._capture_service = capture_service
        self._hotkey_change_handler = hotkey_change_handler
        self._hotkey_suspend_handler = hotkey_suspend_handler
        self._hotkey_resume_handler = hotkey_resume_handler
        self._hotkey_settings = HotkeySettings()
        self._capture_service.capture_failed.connect(self._show_capture_error)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setFixedSize(480, 720)

        self._status_label = QLabel("正在初始化截图服务…")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        capture_button = QPushButton("普通截图")
        long_capture_button = QPushButton("长截图")
        presentation_button = QPushButton("教鞭模式")
        reminder_button = QPushButton("桌面提醒")
        hotkey_button = QPushButton("修改快捷键")
        translation_settings_button = QPushButton("翻译 API 设置")
        diagnostics_button = QPushButton("复制显示器诊断信息")
        capture_button.clicked.connect(self._capture_service.start_capture)
        long_capture_button.clicked.connect(self._capture_service.start_long_capture)
        presentation_button.clicked.connect(self._capture_service.toggle_presentation)
        if reminder_callback is not None:
            reminder_button.clicked.connect(reminder_callback)
        else:
            reminder_button.setEnabled(False)
        hotkey_button.clicked.connect(self.open_hotkey_dialog)
        translation_settings_button.clicked.connect(self.open_translation_settings)
        diagnostics_button.clicked.connect(self.copy_display_diagnostics)
        pin_help = QLabel(
            "贴图说明：截图后点击“贴图”；鼠标拖动移动，每次按 1 旋转 90°，"
            "Ctrl + 鼠标中键滚动调透明度，双击或按 Esc 关闭。"
        )
        pin_help.setWordWrap(True)
        translation_help = QLabel(
            "翻译说明：支持有道、DeepL、OpenAI、Google Cloud 和 Microsoft Translator；"
            "点击“翻译 API 设置”选择服务并填写对应密钥。"
        )
        translation_help.setWordWrap(True)
        long_capture_help = QLabel(
            "长截图说明：按 F2 后只框选需要的内容区域（不要包含固定侧栏）；"
            "单击选区后默认分段自动滚动，画面停稳才会拼接，到底自动完成。"
            "控制条可切换手动模式、暂停、完成或取消；再次按 F2 可提前完成，Esc 取消。"
            "完成后可点击“裁剪”重新保留所需范围。"
        )
        long_capture_help.setWordWrap(True)
        self._presentation_help = QLabel()
        self._presentation_help.setWordWrap(True)
        self._update_presentation_help("")
        reminder_help = QLabel(
            "桌面工具：按 F3 后选择文字贴图、图片贴图、闹钟、计时器或倒计时。"
            "挂件保持在普通窗口底层；其他窗口只遮住重叠区域，未被遮挡的部分仍可看见。"
            "只有按住挂件拖动时才会移动。计时器提供开始、暂停/继续、重置和取消按钮，"
            "倒计时在相同按钮之外还可直接修改。"
            "闹钟和倒计时到点后会弹出最顶层提醒窗，并可使用内置提示音或本机音乐。"
        )
        reminder_help.setWordWrap(True)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.addWidget(
            QLabel(
                APP_DISPLAY_NAME,
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
        )
        layout.addWidget(self._status_label)
        layout.addWidget(capture_button)
        layout.addWidget(long_capture_button)
        layout.addWidget(presentation_button)
        layout.addWidget(reminder_button)
        layout.addWidget(hotkey_button)
        layout.addWidget(translation_settings_button)
        layout.addWidget(diagnostics_button)
        layout.addWidget(translation_help)
        layout.addWidget(long_capture_help)
        layout.addWidget(self._presentation_help)
        layout.addWidget(reminder_help)
        layout.addWidget(pin_help)
        self.setCentralWidget(content)
        center_on_cursor_screen(self)

    def _update_presentation_help(self, shortcut: str) -> None:
        """Keep the help text synchronized with the configured teacher shortcut."""
        shortcut_text = shortcut or "教鞭快捷键"
        self._presentation_help.setText(
            f"教鞭说明：按 {shortcut_text} 进入，可使用画笔、箭头、直线、方框、"
            "实心矩形、圆形、文字和橡皮；工具栏可切换颜色、粗细并可拖动。"
            "右键撤销上一笔，Ctrl+右键恢复刚撤销的一笔，也可使用 Ctrl+Z、"
            "Ctrl+Y 或工具栏按钮。切换“鼠标”可操作下方软件；需要保存画面时"
            f"按 F1 截图。再次按 {shortcut_text} 或点击“退出”关闭；工具快捷键"
            "可在“修改快捷键”中设置。"
        )

    def set_hotkey_status(
        self,
        settings: HotkeySettings,
        registration: dict[str, bool],
    ) -> None:
        """Display active shortcut names and whether Windows registered them."""
        self._hotkey_settings = settings
        self._update_presentation_help(settings.presentation_mode)
        normal_status = "已就绪" if registration.get("normal") else "注册失败"
        long_status = "已就绪" if registration.get("long") else "注册失败"
        presentation_name = settings.presentation_mode or "未设置"
        presentation_status = (
            "已就绪"
            if registration.get("presentation")
            else "未设置"
            if not settings.presentation_mode
            else "注册失败"
        )
        reminder_status = (
            "已就绪" if registration.get("reminder") else "注册失败"
        )
        calculator_name = settings.calculator or "未设置"
        calculator_status = (
            "已就绪"
            if registration.get("calculator")
            else "未设置"
            if not settings.calculator
            else "注册失败"
        )
        sleep_name = settings.sleep or "未设置"
        sleep_status = (
            "已就绪"
            if registration.get("sleep")
            else "未设置"
            if not settings.sleep
            else "注册失败"
        )
        self._status_label.setText(
            f"{settings.normal_capture} 截图：{normal_status}   "
            f"{settings.long_capture} 长截图：{long_status}   "
            f"{presentation_name} 教鞭：{presentation_status}\n"
            f"{settings.reminder} 桌面提醒：{reminder_status}\n"
            f"{calculator_name} 计算器开关：{calculator_status}   "
            f"{sleep_name} 睡眠：{sleep_status}"
        )

    def open_hotkey_dialog(self) -> None:
        """Let the user change both global shortcuts from the launcher or tray."""
        dialog = HotkeyDialog(self._hotkey_settings, self)
        if self._hotkey_suspend_handler is not None:
            self._hotkey_suspend_handler()
        try:
            result = dialog.exec()
        finally:
            if self._hotkey_resume_handler is not None:
                registration = self._hotkey_resume_handler()
                self.set_hotkey_status(self._hotkey_settings, registration)
        if result != HotkeyDialog.DialogCode.Accepted:
            return
        if not self._hotkey_change_handler(dialog.settings):
            QMessageBox.warning(
                self,
                APP_DISPLAY_NAME,
                "快捷键无法注册。请换一个未被其他软件占用的组合。",
            )

    def open_translation_settings(self) -> None:
        """Open the local encrypted translation-provider settings."""
        TranslationSettingsDialog(self).exec()

    def copy_display_diagnostics(self) -> None:
        """Copy diagnostics and save a text file that can be sent for support."""
        diagnostics = collect_display_diagnostics()
        QGuiApplication.clipboard().setText(diagnostics)
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        output_path = Path(desktop or str(Path.home())) / f"{PRODUCT_NAME}_显示器诊断.txt"
        try:
            output_path.write_text(diagnostics, encoding="utf-8")
            detail = f"同时已保存到：\n{output_path}"
        except OSError:
            detail = "诊断信息已复制，但无法自动保存文件。"
        QMessageBox.information(
            self,
            APP_DISPLAY_NAME,
            f"显示器诊断信息已复制，可以直接粘贴发送给开发人员。\n\n{detail}",
        )

    def closeEvent(self, event) -> None:
        """Keep AIShot resident when the optional status window is closed."""
        event.ignore()
        self.hide()

    def _show_capture_error(self, message: str) -> None:
        """Present a recoverable capture error."""
        QMessageBox.warning(self, APP_DISPLAY_NAME, message)
