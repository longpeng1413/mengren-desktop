"""A dark, scrollable window showing the full user guide (使用说明.txt)."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

from app.branding import APP_DISPLAY_NAME

_HEADING = re.compile(r"^[一二三四五六七八九十]+、")
_SUBHEADING = re.compile(r"^\d+\.\s")

_STYLE = """
QDialog { background: #0e0e10; }
QTextBrowser {
    background: #151518;
    border: 1px solid #2a2a31;
    border-radius: 10px;
    color: #ebe8e1;
    padding: 10px;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
    selection-background-color: #2f5a46;
}
QPushButton {
    background: #1c1c21;
    border: 1px solid #2a2a31;
    border-radius: 8px;
    color: #ebe8e1;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
    padding: 0 16px;
    min-height: 32px;
}
QPushButton:hover { background: #23232a; border-color: #8f8c85; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #2a2a31; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


def guide_path() -> Path:
    """The guide next to the packaged EXE, or 使用说明.txt in the source tree."""
    if getattr(sys, "frozen", False):
        folder = Path(sys.executable).resolve().parent
        matches = sorted(folder.glob("*使用说明.txt"))
        if matches:
            return matches[0]
        return folder / "使用说明.txt"
    return Path(__file__).resolve().parent.parent / "使用说明.txt"


def guide_html(text: str) -> str:
    """Turn the plain-text guide into HTML with bold section headings."""
    lines = text.splitlines()
    parts = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        escaped = html.escape(line)
        if index == 0 and stripped:
            parts.append(f'<p style="font-size:17px;font-weight:600;margin:0 0 10px 0">{escaped}</p>')
        elif _HEADING.match(stripped):
            parts.append(
                f'<p style="font-size:15px;font-weight:600;color:#6cc59a;margin:16px 0 6px 0">{escaped}</p>'
            )
        elif _SUBHEADING.match(stripped):
            parts.append(f'<p style="font-weight:600;margin:10px 0 4px 0">{escaped}</p>')
        elif not stripped:
            parts.append('<p style="margin:0;line-height:60%">&nbsp;</p>')
        else:
            parts.append(f'<p style="margin:0 0 2px 0;line-height:150%">{escaped}</p>')
    return "".join(parts)


class UsageGuideDialog(QDialog):
    """Shows the complete user guide in a scrollable, copyable window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_DISPLAY_NAME} - 使用说明")
        self.resize(680, 640)
        self.setStyleSheet(_STYLE)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        path = guide_path()
        try:
            self._browser.setHtml(guide_html(path.read_text(encoding="utf-8")))
        except OSError:
            self._browser.setPlainText(
                f"没有找到使用说明文件：\n{path}\n\n请确认它和程序放在同一个文件夹里。"
            )

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.addWidget(self._browser, 1)
        layout.addLayout(buttons)
