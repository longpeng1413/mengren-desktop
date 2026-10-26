"""Compact single-row editing toolbar for screenshot editors."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from ui import theme
from ui.color_picker import pick_color
from ui.toolbar_drag_handle import ToolbarDragHandle


class EditorToolbar(QWidget):
    """Provides grouped drawing tools and screenshot output actions."""

    tool_selected = Signal(str)
    color_changed = Signal(QColor)
    stroke_width_changed = Signal(int)
    text_size_changed = Signal(int)
    delete_requested = Signal()
    crop_apply_requested = Signal()
    position_changed = Signal(QPoint)

    _DRAWING_TOOLS = {
        "画笔": "brush",
        "箭头": "arrow",
        "直线": "line",
        "圆形": "ellipse",
        "方框": "rectangle",
        "实心框": "filled_rectangle",
    }
    _TEXT_SIZES = {
        "小号 16": 16,
        "中号 24": 24,
        "大号 36": 36,
        "特大 52": 52,
    }
    _STROKE_WIDTHS = {
        "细 2": 2,
        "默认 3": 3,
        "中 5": 5,
        "粗 8": 8,
        "特粗 12": 12,
    }

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        enable_crop: bool = False,
        movable: bool = False,
    ) -> None:
        super().__init__(parent)
        self._color = QColor("#ff3b30")
        self._active_tool = "select"
        self.setObjectName("editorToolbar")
        self.setStyleSheet(theme.toolbar_style("editorToolbar", 13))

        self.drag_handle = ToolbarDragHandle("移动", self) if movable else None
        if self.drag_handle is not None:
            self.drag_handle.moved.connect(self.position_changed.emit)
        self.mirror_button = QPushButton("镜像")
        self.crop_button = QPushButton("裁剪") if enable_crop else None
        if self.crop_button is not None:
            self.crop_button.setCheckable(True)
            self.crop_button.clicked.connect(self._handle_crop_click)
        self.drawing_button = self._menu_button("绘图", self._drawing_menu())
        self.drawing_button.setCheckable(True)
        self.text_button = self._tool_button("文字", "text")
        self.text_size_button = self._menu_button("字号", self._text_size_menu())
        self.stroke_width_button = self._menu_button("粗细", self._stroke_width_menu())
        self.stroke_width_button.setToolTip("当前：中 5（默认）")
        self.eraser_button = self._tool_button("橡皮", "eraser")
        self.delete_button = QPushButton("清除")
        self.delete_button.setToolTip("清除全部标注；可按 Ctrl+Z 撤销")
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.color_button = QPushButton("颜色")
        self.color_button.setToolTip("当前默认颜色：红色；点击可选择其他颜色")
        self.color_button.clicked.connect(self._choose_color)
        self.pin_button = QPushButton("贴图")
        self.copy_button = QPushButton("复制")
        self.save_button = QPushButton("保存")
        self.translate_button = QPushButton("翻译")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("dangerButton")

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(3)
        buttons = []
        if self.drag_handle is not None:
            buttons.append(self.drag_handle)
        buttons.append(self.mirror_button)
        if self.crop_button is not None:
            buttons.append(self.crop_button)
        buttons.extend((
            self.drawing_button,
            self.text_button,
            self.text_size_button,
            self.stroke_width_button,
            self.eraser_button,
            self.delete_button,
            self.color_button,
            self.pin_button,
            self.copy_button,
            self.save_button,
            self.translate_button,
            self.cancel_button,
        ))
        for button in buttons:
            button.setFixedSize(48, 32)
            root_layout.addWidget(button)

        self._tool_buttons = {
            "text": self.text_button,
            "eraser": self.eraser_button,
        }
        if self.crop_button is not None:
            self._tool_buttons["crop"] = self.crop_button
        self._update_color_indicator()
        self._select_tool("select")
        self.text_size_changed.emit(24)

    def showEvent(self, event) -> None:
        """Round the floating toolbar's corners like the main window's cards."""
        super().showEvent(event)
        if self.isWindow():
            theme.round_corners(self)

    def set_apply_mode(self, enabled: bool) -> None:
        """Use the pin action as an Apply action while editing an existing sticker."""
        self.pin_button.setText("完成" if enabled else "贴图")
        self.pin_button.setToolTip("应用修改并返回贴图" if enabled else "把当前图片贴到桌面")

    def finish_crop_mode(self) -> None:
        """Return the crop action to its initial state after applying a crop."""
        if self.crop_button is not None:
            self.crop_button.setText("裁剪")
            self.crop_button.setToolTip("先选中整张长图；拖动边界后再次点击完成")
        self._select_tool("select")

    def _handle_crop_click(self) -> None:
        """Enter crop mode on the first click and apply it on the second."""
        if self._active_tool == "crop":
            self.crop_apply_requested.emit()
            return
        assert self.crop_button is not None
        self.crop_button.setText("完成")
        self.crop_button.setToolTip("拖动蓝色边界；可滚动到长图底部调整")
        self._select_tool("crop")

    def _tool_button(self, text: str, tool: str) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.clicked.connect(lambda _checked=False, selected=tool: self._select_tool(selected))
        return button

    @staticmethod
    def _menu_button(text: str, menu: QMenu) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return button

    def _drawing_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, tool in self._DRAWING_TOOLS.items():
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, selected=tool, title=label: self._select_drawing_tool(selected, title)
            )
        return menu

    def _text_size_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, size in self._TEXT_SIZES.items():
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=size, title=label: self._select_text_size(value, title)
            )
        return menu

    def _stroke_width_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, width in self._STROKE_WIDTHS.items():
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=width, title=label: self._select_stroke_width(value, title)
            )
        return menu

    def _select_drawing_tool(self, tool: str, label: str) -> None:
        self.drawing_button.setToolTip(f"当前：{label}")
        self._select_tool(tool)

    def _select_text_size(self, size: int, label: str) -> None:
        self.text_size_button.setToolTip(f"当前：{label}")
        self.text_size_changed.emit(size)

    def _select_stroke_width(self, width: int, label: str) -> None:
        self.stroke_width_button.setToolTip(f"当前：{label}")
        self.stroke_width_changed.emit(width)

    def _select_tool(self, tool: str) -> None:
        self._active_tool = tool
        if self.crop_button is not None and tool != "crop":
            self.crop_button.setText("裁剪")
            self.crop_button.setToolTip("先选中整张长图；拖动边界后再次点击完成")
        self.drawing_button.setChecked(tool in self._DRAWING_TOOLS.values())
        for name, button in self._tool_buttons.items():
            button.setChecked(name == tool)
        self.tool_selected.emit(tool)

    def _choose_color(self) -> None:
        color = pick_color(self._color, self, "选择标注颜色")
        if not color.isValid():
            return
        self._color = color
        self._update_color_indicator()
        self.color_changed.emit(color)

    def _update_color_indicator(self) -> None:
        self.color_button.setStyleSheet(f"border-bottom: 3px solid {self._color.name()};")
