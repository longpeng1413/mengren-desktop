"""Interactive image canvas shared by screenshot editors."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import atan2, ceil, cos, floor, sin

from PySide6.QtCore import QPoint, QRect, QSize, Signal, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import QLineEdit, QWidget


@dataclass(frozen=True, slots=True)
class _AnnotationCommand:
    """One compact, replayable presentation annotation."""

    tool: str
    color_rgba: int
    width: int
    points: tuple[QPoint, ...] = ()
    text: str = ""
    text_size: int = 0
    item_id: int = 0


def _text_font(pixel_size: int) -> QFont:
    """Return the bold font used for every text annotation."""
    font = QFont()
    font.setPixelSize(max(1, pixel_size))
    font.setBold(True)
    return font


@dataclass(frozen=True, slots=True)
class _TextItem:
    """One movable, editable text annotation stored in native image pixels."""

    item_id: int
    position: QPoint
    text: str
    color_rgba: int
    pixel_size: int

    def rect(self) -> QRect:
        """Return the text's top-left anchored bounds in image pixels."""
        metrics = QFontMetrics(_text_font(self.pixel_size))
        return QRect(
            QPoint(self.position),
            QSize(max(1, metrics.horizontalAdvance(self.text)), metrics.height()),
        )


class _InlineTextEdit(QLineEdit):
    """In-place text box: Enter or clicking elsewhere finishes, Esc cancels."""

    cancelled = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            # Never let Escape reach the editor window, which would close it.
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            event.accept()


# Base image, raster annotations, display size and live text items.
_EditorState = tuple[QImage, QImage, QSize, tuple[_TextItem, ...]]


class ImageCanvas(QWidget):
    """Displays an image and provides non-destructive annotation tools."""

    resize_started = Signal(str, QPoint)
    resize_moved = Signal(QPoint)
    resize_finished = Signal()
    undo_available_changed = Signal(bool)
    redo_available_changed = Signal(bool)

    _HIT_MARGIN = 10
    _HANDLE_SIZE = 10
    _MAX_UNDO_STEPS = 50
    _TEXT_DRAG_THRESHOLD = 3
    # Text-box chrome: 1px border plus Qt's fixed 2px line-edit text margin.
    _TEXT_EDITOR_OFFSET = QPoint(3, 3)
    _TOOLS = {
        "select",
        "arrow",
        "line",
        "ellipse",
        "rectangle",
        "filled_rectangle",
        "brush",
        "eraser",
        "text",
        "crop",
    }
    _DEFAULT_ANNOTATION_COLOR = QColor("#ff3b30")

    def __init__(self, *, resizable: bool = False) -> None:
        super().__init__()
        self._resizable = resizable
        self._tool = "select"
        self._base_image = QImage()
        self._annotations = QImage()
        self._undo_stack: list[_EditorState] = []
        self._redo_stack: list[_EditorState] = []
        self._texts: dict[int, _TextItem] = {}
        self._checkpoint_texts: dict[int, _TextItem] = {}
        self._next_text_id = 1
        self._selected_text_id = 0
        self._text_drag_id = 0
        self._text_drag_origin = QPoint()
        self._text_drag_start = QPoint()
        self._text_drag_moved = False
        self._text_drag_snapshot: tuple[_TextItem, ...] = ()
        self._text_editor: _InlineTextEdit | None = None
        self._text_editing = False
        self._editing_text_id = 0
        self._editing_position = QPoint()
        self._editing_color = QColor()
        self._editing_pixel_size = 0
        self._lightweight_history = False
        self._annotation_commands: list[_AnnotationCommand] = []
        self._annotation_redo_commands: list[_AnnotationCommand] = []
        self._annotation_checkpoint = QImage()
        self._active_command_points: list[QPoint] = []
        self._annotations_visible = True
        self._drawing = False
        self._drag_start = QPoint()
        self._drag_current = QPoint()
        self._brush_last = QPoint()
        self._active_edge = ""
        self._crop_selection = QRect()
        self._crop_resize_edge = ""
        self._crop_resize_origin = QPoint()
        self._crop_resize_start = QRect()
        self._annotation_color = QColor(self._DEFAULT_ANNOTATION_COLOR)
        self._stroke_width = 5
        self._text_size = 24
        self._drawing_cursor = Qt.CursorShape.CrossCursor
        self._presentation_drawing_cursor: QCursor | None = None
        self._presentation_tool_cursors: dict[str, QCursor] = {}

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_image(
        self,
        image: QImage,
        *,
        preserve_resize: bool = False,
        preserve_display_size: bool = False,
    ) -> None:
        """Replace the editable image and start a fresh annotation history."""
        active_edge = self._active_edge if preserve_resize else ""
        display_size = self.size() if preserve_display_size else image.size()
        self._finish_text_editing(commit=False)
        self._base_image = QImage(image)
        self._annotations = self._transparent_layer(self._base_image)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._annotation_commands.clear()
        self._annotation_redo_commands.clear()
        self._annotation_checkpoint = QImage()
        self._texts.clear()
        self._checkpoint_texts.clear()
        self._selected_text_id = 0
        self._text_drag_id = 0
        self._active_command_points.clear()
        self.undo_available_changed.emit(False)
        self.redo_available_changed.emit(False)
        self._drawing = False
        self._active_edge = active_edge
        self._crop_selection = QRect()
        self._crop_resize_edge = ""
        if self._base_image.isNull():
            self.setFixedSize(1, 1)
        else:
            self.setFixedSize(display_size if not display_size.isEmpty() else self._base_image.size())
        self.update()

    def set_lightweight_history_enabled(self, enabled: bool) -> None:
        """Use replayable annotation commands instead of full-image snapshots."""
        enabled = bool(enabled)
        if enabled == self._lightweight_history:
            return
        self._lightweight_history = enabled
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._annotation_commands.clear()
        self._annotation_redo_commands.clear()
        self._annotation_checkpoint = QImage()
        self._checkpoint_texts = dict(self._texts)
        self._active_command_points.clear()
        self.undo_available_changed.emit(False)
        self.redo_available_changed.emit(False)

    @property
    def annotations_visible(self) -> bool:
        """Return whether annotations are currently painted on the canvas."""
        return self._annotations_visible

    def set_annotations_visible(self, visible: bool) -> None:
        """Temporarily show or hide annotations without changing their history."""
        visible = bool(visible)
        if visible == self._annotations_visible:
            return
        if not visible:
            self._finish_text_editing()
        self._annotations_visible = visible
        self.update()

    def replace_image(self, image: QImage) -> None:
        """Replace the rendered image while keeping it undoable and visually stable.

        The replacement is expected to already contain every annotation, so
        both the raster layer and the live text items start empty again.
        """
        if image.isNull():
            return
        self._finish_text_editing()
        display_size = self.size()
        self._push_undo_state()
        self._base_image = QImage(image)
        self._annotations = self._transparent_layer(self._base_image)
        self._texts.clear()
        self._selected_text_id = 0
        self.setFixedSize(display_size if not display_size.isEmpty() else image.size())
        self.update()

    def set_display_size(self, size) -> None:
        """Set the on-screen size without changing the source image resolution."""
        if not self._base_image.isNull():
            self.setFixedSize(size)
            self.update()

    def set_tool(self, tool: str) -> None:
        """Select one editing tool or return to selection-resize mode."""
        if tool not in self._TOOLS:
            return
        self._finish_text_editing()
        if tool not in {"text", "select"}:
            self._selected_text_id = 0
        self._tool = tool
        self._drawing = False
        self._active_edge = ""
        self._crop_resize_edge = ""
        self._crop_selection = QRect(self.rect()) if tool == "crop" else QRect()
        self._update_cursor(self._edge_at(self._drag_current))
        self.update()

    def set_drawing_cursor(self, cursor: Qt.CursorShape) -> None:
        """Set the cursor used by drawing tools without changing resize cursors."""
        self._drawing_cursor = cursor
        self._update_cursor(self._edge_at(self._drag_current))

    def set_presentation_drawing_cursor(
        self,
        cursor: QCursor | Qt.CursorShape | None,
    ) -> None:
        """Override graphical tool cursors while preserving the text caret."""
        self._presentation_drawing_cursor = (
            None if cursor is None else QCursor(cursor)
        )
        self._update_cursor(self._edge_at(self._drag_current))

    def set_presentation_tool_cursor(
        self,
        tool: str,
        cursor: QCursor | Qt.CursorShape | None,
    ) -> None:
        """Override one presentation tool without affecting other cursors."""
        if tool not in self._TOOLS:
            return
        if cursor is None:
            self._presentation_tool_cursors.pop(tool, None)
        else:
            self._presentation_tool_cursors[tool] = QCursor(cursor)
        self._update_cursor(self._edge_at(self._drag_current))

    def apply_crop_selection(self) -> bool:
        """Crop to the adjustable display-space rectangle and keep native pixels."""
        if self._base_image.isNull() or self._crop_selection.isEmpty():
            return False
        display_rect = self._crop_selection.intersected(self.rect())
        image_rect = self._image_rect(display_rect)
        if image_rect.width() < 2 or image_rect.height() < 2:
            return False
        if image_rect == self._base_image.rect():
            self._crop_selection = QRect()
            self.update()
            return True
        self._commit_crop(image_rect, display_rect)
        self._crop_selection = QRect()
        self.update()
        return True

    def set_annotation_color(self, color: QColor) -> None:
        """Use one color for new annotations and recolor the selected text."""
        if not color.isValid():
            return
        self._annotation_color = QColor(color)
        if self._text_editing:
            self._editing_color = QColor(color)
            self._style_text_editor()
            return
        item = self._selected_text()
        if item is not None and item.color_rgba != color.rgba():
            self._store_text(replace(item, color_rgba=color.rgba()))

    def set_stroke_width(self, width: int) -> None:
        """Set the display-space width used by subsequent drawing tools."""
        self._stroke_width = max(1, min(int(width), 16))

    @property
    def stroke_width(self) -> int:
        """Return the selected drawing width in display pixels."""
        return self._stroke_width

    def set_text_size(self, size: int) -> None:
        """Set the text height for new text and resize the selected text."""
        self._text_size = max(12, min(int(size), 72))
        pixel_size = self._native_pen_width(self._text_size)
        if self._text_editing:
            self._editing_pixel_size = pixel_size
            self._style_text_editor()
            return
        item = self._selected_text()
        if item is not None and item.pixel_size != pixel_size:
            self._store_text(replace(item, pixel_size=pixel_size))

    def mirror_horizontal(self) -> None:
        """Mirror image and annotations without changing the selected screen size.

        Text items keep their reading direction and only swap sides.
        """
        if self._base_image.isNull():
            return
        self._finish_text_editing()
        display_size = self.size()
        self._push_undo_state()
        transform = QTransform().scale(-1, 1)
        self._base_image = self._base_image.transformed(transform)
        self._annotations = self._annotations.transformed(transform)
        width = self._base_image.width()
        self._texts = {
            item_id: replace(
                item,
                position=QPoint(
                    width - item.position.x() - item.rect().width(),
                    item.position.y(),
                ),
            )
            for item_id, item in self._texts.items()
        }
        self.setFixedSize(display_size)
        self.update()

    def undo(self) -> None:
        """Restore the most recent image or annotation state."""
        self._finish_text_editing()
        if self._lightweight_history:
            if not self._annotation_commands:
                return
            self._annotation_redo_commands.append(self._annotation_commands.pop())
            self._rebuild_annotations()
            self._forget_missing_selection()
            self.undo_available_changed.emit(bool(self._annotation_commands))
            self.redo_available_changed.emit(True)
            self.update()
            return
        if not self._undo_stack:
            return
        self._append_bounded(self._redo_stack, self._current_state())
        self._restore_state(self._undo_stack.pop())
        self.undo_available_changed.emit(bool(self._undo_stack))
        self.redo_available_changed.emit(True)
        self.update()

    def redo(self) -> None:
        """Restore the most recently undone image or annotation state."""
        self._finish_text_editing()
        if self._lightweight_history:
            if not self._annotation_redo_commands:
                return
            command = self._annotation_redo_commands.pop()
            self._annotation_commands.append(command)
            self._apply_annotation_command(self._annotations, command)
            self._forget_missing_selection()
            self.undo_available_changed.emit(True)
            self.redo_available_changed.emit(bool(self._annotation_redo_commands))
            self.update()
            return
        if not self._redo_stack:
            return
        self._append_bounded(self._undo_stack, self._current_state())
        self._restore_state(self._redo_stack.pop())
        self.undo_available_changed.emit(True)
        self.redo_available_changed.emit(bool(self._redo_stack))
        self.update()

    def clear_annotations(self) -> None:
        """Delete all annotations while preserving the captured image."""
        if self._annotations.isNull():
            return
        self._finish_text_editing()
        self._selected_text_id = 0
        if self._lightweight_history:
            command = self._new_annotation_command("clear")
            self._apply_annotation_command(self._annotations, command)
            self._record_annotation_command(command)
            self.update()
            return
        self._push_undo_state()
        self._annotations.fill(Qt.GlobalColor.transparent)
        self._texts.clear()
        self.update()

    def rendered_image(self) -> QImage:
        """Return the current image with all finished annotations applied."""
        self._finish_text_editing()
        rendered = QImage(self._base_image)
        if rendered.isNull():
            return rendered
        painter = QPainter(rendered)
        try:
            painter.drawImage(0, 0, self._annotations)
            self._paint_text_items(painter)
        finally:
            painter.end()
        return rendered

    def delete_selected_text(self) -> bool:
        """Remove the selected text annotation, if any, as one undoable step."""
        item = self._selected_text()
        if item is None:
            return False
        self._remove_text(item.item_id)
        self._selected_text_id = 0
        self.update()
        return True

    def keyPressEvent(self, event) -> None:
        """Support undo, recovery, and annotation clearing shortcuts."""
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.redo()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            if not self.delete_selected_text():
                self.clear_annotations()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        """Render image, annotations, active shape preview, and resize frame."""
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if not self._base_image.isNull():
                painter.drawImage(self.rect(), self._base_image)
                if self._annotations_visible:
                    painter.drawImage(self.rect(), self._annotations)
                    if self._texts:
                        self._paint_display_texts(painter)
            if self._tool == "crop":
                selection = (
                    QRect(self._drag_start, self._drag_current).normalized()
                    if self._drawing
                    else QRect(self._crop_selection)
                )
                self._draw_crop_frame(painter, selection)
            if self._drawing and self._tool in {
                "arrow",
                "line",
                "ellipse",
                "rectangle",
                "filled_rectangle",
            }:
                self._draw_preview(painter)
            if self._resizable:
                self._draw_resize_frame(painter)
        finally:
            painter.end()

    def mousePressEvent(self, event) -> None:
        """Begin a resize, shape, freehand stroke, erasing, or text placement."""
        if event.button() == Qt.MouseButton.RightButton:
            self._drawing = False
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.redo()
            else:
                self.undo()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or self._base_image.isNull():
            return
        if self._text_editing:
            # The first click outside an open text box only finishes it.
            self._finish_text_editing()
            event.accept()
            return

        self.setFocus(Qt.FocusReason.MouseFocusReason)
        point = event.position().toPoint()
        if self._tool == "crop":
            edge = self._crop_edge_at(point)
            if edge:
                self._crop_resize_edge = edge
                self._crop_resize_origin = point
                self._crop_resize_start = QRect(self._crop_selection)
                self.grabMouse()
                event.accept()
                return
            self._drawing = True
            self._drag_start = point
            self._drag_current = point
            self.update()
            return
        if self._resizable:
            edge = self._edge_at(point)
            if edge:
                self._active_edge = edge
                self.grabMouse()
                self.resize_started.emit(edge, event.globalPosition().toPoint())
                event.accept()
                return

        if self._tool in {"text", "select"}:
            item = self._text_item_at(point)
            if item is not None:
                self._selected_text_id = item.item_id
                self._text_drag_id = item.item_id
                self._text_drag_origin = point
                self._text_drag_start = QPoint(item.position)
                self._text_drag_moved = False
                self._text_drag_snapshot = tuple(self._texts.values())
                self.update()
                event.accept()
                return
            if self._selected_text_id:
                self._selected_text_id = 0
                self.update()
        if self._tool == "text":
            self._begin_text_editing(None, self._to_image(point))
            event.accept()
            return
        if self._tool not in {
            "arrow",
            "line",
            "ellipse",
            "rectangle",
            "filled_rectangle",
            "brush",
            "eraser",
            "crop",
        }:
            return

        self._drawing = True
        self._drag_start = point
        self._drag_current = point
        self._brush_last = self._image_point(point)
        if self._tool in {"brush", "eraser"}:
            if self._lightweight_history:
                self._active_command_points = [QPoint(self._brush_last)]
            else:
                self._push_undo_state()
            self._draw_freehand_segment(self._brush_last, self._brush_last)
            self._request_annotation_update(
                self._freehand_dirty_rect(point, point)
            )
        else:
            self._request_annotation_update(
                self._shape_preview_rect(self._drag_start, self._drag_current)
            )

    def mouseMoveEvent(self, event) -> None:
        """Update a resize operation or active annotation preview."""
        point = event.position().toPoint()
        if self._text_drag_id:
            self._drag_text_to(point)
            event.accept()
            return
        if self._crop_resize_edge:
            self._crop_selection = self._resized_crop_selection(
                self._crop_resize_start,
                self._crop_resize_edge,
                point - self._crop_resize_origin,
            )
            self.update()
            event.accept()
            return
        if self._active_edge:
            self.resize_moved.emit(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drawing:
            previous = QPoint(self._drag_current)
            self._drag_current = point
            if self._tool in {"brush", "eraser"}:
                current = self._image_point(point)
                self._draw_freehand_segment(self._brush_last, current)
                if (
                    self._lightweight_history
                    and (
                        not self._active_command_points
                        or current != self._active_command_points[-1]
                    )
                ):
                    self._active_command_points.append(QPoint(current))
                self._brush_last = current
                self._request_annotation_update(
                    self._freehand_dirty_rect(previous, point)
                )
            else:
                dirty = self._shape_preview_rect(self._drag_start, previous).united(
                    self._shape_preview_rect(self._drag_start, point)
                )
                self._request_annotation_update(dirty)
            return
        if self._tool == "crop":
            self._update_cursor(self._crop_edge_at(point))
            return
        edge = self._edge_at(point)
        if (
            not edge
            and self._tool in {"text", "select"}
            and self._text_item_at(point) is not None
        ):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        self._update_cursor(edge)

    def mouseReleaseEvent(self, event) -> None:
        """Commit an annotation or finish a border resize interaction."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._text_drag_id:
            self._finish_text_drag(event.position().toPoint())
            event.accept()
            return
        if self._crop_resize_edge:
            self._crop_resize_edge = ""
            self.releaseMouse()
            self._update_cursor(self._crop_edge_at(event.position().toPoint()))
            self.update()
            event.accept()
            return
        if self._active_edge:
            self._active_edge = ""
            self.releaseMouse()
            self.resize_finished.emit()
            self._update_cursor(self._edge_at(event.position().toPoint()))
            event.accept()
            return
        if not self._drawing:
            return

        release_previous = QPoint(self._drag_current)
        self._drag_current = event.position().toPoint()
        start = self._image_point(self._drag_start)
        end = self._image_point(self._drag_current)
        if self._tool == "crop":
            display_rect = QRect(self._drag_start, self._drag_current).normalized()
            if display_rect.width() >= 2 and display_rect.height() >= 2:
                self._crop_selection = display_rect.intersected(self.rect())
        elif self._tool in {
            "arrow",
            "line",
            "ellipse",
            "rectangle",
            "filled_rectangle",
        } and start != end:
            if self._lightweight_history:
                command = self._new_annotation_command(
                    self._tool,
                    (start, end),
                )
                self._apply_annotation_command(self._annotations, command)
                self._record_annotation_command(command)
            else:
                self._push_undo_state()
                if self._tool == "arrow":
                    self._commit_arrow(start, end)
                elif self._tool == "line":
                    self._commit_line(start, end)
                elif self._tool == "ellipse":
                    self._commit_ellipse(start, end)
                elif self._tool == "filled_rectangle":
                    self._commit_filled_rectangle(start, end)
                else:
                    self._commit_rectangle(start, end)
        elif self._tool in {"brush", "eraser"}:
            self._draw_freehand_segment(self._brush_last, end)
            if self._lightweight_history:
                if not self._active_command_points or end != self._active_command_points[-1]:
                    self._active_command_points.append(QPoint(end))
                command = self._new_annotation_command(
                    self._tool,
                    tuple(self._active_command_points),
                )
                self._record_annotation_command(command)
                self._active_command_points.clear()
        self._drawing = False
        if self._lightweight_history:
            if self._tool in {"brush", "eraser"}:
                self._request_annotation_update(
                    self._freehand_dirty_rect(release_previous, self._drag_current)
                )
            else:
                self._request_annotation_update(
                    self._shape_preview_rect(self._drag_start, self._drag_current)
                )
        else:
            self.update()

    def _push_undo_state(
        self,
        texts: tuple[_TextItem, ...] | None = None,
    ) -> None:
        """Save a bounded copy of the current (or given earlier) editable state."""
        if self._base_image.isNull():
            return
        state = self._current_state()
        if texts is not None:
            state = (*state[:3], texts)
        self._append_bounded(self._undo_stack, state)
        self._redo_stack.clear()
        self.undo_available_changed.emit(True)
        self.redo_available_changed.emit(False)

    def _current_state(self) -> _EditorState:
        """Return an isolated copy of the current editable state."""
        return (
            QImage(self._base_image),
            QImage(self._annotations),
            QSize(self.size()),
            tuple(self._texts.values()),
        )

    def _restore_state(self, state: _EditorState) -> None:
        """Restore one image, annotation, display-size and text snapshot."""
        base_image, annotations, display_size, texts = state
        self._base_image = QImage(base_image)
        self._annotations = QImage(annotations)
        self._texts = {item.item_id: item for item in texts}
        self._forget_missing_selection()
        self.setFixedSize(display_size)

    def _append_bounded(
        self,
        stack: list[_EditorState],
        state: _EditorState,
    ) -> None:
        """Append one history snapshot while enforcing the shared size limit."""
        stack.append(state)
        if len(stack) > self._MAX_UNDO_STEPS:
            del stack[0]

    def _new_annotation_command(
        self,
        tool: str,
        points: tuple[QPoint, ...] = (),
        *,
        text: str = "",
        text_size: int = 0,
    ) -> _AnnotationCommand:
        """Capture the current drawing properties in one compact command."""
        return _AnnotationCommand(
            tool=tool,
            color_rgba=self._annotation_color.rgba(),
            width=self._stroke_width,
            points=tuple(QPoint(point) for point in points),
            text=text,
            text_size=text_size,
        )

    def _record_annotation_command(self, command: _AnnotationCommand) -> None:
        """Add one lightweight undo step and fold expired steps into a checkpoint."""
        self._annotation_commands.append(command)
        self._annotation_redo_commands.clear()
        if len(self._annotation_commands) > self._MAX_UNDO_STEPS:
            expired = self._annotation_commands.pop(0)
            if self._annotation_checkpoint.isNull():
                self._annotation_checkpoint = self._transparent_layer(self._base_image)
            self._apply_annotation_command(
                self._annotation_checkpoint,
                expired,
                self._checkpoint_texts,
            )
        self.undo_available_changed.emit(True)
        self.redo_available_changed.emit(False)

    def _rebuild_annotations(self) -> None:
        """Replay lightweight commands after undo without retaining image snapshots."""
        self._annotations.fill(Qt.GlobalColor.transparent)
        if not self._annotation_checkpoint.isNull():
            painter = QPainter(self._annotations)
            try:
                painter.drawImage(0, 0, self._annotation_checkpoint)
            finally:
                painter.end()
        texts = dict(self._checkpoint_texts)
        for command in self._annotation_commands:
            self._apply_annotation_command(self._annotations, command, texts)
        self._texts = texts

    def _apply_annotation_command(
        self,
        layer: QImage,
        command: _AnnotationCommand,
        texts: dict[int, _TextItem] | None = None,
    ) -> None:
        """Apply one replayable command to an annotation layer and its texts."""
        if texts is None:
            texts = self._texts
        if command.tool == "clear":
            layer.fill(Qt.GlobalColor.transparent)
            texts.clear()
            return
        if command.tool == "text_delete":
            texts.pop(command.item_id, None)
            return
        if command.tool == "text_set":
            texts[command.item_id] = _TextItem(
                command.item_id,
                QPoint(command.points[0]),
                command.text,
                command.color_rgba,
                command.text_size,
            )
            return
        if not command.points:
            return
        color = QColor.fromRgba(command.color_rgba)
        painter = QPainter(layer)
        try:
            if command.tool in {"brush", "eraser"}:
                if command.tool == "eraser":
                    painter.setCompositionMode(
                        QPainter.CompositionMode.CompositionMode_Clear
                    )
                    width = self._native_pen_width(max(12, command.width * 4))
                    pen = QPen(
                        Qt.GlobalColor.transparent,
                        width,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                else:
                    width = self._native_pen_width(command.width)
                    pen = QPen(
                        color,
                        width,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                painter.setPen(pen)
                points = command.points
                if len(points) == 1:
                    painter.drawLine(points[0], points[0])
                else:
                    for start, end in zip(points, points[1:]):
                        painter.drawLine(start, end)
                if command.tool == "eraser":
                    self._erase_texts(texts, points, width)
                return
            start, end = command.points[0], command.points[-1]
            width = self._native_pen_width(command.width)
            if command.tool == "arrow":
                self._draw_arrow(painter, start, end, width, color)
            elif command.tool == "line":
                painter.setPen(QPen(color, width))
                painter.drawLine(start, end)
            elif command.tool == "ellipse":
                painter.setPen(QPen(color, width))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QRect(start, end).normalized())
            elif command.tool == "filled_rectangle":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRect(QRect(start, end).normalized())
            elif command.tool == "rectangle":
                painter.setPen(QPen(color, width))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRect(start, end).normalized())
        finally:
            painter.end()

    def _request_annotation_update(self, rect: QRect | None = None) -> None:
        """Request a local presentation repaint while retaining normal editor behavior."""
        if self._lightweight_history and rect is not None:
            dirty = rect.normalized().intersected(self.rect())
            if not dirty.isEmpty():
                self.update(dirty)
            return
        self.update()

    def _freehand_dirty_rect(self, start: QPoint, end: QPoint) -> QRect:
        """Return the display-space area touched by one freehand segment."""
        width = (
            max(12, self._stroke_width * 4)
            if self._tool == "eraser"
            else self._stroke_width
        )
        margin = width // 2 + 3
        return QRect(start, end).normalized().adjusted(-margin, -margin, margin, margin)

    def _shape_preview_rect(self, start: QPoint, end: QPoint) -> QRect:
        """Return the display-space area occupied by a shape and its preview."""
        margin = max(self._stroke_width * 5, 16) if self._tool == "arrow" else self._stroke_width + 3
        return QRect(start, end).normalized().adjusted(-margin, -margin, margin, margin)

    @staticmethod
    def _transparent_layer(image: QImage) -> QImage:
        layer = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        return layer

    def _image_point(self, point: QPoint) -> QPoint:
        """Map one local display coordinate into native image coordinates."""
        if self.width() <= 0 or self.height() <= 0 or self._base_image.isNull():
            return QPoint()
        x = round(point.x() * self._base_image.width() / self.width())
        y = round(point.y() * self._base_image.height() / self.height())
        return QPoint(
            max(0, min(x, self._base_image.width() - 1)),
            max(0, min(y, self._base_image.height() - 1)),
        )

    def _image_rect(self, display_rect: QRect) -> QRect:
        """Map a display rectangle to native pixels without losing edge pixels."""
        if self.width() <= 0 or self.height() <= 0 or self._base_image.isNull():
            return QRect()
        left = floor(display_rect.left() * self._base_image.width() / self.width())
        top = floor(display_rect.top() * self._base_image.height() / self.height())
        right = ceil((display_rect.right() + 1) * self._base_image.width() / self.width())
        bottom = ceil((display_rect.bottom() + 1) * self._base_image.height() / self.height())
        return QRect(left, top, right - left, bottom - top).intersected(
            self._base_image.rect()
        )

    def _draw_crop_frame(self, painter: QPainter, selection: QRect) -> None:
        """Dim the discarded area and draw the adjustable crop boundary."""
        selection = selection.intersected(self.rect())
        if selection.isEmpty():
            return
        shade = QColor(0, 0, 0, 115)
        bounds = self.rect()
        painter.fillRect(QRect(bounds.left(), bounds.top(), bounds.width(), selection.top()), shade)
        painter.fillRect(
            QRect(bounds.left(), selection.bottom() + 1, bounds.width(), bounds.bottom() - selection.bottom()),
            shade,
        )
        painter.fillRect(
            QRect(bounds.left(), selection.top(), selection.left() - bounds.left(), selection.height()),
            shade,
        )
        painter.fillRect(
            QRect(selection.right() + 1, selection.top(), bounds.right() - selection.right(), selection.height()),
            shade,
        )
        painter.setPen(QPen(QColor("#2da9ff"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(selection.adjusted(1, 1, -1, -1))
        painter.setBrush(QColor("#ffffff"))
        for point in self._crop_handle_points(selection):
            painter.drawRect(point.x() - 4, point.y() - 4, 8, 8)

    def _draw_preview(self, painter: QPainter) -> None:
        """Draw an uncommitted shape in display coordinates."""
        rect = QRect(self._drag_start, self._drag_current).normalized()
        if self._tool == "crop":
            painter.setPen(QPen(QColor("#2da9ff"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(45, 169, 255, 45))
            painter.drawRect(rect)
            return
        if self._tool == "arrow":
            self._draw_arrow(painter, self._drag_start, self._drag_current, self._stroke_width)
            return
        painter.setPen(QPen(self._annotation_color, self._stroke_width))
        painter.setBrush(
            self._annotation_color
            if self._tool == "filled_rectangle"
            else Qt.BrushStyle.NoBrush
        )
        if self._tool == "line":
            painter.drawLine(self._drag_start, self._drag_current)
        elif self._tool == "ellipse":
            painter.drawEllipse(rect)
        else:
            painter.drawRect(rect)

    def _commit_arrow(self, start: QPoint, end: QPoint) -> None:
        painter = QPainter(self._annotations)
        try:
            self._draw_arrow(painter, start, end, self._native_pen_width(self._stroke_width))
        finally:
            painter.end()

    def _commit_line(self, start: QPoint, end: QPoint) -> None:
        painter = QPainter(self._annotations)
        try:
            painter.setPen(QPen(self._annotation_color, self._native_pen_width(self._stroke_width)))
            painter.drawLine(start, end)
        finally:
            painter.end()

    def _commit_ellipse(self, start: QPoint, end: QPoint) -> None:
        painter = QPainter(self._annotations)
        try:
            painter.setPen(QPen(self._annotation_color, self._native_pen_width(self._stroke_width)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRect(start, end).normalized())
        finally:
            painter.end()

    def _commit_rectangle(self, start: QPoint, end: QPoint) -> None:
        painter = QPainter(self._annotations)
        try:
            painter.setPen(QPen(self._annotation_color, self._native_pen_width(self._stroke_width)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRect(start, end).normalized())
        finally:
            painter.end()

    def _commit_filled_rectangle(self, start: QPoint, end: QPoint) -> None:
        """Cover the selected rectangle with the active solid color."""
        painter = QPainter(self._annotations)
        try:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._annotation_color)
            painter.drawRect(QRect(start, end).normalized())
        finally:
            painter.end()

    def _commit_crop(self, image_rect: QRect, display_rect: QRect) -> None:
        """Crop the source and annotations to one user-dragged rectangle."""
        image_rect = image_rect.intersected(self._base_image.rect())
        display_rect = display_rect.intersected(self.rect())
        if image_rect.width() < 2 or image_rect.height() < 2:
            return
        if display_rect.width() < 2 or display_rect.height() < 2:
            return
        self._push_undo_state()
        self._base_image = self._base_image.copy(image_rect)
        self._annotations = self._annotations.copy(image_rect)
        offset = image_rect.topLeft()
        self._texts = {
            item_id: replace(item, position=item.position - offset)
            for item_id, item in self._texts.items()
        }
        self.setFixedSize(display_rect.size())
        self._drag_start = QPoint()
        self._drag_current = QPoint()

    def _crop_edge_at(self, point: QPoint) -> str:
        """Return the crop edge or corner under the pointer."""
        rect = self._crop_selection
        if rect.isEmpty():
            return ""
        margin = self._HIT_MARGIN
        near_left = abs(point.x() - rect.left()) <= margin
        near_right = abs(point.x() - rect.right()) <= margin
        near_top = abs(point.y() - rect.top()) <= margin
        near_bottom = abs(point.y() - rect.bottom()) <= margin
        within_x = rect.left() - margin <= point.x() <= rect.right() + margin
        within_y = rect.top() - margin <= point.y() <= rect.bottom() + margin
        vertical = "top" if near_top else "bottom" if near_bottom else ""
        horizontal = "left" if near_left else "right" if near_right else ""
        if vertical and horizontal:
            return f"{vertical}-{horizontal}"
        if vertical and within_x:
            return vertical
        if horizontal and within_y:
            return horizontal
        return ""

    def _resized_crop_selection(self, initial: QRect, edge: str, delta: QPoint) -> QRect:
        """Resize one crop edge while retaining a usable image area."""
        bounds = self.rect()
        minimum = 8
        left, right = initial.left(), initial.right()
        top, bottom = initial.top(), initial.bottom()
        if "left" in edge:
            left = max(bounds.left(), min(left + delta.x(), right - minimum + 1))
        if "right" in edge:
            right = min(bounds.right(), max(right + delta.x(), left + minimum - 1))
        if "top" in edge:
            top = max(bounds.top(), min(top + delta.y(), bottom - minimum + 1))
        if "bottom" in edge:
            bottom = min(bounds.bottom(), max(bottom + delta.y(), top + minimum - 1))
        return QRect(left, top, right - left + 1, bottom - top + 1)

    @staticmethod
    def _crop_handle_points(rect: QRect) -> tuple[QPoint, ...]:
        """Return eight visible crop handles."""
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

    def _draw_freehand_segment(self, start: QPoint, end: QPoint) -> None:
        painter = QPainter(self._annotations)
        try:
            if self._tool == "eraser":
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                width = self._native_pen_width(max(12, self._stroke_width * 4))
                pen = QPen(Qt.GlobalColor.transparent, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            else:
                width = self._native_pen_width(self._stroke_width)
                pen = QPen(self._annotation_color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(start, end)
        finally:
            painter.end()
        if self._tool == "eraser" and self._texts:
            self._erase_texts(self._texts, (start, end), width)
            self.update()

    def _draw_arrow(
        self,
        painter: QPainter,
        start: QPoint,
        end: QPoint,
        width: int,
        color: QColor | None = None,
    ) -> None:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if dx * dx + dy * dy < 16:
            return
        pen = QPen(
            color or self._annotation_color,
            width,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
        painter.setPen(pen)
        painter.drawLine(start, end)
        angle = atan2(dy, dx)
        head_length = max(width * 4, 12)
        left = QPoint(
            round(end.x() - head_length * cos(angle - 0.55)),
            round(end.y() - head_length * sin(angle - 0.55)),
        )
        right = QPoint(
            round(end.x() - head_length * cos(angle + 0.55)),
            round(end.y() - head_length * sin(angle + 0.55)),
        )
        painter.drawLine(end, left)
        painter.drawLine(end, right)

    # ----- Text annotations ---------------------------------------------------

    def _selected_text(self) -> _TextItem | None:
        """Return the selected text while a text-capable tool is active."""
        if self._tool not in {"text", "select"}:
            return None
        return self._texts.get(self._selected_text_id)

    def _forget_missing_selection(self) -> None:
        if self._selected_text_id not in self._texts:
            self._selected_text_id = 0

    def _to_image(self, point: QPoint) -> QPoint:
        """Map a display point to image pixels without clamping to the image."""
        if self.width() <= 0 or self.height() <= 0 or self._base_image.isNull():
            return QPoint(point)
        return QPoint(
            round(point.x() * self._base_image.width() / self.width()),
            round(point.y() * self._base_image.height() / self.height()),
        )

    def _to_display(self, point: QPoint) -> QPoint:
        """Map an image pixel position to this widget's display coordinates."""
        if self._base_image.isNull() or self._base_image.width() <= 0:
            return QPoint(point)
        return QPoint(
            round(point.x() * self.width() / self._base_image.width()),
            round(point.y() * self.height() / self._base_image.height()),
        )

    def _display_text_size(self, pixel_size: int) -> int:
        """Convert a native font height to the height shown on screen."""
        if self._base_image.isNull() or self._base_image.height() <= 0:
            return pixel_size
        return max(1, round(pixel_size * self.height() / self._base_image.height()))

    def _text_item_at(self, display_point: QPoint) -> _TextItem | None:
        """Return the top-most visible text under a display point."""
        if not self._annotations_visible:
            return None
        point = self._to_image(display_point)
        margin = max(2, self._native_pen_width(4))
        for item in reversed(list(self._texts.values())):
            if item.rect().adjusted(-margin, -margin, margin, margin).contains(point):
                return item
        return None

    def _paint_text_items(self, painter: QPainter, skip_id: int = 0) -> None:
        """Paint every text item in image coordinates."""
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for item in self._texts.values():
            if item.item_id == skip_id:
                continue
            painter.setFont(_text_font(item.pixel_size))
            painter.setPen(QColor.fromRgba(item.color_rgba))
            metrics = painter.fontMetrics()
            painter.drawText(
                item.position + QPoint(0, metrics.ascent()),
                item.text,
            )

    def _paint_display_texts(self, painter: QPainter) -> None:
        """Paint text items scaled to the display and mark the selected one."""
        image_width = self._base_image.width()
        image_height = self._base_image.height()
        if image_width <= 0 or image_height <= 0:
            return
        skip_id = self._editing_text_id if self._text_editing else 0
        painter.save()
        try:
            painter.scale(self.width() / image_width, self.height() / image_height)
            self._paint_text_items(painter, skip_id)
        finally:
            painter.restore()
        selected = self._texts.get(self._selected_text_id)
        if selected is None or selected.item_id == skip_id:
            return
        rect = selected.rect()
        frame = QRect(
            self._to_display(rect.topLeft()),
            self._to_display(rect.bottomRight() + QPoint(1, 1)),
        ).adjusted(-3, -3, 3, 3)
        painter.save()
        try:
            painter.setPen(QPen(QColor("#2da9ff"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(frame)
        finally:
            painter.restore()

    def _store_text(
        self,
        item: _TextItem,
        previous_texts: tuple[_TextItem, ...] | None = None,
    ) -> None:
        """Add or replace one text item as a single undoable step."""
        if self._lightweight_history:
            command = _AnnotationCommand(
                tool="text_set",
                color_rgba=item.color_rgba,
                width=0,
                points=(QPoint(item.position),),
                text=item.text,
                text_size=item.pixel_size,
                item_id=item.item_id,
            )
            self._apply_annotation_command(self._annotations, command)
            self._record_annotation_command(command)
        else:
            self._push_undo_state(previous_texts)
            self._texts[item.item_id] = item
        self.update()

    def _remove_text(self, item_id: int) -> None:
        """Delete one text item as a single undoable step."""
        if item_id not in self._texts:
            return
        if self._lightweight_history:
            command = _AnnotationCommand(
                tool="text_delete",
                color_rgba=0,
                width=0,
                item_id=item_id,
            )
            self._apply_annotation_command(self._annotations, command)
            self._record_annotation_command(command)
        else:
            self._push_undo_state()
            del self._texts[item_id]
        self.update()

    @staticmethod
    def _erase_texts(
        texts: dict[int, _TextItem],
        points: tuple[QPoint, ...],
        width: int,
    ) -> None:
        """Remove every text item touched by an eraser stroke."""
        if not texts or not points:
            return
        margin = max(1, width // 2)
        segments = list(zip(points, points[1:])) or [(points[0], points[0])]
        areas = [
            QRect(start, end).normalized().adjusted(-margin, -margin, margin, margin)
            for start, end in segments
        ]
        for item_id, item in list(texts.items()):
            bounds = item.rect()
            if any(area.intersects(bounds) for area in areas):
                del texts[item_id]

    def _drag_text_to(self, display_point: QPoint) -> None:
        """Move the dragged text with the mouse, without recording history yet."""
        item = self._texts.get(self._text_drag_id)
        if item is None:
            self._text_drag_id = 0
            return
        delta = display_point - self._text_drag_origin
        if (
            not self._text_drag_moved
            and delta.manhattanLength() < self._TEXT_DRAG_THRESHOLD
        ):
            return
        self._text_drag_moved = True
        image_delta = self._to_image(display_point) - self._to_image(self._text_drag_origin)
        self._texts[item.item_id] = replace(
            item,
            position=self._text_drag_start + image_delta,
        )
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.update()

    def _finish_text_drag(self, display_point: QPoint) -> None:
        """Record a completed move, or open the text for editing after a click."""
        item_id = self._text_drag_id
        self._text_drag_id = 0
        item = self._texts.get(item_id)
        if item is None:
            return
        if self._text_drag_moved:
            if self._lightweight_history:
                self._store_text(item)
            else:
                self._store_text(item, self._text_drag_snapshot)
        else:
            self._begin_text_editing(item, item.position)
        self._text_drag_snapshot = ()
        self._text_drag_moved = False

    def _ensure_text_editor(self) -> _InlineTextEdit:
        if self._text_editor is None:
            editor = _InlineTextEdit(self)
            editor.setFrame(False)
            editor.hide()
            editor.textChanged.connect(self._fit_text_editor)
            editor.editingFinished.connect(self._finish_text_editing)
            editor.cancelled.connect(lambda: self._finish_text_editing(commit=False))
            self._text_editor = editor
        return self._text_editor

    def _begin_text_editing(self, item: _TextItem | None, position: QPoint) -> None:
        """Open the in-place text box for a new or an existing text item."""
        editor = self._ensure_text_editor()
        if item is None:
            self._editing_text_id = 0
            self._editing_color = QColor(self._annotation_color)
            self._editing_pixel_size = self._native_pen_width(self._text_size)
            text = ""
        else:
            self._editing_text_id = item.item_id
            self._editing_color = QColor.fromRgba(item.color_rgba)
            self._editing_pixel_size = item.pixel_size
            text = item.text
        self._selected_text_id = self._editing_text_id
        self._editing_position = QPoint(position)
        self._text_editing = True
        editor.setText(text)
        self._style_text_editor()
        editor.show()
        editor.raise_()
        # The editor lives inside this canvas's own window, so it can never
        # open behind a full-screen top-most screenshot or presentation layer.
        self.window().activateWindow()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        editor.setCursorPosition(len(text))
        self.update()

    def _style_text_editor(self) -> None:
        """Match the text box font and color to the text being edited."""
        editor = self._text_editor
        if editor is None:
            return
        color = self._editing_color.name()
        editor.setStyleSheet(
            "QLineEdit {"
            f" color: {color}; background-color: rgba(255, 255, 255, 215);"
            " border: 1px dashed #2da9ff; padding: 0px; margin: 0px;"
            " selection-color: #ffffff; selection-background-color: #1677c8; }"
        )
        editor.setFont(_text_font(self._display_text_size(self._editing_pixel_size)))
        self._fit_text_editor()

    def _fit_text_editor(self) -> None:
        """Grow the text box with its content and keep text on the anchor."""
        editor = self._text_editor
        if editor is None:
            return
        metrics = QFontMetrics(editor.font())
        width = metrics.horizontalAdvance(editor.text() or "  ") + 24
        height = metrics.height() + 2 * self._TEXT_EDITOR_OFFSET.y()
        editor.setGeometry(
            QRect(
                self._to_display(self._editing_position) - self._TEXT_EDITOR_OFFSET,
                QSize(width, height),
            )
        )

    def _finish_text_editing(self, commit: bool = True) -> None:
        """Close the text box, saving its content unless editing was cancelled."""
        if not self._text_editing:
            return
        self._text_editing = False
        editor = self._text_editor
        text = editor.text() if editor is not None else ""
        item_id = self._editing_text_id
        if editor is not None:
            editor.hide()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if not commit:
            self._forget_missing_selection()
            self.update()
            return
        if not text.strip():
            self._remove_text(item_id)
            self._selected_text_id = 0
            self.update()
            return
        if not item_id:
            item_id = self._next_text_id
            self._next_text_id += 1
        item = _TextItem(
            item_id,
            QPoint(self._editing_position),
            text,
            self._editing_color.rgba(),
            self._editing_pixel_size,
        )
        if self._texts.get(item_id) != item:
            self._store_text(item)
        self._selected_text_id = item_id
        self.update()

    def _native_pen_width(self, display_width: int) -> int:
        if self.width() <= 0:
            return display_width
        return max(1, round(display_width * self._base_image.width() / self.width()))

    def _draw_resize_frame(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#2da9ff"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        painter.setBrush(QColor("#ffffff"))
        for point in self._handle_points():
            painter.drawRect(
                point.x() - self._HANDLE_SIZE // 2,
                point.y() - self._HANDLE_SIZE // 2,
                self._HANDLE_SIZE,
                self._HANDLE_SIZE,
            )

    def _edge_at(self, point: QPoint) -> str:
        if not self._resizable:
            return ""
        left = point.x() <= self._HIT_MARGIN
        right = point.x() >= self.width() - self._HIT_MARGIN
        top = point.y() <= self._HIT_MARGIN
        bottom = point.y() >= self.height() - self._HIT_MARGIN
        if top and left:
            return "top-left"
        if top and right:
            return "top-right"
        if bottom and left:
            return "bottom-left"
        if bottom and right:
            return "bottom-right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return ""

    def _handle_points(self) -> tuple[QPoint, ...]:
        center_x = self.width() // 2
        center_y = self.height() // 2
        return (
            QPoint(1, 1), QPoint(center_x, 1), QPoint(self.width() - 2, 1),
            QPoint(1, center_y), QPoint(self.width() - 2, center_y),
            QPoint(1, self.height() - 2), QPoint(center_x, self.height() - 2),
            QPoint(self.width() - 2, self.height() - 2),
        )

    def _update_cursor(self, edge: str) -> None:
        cursors = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "top-left": Qt.CursorShape.SizeFDiagCursor,
            "bottom-right": Qt.CursorShape.SizeFDiagCursor,
            "top-right": Qt.CursorShape.SizeBDiagCursor,
            "bottom-left": Qt.CursorShape.SizeBDiagCursor,
        }
        if edge:
            self.setCursor(cursors[edge])
        elif self._tool == "text":
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif self._tool in self._presentation_tool_cursors:
            self.setCursor(self._presentation_tool_cursors[self._tool])
        elif (
            self._presentation_drawing_cursor is not None
            and self._tool in self._TOOLS - {"select", "text", "crop"}
        ):
            self.setCursor(self._presentation_drawing_cursor)
        elif self._tool in self._TOOLS - {"select", "text"}:
            self.setCursor(self._drawing_cursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
