"""Always-on-top pinned screenshot window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Signal, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QWidget

from app.branding import APP_DISPLAY_NAME, DEFAULT_IMAGE_FILENAME


class PinnedImageWindow(QWidget):
    """Shows one screenshot that can be moved, rotated, and made transparent."""

    edit_requested = Signal()

    _MIN_OPACITY = 0.2
    _OPACITY_STEP = 0.05

    def __init__(self, image: QImage, position: QPoint, display_size: QSize) -> None:
        super().__init__()
        self._image = QImage(image)
        self._display_size = QSize(display_size)
        self._drag_origin: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setWindowOpacity(1.0)
        self._apply_geometry(position)
        self._update_tooltip()

    def paintEvent(self, event) -> None:
        """Render the pinned screenshot without a window title bar or border."""
        painter = QPainter(self)
        try:
            painter.drawImage(self.rect(), self._image)
        finally:
            painter.end()

    def mousePressEvent(self, event) -> None:
        """Begin moving the pinned image by dragging with the left mouse button."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Move the pinned image while the left mouse button remains pressed."""
        if self._drag_origin is None:
            return
        position = event.globalPosition().toPoint()
        self.move(self.pos() + position - self._drag_origin)
        self._drag_origin = position
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        """Finish a drag operation."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Close the pinned image when it is double-clicked."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.close()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        """Rotate with 1 and close with Escape."""
        if event.key() == Qt.Key.Key_1:
            self._rotate_clockwise()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        """Adjust image opacity with Ctrl plus mouse-wheel scrolling."""
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.ignore()
            return
        direction = 1 if event.angleDelta().y() > 0 else -1
        opacity = min(1.0, max(self._MIN_OPACITY, self.windowOpacity() + direction * self._OPACITY_STEP))
        self.setWindowOpacity(opacity)
        self._update_tooltip()
        event.accept()

    def contextMenuEvent(self, event) -> None:
        """Offer editing, clipboard, file, and close actions."""
        menu = QMenu(self)
        edit_action = menu.addAction("编辑贴图")
        copy_action = menu.addAction("复制贴图")
        save_action = menu.addAction("保存贴图")
        menu.addSeparator()
        close_action = menu.addAction("关闭贴图")
        edit_action.triggered.connect(self.edit_requested.emit)
        copy_action.triggered.connect(self._copy)
        save_action.triggered.connect(self._save)
        close_action.triggered.connect(self.close)
        menu.exec(event.globalPos())

    def image(self) -> QImage:
        """Return a detached copy of the current pinned image."""
        return QImage(self._image)

    def set_image(self, image: QImage) -> None:
        """Apply editor changes while keeping the sticker position and size."""
        if image.isNull():
            return
        self._image = QImage(image)
        self.update()

    def _copy(self) -> None:
        """Copy the current pinned image without closing it."""
        QGuiApplication.clipboard().setPixmap(QPixmap.fromImage(self._image))

    def _save(self) -> None:
        """Save the current pinned image without closing it."""
        default_path = str(Path.home() / "Pictures" / DEFAULT_IMAGE_FILENAME)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存贴图",
            default_path,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if path and not self._image.save(path):
            QMessageBox.warning(self, APP_DISPLAY_NAME, "图片保存失败。")

    def _rotate_clockwise(self) -> None:
        """Rotate the picture by one 90-degree clockwise step around its center."""
        center = self.geometry().center()
        self._image = self._image.transformed(QTransform().rotate(90))
        self._display_size = QSize(self._display_size.height(), self._display_size.width())
        self._apply_geometry(center - QPoint(self._display_size.width() // 2, self._display_size.height() // 2))

    def _apply_geometry(self, position: QPoint) -> None:
        """Apply one image-sized frameless window geometry."""
        size = self._display_size if not self._display_size.isEmpty() else self._image.size()
        self.setGeometry(position.x(), position.y(), size.width(), size.height())

    def _update_tooltip(self) -> None:
        """Show the essential sticker controls without an extra visible toolbar."""
        percentage = round(self.windowOpacity() * 100)
        self.setToolTip(
            f"贴图：拖动移动｜双击关闭｜右键编辑/复制/保存｜每次按 1 旋转 90°｜"
            f"Ctrl + 滚轮 调透明度（{percentage}%）｜Esc 关闭"
        )
