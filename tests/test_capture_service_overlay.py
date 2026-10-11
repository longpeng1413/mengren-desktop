"""Regression tests for the four-screen F1 overlay coordinate space."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from core.capture.capture_service import CaptureService
from core.capture.desktop_capture import DesktopSnapshot, MonitorSnapshot


def test_f1_overlay_uses_one_native_pane_per_monitor() -> None:
    application = QApplication.instance() or QApplication([])
    geometry = QRect(-300, -150, 500, 250)
    image = QImage(geometry.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    first_image = QImage(300, 150, QImage.Format.Format_ARGB32)
    first_image.fill(QColor("#102030"))
    second_image = QImage(300, 150, QImage.Format.Format_ARGB32)
    second_image.fill(QColor("#304050"))
    monitors = (
        MonitorSnapshot(QRect(-300, -150, 200, 100), QRect(-300, -150, 300, 150), first_image),
        MonitorSnapshot(QRect(0, 0, 200, 100), QRect(0, 0, 300, 150), second_image),
    )
    snapshot = DesktopSnapshot(geometry, image, monitors)

    class MonitorManager:
        virtual_geometry = geometry

        @staticmethod
        def refresh() -> None:
            return None

    class CaptureEngine:
        @staticmethod
        def capture(_geometry: QRect) -> DesktopSnapshot:
            return snapshot

    service = CaptureService()
    service._monitor_manager = MonitorManager()
    service._engine = CaptureEngine()

    service.start_capture()
    application.processEvents()

    assert service._overlay is not None
    assert service._overlay.geometry() == geometry
    assert service._overlay._virtual_geometry == geometry
    assert len(service._overlay._panes) == 2
    assert [pane._virtual_geometry for pane in service._overlay._panes] == [
        monitor.logical_geometry for monitor in monitors
    ]
    assert [pane._desktop_image for pane in service._overlay._panes] == [
        first_image,
        second_image,
    ]
    assert all(
        pane._locator._logical_desktop == geometry
        for pane in service._overlay._panes
    )

    service._cancel_capture()
