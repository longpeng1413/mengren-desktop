"""Transparent full-desktop annotation layer used by F5 presentation mode."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QPoint, QRect, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeySequence
from PySide6.QtWidgets import QWidget

from app.preferences import PresentationShortcutSettings
from ui.drawing_cursors import brush_cursor, eraser_cursor
from ui.image_canvas import ImageCanvas
from ui.presentation_toolbar import PresentationToolbar


class PresentationOverlay(QWidget):
    """Draw over the desktop, optionally passing mouse input through to apps."""

    closed = Signal()

    _GWL_EXSTYLE = -20
    _WS_EX_TRANSPARENT = 0x00000020
    _WDA_EXCLUDEFROMCAPTURE = 0x00000011
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010
    _SWP_FRAMECHANGED = 0x0020

    def __init__(
        self,
        geometry: QRect,
        shortcuts: PresentationShortcutSettings,
    ) -> None:
        super().__init__()
        self._desktop_geometry = QRect(geometry)
        self._pointer_mode = False
        self._annotations_visible = True
        self._active_tool = "brush"
        self._suspended = False
        self._toolbar_user_position: QPoint | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(self._desktop_geometry)

        layer = QImage(self._desktop_geometry.size(), QImage.Format.Format_ARGB32_Premultiplied)
        # A fully zero-alpha layered window is treated as click-through by
        # Windows before Qt can receive a mouse event.  Alpha 1 is visually
        # indistinguishable but gives the canvas a reliable hit-test surface.
        layer.fill(QColor(0, 0, 0, 1))
        self._canvas = ImageCanvas()
        self._canvas.setParent(self)
        self._canvas.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._canvas.set_lightweight_history_enabled(True)
        self._canvas.set_image(layer)
        self._canvas.setGeometry(self.rect())
        self._canvas.set_presentation_drawing_cursor(brush_cursor())
        self._canvas.set_presentation_tool_cursor("eraser", eraser_cursor())
        self._canvas.set_tool("brush")

        # A native owner relationship keeps this top-level tool window above
        # its full-desktop drawing surface when menus or dialogs close.
        self._toolbar = PresentationToolbar(shortcuts, self)
        self._toolbar.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._toolbar.setFixedSize(self._toolbar.sizeHint())
        self._toolbar.tool_selected.connect(self.select_tool)
        self._toolbar.pointer_requested.connect(self.toggle_pointer_brush)
        self._toolbar.visibility_requested.connect(self.toggle_annotations_visibility)
        self._toolbar.color_changed.connect(self._set_annotation_color)
        self._toolbar.stroke_width_changed.connect(self._set_stroke_width)
        self._toolbar.undo_requested.connect(self._canvas.undo)
        self._toolbar.redo_requested.connect(self._canvas.redo)
        self._toolbar.clear_requested.connect(self._canvas.clear_annotations)
        self._toolbar.close_requested.connect(self.close)
        self._toolbar.position_changed.connect(self._remember_toolbar_position)

    @property
    def pointer_mode(self) -> bool:
        """Return whether mouse input currently passes to underlying applications."""
        return self._pointer_mode

    @property
    def active_tool(self) -> str:
        """Return the current drawing tool for status and tests."""
        return self._active_tool

    @property
    def annotations_visible(self) -> bool:
        """Return whether saved annotations are currently displayed."""
        return self._annotations_visible

    def execute_shortcut(self, action: str) -> None:
        """Execute one configured presentation-mode shortcut action."""
        if action == "pointer_brush_toggle":
            self.toggle_pointer_brush()
        elif action == "clear":
            self._canvas.clear_annotations()
        elif action == "undo":
            self._canvas.undo()
        elif action == "redo":
            self._canvas.redo()
        elif action in {
            "brush", "line", "rectangle", "filled_rectangle", "ellipse", "arrow", "text", "eraser"
        }:
            self.select_tool(action)

    def restore_toolbar(self) -> None:
        """Publicly restore controls after a notification or dialog changes z-order."""
        self._raise_toolbar()
        QTimer.singleShot(0, self._raise_toolbar)

    def select_tool(self, tool: str) -> None:
        """Leave pointer mode and activate one drawing tool."""
        self._active_tool = tool
        # Apply the requested drawing tool before touching native window state.
        # A z-order or click-through failure must never leave the canvas stuck
        # on the previously selected brush.
        self._canvas.set_tool(tool)
        self._toolbar.set_active_tool(tool)
        self._set_annotations_visible(True)
        self._set_pointer_mode(False)

    def toggle_pointer_brush(self) -> None:
        """Switch between desktop mouse access and the last drawing tool."""
        if self._pointer_mode:
            self.select_tool(self._active_tool or "brush")
        else:
            self._set_pointer_mode(True)

    def toggle_annotations_visibility(self) -> None:
        """Hide annotations for desktop access or restore them for drawing."""
        if self._annotations_visible:
            self._set_annotations_visible(False)
            self._set_pointer_mode(True)
        else:
            self.select_tool(self._active_tool or "brush")

    def _set_annotations_visible(self, visible: bool) -> None:
        """Synchronize annotation visibility between canvas and toolbar."""
        self._annotations_visible = bool(visible)
        self._canvas.set_annotations_visible(self._annotations_visible)
        self._toolbar.set_annotations_visible(self._annotations_visible)

    def _set_annotation_color(self, color: QColor) -> None:
        """Apply a color and restore the toolbar after the color dialog closes."""
        self._canvas.set_annotation_color(color)
        self._restore_toolbar_after_popup()

    def _set_stroke_width(self, width: int) -> None:
        """Apply a line width and restore the toolbar after its menu closes."""
        self._canvas.set_stroke_width(width)
        self._restore_toolbar_after_popup()

    def _restore_toolbar_after_popup(self) -> None:
        """Keep popup menus from returning the drawing layer above the toolbar."""
        self._raise_toolbar()
        QTimer.singleShot(0, self._raise_toolbar)
        QTimer.singleShot(75, self._raise_toolbar)
        QTimer.singleShot(200, self._raise_toolbar)

    def suspend(self) -> None:
        """Hide presentation UI after its annotations were captured by F1."""
        if self._suspended:
            return
        self._suspended = True
        self._toolbar.hide()
        self.hide()

    def resume(self) -> None:
        """Restore presentation mode after the F1 editor closes or is cancelled."""
        if not self._suspended:
            return
        self._suspended = False
        self.show()
        self.raise_()
        self._position_toolbar()
        self._raise_toolbar()

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Undo):
            self._canvas.undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self._canvas.redo()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setGeometry(self._desktop_geometry)
        self._canvas.setGeometry(self.rect())
        self._position_toolbar()
        self._raise_toolbar()
        # CaptureService activates and raises the full-desktop drawing window
        # immediately after show(). Queue one final toolbar raise so the very
        # first F5 session is clickable without toggling mouse mode first.
        QTimer.singleShot(0, self._raise_toolbar)

    def closeEvent(self, event) -> None:
        self._toolbar.close()
        super().closeEvent(event)
        self.closed.emit()

    def _set_pointer_mode(self, enabled: bool) -> None:
        if enabled == self._pointer_mode:
            self._toolbar.set_pointer_mode(enabled)
            return
        self._pointer_mode = enabled
        # Reflect the shortcut immediately. Native full-screen window changes
        # can take noticeably longer and must not leave the toolbar displaying
        # the stale brush state.
        self._toolbar.set_pointer_mode(enabled)
        if sys.platform == "win32":
            # WS_EX_TRANSPARENT already makes the complete native overlay pass
            # input through. Avoid toggling two large Qt widget attributes as
            # well, which can recreate their backing windows and delay F5.
            self._set_windows_click_through(enabled)
        else:
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                enabled,
            )
            self._canvas.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                enabled,
            )
        if not enabled:
            self.show()
            self.raise_()
            self.activateWindow()
            # Both windows are top-most. Raising the drawing surface after a
            # tool click otherwise places it above its own toolbar, making the
            # next tool button appear visible but unable to receive the click.
            self._raise_toolbar()

    def _position_toolbar(self) -> None:
        if self._toolbar_user_position is not None:
            self._toolbar.move(self._toolbar_user_position)
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        bounds = screen.availableGeometry()
        x = bounds.center().x() - self._toolbar.width() // 2
        y = bounds.bottom() - self._toolbar.height() - 18
        self._toolbar.move(x, y)

    def _remember_toolbar_position(self, position: QPoint) -> None:
        """Keep the teacher's chosen toolbar position for this F5 session."""
        self._toolbar_user_position = QPoint(position)

    def _raise_toolbar(self) -> None:
        """Keep the independent controls above the full-desktop drawing layer."""
        if self._suspended:
            return
        self._toolbar.show()
        self._toolbar.raise_()
        if sys.platform == "win32":
            ctypes.windll.user32.SetWindowPos(
                int(self._toolbar.winId()),
                -1,
                0,
                0,
                0,
                0,
                self._SWP_NOSIZE
                | self._SWP_NOMOVE
                | self._SWP_NOACTIVATE,
            )
        self._exclude_toolbar_from_capture()

    def _set_windows_click_through(self, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, self._GWL_EXSTYLE)
        if enabled:
            style |= self._WS_EX_TRANSPARENT
        else:
            style &= ~self._WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, self._GWL_EXSTYLE, style)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            self._SWP_NOSIZE
            | self._SWP_NOMOVE
            | self._SWP_NOZORDER
            | self._SWP_NOACTIVATE
            | self._SWP_FRAMECHANGED,
        )

    def _exclude_toolbar_from_capture(self) -> None:
        if sys.platform == "win32":
            ctypes.windll.user32.SetWindowDisplayAffinity(
                int(self._toolbar.winId()),
                self._WDA_EXCLUDEFROMCAPTURE,
            )
