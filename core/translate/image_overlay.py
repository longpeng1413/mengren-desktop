"""Render translated paragraphs directly over recognized screenshot text."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

import numpy as np
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QTextLayout, QTextOption


_FONT_FAMILY = "Microsoft YaHei"
# A CJK glyph of this pixel size fills about the height of an OCR line box.
_SIZE_PER_LINE_HEIGHT = 0.78
_MIN_PIXEL_SIZE = 9


@dataclass(frozen=True, slots=True)
class OverlayTranslation:
    """One translated paragraph at its original image location."""

    bounds: QRect
    text: str
    line_height: int = 0


class ImageTranslationRenderer:
    """Covers recognized source text and draws Chinese in the same areas.

    Every paragraph uses one shared font size and is left aligned, so the
    result reads as tidy text even when Chinese is shorter than the source.
    Only a paragraph whose translation cannot fit is drawn smaller.
    """

    def apply(self, source: QImage, translations: tuple[OverlayTranslation, ...]) -> QImage:
        """Return a new image containing all translated replacements."""
        image = QImage(source)
        pixels = _rgb_array(source)
        items = []
        for translation in translations:
            bounds = translation.bounds.intersected(image.rect())
            if bounds.isEmpty() or not translation.text.strip():
                continue
            cover = bounds.adjusted(-2, -2, 2, 2).intersected(image.rect())
            background = _estimate_background(pixels, cover)
            items.append(
                (
                    translation,
                    cover,
                    background,
                    _text_color(pixels, bounds, background),
                    translation.line_height or bounds.height(),
                )
            )
        if not items:
            return image

        # Text of about the same original height (body text, list items) shares
        # one size; headings and small print form their own size groups.
        groups = _height_groups([item[4] for item in items])
        sizes = [0] * len(items)
        for members in groups:
            group_height = median(items[index][4] for index in members)
            target = max(_MIN_PIXEL_SIZE, round(group_height * _SIZE_PER_LINE_HEIGHT))
            fitted = {
                index: _fitted_size(items[index][0].text, _text_rect(items[index][1], items[index][4]), target)
                for index in members
            }
            shared = round(median(fitted.values()))
            for index, size in fitted.items():
                # Only a paragraph that cannot fit the shared size gets smaller.
                sizes[index] = min(shared, size)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        try:
            for (translation, cover, background, color, line_height), pixel_size in zip(items, sizes):
                painter.fillRect(cover, background)
                _draw_paragraph(
                    painter,
                    translation.text,
                    _text_rect(cover, line_height),
                    pixel_size,
                    color,
                    line_height,
                )
        finally:
            painter.end()
        return image


def _height_groups(heights: list[int]) -> list[list[int]]:
    """Group item indexes whose line heights are within 30% of each other."""
    groups: list[list[int]] = []
    smallest: list[int] = []
    for index in sorted(range(len(heights)), key=lambda item: heights[item]):
        if groups and heights[index] <= smallest[-1] * 1.3:
            groups[-1].append(index)
        else:
            groups.append([index])
            smallest.append(heights[index])
    return groups


def _text_rect(cover: QRect, line_height: int) -> QRect:
    """Leave a small left margin: OCR boxes start a little before the letters."""
    return cover.adjusted(max(2, round(line_height * 0.2)), 0, 0, 0)


def _font(pixel_size: int) -> QFont:
    font = QFont(_FONT_FAMILY)
    font.setPixelSize(pixel_size)
    return font


def _layout(text: str, pixel_size: int, width: float) -> tuple[QTextLayout, float]:
    """Wrap text to ``width`` and return the layout and its total height."""
    layout = QTextLayout(text.strip(), _font(pixel_size))
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    spacing = QFontMetricsF(_font(pixel_size)).lineSpacing()
    y = 0.0
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        line.setPosition(QPointF(0, y))
        y += spacing
    layout.endLayout()
    return layout, y


def _fitted_size(text: str, rect: QRect, target: int) -> int:
    """Return the largest size up to ``target`` whose wrapped text fits ``rect``."""
    size = target
    while size > _MIN_PIXEL_SIZE:
        _layout_object, height = _layout(text, size, rect.width())
        if height <= rect.height() + size * 0.2:
            return size
        size -= 1
    return _MIN_PIXEL_SIZE


def _draw_paragraph(
    painter: QPainter,
    text: str,
    rect: QRect,
    pixel_size: int,
    color: QColor,
    line_height: int,
) -> None:
    """Draw wrapped text from the paragraph's top-left corner."""
    layout, height = _layout(text, pixel_size, rect.width())
    spacing = QFontMetricsF(_font(pixel_size)).lineSpacing()
    # Centre the first line on the first source line, like the original text.
    top = rect.top() + max(0.0, (line_height + 4 - spacing) / 2)
    top = min(top, max(float(rect.top()), rect.bottom() + 1 - height))
    painter.setPen(color)
    painter.save()
    painter.setClipRect(rect.adjusted(0, 0, 0, round(pixel_size * 0.2)))
    layout.draw(painter, QPointF(rect.left(), top))
    painter.restore()


def _rgb_array(image: QImage) -> np.ndarray:
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = rgb.width(), rgb.height()
    data = np.frombuffer(rgb.constBits(), dtype=np.uint8)
    return data.reshape((height, rgb.bytesPerLine()))[:, : width * 3].reshape((height, width, 3)).copy()


def _estimate_background(pixels: np.ndarray, rect: QRect) -> QColor:
    """Estimate the background from the median colour along the area's border."""
    area = pixels[rect.top(): rect.bottom() + 1, rect.left(): rect.right() + 1]
    border = np.concatenate((area[0], area[-1], area[:, 0], area[:, -1]))
    red, green, blue = (int(value) for value in np.median(border, axis=0))
    return QColor(red, green, blue)


def _text_color(pixels: np.ndarray, rect: QRect, background: QColor) -> QColor:
    """Reuse the source text colour when it stands out; else black or white."""
    area = pixels[rect.top(): rect.bottom() + 1, rect.left(): rect.right() + 1].reshape(-1, 3)
    base = np.array((background.red(), background.green(), background.blue()), dtype=np.int16)
    distance = np.abs(area.astype(np.int16) - base).sum(axis=1)
    strongest = area[distance >= np.percentile(distance, 95)]
    if strongest.size:
        red, green, blue = (int(value) for value in strongest.mean(axis=0))
        candidate = QColor(red, green, blue)
        if _contrast(candidate, background) >= 3.0:
            return candidate
    return _contrast_color(background)


def _luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _contrast(first: QColor, second: QColor) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _contrast_color(background: QColor) -> QColor:
    """Select a readable neutral text color for the estimated background."""
    black = QColor(Qt.GlobalColor.black)
    white = QColor(Qt.GlobalColor.white)
    return black if _contrast(black, background) >= _contrast(white, background) else white
