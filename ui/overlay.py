"""Full virtual-desktop selection overlay."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Signal, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from core.capture.window_capture import WindowLocator


class Overlay(QWidget):
    """Draws a desktop snapshot and emits the user's selected global rectangle."""

    selection_completed = Signal(QRect)
    cancelled = Signal()
    drag_selection_changed = Signal(QRect)

    _MIN_SELECTION_SIZE = 24
    _HANDLE_RADIUS = 7

    def __init__(
        self,
        geometry: QRect,
        desktop_image: QImage,
        adjustable: bool = False,
        confirm_text: str = "开始",
        click_to_confirm: bool = False,
        show_confirmation_buttons: bool = True,
        window_locator: WindowLocator | None = None,
    ) -> None:
        super().__init__()
        self._virtual_geometry = QRect(geometry)
        self._desktop_image = desktop_image
        self._dragging = False
        self._adjustable = adjustable
        self._click_to_confirm = click_to_confirm
        self._show_buttons = show_confirmation_buttons
        self._selection = QRect()
        self._external_drag_selection = QRect()
        self._resize_edge = ""
        self._resize_origin = QPoint()
        self._resize_start = QRect()
        self._start = QPoint()
        self._end = QPoint()
        self._start_global = QPoint()
        self._end_global = QPoint()
        self._locator = window_locator or WindowLocator(geometry)
        self._hover_window = self._locator.target_at(QCursor.pos())
        self._hover_selection = (
            QRect(self._hover_window.geometry)
            if self._hover_window is not None
            else QRect()
        )
        self._selected_window_handle = 0

        self.setGeometry(geometry)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._confirm_button = QPushButton(confirm_text, self)
        self._cancel_button = QPushButton("取消", self)
        for button in (self._confirm_button, self._cancel_button):
            button.setFixedHeight(28)
            button.setStyleSheet(
                "QPushButton { color: white; background: #263544; border: 1px solid #7890a5; "
                "border-radius: 4px; padding: 2px 12px; font-weight: bold; }"
                "QPushButton:hover { background: #34495e; }"
            )
            button.hide()
        self._confirm_button.clicked.connect(self._confirm_adjusted_selection)
        self._cancel_button.clicked.connect(self.cancelled.emit)

    def paintEvent(self, event) -> None:
        """Render the captured desktop, dimmer, and live selection."""
        painter = QPainter(self)
        painter.drawImage(self.rect(), self._desktop_image)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self._dragging:
            selection = self._local_selection(
                QRect(self._start_global, self._end_global).normalized()
            )
            pen = QPen(Qt.GlobalColor.white, 2)
        elif not self._external_drag_selection.isEmpty():
            selection = self._local_selection(self._external_drag_selection)
            pen = QPen(Qt.GlobalColor.white, 2)
        elif not self._selection.isEmpty():
            selection = QRect(self._selection)
            pen = QPen(QColor("#2da9ff"), 2)
        elif not self._hover_selection.isEmpty():
            selection = QRect(self._hover_selection)
            selection.translate(-self._virtual_geometry.topLeft())
            pen = QPen(QColor("#2da9ff"), 3)
        else:
            return
        if selection.isEmpty():
            return
        painter.save()
        painter.setClipRect(selection)
        painter.drawImage(self.rect(), self._desktop_image)
        painter.restore()

        painter.setPen(pen)
        painter.drawRect(selection.adjusted(1, 1, -2, -2))
        if self._adjustable and not self._selection.isEmpty():
            painter.setBrush(QColor("#ffffff"))
            for point in self._handle_points(selection):
                painter.drawRect(point.x() - 3, point.y() - 3, 6, 6)
            message_rect = selection.adjusted(8, 8, -8, -8)
            painter.setPen(Qt.GlobalColor.white)
            instruction = (
                "拖动边框调整，单击选区开始"
                if self._click_to_confirm
                else "拖动边框调整，点击开始"
            )
            painter.drawText(
                message_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                instruction,
            )

    def mousePressEvent(self, event) -> None:
        """Start a new selection."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position().toPoint()
        if self._adjustable and not self._selection.isEmpty():
            edge = self._edge_at(position)
            if edge:
                self._resize_edge = edge
                self._resize_origin = position
                self._resize_start = QRect(self._selection)
                return
            if self._selection.contains(position):
                if self._click_to_confirm:
                    self._confirm_adjusted_selection()
                return
            self._selection = QRect()
            self._selected_window_handle = 0
            self._hide_confirmation_buttons()
        self._dragging = True
        self._start = position
        self._end = self._start
        self._start_global = event.globalPosition().toPoint()
        self._end_global = self._start_global
        self.drag_selection_changed.emit(
            QRect(self._start_global, self._end_global).normalized()
        )
        self.update()

    def mouseMoveEvent(self, event) -> None:
        """Highlight a hovered window or update a freehand selection rectangle."""
        position = event.position().toPoint()
        if self._resize_edge:
            delta = position - self._resize_origin
            self._selection = self._resized_selection(
                self._resize_start,
                self._resize_edge,
                delta,
            )
            self._position_confirmation_buttons()
            self.update()
            return
        if self._dragging:
            self._end = position
            self._end_global = event.globalPosition().toPoint()
            self.drag_selection_changed.emit(
                QRect(self._start_global, self._end_global).normalized()
            )
            self.update()
            return
        if self._adjustable and not self._selection.isEmpty():
            self.setCursor(self._cursor_for_edge(self._edge_at(position)))
            return
        target = self._locator.target_at(event.globalPosition().toPoint())
        selection = QRect(target.geometry) if target is not None else QRect()
        if selection != self._hover_selection:
            self._hover_window = target
            self._hover_selection = selection
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        """Finish a non-empty selection without capturing the overlay."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._resize_edge:
            self._resize_edge = ""
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()
            return
        if not self._dragging:
            return
        self._dragging = False
        self._end = event.position().toPoint()
        self._end_global = event.globalPosition().toPoint()
        self.drag_selection_changed.emit(QRect())
        dragged = QRect(self._start_global, self._end_global).normalized()
        moved = max(
            abs(self._end_global.x() - self._start_global.x()),
            abs(self._end_global.y() - self._start_global.y()),
        ) >= 4
        if moved and dragged.width() >= 2 and dragged.height() >= 2:
            self._selected_window_handle = 0
            if self._adjustable:
                self._selection = self._local_selection(dragged)
                self._show_confirmation_buttons()
                self.update()
                return
            self.selection_completed.emit(dragged)
            return
        if self._hover_selection.isEmpty():
            self.cancelled.emit()
            return
        self._selected_window_handle = (
            self._hover_window.handle if self._hover_window is not None else 0
        )
        if self._adjustable:
            self._selection = QRect(self._hover_selection)
            self._selection.translate(-self._virtual_geometry.topLeft())
            self._show_confirmation_buttons()
            self.update()
            return
        self.selection_completed.emit(QRect(self._hover_selection))

    @property
    def selected_window_handle(self) -> int:
        """Return the exact HWND chosen by a click, or zero for a dragged area."""
        return self._selected_window_handle

    def set_external_drag_selection(self, selection: QRect) -> None:
        """Display a global drag rectangle started on another monitor pane."""
        self._external_drag_selection = QRect(selection)
        self.update()

    def clear_external_drag_selection(self) -> None:
        """Remove the shared cross-monitor drag rectangle."""
        if self._external_drag_selection.isEmpty():
            return
        self._external_drag_selection = QRect()
        self.update()

    def _local_selection(self, global_selection: QRect) -> QRect:
        intersection = global_selection.intersected(self._virtual_geometry)
        if intersection.isEmpty():
            return QRect()
        intersection.translate(-self._virtual_geometry.topLeft())
        return intersection

    def keyPressEvent(self, event) -> None:
        """Cancel selection with Escape."""
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Allow a double-click inside an adjusted selection to start capture."""
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._adjustable
            and self._selection.contains(event.position().toPoint())
        ):
            self._confirm_adjusted_selection()

    def _confirm_adjusted_selection(self) -> None:
        if self._selection.isEmpty():
            return
        selection = QRect(self._selection)
        selection.translate(self._virtual_geometry.topLeft())
        self._hide_confirmation_buttons()
        self.selection_completed.emit(selection)

    def _show_confirmation_buttons(self) -> None:
        if not self._adjustable or not self._show_buttons or self._selection.isEmpty():
            return
        self._confirm_button.adjustSize()
        self._cancel_button.adjustSize()
        self._position_confirmation_buttons()
        self._confirm_button.show()
        self._cancel_button.show()
        self._confirm_button.raise_()
        self._cancel_button.raise_()

    def _hide_confirmation_buttons(self) -> None:
        self._confirm_button.hide()
        self._cancel_button.hide()

    def _position_confirmation_buttons(self) -> None:
        if self._selection.isEmpty():
            return
        gap = 6
        total_width = self._confirm_button.width() + gap + self._cancel_button.width()
        left = self._selection.right() - total_width + 1
        left = max(0, min(left, self.width() - total_width))
        top = self._selection.bottom() + 7
        button_height = max(self._confirm_button.height(), self._cancel_button.height())
        if top + button_height > self.height():
            top = max(0, self._selection.top() - button_height - 7)
        self._confirm_button.move(left, top)
        self._cancel_button.move(left + self._confirm_button.width() + gap, top)

    def _edge_at(self, position: QPoint) -> str:
        """Return the resize edge or corner under the pointer."""
        if self._selection.isEmpty():
            return ""
        rect = self._selection
        near_left = abs(position.x() - rect.left()) <= self._HANDLE_RADIUS
        near_right = abs(position.x() - rect.right()) <= self._HANDLE_RADIUS
        near_top = abs(position.y() - rect.top()) <= self._HANDLE_RADIUS
        near_bottom = abs(position.y() - rect.bottom()) <= self._HANDLE_RADIUS
        within_x = rect.left() - self._HANDLE_RADIUS <= position.x() <= rect.right() + self._HANDLE_RADIUS
        within_y = rect.top() - self._HANDLE_RADIUS <= position.y() <= rect.bottom() + self._HANDLE_RADIUS
        vertical = "top" if near_top else "bottom" if near_bottom else ""
        horizontal = "left" if near_left else "right" if near_right else ""
        if vertical and horizontal:
            return f"{vertical}_{horizontal}"
        if vertical and within_x:
            return vertical
        if horizontal and within_y:
            return horizontal
        return ""

    def _resized_selection(self, initial: QRect, edge: str, delta: QPoint) -> QRect:
        bounds = self.rect()
        left, right = initial.left(), initial.right()
        top, bottom = initial.top(), initial.bottom()
        if "left" in edge:
            left = max(bounds.left(), min(left + delta.x(), right - self._MIN_SELECTION_SIZE + 1))
        if "right" in edge:
            right = min(bounds.right(), max(right + delta.x(), left + self._MIN_SELECTION_SIZE - 1))
        if "top" in edge:
            top = max(bounds.top(), min(top + delta.y(), bottom - self._MIN_SELECTION_SIZE + 1))
        if "bottom" in edge:
            bottom = min(bounds.bottom(), max(bottom + delta.y(), top + self._MIN_SELECTION_SIZE - 1))
        return QRect(left, top, right - left + 1, bottom - top + 1)

    @staticmethod
    def _handle_points(rect: QRect) -> tuple[QPoint, ...]:
        return (
            rect.topLeft(),
            QPoint(rect.center().x(), rect.top()),
            rect.topRight(),
            QPoint(rect.right(), rect.center().y()),
            rect.bottomRight(),
            QPoint(rect.center().x(), rect.bottom()),
            rect.bottomLeft(),
            QPoint(rect.left(), rect.center().y()),
        )

    @staticmethod
    def _cursor_for_edge(edge: str) -> Qt.CursorShape:
        if edge in {"top_left", "bottom_right"}:
            return Qt.CursorShape.SizeFDiagCursor
        if edge in {"top_right", "bottom_left"}:
            return Qt.CursorShape.SizeBDiagCursor
        if edge in {"left", "right"}:
            return Qt.CursorShape.SizeHorCursor
        if edge in {"top", "bottom"}:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.CrossCursor
