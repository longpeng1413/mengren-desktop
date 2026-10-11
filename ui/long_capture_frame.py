"""Visible, click-through frame used while a manual long capture is active."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class LongCaptureFrame(QWidget):
    """Keep the selected long-capture boundary visible without blocking scrolling."""

    _OUTER_MARGIN = 7

    def __init__(self, selection: QRect, color: str = "#2da9ff") -> None:
        super().__init__()
        self._selection = QRect(selection)
        self._color = QColor(color)
        self.setGeometry(self.frame_geometry(selection))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._excluded_from_capture = False

    @classmethod
    def frame_geometry(cls, selection: QRect) -> QRect:
        """Return the outer geometry that leaves the captured pixels untouched."""
        return selection.adjusted(
            -cls._OUTER_MARGIN,
            -cls._OUTER_MARGIN,
            cls._OUTER_MARGIN,
            cls._OUTER_MARGIN,
        )

    @property
    def excluded_from_capture(self) -> bool:
        """Whether Windows can omit this frame from screen-capture output."""
        return self._excluded_from_capture

    def exclude_from_capture(self) -> bool:
        """Ask supported Windows versions to omit this helper window from captures."""
        if sys.platform != "win32":
            return False
        self._excluded_from_capture = bool(
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x00000011)
        )
        return self._excluded_from_capture

    def paintEvent(self, event) -> None:
        """Draw a compact WeChat-style selection outline and corner handles."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(self._color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
            painter.setBrush(QColor("#ffffff"))
            for point in (
                self.rect().topLeft(),
                self.rect().topRight(),
                self.rect().bottomLeft(),
                self.rect().bottomRight(),
            ):
                painter.drawRect(point.x() - 3, point.y() - 3, 6, 6)
        finally:
            painter.end()
