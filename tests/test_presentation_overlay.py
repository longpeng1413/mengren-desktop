"""Tests for F5 desktop presentation tool switching."""

import pytest
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.preferences import PresentationShortcutSettings
from ui.drawing_cursors import brush_cursor
from ui import presentation_overlay as presentation_overlay_module
from ui.presentation_overlay import PresentationOverlay


def test_brush_cursor_is_three_quarters_of_its_previous_size() -> None:
    _application = QApplication.instance() or QApplication([])
    cursor = brush_cursor()

    assert cursor.pixmap().size().width() == 27
    assert cursor.pixmap().size().height() == 27
    assert cursor.hotSpot() == QPoint(3, 3)


def test_presentation_shortcuts_switch_tools_and_pointer_mode() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())

    assert overlay.active_tool == "brush"
    assert not overlay.pointer_mode

    overlay.execute_shortcut("rectangle")
    assert overlay.active_tool == "rectangle"

    overlay.execute_shortcut("pointer_brush_toggle")
    assert overlay.pointer_mode

    overlay.execute_shortcut("pointer_brush_toggle")
    assert not overlay.pointer_mode
    assert overlay.active_tool == "rectangle"

    overlay.close()


def test_presentation_tools_use_brush_eraser_and_text_cursors() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())

    brush_pixmap_key = None
    for tool in (
        "brush",
        "line",
        "arrow",
        "rectangle",
        "filled_rectangle",
        "ellipse",
    ):
        overlay.select_tool(tool)
        assert overlay._canvas.cursor().shape() == Qt.CursorShape.BitmapCursor
        assert not overlay._canvas.cursor().pixmap().isNull()
        current_key = overlay._canvas.cursor().pixmap().cacheKey()
        brush_pixmap_key = current_key if brush_pixmap_key is None else brush_pixmap_key
        assert current_key == brush_pixmap_key
        assert overlay._canvas.cursor().hotSpot() == QPoint(3, 3)

    overlay.select_tool("eraser")
    assert overlay._canvas.cursor().shape() == Qt.CursorShape.BitmapCursor
    assert overlay._canvas.cursor().pixmap().cacheKey() != brush_pixmap_key

    overlay.select_tool("text")
    assert overlay._canvas.cursor().shape() == Qt.CursorShape.IBeamCursor
    assert overlay._toolbar.cursor().shape() == Qt.CursorShape.ArrowCursor

    overlay.close()


def test_presentation_canvas_receives_drawing_mouse_events() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 320, 200), PresentationShortcutSettings())
    canvas = overlay._canvas

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(canvas, QPoint(90, 90))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(90, 90))

    color = canvas.rendered_image().pixelColor(60, 60)
    assert color.red() > 200
    assert color.alpha() > 200

    overlay.close()


def test_toolbar_switches_directly_between_visible_drawing_buttons() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())
    toolbar = overlay._toolbar

    toolbar.rectangle_button.click()
    assert overlay.active_tool == "rectangle"
    assert toolbar.rectangle_button.isChecked()

    toolbar.line_button.click()
    assert overlay.active_tool == "line"
    assert toolbar.line_button.isChecked()
    assert not toolbar.rectangle_button.isChecked()

    toolbar.filled_rectangle_button.click()
    assert overlay.active_tool == "filled_rectangle"
    assert toolbar.filled_rectangle_button.isChecked()

    overlay.close()


def test_first_show_queues_final_toolbar_raise() -> None:
    application = QApplication.instance() or QApplication([])

    class TrackingOverlay(PresentationOverlay):
        def __init__(self) -> None:
            self.toolbar_raise_count = 0
            super().__init__(QRect(0, 0, 640, 360), PresentationShortcutSettings())

        def _raise_toolbar(self) -> None:
            self.toolbar_raise_count += 1
            super()._raise_toolbar()

    overlay = TrackingOverlay()
    overlay.show()
    application.processEvents()

    assert overlay.toolbar_raise_count >= 2
    overlay.close()


def test_presentation_toolbar_changes_drawing_width() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())

    overlay._toolbar._select_stroke_width(8, "粗 8")

    assert overlay._canvas.stroke_width == 8
    overlay.close()


def test_presentation_toolbar_uses_recovery_name_and_action() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 320, 200), PresentationShortcutSettings())
    canvas = overlay._canvas

    assert overlay._toolbar.redo_button.text() == "恢复"
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(canvas, QPoint(90, 90))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(90, 90))
    edited = canvas.rendered_image()
    canvas.undo()

    overlay._toolbar.redo_button.click()

    assert canvas.rendered_image() == edited
    overlay.close()


def test_presentation_toolbar_is_large_and_keeps_manual_position() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 1200, 700), PresentationShortcutSettings())
    toolbar = overlay._toolbar

    assert toolbar.drag_handle.text() == "移动"
    assert toolbar.brush_button.width() == 56
    assert toolbar.brush_button.height() == 34

    chosen = QPoint(140, 90)
    overlay._remember_toolbar_position(chosen)
    overlay._position_toolbar()
    assert toolbar.pos() == chosen
    overlay.close()


def test_presentation_toolbar_uses_requested_single_row_order() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 1200, 700), PresentationShortcutSettings())
    toolbar = overlay._toolbar
    layout = toolbar.layout()
    labels = [
        layout.itemAt(index).widget().text()
        for index in range(layout.count())
        if layout.itemAt(index).widget() is not None
    ]

    assert labels == [
        "移动",
        "隐藏",
        "鼠标",
        "画笔",
        "箭头",
        "直线",
        "方框",
        "实心",
        "圆形",
        "文字",
        "颜色",
        "粗细",
        "橡皮",
        "撤销",
        "恢复",
        "清除",
        "退出",
    ]
    assert "rgba(22, 25, 29, 242)" in toolbar.styleSheet()
    assert not toolbar.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert toolbar.sizeHint().height() < 50
    overlay.close()


def test_toolbar_raise_uses_complete_windows_set_window_pos_signature(
    monkeypatch,
) -> None:
    """Prevent the six-argument call that aborted every real presentation action."""
    _application = QApplication.instance() or QApplication([])
    calls: list[tuple[int, ...]] = []
    fake_user32 = SimpleNamespace(
        SetWindowPos=lambda hwnd, after, x, y, width, height, flags: calls.append(
            (hwnd, after, x, y, width, height, flags)
        ),
        SetWindowDisplayAffinity=lambda _hwnd, _affinity: True,
    )
    monkeypatch.setattr(presentation_overlay_module.sys, "platform", "win32")
    monkeypatch.setattr(
        presentation_overlay_module.ctypes,
        "windll",
        SimpleNamespace(user32=fake_user32),
    )
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())

    overlay._raise_toolbar()

    assert len(calls) == 1
    assert calls[0][2:6] == (0, 0, 0, 0)
    overlay.close()


@pytest.mark.parametrize(
    ("button_name", "tool"),
    [
        ("arrow_button", "arrow"),
        ("line_button", "line"),
        ("rectangle_button", "rectangle"),
        ("filled_rectangle_button", "filled_rectangle"),
        ("ellipse_button", "ellipse"),
        ("text_button", "text"),
        ("eraser_button", "eraser"),
    ],
)
def test_switching_every_drawing_tool_does_not_repeat_native_pointer_setup(
    monkeypatch,
    button_name: str,
    tool: str,
) -> None:
    """Every brush-to-tool click must switch directly without native window work."""
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())
    monkeypatch.setattr(
        overlay,
        "_set_windows_click_through",
        lambda _enabled: pytest.fail("native click-through should not run"),
    )
    monkeypatch.setattr(
        overlay,
        "_raise_toolbar",
        lambda: pytest.fail("toolbar z-order should not be rebuilt"),
    )

    getattr(overlay._toolbar, button_name).click()

    assert overlay.active_tool == tool
    assert overlay._canvas._tool == tool
    overlay.close()


def test_canvas_tool_changes_before_pointer_window_restoration(monkeypatch) -> None:
    """Retain the requested tool even if native pointer restoration raises."""
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())
    overlay._pointer_mode = True

    def fail_pointer_restoration(_enabled: bool) -> None:
        raise RuntimeError("simulated native window failure")

    monkeypatch.setattr(overlay, "_set_pointer_mode", fail_pointer_restoration)

    with pytest.raises(RuntimeError, match="simulated native window failure"):
        overlay.select_tool("ellipse")

    assert overlay.active_tool == "ellipse"
    assert overlay._canvas._tool == "ellipse"
    assert overlay._toolbar.ellipse_button.isChecked()
    overlay.close()


def test_pointer_shortcut_updates_toolbar_before_native_window_change(
    monkeypatch,
) -> None:
    """F5 must visibly select mouse before Windows click-through processing."""
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())
    native_calls: list[bool] = []

    def inspect_toolbar_state(enabled: bool) -> None:
        native_calls.append(enabled)
        assert overlay.pointer_mode
        assert overlay._toolbar.pointer_button.isChecked()
        assert not overlay._toolbar.brush_button.isChecked()

    monkeypatch.setattr(overlay, "_set_windows_click_through", inspect_toolbar_state)

    overlay.execute_shortcut("pointer_brush_toggle")

    assert native_calls == [True]
    assert overlay._toolbar.pointer_button.isChecked()
    assert not overlay._toolbar.brush_button.isChecked()
    overlay.close()


def test_pointer_toolbar_state_survives_native_window_failure(monkeypatch) -> None:
    """A native failure cannot leave F5 visually stuck on the brush button."""
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 640, 360), PresentationShortcutSettings())

    def fail_click_through(_enabled: bool) -> None:
        raise RuntimeError("simulated click-through failure")

    monkeypatch.setattr(overlay, "_set_windows_click_through", fail_click_through)

    with pytest.raises(RuntimeError, match="simulated click-through failure"):
        overlay.execute_shortcut("pointer_brush_toggle")

    assert overlay.pointer_mode
    assert overlay._toolbar.pointer_button.isChecked()
    assert not overlay._toolbar.brush_button.isChecked()
    overlay.close()


@pytest.mark.parametrize(
    ("button_name", "tool"),
    [
        ("brush_button", "brush"),
        ("arrow_button", "arrow"),
        ("line_button", "line"),
        ("rectangle_button", "rectangle"),
        ("filled_rectangle_button", "filled_rectangle"),
        ("ellipse_button", "ellipse"),
    ],
)
def test_toolbar_selection_controls_the_next_real_drawing_command(
    button_name: str,
    tool: str,
) -> None:
    """Cover the complete button -> overlay -> canvas -> command path."""
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 320, 200), PresentationShortcutSettings())
    canvas = overlay._canvas

    getattr(overlay._toolbar, button_name).click()
    assert overlay.active_tool == tool
    assert canvas._tool == tool

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(canvas, QPoint(130, 90))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(130, 90))

    assert canvas._annotation_commands[-1].tool == tool
    overlay.close()


def test_toolbar_eraser_selection_controls_the_next_real_drawing_command() -> None:
    """The eraser must remain an eraser after leaving the toolbar for the canvas."""
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 320, 200), PresentationShortcutSettings())
    canvas = overlay._canvas

    overlay._toolbar.eraser_button.click()
    assert overlay.active_tool == "eraser"
    assert canvas._tool == "eraser"

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(canvas, QPoint(130, 90))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(130, 90))

    assert canvas._annotation_commands[-1].tool == "eraser"
    overlay.close()


def test_presentation_right_click_undoes_last_brush_stroke() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 320, 200), PresentationShortcutSettings())
    canvas = overlay._canvas

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(canvas, QPoint(90, 90))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(90, 90))
    assert canvas.rendered_image().pixelColor(60, 60).red() > 200

    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=QPoint(60, 60))
    restored = canvas.rendered_image().pixelColor(60, 60)
    assert restored.alpha() <= 1
    overlay.close()


def test_hide_annotations_switches_to_mouse_and_restores_existing_drawing() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 320, 200), PresentationShortcutSettings())
    canvas = overlay._canvas

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(canvas, QPoint(90, 90))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(90, 90))
    drawing = canvas.rendered_image()

    overlay._toolbar.visibility_button.click()

    assert not overlay.annotations_visible
    assert overlay.pointer_mode
    assert overlay._toolbar.visibility_button.text() == "显示"
    assert not canvas.annotations_visible

    overlay._toolbar.visibility_button.click()

    assert overlay.annotations_visible
    assert not overlay.pointer_mode
    assert overlay.active_tool == "brush"
    assert overlay._toolbar.visibility_button.text() == "隐藏"
    assert canvas.annotations_visible
    assert canvas.rendered_image() == drawing
    overlay.close()


def test_selecting_a_drawing_tool_restores_hidden_annotations() -> None:
    _application = QApplication.instance() or QApplication([])
    overlay = PresentationOverlay(QRect(0, 0, 320, 200), PresentationShortcutSettings())

    overlay.toggle_annotations_visibility()
    assert not overlay.annotations_visible
    assert overlay.pointer_mode

    overlay.select_tool("rectangle")

    assert overlay.annotations_visible
    assert not overlay.pointer_mode
    assert overlay.active_tool == "rectangle"
    assert overlay._toolbar.visibility_button.text() == "隐藏"
    overlay.close()


def test_width_and_color_popups_restore_toolbar_above_canvas() -> None:
    application = QApplication.instance() or QApplication([])

    class TrackingOverlay(PresentationOverlay):
        def __init__(self) -> None:
            self.toolbar_raise_count = 0
            super().__init__(QRect(0, 0, 640, 360), PresentationShortcutSettings())

        def _raise_toolbar(self) -> None:
            self.toolbar_raise_count += 1
            super()._raise_toolbar()

    overlay = TrackingOverlay()
    assert overlay._toolbar.parent() is overlay
    initial_count = overlay.toolbar_raise_count

    overlay._toolbar._select_stroke_width(8, "粗 8")
    overlay._toolbar.color_changed.emit(overlay._toolbar._color)
    QTest.qWait(250)
    application.processEvents()

    assert overlay.toolbar_raise_count >= initial_count + 8
    assert overlay._canvas.stroke_width == 8
    overlay.close()
