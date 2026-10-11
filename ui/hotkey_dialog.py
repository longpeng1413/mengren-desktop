"""Dialog for global capture and temporary presentation-mode shortcuts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DISPLAY_NAME
from app.preferences import HotkeySettings, PresentationShortcutSettings


class ShortcutSequenceEdit(QKeySequenceEdit):
    """Record shortcuts while keeping bare Escape as a safe dialog exit."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_Escape
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            window = self.window()
            if isinstance(window, QDialog):
                window.reject()
            event.accept()
            return
        super().keyPressEvent(event)


class HotkeyDialog(QDialog):
    """Edit global actions and shortcuts available inside presentation mode."""

    _GLOBAL_LABELS = {
        "normal_capture": "普通截图：",
        "long_capture": "纵向长截图：",
        "presentation_mode": "教鞭模式：",
        "reminder": "桌面提醒：",
        "calculator": "打开/关闭计算器：",
        "sleep": "计算机睡眠：",
    }
    _TOOL_LABELS = {
        "pointer_brush_toggle": "鼠标/画笔切换：",
        "brush": "画笔：",
        "line": "直线：",
        "rectangle": "方框：",
        "ellipse": "圆形：",
        "arrow": "箭头：",
        "text": "文字：",
        "eraser": "橡皮擦：",
        "clear": "清除全部：",
        "undo": "撤销：",
        "redo": "恢复：",
    }

    def __init__(
        self,
        settings: HotkeySettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("修改快捷键")
        self.setMinimumWidth(430)

        global_labels = self._GLOBAL_LABELS
        self._global_edits = {
            name: ShortcutSequenceEdit(QKeySequence(getattr(settings, name)))
            for name in global_labels
        }
        self._tool_edits = {
            name: ShortcutSequenceEdit(QKeySequence(sequence))
            for name, sequence in settings.presentation_tools.as_action_map().items()
        }

        tabs = QTabWidget()
        tabs.addTab(self._form_page(global_labels, self._global_edits), "全局功能")
        tabs.addTab(self._form_page(self._TOOL_LABELS, self._tool_edits), "教鞭工具")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        restore_button = buttons.addButton(
            "恢复默认",
            QDialogButtonBox.ButtonRole.ResetRole,
        )
        restore_button.setToolTip("恢复全部默认快捷键并立即保存")
        restore_button.clicked.connect(self._restore_defaults)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        label = QLabel(
            "默认快捷键：F1 截图、F2 长截图、F3 桌面工具、F4 教鞭、"
            "Shift+Q 打开/关闭计算器、Shift+F12 直接睡眠。"
            "设置窗口打开期间，全局快捷键会暂时停用；按 Esc 可安全取消。"
            "教鞭工具快捷键只在教鞭模式中生效。"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    @property
    def settings(self) -> HotkeySettings:
        """Return validated settings after the dialog has been accepted."""
        return self._settings

    @staticmethod
    def _form_page(labels: dict[str, str], edits: dict[str, QKeySequenceEdit]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        for name, label in labels.items():
            form.addRow(label, edits[name])
        return page

    def _save(self) -> None:
        global_values = {
            name: self._sequence_text(edit.keySequence())
            for name, edit in self._global_edits.items()
        }
        tool_values = {
            name: self._sequence_text(edit.keySequence())
            for name, edit in self._tool_edits.items()
        }
        required_globals = {"normal_capture", "long_capture"}
        if any(not global_values.get(name, "") for name in required_globals):
            QMessageBox.warning(
                self,
                APP_DISPLAY_NAME,
                "普通截图和长截图必须设置快捷键。",
            )
            return
        all_values = tuple(global_values.values()) + tuple(tool_values.values())
        configured = [value.casefold() for value in all_values if value]
        if len(set(configured)) != len(configured):
            QMessageBox.warning(self, APP_DISPLAY_NAME, "不同功能不能使用相同快捷键。")
            return
        tools = PresentationShortcutSettings(**tool_values)
        self._settings = HotkeySettings(
            presentation_tools=tools,
            **global_values,
        )
        self.accept()

    def _restore_defaults(self) -> None:
        """Restore every global and presentation shortcut and apply immediately."""
        defaults = HotkeySettings()
        for name, edit in self._global_edits.items():
            edit.setKeySequence(QKeySequence(getattr(defaults, name)))
        for name, edit in self._tool_edits.items():
            edit.setKeySequence(
                QKeySequence(getattr(defaults.presentation_tools, name))
            )
        self._save()

    @staticmethod
    def _sequence_text(sequence: QKeySequence) -> str:
        return sequence.toString(QKeySequence.SequenceFormat.PortableText)
