from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from core.capture.desktop_capture import (
    DesktopCaptureEngine,
    DesktopSnapshot,
    MonitorSnapshot,
)


def test_crop_converts_global_coordinates_to_image_coordinates() -> None:
    image = QImage(100, 50, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    snapshot = DesktopSnapshot(QRect(-50, 10, 100, 50), image)

    result = snapshot.crop(QRect(-25, 20, 25, 10))

    assert result.size().width() == 25
    assert result.size().height() == 10
    assert result.pixelColor(0, 0) == QColor("red")


def test_physical_region_preserves_the_selected_logical_area() -> None:
    region = DesktopCaptureEngine._physical_region(
        QRect(-100, 0, 200, 100),
        QRect(-50, 20, 50, 40),
        {"left": -200, "top": 0, "width": 400, "height": 200},
    )

    assert region == {"left": -100, "top": 40, "width": 100, "height": 80}


def test_native_monitor_crop_preserves_high_dpi_pixels() -> None:
    preview = QImage(100, 50, QImage.Format.Format_ARGB32)
    preview.fill(QColor("red"))
    native = QImage(200, 100, QImage.Format.Format_ARGB32)
    native.fill(QColor("red"))
    monitor = MonitorSnapshot(
        QRect(100, 50, 100, 50),
        QRect(100, 50, 200, 100),
        native,
    )
    snapshot = DesktopSnapshot(QRect(100, 50, 100, 50), preview, (monitor,))

    result = snapshot.crop(QRect(125, 60, 25, 10))

    assert result.size().width() == 50
    assert result.size().height() == 20
    assert result.pixelColor(0, 0) == QColor("red")


def test_monitor_matching_uses_position_and_native_scale() -> None:
    monitors = (
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 3840, "height": 2160},
    )

    result = DesktopCaptureEngine._match_monitor(
        QRect(1920, 0, 2560, 1440),
        1.5,
        monitors,
    )

    assert result == monitors[1]

