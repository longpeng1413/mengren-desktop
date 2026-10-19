"""WeChat-style borderless editor shown at the original F1 selection position."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Signal, Qt, QThread
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from app.branding import APP_DISPLAY_NAME, DEFAULT_IMAGE_FILENAME
from core.capture.desktop_capture import DesktopSnapshot
from ui.resizable_frame import ResizableFrame
from ui.toolbar import EditorToolbar
from ui.translation_worker import TranslationWorker


def spanned_host_geometry(
    selection: QRect,
    screens: list[tuple[QRect, float]],
) -> QRect | None:
    """Return one window rectangle for editing the selection in place.

    It covers every screen the selection touches plus every other screen of the
    same scaling, so a screenshot taken on one screen can still be dragged out
    across the others. Screens with different scaling do not share one
    coordinate space: they are left out, and ``None`` means the selection
    itself crosses them so no single window can host it.
    """
    touched = [(geometry, ratio) for geometry, ratio in screens if geometry.intersects(selection)]
    if not touched:
        return None
    ratios = {round(ratio, 3) for _geometry, ratio in touched}
    if len(ratios) > 1:
        return None
    host = QRect(touched[0][0])
    for geometry, _ratio in touched[1:]:
        host = host.united(geometry)

    others = [geometry for geometry, ratio in screens if round(ratio, 3) not in ratios]
    candidates = [
        geometry
        for geometry, ratio in screens
        if round(ratio, 3) in ratios and not host.contains(geometry)
    ]
    grown = True
    while grown:
        grown = False
        for geometry in list(candidates):
            united = host.united(geometry)
            # Never stretch the window over a screen with different scaling.
            if any(united.intersects(other) for other in others):
                continue
            host = united
            candidates.remove(geometry)
            grown = True
    return host


def screen_layout() -> list[tuple[QRect, float]]:
    """Return every screen's logical geometry and scaling factor."""
    return [
        (QRect(screen.geometry()), screen.devicePixelRatio())
        for screen in QGuiApplication.screens()
    ]


def can_edit_in_place(selection: QRect) -> bool:
    """Return whether one in-place editor window can show the whole selection."""
    return spanned_host_geometry(selection, screen_layout()) is not None


class OverlayEditor(QDialog):
    """Edits a normal screenshot directly over its source desktop position."""

    pin_requested = Signal(QImage, QPoint, QSize)

    _MIN_SELECTION_SIZE = 48

    def __init__(self, snapshot: DesktopSnapshot, selection: QRect) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._selection = QRect(selection)
        screen = QGuiApplication.screenAt(self._selection.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        self._host_screen = screen
        host = spanned_host_geometry(self._selection, screen_layout())
        if host is None:
            host = QRect(screen.geometry()) if screen is not None else QRect(selection)
        self._host_geometry = host
        self._image = snapshot.crop(self._selection)
        self._pixmap = QPixmap.fromImage(self._image)
        self._resize_edge = ""
        self._resize_origin = QPoint()
        self._resize_start = QRect()
        self._translation_thread: QThread | None = None
        self._translation_worker: TranslationWorker | None = None
        self._toolbar_user_position: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("overlayEditor")
        self.setStyleSheet("#overlayEditor { background: transparent; }")

        self._frame = ResizableFrame()
        self._frame.setParent(self)
        self._frame.set_image(self._image)
        self._frame.resize_started.connect(self._begin_resize)
        self._frame.resize_moved.connect(self._continue_resize)
        self._frame.resize_finished.connect(self._end_resize)

        # Keep the floating toolbar owned by this editor.  It still behaves as
        # an independent tool window, but Windows now destroys/hides it with
        # the screenshot editor on every cancel and close path.
        self._toolbar = EditorToolbar(self, movable=True)
        self._toolbar.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._toolbar.setFixedSize(self._toolbar.sizeHint())
        self._toolbar.copy_button.clicked.connect(self._copy)
        self._toolbar.save_button.clicked.connect(self._save)
        self._toolbar.translate_button.clicked.connect(self._translate)
        self._toolbar.cancel_button.clicked.connect(self.reject)
        self._toolbar.pin_button.clicked.connect(self._pin)
        self._toolbar.mirror_button.clicked.connect(self._frame.mirror_horizontal)
        self._toolbar.tool_selected.connect(self._frame.set_tool)
        self._toolbar.color_changed.connect(self._frame.set_annotation_color)
        self._toolbar.stroke_width_changed.connect(self._frame.set_stroke_width)
        self._toolbar.text_size_changed.connect(self._frame.set_text_size)
        self._toolbar.delete_requested.connect(self._frame.clear_annotations)
        self._toolbar.position_changed.connect(self._remember_toolbar_position)
        self._toolbar_escape = QShortcut(
            QKeySequence(Qt.Key.Key_Escape),
            self._toolbar,
        )
        self._toolbar_escape.activated.connect(self.reject)

        self._apply_selection_geometry()

    def keyPressEvent(self, event) -> None:
        """Cancel the overlay editor with Escape."""
        if event.matches(QKeySequence.StandardKey.Undo):
            self._frame.undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self._frame.redo()
            return
        if event.key() == Qt.Key.Key_Delete:
            if not self._frame.delete_selected_text():
                self._frame.clear_annotations()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        """Show the independent toolbar without enlarging the selection window."""
        super().showEvent(event)
        # A Qt virtual desktop can contain physical screen positions together
        # with DPI-scaled screen sizes.  Never span that mixed coordinate space
        # with one native window: the host only spans screens of equal scaling.
        window = self.windowHandle()
        if window is not None and self._host_screen is not None:
            window.setScreen(self._host_screen)
        self.setGeometry(self._host_geometry)
        self._frame.show()
        self._position_toolbar()
        self._toolbar.show()
        self._toolbar.raise_()

    def moveEvent(self, event) -> None:
        """Keep the toolbar attached when Windows moves the editor window."""
        super().moveEvent(event)
        self._position_toolbar()

    def done(self, result: int) -> None:
        """Close the independent toolbar together with the screenshot editor."""
        self._close_toolbar()
        super().done(result)

    def closeEvent(self, event) -> None:
        """Never leave a detached toolbar behind after an external close."""
        self._close_toolbar()
        super().closeEvent(event)

    def _close_toolbar(self) -> None:
        """Hide the toolbar immediately before its owning editor disappears."""
        self._toolbar.hide()
        self._toolbar.close()

    def _begin_resize(self, edge: str, global_position: QPoint) -> None:
        """Store the original selection before one border drag begins."""
        self._resize_edge = edge
        self._resize_origin = QPoint(global_position)
        self._resize_start = QRect(self._selection)

    def _continue_resize(self, global_position: QPoint) -> None:
        """Resize the selected screenshot area within the frozen desktop image."""
        if not self._resize_edge:
            return
        delta = global_position - self._resize_origin
        selection = self._resized_selection(self._resize_start, self._resize_edge, delta)
        if selection == self._selection:
            return
        self._selection = selection
        self._image = self._snapshot.crop(selection)
        self._pixmap = QPixmap.fromImage(self._image)
        self._frame.set_image(self._image, preserve_resize=True)
        self._apply_selection_geometry()

    def _end_resize(self) -> None:
        """Finish the current border drag."""
        self._resize_edge = ""

    def _resized_selection(self, initial: QRect, edge: str, delta: QPoint) -> QRect:
        """Return a bounded rectangle after moving one edge or corner."""
        bounds = self._host_geometry
        left = initial.left()
        right = initial.right()
        top = initial.top()
        bottom = initial.bottom()

        if "left" in edge:
            left = max(
                bounds.left(),
                min(initial.left() + delta.x(), initial.right() - self._MIN_SELECTION_SIZE + 1),
            )
        if "right" in edge:
            right = min(
                bounds.right(),
                max(initial.right() + delta.x(), initial.left() + self._MIN_SELECTION_SIZE - 1),
            )
        if "top" in edge:
            top = max(
                bounds.top(),
                min(initial.top() + delta.y(), initial.bottom() - self._MIN_SELECTION_SIZE + 1),
            )
        if "bottom" in edge:
            bottom = min(
                bounds.bottom(),
                max(initial.bottom() + delta.y(), initial.top() + self._MIN_SELECTION_SIZE - 1),
            )

        return QRect(left, top, right - left + 1, bottom - top + 1)

    def _apply_selection_geometry(self) -> None:
        """Position the image frame without remapping the top-level window."""
        local_selection = QRect(self._selection)
        local_selection.translate(-self._host_geometry.topLeft())

        self.setGeometry(self._host_geometry)
        self._frame.set_display_size(self._selection.size())
        self._frame.setGeometry(local_selection)
        self._position_toolbar()

    def _position_toolbar(self) -> None:
        """Place the toolbar below or above the selection without shifting it."""
        if self._toolbar_user_position is not None:
            self._toolbar.move(self._toolbar_user_position)
            return
        # A selection spanning several screens keeps the toolbar on the screen
        # under its bottom edge, next to where the screenshot ends.
        bottom_center = QPoint(self._selection.center().x(), self._selection.bottom())
        screen = (
            QGuiApplication.screenAt(bottom_center)
            or QGuiApplication.screenAt(self._selection.center())
            or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return
        bounds = screen.geometry()
        width = self._toolbar.width()
        height = self._toolbar.height()
        x = self._selection.center().x() - width // 2
        x = max(bounds.left(), min(x, bounds.right() - width + 1))
        below = self._selection.bottom() + 1
        above = self._selection.top() - height
        if below + height - 1 <= bounds.bottom():
            y = below
        elif above >= bounds.top():
            y = above
        else:
            y = max(bounds.top(), self._selection.bottom() - height + 1)
        self._toolbar.move(x, y)

    def _remember_toolbar_position(self, position: QPoint) -> None:
        """Preserve a manually dragged toolbar position while editing."""
        self._toolbar_user_position = QPoint(position)

    def _copy(self) -> None:
        """Copy the adjusted current screenshot to the system clipboard."""
        QGuiApplication.clipboard().setPixmap(QPixmap.fromImage(self._frame.rendered_image()))
        self.accept()

    def _pin(self) -> None:
        """Keep the current F1 image on the desktop as a movable sticker."""
        self.pin_requested.emit(
            self._frame.rendered_image(),
            self._selection.topLeft(),
            self._selection.size(),
        )
        self.accept()

    def _save(self) -> None:
        """Save the adjusted current screenshot as PNG or JPEG."""
        default_path = str(Path.home() / "Pictures" / DEFAULT_IMAGE_FILENAME)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存截图",
            default_path,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        if not self._frame.rendered_image().save(path):
            QMessageBox.warning(self, APP_DISPLAY_NAME, "图片保存失败。")
            return
        self.accept()

    def _translate(self) -> None:
        """Translate the current adjusted area directly into the image."""
        if self._translation_thread is not None:
            return

        self._toolbar.translate_button.setEnabled(False)
        self._toolbar.translate_button.setText("翻译中…")
        thread = QThread(self)
        worker = TranslationWorker(self._frame.rendered_image())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._apply_translated_image)
        worker.failed.connect(self._show_translation_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._finish_translation)

        self._translation_thread = thread
        self._translation_worker = worker
        thread.start()

    def _apply_translated_image(self, image: QImage) -> None:
        """Refresh the border frame with translated Chinese drawn in place."""
        self._image = QImage(image)
        self._pixmap = QPixmap.fromImage(self._image)
        self._frame.replace_image(self._image)
        self._apply_selection_geometry()

    def _show_translation_error(self, message: str) -> None:
        """Show an error without discarding the current adjusted screenshot."""
        QMessageBox.warning(self, f"{APP_DISPLAY_NAME} 翻译", message)

    def _finish_translation(self) -> None:
        """Release the worker and restore the Translate action."""
        self._toolbar.translate_button.setText("翻译")
        self._toolbar.translate_button.setEnabled(True)
        self._translation_thread = None
        self._translation_worker = None
