"""Tests for non-destructive screenshot annotation canvas operations."""

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from ui.image_canvas import ImageCanvas


def _application() -> QApplication:
    """Return the shared Qt application used by lightweight widget tests."""
    return QApplication.instance() or QApplication([])


def test_mirror_horizontal_flips_image_without_changing_size() -> None:
    _application()
    image = QImage(24, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor("#111111"))
    image.setPixelColor(3, 5, QColor("#ff0000"))

    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.mirror_horizontal()

    mirrored = canvas.rendered_image()
    assert mirrored.size() == image.size()
    assert mirrored.pixelColor(20, 5) == QColor("#ff0000")


def test_mirror_keeps_scaled_display_size() -> None:
    _application()
    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("#111111"))

    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.set_display_size(QSize(100, 50))
    display_size = canvas.size()
    canvas.mirror_horizontal()

    assert canvas.size() == display_size


def test_rectangle_annotation_changes_rendered_image() -> None:
    _application()
    image = QImage(80, 60, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))

    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas._commit_rectangle(QPoint(10, 10), QPoint(60, 40))

    assert canvas.rendered_image() != image


def test_filled_rectangle_uses_selected_solid_color() -> None:
    _application()
    image = QImage(80, 60, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.set_annotation_color(QColor("#00ff00"))

    canvas._commit_filled_rectangle(QPoint(10, 10), QPoint(60, 40))

    assert canvas.rendered_image().pixelColor(30, 25) == QColor("#00ff00")


def test_crop_changes_image_and_undo_restores_original_size() -> None:
    _application()
    image = QImage(100, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_image(image)

    canvas._commit_crop(QRect(10, 15, 50, 40), QRect(10, 15, 50, 40))

    assert canvas.rendered_image().size() == QSize(50, 40)
    assert canvas.size() == QSize(50, 40)
    canvas.undo()
    assert canvas.rendered_image().size() == QSize(100, 80)
    assert canvas.size() == QSize(100, 80)


def test_long_crop_starts_with_the_complete_image_and_trims_only_the_bottom() -> None:
    _application()
    image = QImage(300, 2400, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.set_tool("crop")

    assert canvas._crop_selection == canvas.rect()
    canvas._crop_selection.setBottom(2199)

    assert canvas.apply_crop_selection()
    assert canvas.rendered_image().size() == QSize(300, 2200)


def test_long_crop_preserves_native_pixels_when_canvas_is_scaled() -> None:
    _application()
    image = QImage(600, 4000, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.set_display_size(QSize(300, 2000))
    canvas.set_tool("crop")
    canvas._crop_selection.setBottom(1799)

    assert canvas.apply_crop_selection()
    assert canvas.rendered_image().size() == QSize(600, 3600)


def test_resize_handles_remain_active_for_annotation_tools() -> None:
    _application()
    image = QImage(80, 60, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))

    canvas = ImageCanvas(resizable=True)
    canvas.set_image(image)
    canvas.set_tool("arrow")

    assert canvas._edge_at(QPoint(0, 30)) == "left"


def test_resizable_canvas_still_accepts_annotation_mouse_input() -> None:
    _application()
    image = QImage(100, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))

    canvas = ImageCanvas(resizable=True)
    canvas.set_image(image)
    canvas.set_tool("rectangle")
    canvas.show()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(canvas, QPoint(70, 55))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 55))

    assert canvas.rendered_image() != image


def test_default_annotation_color_is_red() -> None:
    _application()
    canvas = ImageCanvas()

    assert canvas._annotation_color == QColor("#ff3b30")


def test_undo_restores_image_before_mirror() -> None:
    _application()
    image = QImage(24, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor("#111111"))
    image.setPixelColor(3, 5, QColor("#ff0000"))

    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.mirror_horizontal()
    canvas.undo()

    assert canvas.rendered_image() == image


def test_line_and_ellipse_tools_change_rendered_image() -> None:
    _application()
    image = QImage(100, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_image(image)

    canvas._commit_line(QPoint(10, 10), QPoint(80, 60))
    canvas._commit_ellipse(QPoint(20, 15), QPoint(70, 55))

    assert canvas.rendered_image() != image


def test_right_click_undoes_last_brush_stroke() -> None:
    _application()
    image = QImage(100, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.set_tool("brush")
    canvas.show()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(canvas, QPoint(70, 55))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 55))
    assert canvas.rendered_image() != image

    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=QPoint(50, 40))
    assert canvas.rendered_image() == image


def test_control_right_click_recovers_last_undone_brush_stroke() -> None:
    _application()
    image = QImage(100, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_image(image)
    canvas.set_tool("brush")
    canvas.show()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(canvas, QPoint(70, 55))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 55))
    edited = canvas.rendered_image()

    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=QPoint(50, 40))
    assert canvas.rendered_image() == image

    QTest.mouseClick(
        canvas,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=QPoint(50, 40),
    )
    assert canvas.rendered_image() == edited


def test_new_edit_clears_recovery_history() -> None:
    _application()
    image = QImage(24, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor("#111111"))
    image.setPixelColor(3, 5, QColor("#ff0000"))
    canvas = ImageCanvas()
    canvas.set_image(image)

    canvas.mirror_horizontal()
    canvas.undo()
    assert canvas._redo_stack

    canvas.clear_annotations()
    assert not canvas._redo_stack


def test_stroke_width_is_configurable() -> None:
    _application()
    canvas = ImageCanvas()

    assert canvas.stroke_width == 5
    canvas.set_stroke_width(8)

    assert canvas.stroke_width == 8


def test_lightweight_history_keeps_commands_instead_of_full_image_snapshots() -> None:
    _application()
    image = QImage(640, 360, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_lightweight_history_enabled(True)
    canvas.set_image(image)
    canvas.set_tool("brush")
    canvas.show()

    for offset in range(12):
        start = QPoint(20, 20 + offset * 10)
        end = QPoint(180, 20 + offset * 10)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

    assert not canvas._undo_stack
    assert not canvas._redo_stack
    assert len(canvas._annotation_commands) == 12
    assert all(command.tool == "brush" for command in canvas._annotation_commands)
    assert all(len(command.points) >= 2 for command in canvas._annotation_commands)


def test_lightweight_history_replays_undo_redo_and_clear() -> None:
    _application()
    image = QImage(160, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = ImageCanvas()
    canvas.set_lightweight_history_enabled(True)
    canvas.set_image(image)
    canvas.set_tool("brush")
    canvas.show()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(canvas, QPoint(120, 20))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(120, 20))
    edited = canvas.rendered_image()

    canvas.undo()
    assert canvas.rendered_image() == image
    canvas.redo()
    assert canvas.rendered_image() == edited

    canvas.clear_annotations()
    assert canvas.rendered_image() == image
    canvas.undo()
    assert canvas.rendered_image() == edited
    canvas.redo()
    assert canvas.rendered_image() == image


def test_lightweight_freehand_requests_only_a_local_repaint() -> None:
    _application()

    class TrackingCanvas(ImageCanvas):
        def __init__(self) -> None:
            self.repaint_rects: list[QRect] = []
            super().__init__()

        def _request_annotation_update(self, rect: QRect | None = None) -> None:
            if rect is not None:
                self.repaint_rects.append(QRect(rect))
            super()._request_annotation_update(rect)

    image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    canvas = TrackingCanvas()
    canvas.set_lightweight_history_enabled(True)
    canvas.set_image(image)
    canvas.set_tool("brush")
    canvas.show()
    canvas.repaint_rects.clear()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(canvas, QPoint(140, 120))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(140, 120))

    assert canvas.repaint_rects
    assert max(rect.width() * rect.height() for rect in canvas.repaint_rects) < 10_000
