"""Tests for keeping the annotation text prompt near its click."""

from PySide6.QtCore import QPoint, QRect, QSize

from ui.image_canvas import ImageCanvas


def test_text_dialog_stays_on_clicked_negative_coordinate_screen() -> None:
    bounds = QRect(-3840, -1080, 1920, 1080)
    position = ImageCanvas._text_dialog_position(
        QPoint(-2100, -120),
        QSize(220, 130),
        bounds,
    )

    assert bounds.contains(QRect(position, QSize(220, 130)))
    assert position.x() < -1920


def test_text_dialog_flips_above_click_near_screen_bottom() -> None:
    bounds = QRect(0, 0, 1920, 1080)
    position = ImageCanvas._text_dialog_position(
        QPoint(1850, 1040),
        QSize(220, 130),
        bounds,
    )

    assert bounds.contains(QRect(position, QSize(220, 130)))
    assert position.x() < 1850
    assert position.y() < 1040
