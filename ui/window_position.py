"""Reliable window placement on Windows multi-monitor desktops."""

from __future__ import annotations

from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QWidget


def center_on_cursor_screen(window: QWidget) -> None:
    """Center a window on the display currently containing the mouse cursor."""
    screen = QGuiApplication.screenAt(QCursor.pos())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return

    frame = window.frameGeometry()
    frame.moveCenter(screen.availableGeometry().center())
    window.move(frame.topLeft())
