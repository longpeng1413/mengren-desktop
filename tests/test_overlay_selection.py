"""Tests for adjustable long-capture selections."""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from ui.overlay import Overlay


def test_adjustable_selection_resizes_from_its_right_edge() -> None:
    _app = QApplication.instance() or QApplication([])
    overlay = Overlay(QRect(0, 0, 800, 600), QImage(800, 600, QImage.Format.Format_ARGB32), True)
    overlay.resize(800, 600)

    resized = overlay._resized_selection(
        QRect(100, 100, 300, 200),
        "right",
        QPoint(80, 0),
    )

    assert resized == QRect(100, 100, 380, 200)
