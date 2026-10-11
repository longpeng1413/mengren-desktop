"""Tests for ordinary screenshot sticker interactions."""

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from ui.pinned_image import PinnedImageWindow


def test_double_click_closes_pinned_image_without_requesting_edit() -> None:
    application = QApplication.instance() or QApplication([])
    image = QImage(80, 60, QImage.Format.Format_ARGB32)
    window = PinnedImageWindow(image, QPoint(20, 20), QSize(80, 60))
    edit_spy = QSignalSpy(window.edit_requested)
    destroyed_spy = QSignalSpy(window.destroyed)
    window.show()
    application.processEvents()

    QTest.mouseDClick(window, Qt.MouseButton.LeftButton)
    application.processEvents()

    assert destroyed_spy.count() == 1
    assert edit_spy.count() == 0


def test_pinned_image_tooltip_describes_double_click_close_and_right_click_edit() -> None:
    _application = QApplication.instance() or QApplication([])
    image = QImage(80, 60, QImage.Format.Format_ARGB32)
    window = PinnedImageWindow(image, QPoint(20, 20), QSize(80, 60))

    assert "双击关闭" in window.toolTip()
    assert "右键编辑" in window.toolTip()
    assert "Esc 关闭" in window.toolTip()
    window.close()
