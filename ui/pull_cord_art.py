"""Drawings of the to-do list's pull cord, one per selectable style.

Every style shares a small metal ceiling mount with a ring and a thin cord
with a soft halo, so the cord stays visible on dark and on light wallpapers.
The knob at the end differs: an emerald glass bead, a kraft paper tag, a
frosted capsule or a minimal outline. The knob shows the list's name and
grows with it (up to a limit, then the name is cut short with "…"), so
several closed lists can be told apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

MOUNT_HEIGHT = 14
MAX_KNOB_WIDTH = 180


@dataclass(frozen=True, slots=True)
class CordStyle:
    """One look of the cord: its smallest width, knob height and drawing.

    ``pad`` is the room the knob needs around the name, so the knob is at
    least ``width`` wide and otherwise the name's width plus ``pad``.
    """

    key: str
    label: str
    width: int
    knob_height: int
    draw_knob: Callable[[QPainter, QRectF, str], None]
    attach: float = 2
    string_width: float = 1.6
    pad: int = 28
    font_size: int = 12


def _font(size: int, bold: bool = True) -> QFont:
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def _draw_name(painter: QPainter, rect: QRectF, name: str, size: int, color: QColor) -> None:
    """Draw ``name`` centred in ``rect``, cut short with "…" if it is too long."""
    font = _font(size)
    text = QFontMetrics(font).elidedText(name, Qt.TextElideMode.ElideRight, int(rect.width()))
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


def knob_width(cord: CordStyle, name: str) -> int:
    """Width of the cord with ``name`` on its knob; always even so it stays centred."""
    text = QFontMetrics(_font(cord.font_size)).horizontalAdvance(name)
    width = max(cord.width, min(MAX_KNOB_WIDTH, text + cord.pad))
    return width + width % 2


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


def draw_bead(painter: QPainter, area: QRectF, name: str) -> None:
    """An emerald glass bead, stretched to fit the name, with a gold cap."""
    center = area.center().x()
    cap = QRectF(center - 4, area.top(), 8, 5)
    painter.setPen(QPen(QColor("#8a6a24"), 0.8))
    painter.setBrush(QColor("#d6b25a"))
    painter.drawRoundedRect(cap, 2, 2)
    bead = QRectF(area.left() + 2, area.top() + 4, area.width() - 4, area.height() - 8)
    radius = bead.height() / 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 45))
    painter.drawRoundedRect(bead.translated(0, 2), radius, radius)
    glass = QLinearGradient(bead.topLeft(), bead.bottomLeft())
    glass.setColorAt(0.0, QColor("#8fe6bb"))
    glass.setColorAt(0.45, QColor("#3fb382"))
    glass.setColorAt(1.0, QColor("#145c40"))
    painter.setBrush(glass)
    painter.setPen(QPen(QColor(10, 60, 40, 140), 0.8))
    painter.drawRoundedRect(bead, radius, radius)
    shine = QRectF(bead.left() + radius * 0.6, bead.top() + 3, max(8, bead.width() * 0.3), bead.height() * 0.22)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 120))
    painter.drawRoundedRect(shine, shine.height() / 2, shine.height() / 2)
    text = bead.adjusted(12, 0, -12, 0)
    _draw_name(painter, text.translated(0, 1), name, 12, QColor(0, 40, 25, 90))
    _draw_name(painter, text, name, 12, QColor("#ffffff"))


def draw_tag(painter: QPainter, area: QRectF, name: str) -> None:
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
    text = QRectF(tag.left() + 10, tag.top() + 11, tag.width() - 20, tag.height() - 12)
    _draw_name(painter, text, name, 12, QColor("#5e4320"))


def draw_capsule(painter: QPainter, area: QRectF, name: str) -> None:
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
    text = QRectF(pill.left() + 22, pill.top(), pill.width() - 32, pill.height())
    _draw_name(painter, text, name, 12, QColor("#2b2f2d"))


def draw_ring(painter: QPainter, area: QRectF, name: str) -> None:
    """A small hollow outline with the name inside: the quietest look."""
    ring = QRectF(area.left() + 2, area.top() + 2, area.width() - 4, area.height() - 4)
    radius = ring.height() / 2
    painter.setBrush(QColor(255, 255, 255, 170))
    painter.setPen(QPen(QColor(255, 255, 255, 150), 4))
    painter.drawRoundedRect(ring, radius, radius)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#4b4c48"), 1.6))
    painter.drawRoundedRect(ring, radius, radius)
    _draw_name(painter, ring.adjusted(9, 0, -9, 0), name, 11, QColor("#3a3b37"))


STYLES: dict[str, CordStyle] = {
    "bead": CordStyle("bead", "翡翠吊珠", 52, 40, draw_bead, pad=32),
    "tag": CordStyle("tag", "牛皮纸吊牌", 72, 44, draw_tag, attach=9, pad=28),
    "pill": CordStyle("pill", "磨砂胶囊", 88, 34, draw_capsule, attach=3, pad=46),
    "minimal": CordStyle(
        "minimal", "极简细线", 40, 26, draw_ring, attach=2, string_width=1.2, pad=26, font_size=11
    ),
}


def style(key: str) -> CordStyle:
    return STYLES.get(key, STYLES["bead"])
