"""Tests for DPI-stable in-place screenshot editor positioning."""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from core.capture.desktop_capture import DesktopSnapshot
from ui.overlay_editor import OverlayEditor, spanned_host_geometry


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
    monkeypatch.setattr(
        "ui.overlay_editor.screen_layout",
        lambda: [(QRect(host_geometry), 1.5), (QRect(0, 0, 2560, 1440), 1.0)],
    )
    editor = OverlayEditor(
        DesktopSnapshot(virtual_geometry, image),
        selection,
    )

    assert editor.geometry() == host_geometry
    assert editor._frame.geometry() == QRect(322, 267, 900, 520)

    editor.close()


# The developer's 2x2 wall of 1920x1080 screens at 100% scaling.
FOUR_SCREENS = [
    (QRect(0, 0, 1920, 1080), 1.0),
    (QRect(1920, 4, 1920, 1080), 1.0),
    (QRect(1929, -1076, 1920, 1080), 1.0),
    (QRect(9, -1080, 1920, 1080), 1.0),
]


def test_host_always_covers_every_screen_of_equal_scaling() -> None:
    wall = QRect(0, -1080, 3849, 2164)

    # A window across all four screens, across the top two, or on one screen:
    # the editor always spans the whole wall so the frame can grow anywhere.
    assert spanned_host_geometry(wall, FOUR_SCREENS) == wall
    assert spanned_host_geometry(QRect(15, -1074, 3827, 1023), FOUR_SCREENS) == wall
    assert spanned_host_geometry(QRect(100, 100, 400, 300), FOUR_SCREENS) == wall


def test_host_refuses_screens_with_different_scaling() -> None:
    screens = [(QRect(0, 0, 2560, 1440), 1.5), (QRect(3840, 0, 1920, 1080), 1.0)]

    assert spanned_host_geometry(QRect(2000, 100, 2500, 500), screens) is None
    assert spanned_host_geometry(QRect(100, 100, 400, 300), screens) == QRect(0, 0, 2560, 1440)
    assert spanned_host_geometry(QRect(-900, -900, 100, 100), screens) is None


def test_host_never_stretches_over_a_screen_of_other_scaling() -> None:
    left = QRect(0, 0, 1920, 1080)
    middle = QRect(1920, 0, 1707, 960)
    right = QRect(4480, 0, 1920, 1080)
    below = QRect(0, 1080, 1920, 1080)
    screens = [(left, 1.0), (middle, 1.5), (right, 1.0), (below, 1.0)]

    # The right screen shares the scaling but lies beyond the 150% screen.
    assert spanned_host_geometry(QRect(100, 100, 400, 300), screens) == QRect(0, 0, 1920, 2160)
    assert spanned_host_geometry(QRect(4600, 100, 400, 300), screens) == right


def test_window_across_four_screens_stays_whole_in_place(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    virtual_geometry = QRect(0, -1080, 3849, 2164)
    image = QImage(virtual_geometry.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    selection = QRect(15, -1074, 3827, 2150)
    monkeypatch.setattr("ui.overlay_editor.screen_layout", lambda: list(FOUR_SCREENS))

    editor = OverlayEditor(DesktopSnapshot(virtual_geometry, image), selection)
    editor.show()
    application.processEvents()

    assert editor._host_geometry == virtual_geometry
    assert editor._frame.geometry() == QRect(15, 6, 3827, 2150)
    assert editor._frame.rendered_image().size() == selection.size()

    # Dragging the left edge may reach the far screen instead of stopping at one.
    widened = editor._resized_selection(selection, "left", QPoint(-100, 0))
    assert widened.left() == 0
    assert widened.right() == selection.right()

    editor.reject()


def test_screenshot_from_one_screen_can_be_dragged_onto_the_others(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    virtual_geometry = QRect(0, -1080, 3849, 2164)
    image = QImage(virtual_geometry.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    selection = QRect(400, 300, 800, 500)
    monkeypatch.setattr("ui.overlay_editor.screen_layout", lambda: list(FOUR_SCREENS))

    editor = OverlayEditor(DesktopSnapshot(virtual_geometry, image), selection)
    editor.show()
    application.processEvents()

    assert editor._host_geometry == virtual_geometry
    grown = editor._resized_selection(selection, "top_right", QPoint(3000, -2000))
    assert grown == QRect(400, -1080, 3449, 1880)

    editor.reject()


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
