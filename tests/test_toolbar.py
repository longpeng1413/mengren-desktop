"""Tests for the compact single-row screenshot editor toolbar."""

from PySide6.QtWidgets import QApplication

from ui.toolbar import EditorToolbar


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_default_toolbar_uses_large_readable_buttons_and_hides_crop() -> None:
    _application()
    toolbar = EditorToolbar()

    assert toolbar.sizeHint().height() >= 40
    assert toolbar.mirror_button.size().width() == 48
    assert toolbar.mirror_button.size().height() == 32
    assert "font-size: 13px" in toolbar.styleSheet()
    assert toolbar.crop_button is None
    assert not hasattr(toolbar, "rotate_button")
    assert hasattr(toolbar, "mirror_button")
    assert hasattr(toolbar, "drawing_button")
    assert hasattr(toolbar, "stroke_width_button")
    assert hasattr(toolbar, "eraser_button")
    assert hasattr(toolbar, "delete_button")
    assert not hasattr(toolbar, "arrow_button")


def test_floating_editor_toolbar_has_drag_handle() -> None:
    _application()
    toolbar = EditorToolbar(movable=True)

    assert toolbar.drag_handle is not None
    assert toolbar.drag_handle.text() == "移动"
    assert "拖动" in toolbar.drag_handle.toolTip()


def test_long_capture_toolbar_exposes_crop_and_solid_rectangle() -> None:
    _application()
    toolbar = EditorToolbar(enable_crop=True)

    assert toolbar.crop_button is not None
    assert "实心框" in toolbar._DRAWING_TOOLS


def test_crop_button_enters_mode_then_requests_apply() -> None:
    _application()
    toolbar = EditorToolbar(enable_crop=True)
    requested: list[bool] = []
    toolbar.crop_apply_requested.connect(lambda: requested.append(True))

    toolbar._handle_crop_click()
    assert toolbar._active_tool == "crop"
    assert toolbar.crop_button.text() == "完成"

    toolbar._handle_crop_click()
    assert requested == [True]


def test_toolbar_emits_selected_stroke_width() -> None:
    _application()
    toolbar = EditorToolbar()
    selected: list[int] = []
    toolbar.stroke_width_changed.connect(selected.append)

    toolbar._select_stroke_width(8, "粗 8")

    assert selected == [8]
