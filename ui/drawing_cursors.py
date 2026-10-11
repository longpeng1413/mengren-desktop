"""Custom cursors used by the presentation annotation layer."""

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtSvg import QSvgRenderer

from app.config import RESOURCE_DIR


def brush_cursor() -> QCursor:
    """Return the compact pencil icon with its upper-left tip as hotspot."""
    cursor_size = 27
    pixmap = QPixmap(cursor_size, cursor_size)
    pixmap.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(str(RESOURCE_DIR / "icons" / "brush_cursor.svg"))
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, cursor_size, cursor_size))
    finally:
        painter.end()

    return QCursor(pixmap, 3, 3)


def eraser_cursor() -> QCursor:
    """Return a high-contrast eraser cursor with its lower edge as hotspot."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    back = QPolygon(
        (QPoint(20, 3), QPoint(30, 13), QPoint(21, 22), QPoint(11, 12))
    )
    front = QPolygon(
        (QPoint(11, 12), QPoint(21, 22), QPoint(13, 30), QPoint(3, 20))
    )
    outline = QPolygon(
        (QPoint(20, 3), QPoint(30, 13), QPoint(13, 30), QPoint(3, 20))
    )

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ff6b81"))
    painter.drawPolygon(back)
    painter.setBrush(QColor("#f5f7fa"))
    painter.drawPolygon(front)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#111418"), 2))
    painter.drawPolygon(outline)
    painter.drawLine(QPoint(11, 12), QPoint(21, 22))
    painter.end()

    return QCursor(pixmap, 8, 25)
