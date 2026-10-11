"""Render translated text directly over recognized screenshot text."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter


@dataclass(frozen=True, slots=True)
class OverlayTranslation:
    """One translated text replacement at its original image location."""

    bounds: QRect
    text: str


class ImageTranslationRenderer:
    """Covers recognized source text and draws Chinese in the same area."""

    def apply(self, source: QImage, translations: tuple[OverlayTranslation, ...]) -> QImage:
        """Return a new image containing all translated replacements."""
        image = QImage(source)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        try:
            for translation in translations:
                self._draw_translation(painter, image, translation)
        finally:
            painter.end()
        return image

    def _draw_translation(
        self,
        painter: QPainter,
        image: QImage,
        translation: OverlayTranslation,
    ) -> None:
        """Replace one OCR line while retaining the surrounding image."""
        text_rect = translation.bounds.intersected(image.rect())
        if text_rect.isEmpty() or not translation.text:
            return

        cover_rect = text_rect.adjusted(-3, -2, 3, 2).intersected(image.rect())
        background = _estimate_background(image, cover_rect)
        painter.fillRect(cover_rect, background)

        font = _fitted_font(translation.text, cover_rect)
        painter.setFont(font)
        painter.setPen(_contrast_color(background))
        painter.drawText(cover_rect, _text_flags(), translation.text)


def _estimate_background(image: QImage, rect: QRect) -> QColor:
    """Estimate a text area's background from pixels around its corners."""
    positions = (
        (rect.left(), rect.top()),
        (rect.right(), rect.top()),
        (rect.left(), rect.bottom()),
        (rect.right(), rect.bottom()),
        (rect.center().x(), rect.top()),
        (rect.center().x(), rect.bottom()),
    )
    colors = [image.pixelColor(x, y) for x, y in positions]
    return QColor(
        sum(color.red() for color in colors) // len(colors),
        sum(color.green() for color in colors) // len(colors),
        sum(color.blue() for color in colors) // len(colors),
    )


def _contrast_color(background: QColor) -> QColor:
    """Select a readable neutral text color for the estimated background."""
    luminance = (
        background.red() * 0.2126
        + background.green() * 0.7152
        + background.blue() * 0.0722
    )
    return QColor(Qt.GlobalColor.black if luminance > 150 else Qt.GlobalColor.white)


def _fitted_font(text: str, rect: QRect) -> QFont:
    """Fit one translated line inside its original OCR rectangle."""
    pixel_size = max(8, int(rect.height() * 0.78))
    while pixel_size > 7:
        font = QFont("Microsoft YaHei")
        font.setPixelSize(pixel_size)
        required = QFontMetrics(font).boundingRect(rect, _text_flags(), text)
        if required.width() <= rect.width() and required.height() <= rect.height():
            return font
        pixel_size -= 1

    font = QFont("Microsoft YaHei")
    font.setPixelSize(8)
    return font


def _text_flags() -> Qt.AlignmentFlag | Qt.TextFlag:
    """Return the shared alignment and wrapping flags for replacement text."""
    return (
        Qt.AlignmentFlag.AlignHCenter
        | Qt.AlignmentFlag.AlignVCenter
        | Qt.TextFlag.TextWordWrap
    )
