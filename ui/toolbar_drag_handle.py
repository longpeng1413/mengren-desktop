"""Reusable drag handle for floating screenshot toolbars."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Signal, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QPushButton


class ToolbarDragHandle(QPushButton):
    """Move the containing floating toolbar by dragging this handle."""

    moved = Signal(QPoint)

    def __init__(self, text: str = "移动", parent=None) -> None:
        super().__init__(text, parent)
        self._drag_offset: QPoint | None = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("按住这里拖动工具栏")

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_offset = (
            event.globalPosition().toPoint()
            - self.window().frameGeometry().topLeft()
        )
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_offset is None
            or not event.buttons() & Qt.MouseButton.LeftButton
        ):
            super().mouseMoveEvent(event)
            return
        global_position = event.globalPosition().toPoint()
        position = self._bounded_position(global_position - self._drag_offset)
        self.window().move(position)
        self.moved.emit(position)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _bounded_position(self, position: QPoint) -> QPoint:
        """Keep enough of the toolbar visible to drag it again."""
        screen = QGuiApplication.screenAt(position)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return position
        bounds = screen.availableGeometry()
        window = self.window()
        minimum_visible = min(80, window.width())
        left = bounds.left() - window.width() + minimum_visible
        right = bounds.right() - minimum_visible + 1
        top = bounds.top()
        bottom = bounds.bottom() - min(window.height(), 24) + 1
        return QPoint(
            max(left, min(position.x(), right)),
            max(top, min(position.y(), bottom)),
        )
