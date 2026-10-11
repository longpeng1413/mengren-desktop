"""Regression tests for coordinated DPI-safe monitor overlays."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from core.capture.desktop_capture import DesktopSnapshot, MonitorSnapshot
from ui.multi_screen_overlay import MultiScreenOverlay


def _image(width: int, height: int, color: str) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


def test_global_drag_is_mapped_into_each_monitor_pane() -> None:
    _app = QApplication.instance() or QApplication([])
    virtual = QRect(-300, -150, 500, 250)
    monitors = (
        MonitorSnapshot(
            QRect(-300, -150, 200, 100),
            QRect(-300, -150, 300, 150),
            _image(300, 150, "#102030"),
        ),
        MonitorSnapshot(
            QRect(0, 0, 200, 100),
            QRect(0, 0, 300, 150),
            _image(300, 150, "#304050"),
        ),
    )
    snapshot = DesktopSnapshot(virtual, _image(500, 250, "#000000"), monitors)
    overlay = MultiScreenOverlay(snapshot)

    selection = QRect(-150, -75, 250, 125)
    overlay._relay_drag_selection(selection)

    assert len(overlay._panes) == 2
    assert all(
        pane._external_drag_selection == selection for pane in overlay._panes
    )
    assert overlay._panes[0]._local_selection(selection) == QRect(150, 75, 50, 25)
    assert overlay._panes[1]._local_selection(selection) == QRect(0, 0, 100, 50)

    overlay.close()
