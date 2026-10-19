"""Tests for in-place, movable, editable and recolorable text annotations."""

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QFocusEvent, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.image_canvas import ImageCanvas


@pytest.fixture(params=[False, True], ids=["editor", "presentation"])
def canvas(request):
    """A shown canvas in normal (F1) and lightweight (presentation) history mode."""
    _app = QApplication.instance() or QApplication([])
    widget = ImageCanvas()
    image = QImage(400, 200, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    widget.set_lightweight_history_enabled(request.param)
    widget.set_image(image)
    widget.set_tool("text")
    widget.show()
    yield widget
    widget.close()
    widget.deleteLater()


def _type_text(canvas: ImageCanvas, point: QPoint, text: str) -> None:
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    editor = canvas._text_editor
    editor.setText(text)
    QTest.keyClick(editor, Qt.Key.Key_Return)


def _only_text(canvas: ImageCanvas):
    assert len(canvas._texts) == 1
    return next(iter(canvas._texts.values()))


def test_text_box_opens_inside_the_canvas_window(canvas) -> None:
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))

    editor = canvas._text_editor
    assert editor is not None
    assert editor.parent() is canvas
    assert editor.window() is canvas.window()
    assert editor.isVisible()


def test_typed_text_is_kept_and_rendered(canvas) -> None:
    canvas.set_annotation_color(QColor("#ff0000"))
    _type_text(canvas, QPoint(50, 60), "Hello")

    item = _only_text(canvas)
    assert item.text == "Hello"
    assert item.position == QPoint(50, 60)
    assert not canvas._text_editor.isVisible()
    rendered = canvas.rendered_image()
    rect = item.rect()
    reds = [
        rendered.pixelColor(x, y)
        for x in range(rect.left(), rect.right())
        for y in range(rect.top(), rect.bottom())
    ]
    assert any(color.red() > 200 and color.green() < 80 for color in reds)


def test_text_can_be_added_again_after_the_first_one(canvas) -> None:
    _type_text(canvas, QPoint(30, 40), "one")
    _type_text(canvas, QPoint(300, 150), "two")

    assert sorted(item.text for item in canvas._texts.values()) == ["one", "two"]


def test_dragging_moves_text_and_undo_restores_it(canvas) -> None:
    _type_text(canvas, QPoint(50, 60), "Move")
    inside = _only_text(canvas).rect().center()

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=inside)
    QTest.mouseMove(canvas, inside + QPoint(40, 30))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=inside + QPoint(40, 30))

    assert _only_text(canvas).position == QPoint(90, 90)
    assert not canvas._text_editor.isVisible()
    canvas.undo()
    assert _only_text(canvas).position == QPoint(50, 60)


def test_clicking_text_reopens_it_for_correction(canvas) -> None:
    _type_text(canvas, QPoint(50, 60), "Helo")
    inside = _only_text(canvas).rect().center()

    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=inside)
    editor = canvas._text_editor
    assert editor.isVisible()
    assert editor.text() == "Helo"
    editor.setText("Hello")
    QTest.keyClick(editor, Qt.Key.Key_Return)

    assert _only_text(canvas).text == "Hello"
    assert _only_text(canvas).position == QPoint(50, 60)
    canvas.undo()
    assert _only_text(canvas).text == "Helo"


def test_selected_text_can_be_recolored_and_undone(canvas) -> None:
    canvas.set_annotation_color(QColor("#ff0000"))
    _type_text(canvas, QPoint(50, 60), "Color")

    canvas.set_annotation_color(QColor("#00aa00"))

    assert QColor.fromRgba(_only_text(canvas).color_rgba) == QColor("#00aa00")
    canvas.undo()
    assert QColor.fromRgba(_only_text(canvas).color_rgba) == QColor("#ff0000")


def test_color_change_while_typing_applies_to_that_text(canvas) -> None:
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))
    canvas._text_editor.setText("Live")
    canvas.set_annotation_color(QColor("#0000ff"))
    QTest.keyClick(canvas._text_editor, Qt.Key.Key_Return)

    assert QColor.fromRgba(_only_text(canvas).color_rgba) == QColor("#0000ff")


def test_clearing_the_content_deletes_the_text(canvas) -> None:
    _type_text(canvas, QPoint(50, 60), "Gone")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_only_text(canvas).rect().center())
    canvas._text_editor.setText("")
    QTest.keyClick(canvas._text_editor, Qt.Key.Key_Return)

    assert not canvas._texts
    canvas.undo()
    assert _only_text(canvas).text == "Gone"


def test_escape_cancels_a_new_text_without_closing_the_window(canvas) -> None:
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))
    canvas._text_editor.setText("draft")
    escaped: list[bool] = []
    canvas.keyPressEvent = lambda event: escaped.append(True)

    QTest.keyClick(canvas._text_editor, Qt.Key.Key_Escape)

    assert not canvas._texts
    assert not canvas._text_editor.isVisible()
    assert not escaped


def test_clicking_elsewhere_finishes_typing_without_a_new_box(canvas) -> None:
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))
    canvas._text_editor.setText("Done")

    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 150))

    assert _only_text(canvas).text == "Done"
    assert not canvas._text_editor.isVisible()


def test_click_that_steals_focus_first_still_opens_no_new_box(canvas) -> None:
    # In a focused window Qt takes focus from the text box before the click
    # itself arrives; that order must not open a second, empty box.
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))
    canvas._text_editor.setText("Done")

    QApplication.sendEvent(
        canvas._text_editor,
        QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.MouseFocusReason),
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 150))
    QApplication.processEvents()

    assert _only_text(canvas).text == "Done"
    assert not canvas._text_editor.isVisible()


def test_leaving_the_window_while_typing_keeps_the_text(canvas) -> None:
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 60))
    canvas._text_editor.setText("Kept")

    QApplication.sendEvent(
        canvas._text_editor,
        QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason),
    )

    assert _only_text(canvas).text == "Kept"
    assert not canvas._text_editor.isVisible()


def test_delete_key_removes_only_the_selected_text(canvas) -> None:
    _type_text(canvas, QPoint(30, 40), "keep")
    _type_text(canvas, QPoint(300, 150), "drop")

    QTest.keyClick(canvas, Qt.Key.Key_Delete)

    assert [item.text for item in canvas._texts.values()] == ["keep"]


def test_eraser_removes_touched_text(canvas) -> None:
    _type_text(canvas, QPoint(50, 60), "Erase")
    center = _only_text(canvas).rect().center()
    canvas.set_tool("eraser")

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=center)

    assert not canvas._texts
    canvas.undo()
    assert _only_text(canvas).text == "Erase"


def test_clear_all_removes_text_and_undo_restores_it(canvas) -> None:
    _type_text(canvas, QPoint(50, 60), "Clear")

    canvas.clear_annotations()

    assert not canvas._texts
    canvas.undo()
    assert _only_text(canvas).text == "Clear"


def test_mirror_keeps_text_readable_and_moves_it_across() -> None:
    _app = QApplication.instance() or QApplication([])
    canvas = ImageCanvas()
    image = QImage(400, 200, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    canvas.set_image(image)
    canvas.set_tool("text")
    canvas.show()
    _type_text(canvas, QPoint(20, 60), "Side")
    width = _only_text(canvas).rect().width()

    canvas.mirror_horizontal()

    item = _only_text(canvas)
    assert item.text == "Side"
    assert item.position == QPoint(400 - 20 - width, 60)
    canvas.close()
