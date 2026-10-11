"""Compact controls displayed while a vertical long capture is active."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QRect, Signal, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class LongCaptureControls(QWidget):
    """Allow automatic/manual switching and explicit safe completion."""

    automatic_mode_requested = Signal(bool)
    pause_requested = Signal()
    resume_requested = Signal()
    finish_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, selection: QRect) -> None:
        super().__init__()
        self._selection = QRect(selection)
        self._automatic = True
        self._paused = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "QWidget { background: #20252b; color: #f6f8fa; }"
            "QLabel { padding: 0 4px; }"
            "QPushButton { background: #34404b; color: white; "
            "border: 1px solid #85919d; border-radius: 4px; "
            "min-height: 28px; padding: 0 10px; font-size: 13px; "
            "font-weight: 700; }"
            "QPushButton:hover { background: #1677c8; }"
            "QPushButton#finishButton { background: #147d44; border-color: #5fd38a; }"
            "QPushButton#cancelButton { background: #8f3038; border-color: #ff7379; }"
        )

        self.status_label = QLabel("自动长截图：准备滚动")
        self.mode_button = QPushButton("自动模式")
        self.pause_button = QPushButton("暂停")
        self.finish_button = QPushButton("完成（F2）")
        self.cancel_button = QPushButton("取消")
        self.finish_button.setObjectName("finishButton")
        self.cancel_button.setObjectName("cancelButton")
        self.mode_button.setToolTip("切换自动分段滚动或手动滚轮模式")
        self.pause_button.setToolTip("暂停或继续长截图")
        self.finish_button.setToolTip("在当前位置生成已经验证的长截图")
        self.cancel_button.setToolTip("放弃本次长截图")

        self.mode_button.clicked.connect(self._toggle_mode)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.finish_button.clicked.connect(self.finish_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(6)
        layout.addWidget(self.status_label)
        layout.addWidget(self.mode_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.finish_button)
        layout.addWidget(self.cancel_button)
        self.adjustSize()
        self._place_near(selection)

    def exclude_from_capture(self) -> bool:
        """Ask Windows to keep the helper bar out of captured pixels."""
        if sys.platform != "win32":
            return False
        return bool(
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x00000011)
        )

    def set_status(self, text: str) -> None:
        self.status_label.setStyleSheet("")
        self.status_label.setText(text)
        self.adjustSize()
        self._place_near(self._selection)

    def show_attention(self, text: str) -> None:
        self.status_label.setStyleSheet("color: #ffcf4a; font-weight: 700;")
        self.status_label.setText(text)
        self.adjustSize()
        self._place_near(self._selection)

    def set_automatic_mode(self, enabled: bool) -> None:
        self._automatic = enabled
        self.mode_button.setText("自动模式" if enabled else "手动模式")

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.pause_button.setText("继续" if paused else "暂停")

    def _toggle_mode(self) -> None:
        self.automatic_mode_requested.emit(not self._automatic)

    def _toggle_pause(self) -> None:
        if self._paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def _place_near(self, selection: QRect) -> None:
        screen = QGuiApplication.screenAt(selection.center())
        available = screen.availableGeometry() if screen is not None else selection
        left = min(selection.right() - self.width() + 1, available.right() - self.width() + 1)
        left = max(available.left(), left)
        top = selection.bottom() + 8
        if top + self.height() > available.bottom():
            top = max(available.top(), selection.top() - self.height() - 8)
        self.move(left, top)
