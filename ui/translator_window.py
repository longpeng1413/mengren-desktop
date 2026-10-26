"""F3 desktop-tool translator: type or paste text and translate it.

Chinese and English translate both ways automatically; Japanese, Korean,
French, German, Russian, Spanish and Portuguese can be chosen as well. The
work runs on a background thread so the window never freezes while waiting.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_DISPLAY_NAME
from app.config import RESOURCE_DIR
from core.translate import languages
from core.translate.base import TranslationError
from core.translate.free_text import AUTO_PAIR, FreeTextResult, translate_text
from ui import theme

_log = logging.getLogger(__name__)
_CHEVRON = (RESOURCE_DIR / "icons" / "chevron_down.svg").as_posix()

_STYLE = f"""
#translatorWindow {{ background: {theme.BACKGROUND}; }}
#translatorWindow QLabel {{ color: {theme.TEXT}; font-family: {theme.FONT}; font-size: 13px; }}
#translatorWindow QLabel#muted {{ color: {theme.MUTED}; font-size: 12px; }}
#translatorWindow QLabel#title {{ font-size: 16px; font-weight: 600; }}
#translatorWindow QPlainTextEdit {{
    color: {theme.TEXT};
    background: {theme.PANEL};
    border: 1px solid {theme.LINE};
    border-radius: 10px;
    padding: 8px;
    font-family: {theme.FONT};
    font-size: 14px;
    selection-background-color: #2f5a46;
}}
#translatorWindow QPlainTextEdit:focus {{ border-color: {theme.ACCENT}; }}
#translatorWindow QComboBox {{
    color: {theme.TEXT};
    background: {theme.RAISED};
    border: 1px solid {theme.LINE};
    border-radius: 7px;
    padding: 0 10px;
    min-height: 30px;
    min-width: 120px;
    font-family: {theme.FONT};
    font-size: 13px;
}}
#translatorWindow QComboBox:hover {{ border-color: {theme.ACCENT}; }}
#translatorWindow QComboBox::drop-down {{ border: none; width: 24px; }}
#translatorWindow QComboBox::down-arrow {{ image: url({_CHEVRON}); width: 12px; height: 12px; }}
#translatorWindow QComboBox QAbstractItemView {{
    color: {theme.TEXT};
    background: {theme.RAISED};
    border: 1px solid {theme.LINE};
    selection-background-color: {theme.ACCENT};
    selection-color: {theme.ACCENT_INK};
    outline: none;
}}
#translatorWindow QPushButton {{
    color: {theme.TEXT};
    background: {theme.RAISED};
    border: 1px solid {theme.LINE};
    border-radius: 8px;
    padding: 0 14px;
    min-height: 32px;
    font-family: {theme.FONT};
    font-size: 13px;
}}
#translatorWindow QPushButton:hover {{ background: {theme.HOVER}; border-color: {theme.MUTED}; }}
#translatorWindow QPushButton:disabled {{ color: {theme.DISABLED}; }}
#translatorWindow QPushButton#primaryButton {{
    color: {theme.ACCENT_INK};
    background: {theme.ACCENT};
    border-color: {theme.ACCENT};
    font-weight: 600;
    min-width: 96px;
}}
#translatorWindow QPushButton#primaryButton:hover {{ background: #7fd3aa; }}
#translatorWindow QPushButton#primaryButton:disabled {{ color: {theme.ACCENT_INK}; background: #3e6b55; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {theme.LINE}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


class _Worker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, text: str, target: str, source: str) -> None:
        super().__init__()
        self._text = text
        self._target = target
        self._source = source

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(translate_text(self._text, self._target, self._source))
        except TranslationError as error:
            _log.warning("桌面工具翻译失败：%s", error, exc_info=error.__cause__ is not None)
            self.failed.emit(str(error))
        except Exception:
            _log.exception("桌面工具翻译出现意外错误")
            self.failed.emit("翻译失败，请重试。详细原因已写入日志。")
        finally:
            self.finished.emit()


class TranslatorWindow(QWidget):
    """A small dark window for translating typed or pasted text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("translatorWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle(f"{APP_DISPLAY_NAME} - 翻译")
        self.resize(560, 600)
        self.setStyleSheet(_STYLE)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

        title = QLabel("翻译")
        title.setObjectName("title")
        hint = QLabel("中英文自动互译，也可选择其他语言")
        hint.setObjectName("muted")
        self.source_language = QComboBox()
        self.source_language.addItem("自动检测", languages.AUTO)
        self.target_language = QComboBox()
        self.target_language.addItem("自动（中⇄英）", AUTO_PAIR)
        for item in languages.LANGUAGES:
            self.source_language.addItem(item.label, item.code)
            self.target_language.addItem(item.label, item.code)
        self.swap_button = QPushButton("⇄")
        self.swap_button.setToolTip("交换原文和目标语言")
        self.swap_button.setFixedWidth(44)
        self.swap_button.setStyleSheet("font-size: 17px;")
        self.swap_button.clicked.connect(self.swap_languages)

        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText("输入或粘贴要翻译的文字，按 Ctrl+Enter 翻译")
        self.result_edit = QPlainTextEdit()
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText("译文会显示在这里")

        paste_button = QPushButton("粘贴")
        clear_button = QPushButton("清空")
        self.translate_button = QPushButton("翻译")
        self.translate_button.setObjectName("primaryButton")
        self.translate_button.setToolTip("Ctrl+Enter")
        self.copy_button = QPushButton("复制译文")
        self.copy_button.setEnabled(False)
        self.status_label = QLabel("使用“翻译设置”中的服务：先 ChatGPT 账号（如已开启），再 API")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        paste_button.clicked.connect(self._paste)
        clear_button.clicked.connect(self._clear)
        self.translate_button.clicked.connect(self.translate)
        self.copy_button.clicked.connect(self._copy)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, activated=self.translate)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addWidget(hint, 0, Qt.AlignmentFlag.AlignBottom)
        heading.addStretch()
        language_row = QHBoxLayout()
        language_row.setSpacing(8)
        language_row.addWidget(self.source_language, 1)
        language_row.addWidget(self.swap_button)
        language_row.addWidget(self.target_language, 1)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(paste_button)
        action_row.addWidget(clear_button)
        action_row.addStretch()
        action_row.addWidget(self.translate_button)
        result_row = QHBoxLayout()
        result_row.addWidget(self.status_label, 1)
        result_row.addWidget(self.copy_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addLayout(heading)
        layout.addLayout(language_row)
        layout.addWidget(self.source_edit, 1)
        layout.addLayout(action_row)
        layout.addWidget(self.result_edit, 1)
        layout.addLayout(result_row)

    def open(self) -> None:
        """Show the window in front, ready for typing."""
        self.show()
        self.raise_()
        self.activateWindow()
        self.source_edit.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        theme.dark_title_bar(self)

    def swap_languages(self) -> None:
        """Swap source and target; an automatic choice becomes automatic again."""
        source = self.source_language.currentData()
        target = self.target_language.currentData()
        new_source = languages.AUTO if target == AUTO_PAIR else target
        new_target = AUTO_PAIR if source == languages.AUTO else source
        self.source_language.setCurrentIndex(self.source_language.findData(new_source))
        self.target_language.setCurrentIndex(self.target_language.findData(new_target))
        translated = self.result_edit.toPlainText().strip()
        if translated:
            self.source_edit.setPlainText(translated)
            self.result_edit.clear()
            self.copy_button.setEnabled(False)

    def translate(self) -> None:
        if self._thread is not None:
            return
        text = self.source_edit.toPlainText()
        if not text.strip():
            self.status_label.setText("请先输入要翻译的文字。")
            return
        self.translate_button.setEnabled(False)
        self.translate_button.setText("翻译中…")
        self.status_label.setText("正在翻译……")
        thread = QThread(self)
        worker = _Worker(
            text,
            self.target_language.currentData(),
            self.source_language.currentData(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._show_result)
        worker.failed.connect(self._show_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._finish)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _show_result(self, result: FreeTextResult) -> None:
        self.result_edit.setPlainText(result.text)
        self.copy_button.setEnabled(True)
        self.status_label.setText(
            f"已翻译成{languages.label(result.target)} · {result.service} · 用时 {result.seconds:.1f} 秒"
        )

    def _show_error(self, message: str) -> None:
        self.status_label.setText(f"<span style='color:{theme.DANGER}'>{message}</span>")

    def _finish(self) -> None:
        self.translate_button.setText("翻译")
        self.translate_button.setEnabled(True)
        self._thread = None
        self._worker = None

    def _paste(self) -> None:
        self.source_edit.setPlainText(QGuiApplication.clipboard().text())
        self.source_edit.setFocus()

    def _clear(self) -> None:
        self.source_edit.clear()
        self.result_edit.clear()
        self.copy_button.setEnabled(False)
        self.source_edit.setFocus()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.result_edit.toPlainText())
        self.status_label.setText("译文已复制。")
