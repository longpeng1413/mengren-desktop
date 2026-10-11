"""Compact always-on-top toolbar for desktop presentation annotations."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget

from app.preferences import PresentationShortcutSettings
from ui.toolbar_drag_handle import ToolbarDragHandle


class PresentationToolbar(QWidget):
    """Select presentation tools while keeping the desktop visible."""

    tool_selected = Signal(str)
    pointer_requested = Signal()
    visibility_requested = Signal()
    color_changed = Signal(QColor)
    stroke_width_changed = Signal(int)
    undo_requested = Signal()
    redo_requested = Signal()
    clear_requested = Signal()
    close_requested = Signal()
    position_changed = Signal(QPoint)

    _DRAWING_TOOLS = {
        "画笔": "brush",
        "箭头": "arrow",
        "直线": "line",
        "圆形": "ellipse",
        "方框": "rectangle",
    }
    _STROKE_WIDTHS = {
        "细 2": 2,
        "默认 3": 3,
        "中 5": 5,
        "粗 8": 8,
        "特粗 12": 12,
    }

    def __init__(self, shortcuts: PresentationShortcutSettings, parent=None) -> None:
        super().__init__(parent)
        self._color = QColor("#ff3b30")
        self.setObjectName("presentationToolbar")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setStyleSheet(
            """
            #presentationToolbar {
                background-color: rgba(22, 25, 29, 242);
                border: 1px solid #66717d; border-radius: 7px;
            }
            #presentationToolbar QPushButton, #presentationToolbar QToolButton {
                color: #f5f7fa; background-color: #303841;
                border: 1px solid #7b8794; border-radius: 4px;
                font-size: 16px; font-weight: 700; padding: 0px;
            }
            #presentationToolbar QPushButton:hover, #presentationToolbar QToolButton:hover { background-color: #1677c8; }
            #presentationToolbar QPushButton:checked, #presentationToolbar QToolButton:checked { background-color: #0c6aa8; }
            #presentationToolbar QToolButton::menu-indicator { image: none; }
            QMenu { color: #f5f7fa; background-color: #252b31; border: 1px solid #66717d; }
            QMenu::item { padding: 5px 22px 5px 10px; }
            QMenu::item:selected { background-color: #1677c8; }
            """
        )

        self.drag_handle = ToolbarDragHandle("移动", self)
        self.drag_handle.moved.connect(self.position_changed.emit)
        self.pointer_button = QPushButton("鼠标")
        self.pointer_button.setCheckable(True)
        self.pointer_button.clicked.connect(self.pointer_requested.emit)
        self.visibility_button = QPushButton("隐藏")
        self.visibility_button.setCheckable(True)
        self.visibility_button.clicked.connect(self.visibility_requested.emit)
        self.brush_button = self._tool_button("画笔", "brush")
        self.arrow_button = self._tool_button("箭头", "arrow")
        self.line_button = self._tool_button("直线", "line")
        self.rectangle_button = self._tool_button("方框", "rectangle")
        self.filled_rectangle_button = self._tool_button("实心", "filled_rectangle")
        self.ellipse_button = self._tool_button("圆形", "ellipse")
        self.text_button = self._tool_button("文字", "text")
        self.eraser_button = self._tool_button("橡皮", "eraser")
        self.stroke_width_button = self._menu_button("粗细", self._stroke_width_menu())
        self.stroke_width_button.setToolTip("当前：中 5（默认）")
        self.undo_button = QPushButton("撤销")
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.redo_button = QPushButton("恢复")
        self.redo_button.clicked.connect(self.redo_requested.emit)
        self.clear_button = QPushButton("清除")
        self.clear_button.clicked.connect(self.clear_requested.emit)
        self.color_button = QPushButton("颜色")
        self.color_button.clicked.connect(self._choose_color)
        self.close_button = QPushButton("退出")
        self.close_button.clicked.connect(self.close_requested.emit)

        drawing_buttons = (
            self.arrow_button,
            self.line_button,
            self.rectangle_button,
            self.filled_rectangle_button,
            self.ellipse_button,
            self.text_button,
            self.color_button,
            self.stroke_width_button,
            self.eraser_button,
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        buttons = (
            self.drag_handle,
            self.visibility_button,
            self.pointer_button,
            self.brush_button,
            *drawing_buttons,
            self.undo_button,
            self.redo_button,
            self.clear_button,
            self.close_button,
        )
        for button in buttons:
            button.setFixedSize(56, 34)
            layout.addWidget(button)
        self._tool_buttons = {
            "brush": self.brush_button,
            "arrow": self.arrow_button,
            "line": self.line_button,
            "rectangle": self.rectangle_button,
            "filled_rectangle": self.filled_rectangle_button,
            "ellipse": self.ellipse_button,
            "text": self.text_button,
            "eraser": self.eraser_button,
        }
        self.set_shortcuts(shortcuts)
        self.set_active_tool("brush")
        self._update_color_indicator()

    def set_shortcuts(self, shortcuts: PresentationShortcutSettings) -> None:
        """Display current configurable shortcuts as button tooltips."""
        self.pointer_button.setToolTip(f"鼠标/画笔切换：{shortcuts.pointer_brush_toggle}")
        self.visibility_button.setToolTip("隐藏笔迹并切换到鼠标；再次点击恢复笔迹")
        self.brush_button.setToolTip(f"画笔：{shortcuts.brush}")
        self.arrow_button.setToolTip(f"箭头：{shortcuts.arrow}")
        self.line_button.setToolTip(f"直线：{shortcuts.line}")
        self.rectangle_button.setToolTip(f"方框：{shortcuts.rectangle}")
        self.filled_rectangle_button.setToolTip("实心矩形：使用当前颜色覆盖")
        self.ellipse_button.setToolTip(f"圆形：{shortcuts.ellipse}")
        self.text_button.setToolTip(f"文字：{shortcuts.text}")
        self.eraser_button.setToolTip(f"橡皮：{shortcuts.eraser}")
        self.undo_button.setToolTip(
            f"撤销：{shortcuts.undo or 'Ctrl+Z / 右键'}"
        )
        self.redo_button.setToolTip(
            f"恢复：{shortcuts.redo or 'Ctrl+Y / Ctrl+右键'}"
        )
        self.clear_button.setToolTip(f"清除全部：{shortcuts.clear}")

    def set_pointer_mode(self, enabled: bool) -> None:
        """Reflect whether mouse events currently pass through to the desktop."""
        self.pointer_button.setChecked(enabled)
        if enabled:
            for button in self._tool_buttons.values():
                button.setChecked(False)

    def set_active_tool(self, tool: str) -> None:
        """Reflect one tool selected by either toolbar or keyboard shortcut."""
        self.pointer_button.setChecked(False)
        for name, button in self._tool_buttons.items():
            button.setChecked(name == tool)

    def set_annotations_visible(self, visible: bool) -> None:
        """Reflect whether saved presentation annotations are displayed."""
        self.visibility_button.setText("隐藏" if visible else "显示")
        self.visibility_button.setChecked(not visible)

    def _tool_button(self, label: str, tool: str) -> QPushButton:
        button = QPushButton(label)
        button.setCheckable(True)
        button.clicked.connect(lambda _checked=False, selected=tool: self._select_tool(selected))
        return button

    @staticmethod
    def _menu_button(label: str, menu: QMenu) -> QToolButton:
        button = QToolButton()
        button.setText(label)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return button

    def _stroke_width_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, width in self._STROKE_WIDTHS.items():
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=width, title=label: self._select_stroke_width(value, title)
            )
        return menu

    def _select_stroke_width(self, width: int, label: str) -> None:
        self.stroke_width_button.setToolTip(f"当前：{label}")
        self.stroke_width_changed.emit(width)

    def _select_tool(self, tool: str) -> None:
        self.set_active_tool(tool)
        self.tool_selected.emit(tool)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, "选择教鞭颜色")
        if not color.isValid():
            return
        self._color = QColor(color)
        self._update_color_indicator()
        self.color_changed.emit(color)

    def _update_color_indicator(self) -> None:
        self.color_button.setStyleSheet(f"border-bottom: 3px solid {self._color.name()};")
