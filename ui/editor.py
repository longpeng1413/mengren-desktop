"""Screenshot editor with four fixed actions and original-position preview mode."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Signal, Qt, QThread
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QScrollArea,
    QVBoxLayout,
)

from app.branding import APP_DISPLAY_NAME, DEFAULT_IMAGE_FILENAME
from ui.toolbar import EditorToolbar
from ui.translation_worker import TranslationWorker
from ui.window_position import center_on_cursor_screen
from ui.image_canvas import ImageCanvas


class Editor(QDialog):
    """Displays a captured image with Copy, Save, Translate, and Cancel only."""

    pin_requested = Signal(QImage, QPoint, QSize)
    image_applied = Signal(QImage)

    def __init__(
        self,
        image: QImage,
        placement: QRect | None = None,
        *,
        apply_mode: bool = False,
    ) -> None:
        super().__init__()
        self._image = QImage(image)
        self._pixmap = QPixmap.fromImage(self._image)
        self._placement = QRect(placement) if placement is not None else None
        self._apply_mode = apply_mode
        self._translation_thread: QThread | None = None
        self._translation_worker: TranslationWorker | None = None
        self._translation_progress: QProgressDialog | None = None

        self._canvas = ImageCanvas()

        self._preview_area = QScrollArea()
        self._preview_area.setWidget(self._canvas)
        self._preview_area.setWidgetResizable(False)
        self._preview_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._toolbar = EditorToolbar(
            enable_crop=self._placement is None and not apply_mode
        )
        self._toolbar.copy_button.clicked.connect(self._copy)
        self._toolbar.save_button.clicked.connect(self._save)
        self._toolbar.translate_button.clicked.connect(self._translate)
        self._toolbar.cancel_button.clicked.connect(self.reject)
        self._toolbar.set_apply_mode(apply_mode)
        if apply_mode:
            self._toolbar.pin_button.clicked.connect(self._apply_and_close)
        else:
            self._toolbar.pin_button.clicked.connect(self._pin)
        self._toolbar.mirror_button.clicked.connect(self._canvas.mirror_horizontal)
        self._toolbar.tool_selected.connect(self._canvas.set_tool)
        self._toolbar.crop_apply_requested.connect(self._apply_crop)
        self._toolbar.color_changed.connect(self._canvas.set_annotation_color)
        self._toolbar.stroke_width_changed.connect(self._canvas.set_stroke_width)
        self._toolbar.text_size_changed.connect(self._canvas.set_text_size)
        self._toolbar.delete_requested.connect(self._canvas.clear_annotations)

        layout = QVBoxLayout(self)
        layout.addWidget(self._preview_area)
        layout.addWidget(self._toolbar, alignment=Qt.AlignmentFlag.AlignCenter)

        if self._placement is None:
            self._configure_windowed_mode()
        else:
            self._configure_original_position_mode(layout)
        self._refresh_preview()

    def keyPressEvent(self, event) -> None:
        """Support undo, recovery, annotation clearing, and cancellation."""
        if event.matches(QKeySequence.StandardKey.Undo):
            self._canvas.undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self._canvas.redo()
            return
        if event.key() == Qt.Key.Key_Delete:
            self._canvas.clear_annotations()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def _configure_windowed_mode(self) -> None:
        """Configure the scrollable editor used for F2 long screenshots."""
        self.setWindowTitle(f"{APP_DISPLAY_NAME} 编辑")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(
            min(max(self._pixmap.width() + 24, 360), 1200),
            min(max(self._pixmap.height() + 90, 180), 900),
        )
        center_on_cursor_screen(self)

    def _configure_original_position_mode(self, layout: QVBoxLayout) -> None:
        """Place a borderless F1 editor directly over the selected screen region."""
        assert self._placement is not None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._preview_area.setFrameShape(QFrame.Shape.NoFrame)
        self._preview_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_area.setFixedSize(self._placement.size())
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar_height = self._toolbar.sizeHint().height()
        self.setGeometry(
            self._placement.x(),
            self._placement.y(),
            self._placement.width(),
            self._placement.height() + toolbar_height,
        )

    def _refresh_preview(self) -> None:
        """Show the current image at its actual or original selected size."""
        self._canvas.set_image(self._image)
        if self._placement is not None:
            self._canvas.set_display_size(self._placement.size())

    def _apply_crop(self) -> None:
        """Apply the adjustable full-image crop used by long screenshots."""
        if self._canvas.apply_crop_selection():
            self._image = self._canvas.rendered_image()
            self._pixmap = QPixmap.fromImage(self._image)
        self._toolbar.finish_crop_mode()

    def _copy(self) -> None:
        """Copy the current image to the system clipboard."""
        QGuiApplication.clipboard().setPixmap(QPixmap.fromImage(self._canvas.rendered_image()))
        if not self._apply_mode:
            self.accept()

    def _pin(self) -> None:
        """Keep the current image on the desktop as a movable sticker."""
        self.pin_requested.emit(
            self._canvas.rendered_image(),
            self.geometry().topLeft(),
            self._canvas.size(),
        )
        self.accept()

    def _apply_and_close(self) -> None:
        """Apply edits to the pinned image that opened this editor."""
        self.image_applied.emit(self._canvas.rendered_image())
        self.accept()

    def _save(self) -> None:
        """Save the current image as PNG or JPEG selected by the user."""
        default_path = str(Path.home() / "Pictures" / DEFAULT_IMAGE_FILENAME)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存截图",
            default_path,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        if not self._canvas.rendered_image().save(path):
            QMessageBox.warning(self, APP_DISPLAY_NAME, "图片保存失败。")
            return
        if not self._apply_mode:
            self.accept()

    def _translate(self) -> None:
        """Replace detected source text with Chinese in the image preview."""
        if self._translation_thread is not None:
            return

        self._toolbar.translate_button.setEnabled(False)
        self._translation_progress = QProgressDialog("正在识别并覆盖翻译…", None, 0, 0, self)
        self._translation_progress.setWindowTitle(APP_DISPLAY_NAME)
        self._translation_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._translation_progress.setCancelButton(None)
        self._translation_progress.setMinimumDuration(0)
        self._translation_progress.show()

        thread = QThread(self)
        worker = TranslationWorker(self._canvas.rendered_image())
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
        """Refresh the preview with the translated screenshot image."""
        self._close_translation_progress()
        self._image = QImage(image)
        self._pixmap = QPixmap.fromImage(self._image)
        self._canvas.replace_image(self._image)

    def _show_translation_error(self, message: str) -> None:
        """Show a concise error while preserving the original screenshot."""
        self._close_translation_progress()
        QMessageBox.warning(self, f"{APP_DISPLAY_NAME} 翻译", message)

    def _finish_translation(self) -> None:
        """Release the worker and restore the Translate action."""
        self._close_translation_progress()
        self._toolbar.translate_button.setEnabled(True)
        self._translation_thread = None
        self._translation_worker = None

    def _close_translation_progress(self) -> None:
        """Close the progress display when background work completes."""
        if self._translation_progress is not None:
            self._translation_progress.close()
            self._translation_progress.deleteLater()
        self._translation_progress = None
