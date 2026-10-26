"""The launcher window: four tools, settings, log size and usage tips.

Styled like 猛人学习: a dark background, quiet panels with thin borders,
8-10 px corners and the Microsoft YaHei UI font, with the emerald of the
app icon as the accent. The style is set on the central widget only, so the
dialogs this window opens keep their normal look.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app import logs
from app.branding import APP_DISPLAY_NAME, APP_VERSION, PRODUCT_NAME
from app.display_diagnostics import collect_display_diagnostics
from app.icon import application_icon
from app.preferences import HotkeySettings
from core.capture.capture_service import CaptureService
from ui.hotkey_dialog import HotkeyDialog
from ui.translation_settings_dialog import TranslationSettingsDialog
from ui.usage_guide_dialog import UsageGuideDialog
from ui.window_position import center_on_cursor_screen

ACCENT = "#6cc59a"

_STYLE = f"""
#launcher {{ background: #0e0e10; }}
#launcher QLabel {{
    color: #ebe8e1;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}}
QLabel#appTitle {{ font-size: 19px; font-weight: 600; }}
QLabel#version {{ color: #8f8c85; font-size: 12px; }}
QLabel#statusOk {{ color: #4cc38a; font-size: 12px; }}
QLabel#statusWarn {{ color: #ff6b5e; font-size: 12px; }}
QLabel#statusIdle {{ color: #8f8c85; font-size: 12px; }}
QLabel#muted {{ color: #8f8c85; font-size: 12px; }}
QLabel#sectionTitle {{ color: #8f8c85; font-size: 12px; font-weight: 600; }}
QPushButton#launchCard {{
    background: #151518;
    border: 1px solid #2a2a31;
    border-radius: 10px;
    color: transparent;
}}
QPushButton#launchCard:hover {{ background: #1c1c21; border-color: {ACCENT}; }}
QPushButton#launchCard:pressed {{ background: #23232a; }}
QPushButton#launchCard:disabled {{ background: #121214; border-color: #1e1e23; }}
QLabel#cardTitle {{ font-size: 15px; font-weight: 600; }}
QLabel#cardKey {{
    color: #0b1a12;
    background: {ACCENT};
    border-radius: 5px;
    padding: 1px 7px;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#cardKeyOff {{
    color: #8f8c85;
    background: #23232a;
    border-radius: 5px;
    padding: 1px 7px;
    font-size: 12px;
}}
QLabel#cardDesc {{ color: #8f8c85; font-size: 12px; }}
QPushButton#plainButton, QPushButton#smallButton {{
    background: #1c1c21;
    border: 1px solid #2a2a31;
    border-radius: 8px;
    color: #ebe8e1;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
    padding: 0 12px;
    min-height: 32px;
}}
QPushButton#smallButton {{ font-size: 12px; min-height: 26px; padding: 0 10px; }}
QPushButton#plainButton:hover, QPushButton#smallButton:hover {{
    background: #23232a;
    border-color: #8f8c85;
}}
QFrame#panel {{ background: #151518; border: 1px solid #2a2a31; border-radius: 10px; }}
QScrollArea#tipsArea {{ background: transparent; border: none; }}
QWidget#tips {{ background: transparent; }}
QWidget#tips QLabel {{ color: #8f8c85; font-size: 12px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a2a31; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a3a43; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


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
        self.setFixedSize(520, 720)

        content = QWidget()
        content.setObjectName("launcher")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        content.setStyleSheet(_STYLE)

        # Header: icon, name, version and the shortcut status.
        icon = QLabel()
        icon.setPixmap(application_icon().pixmap(40, 40))
        title = QLabel(PRODUCT_NAME)
        title.setObjectName("appTitle")
        version = QLabel(f"v{APP_VERSION} 正式版")
        version.setObjectName("version")
        self._status_label = QLabel("正在初始化截图服务…")
        self._status_label.setObjectName("statusIdle")
        self._status_label.setWordWrap(True)
        self._extra_keys = QLabel()
        self._extra_keys.setObjectName("muted")
        name_row = QHBoxLayout()
        name_row.addWidget(title)
        name_row.addWidget(version, 0, Qt.AlignmentFlag.AlignBottom)
        name_row.addStretch()
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addLayout(name_row)
        names.addWidget(self._status_label)
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(names, 1)

        # The four tools as cards; each card shows its live shortcut.
        capture_button, self._normal_key = self._card(
            "普通截图", "框选区域或单击识别窗口\n可标注、贴图、翻译"
        )
        long_capture_button, self._long_key = self._card(
            "长截图", "自动分段滚动并拼接\n到底自动完成"
        )
        reminder_button, self._reminder_key = self._card(
            "桌面工具", "贴文字、贴图片、翻译\n闹钟、计时器、倒计时"
        )
        presentation_button, self._presentation_key = self._card(
            "教鞭模式", "在屏幕上用画笔标注\n随时切回鼠标操作"
        )
        capture_button.clicked.connect(self._capture_service.start_capture)
        long_capture_button.clicked.connect(self._capture_service.start_long_capture)
        presentation_button.clicked.connect(self._capture_service.toggle_presentation)
        if reminder_callback is not None:
            reminder_button.clicked.connect(reminder_callback)
        else:
            reminder_button.setEnabled(False)
        cards = QGridLayout()
        cards.setSpacing(10)
        cards.addWidget(capture_button, 0, 0)
        cards.addWidget(long_capture_button, 0, 1)
        cards.addWidget(reminder_button, 1, 0)
        cards.addWidget(presentation_button, 1, 1)

        # Settings and the log.
        hotkey_button = self._button("修改快捷键")
        translation_settings_button = self._button("翻译设置")
        diagnostics_button = self._button("显示器诊断")
        diagnostics_button.setToolTip("复制显示器诊断信息，并保存到桌面")
        hotkey_button.clicked.connect(self.open_hotkey_dialog)
        translation_settings_button.clicked.connect(self.open_translation_settings)
        diagnostics_button.clicked.connect(self.copy_display_diagnostics)
        settings_row = QHBoxLayout()
        settings_row.setSpacing(8)
        settings_row.addWidget(hotkey_button)
        settings_row.addWidget(translation_settings_button)
        settings_row.addWidget(diagnostics_button)

        self._log_size_label = QLabel()
        self._log_size_label.setObjectName("muted")
        open_logs_button = self._button("打开日志文件夹", small=True)
        clear_logs_button = self._button("清空日志", small=True)
        open_logs_button.clicked.connect(self._open_log_folder)
        clear_logs_button.clicked.connect(self._clear_logs)
        log_row = QHBoxLayout()
        log_row.setSpacing(8)
        log_row.addWidget(self._log_size_label, 1)
        log_row.addWidget(open_logs_button)
        log_row.addWidget(clear_logs_button)

        # Usage tips in a quiet scrolling panel.
        translation_help = QLabel(
            "翻译说明：可登录 ChatGPT 账号用会员额度翻译，额度用完自动改用 API；"
            "API 支持有道、DeepL、OpenAI、Google Cloud 和 Microsoft Translator，"
            "点击“翻译设置”选择服务并填写对应密钥。"
        )
        long_capture_help = QLabel(
            "长截图说明：按 F2 后只框选需要的内容区域（不要包含固定侧栏）；"
            "单击选区后默认分段自动滚动，画面停稳才会拼接，到底自动完成。"
            "控制条可切换手动模式、暂停、完成或取消；再次按 F2 可提前完成，Esc 取消。"
            "完成后可点击“裁剪”重新保留所需范围。"
        )
        self._presentation_help = QLabel()
        self._update_presentation_help("")
        reminder_help = QLabel(
            "桌面工具：按 F3 后选择贴文字、贴图片、翻译、闹钟、计时器或倒计时。"
            "挂件保持在普通窗口底层；其他窗口只遮住重叠区域，未被遮挡的部分仍可看见。"
            "只有按住挂件拖动时才会移动。计时器提供开始、暂停/继续、重置和取消按钮，"
            "倒计时在相同按钮之外还可直接修改。"
            "闹钟和倒计时到点后会弹出最顶层提醒窗，并可使用内置提示音或本机音乐。"
        )
        pin_help = QLabel(
            "贴图说明：截图后点击“贴图”；鼠标拖动移动，每次按 1 旋转 90°，"
            "Ctrl + 鼠标中键滚动调透明度，双击或按 Esc 关闭。"
        )
        tips = QWidget()
        tips.setObjectName("tips")
        tips_layout = QVBoxLayout(tips)
        tips_layout.setContentsMargins(14, 12, 14, 12)
        tips_layout.setSpacing(10)
        for tip in (
            translation_help,
            long_capture_help,
            self._presentation_help,
            reminder_help,
            pin_help,
        ):
            tip.setWordWrap(True)
            tips_layout.addWidget(tip)
        tips_layout.addStretch()
        tips_area = QScrollArea()
        tips_area.setObjectName("tipsArea")
        tips_area.setWidget(tips)
        tips_area.setWidgetResizable(True)
        tips_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tips_panel = QFrame()
        tips_panel.setObjectName("panel")
        panel_layout = QVBoxLayout(tips_panel)
        panel_layout.setContentsMargins(1, 1, 1, 1)
        panel_layout.addWidget(tips_area)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self._extra_keys)
        layout.addSpacing(6)
        layout.addLayout(cards)
        layout.addSpacing(8)
        layout.addWidget(self._section("设置"))
        layout.addLayout(settings_row)
        layout.addLayout(log_row)
        layout.addSpacing(8)
        guide_button = self._button("查看完整使用说明", small=True)
        guide_button.clicked.connect(self.open_usage_guide)
        tips_title = QHBoxLayout()
        tips_title.addWidget(self._section("使用提示"))
        tips_title.addStretch()
        tips_title.addWidget(guide_button)
        layout.addLayout(tips_title)
        layout.addWidget(tips_panel, 1)
        self.setCentralWidget(content)
        center_on_cursor_screen(self)

    @staticmethod
    def _card(title: str, description: str) -> tuple[QPushButton, QLabel]:
        """A tool card. Its button text stays the tool name for accessibility."""
        card = QPushButton(title)
        card.setObjectName("launchCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumHeight(96)
        name = QLabel(title)
        name.setObjectName("cardTitle")
        key = QLabel("未设置")
        key.setObjectName("cardKeyOff")
        detail = QLabel(description)
        detail.setObjectName("cardDesc")
        detail.setWordWrap(True)
        for label in (name, key, detail):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        top = QHBoxLayout()
        top.addWidget(name)
        top.addStretch()
        top.addWidget(key)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(detail)
        layout.addStretch()
        return card, key

    @staticmethod
    def _button(text: str, small: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("smallButton" if small else "plainButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _set_key(label: QLabel, shortcut: str) -> None:
        label.setText(shortcut or "未设置")
        _restyle(label, "cardKey" if shortcut else "cardKeyOff")

    def showEvent(self, event) -> None:
        """Show the current log size and a dark title bar whenever it opens."""
        super().showEvent(event)
        self._refresh_log_size()
        _use_dark_title_bar(self)

    def _refresh_log_size(self) -> None:
        self._log_size_label.setText(
            f"日志占用 {logs.format_size(logs.log_size())}　最多约 3MB，14 天自动清理"
        )

    def _open_log_folder(self) -> None:
        folder = logs.log_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _clear_logs(self) -> None:
        logs.clear_logs()
        self._refresh_log_size()

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
        """Show each tool's shortcut and whether Windows registered them."""
        self._hotkey_settings = settings
        self._update_presentation_help(settings.presentation_mode)
        self._set_key(self._normal_key, settings.normal_capture)
        self._set_key(self._long_key, settings.long_capture)
        self._set_key(self._reminder_key, settings.reminder)
        self._set_key(self._presentation_key, settings.presentation_mode)

        entries = (
            ("normal", settings.normal_capture, "截图"),
            ("long", settings.long_capture, "长截图"),
            ("presentation", settings.presentation_mode, "教鞭"),
            ("reminder", settings.reminder, "桌面工具"),
            ("calculator", settings.calculator, "计算器开关"),
            ("sleep", settings.sleep, "睡眠"),
        )
        details = []
        failed = []
        for key, shortcut, name in entries:
            if not shortcut:
                state = "未设置"
            elif registration.get(key):
                state = "已就绪"
            else:
                state = "注册失败"
                failed.append(f"{shortcut} {name}")
            details.append(f"{shortcut or '—'} {name}：{state}")
        if failed:
            self._status_label.setText(
                "● 快捷键注册失败：" + "、".join(failed) + "（可能被其他软件占用）"
            )
            _restyle(self._status_label, "statusWarn")
        else:
            self._status_label.setText("● 全部快捷键已就绪")
            _restyle(self._status_label, "statusOk")
        self._status_label.setToolTip("\n".join(details))
        self._extra_keys.setText(
            f"计算器开关 {settings.calculator or '未设置'}　·　睡眠 {settings.sleep or '未设置'}"
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

    def open_usage_guide(self) -> None:
        """Show the complete user guide."""
        UsageGuideDialog(self).exec()

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


def _restyle(widget: QWidget, object_name: str) -> None:
    """Switch a widget to another style rule."""
    if widget.objectName() == object_name:
        return
    widget.setObjectName(object_name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _use_dark_title_bar(window: QWidget) -> None:
    """Ask Windows 10/11 for a dark title bar to match the dark window."""
    try:
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(window.winId()), 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except (AttributeError, OSError):
        pass
