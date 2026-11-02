"""Drawings of the to-do list's pull cord, one per selectable style.

Every style shares a small metal ceiling mount with a ring and a thin cord
with a soft halo, so the cord stays visible on dark and on light wallpapers.
The knob at the end differs: an emerald glass bead, a kraft paper tag, a
frosted capsule or a minimal ring. The knob shows how many items are open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

MOUNT_HEIGHT = 14


@dataclass(frozen=True, slots=True)
class CordStyle:
    """One look of the cord: its width, knob height and knob drawing."""

    key: str
    label: str
    width: int
    knob_height: int
    draw_knob: Callable[[QPainter, QRectF, int], None]
    attach: float = 2
    string_width: float = 1.6


def _font(size: int, bold: bool = True) -> QFont:
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def _count_text(count: int) -> str:
    return str(count) if count else "✓"


def draw_mount(painter: QPainter, center: float) -> None:
    """A brushed-metal ceiling plate with a small ring under it."""
    plate = QRectF(center - 11, 1, 22, 6)
    shade = QLinearGradient(plate.topLeft(), plate.bottomLeft())
    shade.setColorAt(0, QColor("#f4f4f2"))
    shade.setColorAt(1, QColor("#a9aaa6"))
    painter.setPen(QPen(QColor(0, 0, 0, 70), 0.8))
    painter.setBrush(shade)
    painter.drawRoundedRect(plate, 3, 3)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 170), 3))
    painter.drawEllipse(QPointF(center, 10), 3, 3)
    painter.setPen(QPen(QColor("#8d8e8a"), 1.4))
    painter.drawEllipse(QPointF(center, 10), 3, 3)


def draw_string(painter: QPainter, center: float, top: float, bottom: float, width: float) -> None:
    """A thin cord with a pale halo around it."""
    painter.setPen(QPen(QColor(255, 255, 255, 120), width + 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(center, top), QPointF(center, bottom))
    painter.setPen(QPen(QColor("#6f706c"), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(center, top), QPointF(center, bottom))


def _soft_shadow(painter: QPainter, rect: QRectF, radius: float) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    for spread, alpha in ((3.0, 18), (2.0, 26), (1.0, 34)):
        painter.setBrush(QColor(0, 0, 0, alpha))
        painter.drawRoundedRect(rect.adjusted(-spread, -spread + 2, spread, spread + 2), radius + spread, radius + spread)


def draw_bead(painter: QPainter, area: QRectF, count: int) -> None:
    """An emerald glass bead with a gold cap and a highlight."""
    center = area.center().x()
    cap = QRectF(center - 4, area.top(), 8, 5)
    painter.setPen(QPen(QColor("#8a6a24"), 0.8))
    painter.setBrush(QColor("#d6b25a"))
    painter.drawRoundedRect(cap, 2, 2)
    diameter = min(area.width(), area.height() - 4)
    bead = QRectF(center - diameter / 2, area.top() + 4, diameter, diameter)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 45))
    painter.drawEllipse(bead.translated(0, 2))
    glass = QRadialGradient(bead.center() + QPointF(-diameter * 0.18, -diameter * 0.2), diameter * 0.75)
    glass.setColorAt(0.0, QColor("#a8f0cb"))
    glass.setColorAt(0.45, QColor("#3fb382"))
    glass.setColorAt(1.0, QColor("#145c40"))
    painter.setBrush(glass)
    painter.setPen(QPen(QColor(10, 60, 40, 140), 0.8))
    painter.drawEllipse(bead)
    shine = QRectF(bead.left() + diameter * 0.2, bead.top() + diameter * 0.12, diameter * 0.32, diameter * 0.2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 150))
    painter.drawEllipse(shine)
    painter.setFont(_font(12))
    painter.setPen(QColor(0, 40, 25, 90))
    painter.drawText(bead.translated(0, 1), Qt.AlignmentFlag.AlignCenter, _count_text(count))
    painter.setPen(QColor("#ffffff"))
    painter.drawText(bead, Qt.AlignmentFlag.AlignCenter, _count_text(count))


def draw_tag(painter: QPainter, area: QRectF, count: int) -> None:
    """A kraft paper tag with clipped top corners and an eyelet."""
    tag = QRectF(area.left() + 2, area.top() + 2, area.width() - 4, area.height() - 4)
    cut = 9
    shape = QPainterPath()
    shape.moveTo(tag.left() + cut, tag.top())
    shape.lineTo(tag.right() - cut, tag.top())
    shape.lineTo(tag.right(), tag.top() + cut)
    shape.lineTo(tag.right(), tag.bottom() - 4)
    shape.quadTo(tag.right(), tag.bottom(), tag.right() - 4, tag.bottom())
    shape.lineTo(tag.left() + 4, tag.bottom())
    shape.quadTo(tag.left(), tag.bottom(), tag.left(), tag.bottom() - 4)
    shape.lineTo(tag.left(), tag.top() + cut)
    shape.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 40))
    painter.drawPath(shape.translated(0, 2))
    paper = QLinearGradient(tag.topLeft(), tag.bottomLeft())
    paper.setColorAt(0, QColor("#f3e4c8"))
    paper.setColorAt(1, QColor("#dcc095"))
    painter.setBrush(paper)
    painter.setPen(QPen(QColor("#b48f58"), 1))
    painter.drawPath(shape)
    eyelet = QPointF(tag.center().x(), tag.top() + 7)
    painter.setBrush(QColor("#fbf6ec"))
    painter.setPen(QPen(QColor("#9a7a46"), 1.4))
    painter.drawEllipse(eyelet, 3, 3)
    text = QRectF(tag.left(), tag.top() + 11, tag.width(), tag.height() - 12)
    painter.setFont(_font(12))
    painter.setPen(QColor("#5e4320"))
    painter.drawText(text, Qt.AlignmentFlag.AlignCenter, f"待办 {_count_text(count)}")


def draw_capsule(painter: QPainter, area: QRectF, count: int) -> None:
    """A frosted white capsule with a green dot and a soft shadow."""
    pill = QRectF(area.left() + 4, area.top() + 2, area.width() - 8, area.height() - 6)
    radius = pill.height() / 2
    _soft_shadow(painter, pill, radius)
    frost = QLinearGradient(pill.topLeft(), pill.bottomLeft())
    frost.setColorAt(0, QColor(255, 255, 255, 235))
    frost.setColorAt(1, QColor(236, 238, 240, 225))
    painter.setBrush(frost)
    painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
    painter.drawRoundedRect(pill, radius, radius)
    dot = QPointF(pill.left() + 13, pill.center().y())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(76, 195, 138, 70))
    painter.drawEllipse(dot, 5.5, 5.5)
    painter.setBrush(QColor("#2fae73"))
    painter.drawEllipse(dot, 3.5, 3.5)
    text = QRectF(pill.left() + 20, pill.top(), pill.width() - 24, pill.height())
    painter.setFont(_font(12))
    painter.setPen(QColor("#2b2f2d"))
    painter.drawText(text, Qt.AlignmentFlag.AlignCenter, f"待办 {_count_text(count)}")


def draw_ring(painter: QPainter, area: QRectF, count: int) -> None:
    """A small hollow ring with the number inside: the quietest look."""
    diameter = min(area.width(), area.height()) - 4
    ring = QRectF(area.center().x() - diameter / 2, area.top() + 2, diameter, diameter)
    painter.setBrush(QColor(255, 255, 255, 170))
    painter.setPen(QPen(QColor(255, 255, 255, 150), 4))
    painter.drawEllipse(ring)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#4b4c48"), 1.6))
    painter.drawEllipse(ring)
    painter.setFont(_font(11))
    painter.setPen(QColor("#3a3b37"))
    painter.drawText(ring, Qt.AlignmentFlag.AlignCenter, _count_text(count))


STYLES: dict[str, CordStyle] = {
    "bead": CordStyle("bead", "翡翠吊珠", 52, 40, draw_bead),
    "tag": CordStyle("tag", "牛皮纸吊牌", 72, 44, draw_tag, attach=9),
    "pill": CordStyle("pill", "磨砂胶囊", 88, 34, draw_capsule, attach=3),
    "minimal": CordStyle("minimal", "极简细线", 40, 26, draw_ring, attach=2, string_width=1.2),
}


def style(key: str) -> CordStyle:
    return STYLES.get(key, STYLES["bead"])
