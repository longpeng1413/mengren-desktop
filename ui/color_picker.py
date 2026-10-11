"""Color picker that always opens above the full-screen editing layers."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QPoint, QRect, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QColorDialog, QDialog, QWidget

_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002


def pick_color(initial: QColor, anchor: QWidget, title: str) -> QColor:
    """Ask for a color above every top-most screenshot or presentation window.

    The F1 editor and the presentation layer are full-screen top-most windows.
    A normal dialog opens underneath them, where it can be seen through the
    transparent layer but not clicked. Returns an invalid color on cancel.
    """
    dialog = QColorDialog(QColor(initial), anchor)
    dialog.setWindowTitle(title)
    dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.adjustSize()
    screen = QGuiApplication.screenAt(anchor.mapToGlobal(anchor.rect().center()))
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is not None:
        anchor_rect = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        dialog.move(
            dialog_position(anchor_rect, dialog.sizeHint(), screen.availableGeometry())
        )
    QTimer.singleShot(0, lambda: _bring_to_front(dialog))
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return QColor()
        return dialog.selectedColor()
    finally:
        dialog.deleteLater()


def dialog_position(anchor: QRect, size: QSize, bounds: QRect) -> QPoint:
    """Place the picker below the toolbar, or above it, without leaving the screen."""
    margin = 8
    x = anchor.center().x() - size.width() // 2
    y = anchor.bottom() + 1 + margin
    if y + size.height() - 1 > bounds.bottom():
        y = anchor.top() - margin - size.height()
    x = max(bounds.left(), min(x, bounds.right() - size.width() + 1))
    y = max(bounds.top(), min(y, bounds.bottom() - size.height() + 1))
    return QPoint(x, y)


def _bring_to_front(dialog: QDialog) -> None:
    """Re-assert top-most z-order after Windows has created the dialog."""
    if not dialog.isVisible():
        return
    dialog.raise_()
    dialog.activateWindow()
    if sys.platform == "win32":
        ctypes.windll.user32.SetWindowPos(
            int(dialog.winId()),
            _HWND_TOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE,
        )
