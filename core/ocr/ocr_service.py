"""Local image-to-text recognition powered by RapidOCR."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from rapidocr import RapidOCR


@dataclass(frozen=True, slots=True)
class OcrLine:
    """One recognized text line and its image location."""

    text: str
    confidence: float
    bounds: QRect


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Recognized text returned from one screenshot."""

    lines: tuple[OcrLine, ...]

    @property
    def text(self) -> str:
        """Return all recognized lines in their OCR reading order."""
        return "\n".join(line.text for line in self.lines)


class OcrService:
    """Recognizes screenshot text locally without uploading the image."""

    def __init__(self) -> None:
        self._engine = RapidOCR()

    def recognize(self, image: QImage) -> OcrResult:
        """Extract text and its locations from a Qt image."""
        if image.isNull():
            return OcrResult(())

        output = self._engine(_to_bgr_array(image))
        texts = output.txts or ()
        scores = output.scores or ()
        boxes = output.boxes
        lines: list[OcrLine] = []
        for index, raw_text in enumerate(texts):
            text = raw_text.strip()
            if not text:
                continue

            raw_box = boxes[index] if boxes is not None and index < len(boxes) else None
            bounds = _box_to_rect(raw_box, image.rect())
            if bounds.isEmpty():
                continue

            score = float(scores[index]) if index < len(scores) else 0.0
            lines.append(OcrLine(text=text, confidence=score, bounds=bounds))
        return OcrResult(tuple(lines))


def _to_bgr_array(image: QImage) -> np.ndarray:
    """Convert QImage pixels to RapidOCR's BGR array format."""
    rgba_image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    height = rgba_image.height()
    width = rgba_image.width()
    row_bytes = rgba_image.bytesPerLine()
    pixels = np.frombuffer(rgba_image.constBits(), dtype=np.uint8)
    rgba = pixels.reshape((height, row_bytes))[:, : width * 4].reshape((height, width, 4))
    return rgba[:, :, [2, 1, 0]].copy()


def _box_to_rect(raw_box: object, image_rect: QRect) -> QRect:
    """Convert RapidOCR's four-point polygon into a clipped QRect."""
    if raw_box is None:
        return QRect()

    points = np.asarray(raw_box).reshape((-1, 2))
    if points.size == 0:
        return QRect()

    left = int(np.floor(points[:, 0].min()))
    top = int(np.floor(points[:, 1].min()))
    right = int(np.ceil(points[:, 0].max()))
    bottom = int(np.ceil(points[:, 1].max()))
    return QRect(left, top, max(1, right - left + 1), max(1, bottom - top + 1)).intersected(image_rect)
