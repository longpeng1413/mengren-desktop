"""Tests for DPI-stable in-place screenshot editor positioning."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from core.capture.desktop_capture import DesktopSnapshot
from ui.overlay_editor import OverlayEditor


def test_error_message_keeps_readable_palette() -> None:
    _application = QApplication.instance() or QApplication([])
    virtual_geometry = QRect(0, 0, 320, 200)
    image = QImage(virtual_geometry.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    editor = OverlayEditor(
        DesktopSnapshot(virtual_geometry, image),
        QRect(20, 20, 160, 100),
    )
    message_box = QMessageBox(
        QMessageBox.Icon.Warning,
        "翻译提示",
        "请先填写翻译密钥。",
        QMessageBox.StandardButton.Ok,
        editor,
    )
    message_box.ensurePolished()

    palette = message_box.palette()
    assert editor.objectName() == "overlayEditor"
    assert palette.color(QPalette.ColorRole.Window) != palette.color(
        QPalette.ColorRole.WindowText
    )

    message_box.close()
    editor.close()


def test_editor_frame_uses_host_screen_local_coordinates(monkeypatch) -> None:
    _application = QApplication.instance() or QApplication([])
    virtual_geometry = QRect(-3840, -2167, 6418, 3607)
    image = QImage(virtual_geometry.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    host_geometry = QRect(-3822, -2167, 2560, 1440)
    selection = QRect(-3500, -1900, 900, 520)

    class HostScreen:
        @staticmethod
        def geometry() -> QRect:
            return QRect(host_geometry)

    monkeypatch.setattr(
        "ui.overlay_editor.QGuiApplication.screenAt",
        lambda _point: HostScreen(),
    )
    editor = OverlayEditor(
        DesktopSnapshot(virtual_geometry, image),
        selection,
    )

    assert editor.geometry() == host_geometry
    assert editor._frame.geometry() == QRect(322, 267, 900, 520)

    editor.close()


def test_cancel_closes_owned_floating_toolbar() -> None:
    application = QApplication.instance() or QApplication([])
    virtual_geometry = QRect(-1920, 0, 3840, 1080)
    image = QImage(virtual_geometry.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    editor = OverlayEditor(
        DesktopSnapshot(virtual_geometry, image),
        QRect(200, 180, 640, 360),
    )
    editor.show()
    application.processEvents()

    toolbar = editor._toolbar
    assert toolbar.parent() is editor
    assert toolbar.isVisible()

    editor.reject()

    assert not toolbar.isVisible()
