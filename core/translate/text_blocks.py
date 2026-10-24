"""Group OCR lines into paragraphs so each is translated as a whole."""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median

import cv2
import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from core.ocr.ocr_service import OcrLine


# A leading list marker is kept aside so translation can never drop it.
_LIST_MARKER = re.compile(r"^\s*([•·●▪◦■□➢►\-–—*]|\d{1,2}[.)、]|[a-zA-Z][.)])\s+")


@dataclass(frozen=True, slots=True)
class TextBlock:
    """One paragraph: its source text, image area and typical line height."""

    text: str
    bounds: QRect
    line_height: int
    prefix: str = ""


@dataclass(slots=True)
class _Row:
    text: str
    bounds: QRect


def group_text_blocks(lines: tuple[OcrLine, ...], image: QImage | None = None) -> tuple[TextBlock, ...]:
    """Merge OCR lines into rows, then rows into paragraphs, in reading order."""
    rows = _merge_rows(lines)
    paragraphs: list[list[_Row]] = []
    for row in sorted(rows, key=lambda item: (item.bounds.top(), item.bounds.left())):
        starts_new = _starts_list_item(row, rows, image)
        target = None
        if not starts_new:
            candidates = [
                paragraph
                for paragraph in paragraphs
                if _continues(paragraph[-1], row)
            ]
            if candidates:
                target = min(
                    candidates,
                    key=lambda paragraph: row.bounds.top() - paragraph[-1].bounds.top(),
                )
        if target is None:
            paragraphs.append([row])
        else:
            target.append(row)

    blocks = []
    for paragraph in paragraphs:
        text = paragraph[0].text
        bounds = QRect(paragraph[0].bounds)
        for row in paragraph[1:]:
            text = _join(text, row.text)
            bounds = bounds.united(row.bounds)
        prefix = ""
        marker = _LIST_MARKER.match(text)
        if marker is not None and len(text) > marker.end():
            prefix = marker.group(1) + " "
            text = text[marker.end():]
        line_height = round(median(row.bounds.height() for row in paragraph))
        blocks.append(TextBlock(text.strip(), bounds, line_height, prefix))
    blocks.sort(key=lambda block: (block.bounds.top(), block.bounds.left()))
    return tuple(_snap_left_edges(blocks))


def _snap_left_edges(blocks: list[TextBlock]) -> list[TextBlock]:
    """Give paragraphs whose OCR left edges differ by a few pixels one shared edge."""
    snapped = []
    for block in blocks:
        near = [
            other.bounds.left()
            for other in blocks
            if abs(other.bounds.left() - block.bounds.left()) <= 4
        ]
        bounds = QRect(block.bounds)
        bounds.setLeft(min(near))
        snapped.append(TextBlock(block.text, bounds, block.line_height, block.prefix))
    return snapped


def _merge_rows(lines: tuple[OcrLine, ...]) -> list[_Row]:
    """Join fragments that OCR split from one visual line."""
    rows: list[_Row] = []
    for line in sorted(lines, key=lambda item: (item.bounds.left(), item.bounds.top())):
        bounds = line.bounds
        target = None
        for row in rows:
            height = min(row.bounds.height(), bounds.height())
            overlap = min(row.bounds.bottom(), bounds.bottom()) - max(row.bounds.top(), bounds.top())
            gap = bounds.left() - row.bounds.right()
            if overlap >= 0.6 * height and -height <= gap <= 1.5 * height:
                target = row
                break
        if target is None:
            rows.append(_Row(line.text.strip(), QRect(bounds)))
        else:
            target.text = _join(target.text, line.text.strip())
            target.bounds = target.bounds.united(bounds)
    return rows


def _continues(previous: _Row, row: _Row) -> bool:
    """Return whether ``row`` is the next line of the paragraph ending in ``previous``."""
    above = previous.bounds
    below = row.bounds
    height = (above.height() + below.height()) / 2
    if max(above.height(), below.height()) > 1.5 * min(above.height(), below.height()):
        return False
    pitch = below.top() - above.top()
    if not 0.6 * height <= pitch <= 1.5 * height:
        return False
    left_aligned = abs(below.left() - above.left()) <= 1.5 * height
    centered = abs(below.center().x() - above.center().x()) <= 1.5 * height
    if not (left_aligned or centered):
        return False
    # A line that stops well short of the next one ended its paragraph,
    # e.g. a "Checks:" heading or the last line of a list item. Ragged-right
    # lines inside one paragraph often differ by several words, so compare
    # widths rather than a fixed distance.
    if (
        left_aligned
        and not centered
        and above.width() < 0.7 * below.width()
        and above.right() + 3 * height < below.right()
    ):
        return False
    return True


def _starts_list_item(row: _Row, rows: list[_Row], image: QImage | None) -> bool:
    """Detect a list item from a text marker or a bullet dot drawn left of it."""
    if _LIST_MARKER.match(row.text):
        return True
    if image is None or image.isNull():
        return False
    height = row.bounds.height()
    strip = QRect(
        row.bounds.left() - int(2.2 * height),
        row.bounds.top(),
        int(2.2 * height) - 2,
        height,
    ).intersected(image.rect())
    if strip.width() < 4 or strip.height() < 4:
        return False
    if any(other is not row and other.bounds.intersects(strip) for other in rows):
        return False
    pixels = _rgb_array(image.copy(strip)).astype(np.int16)
    border = np.concatenate((pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]))
    background = np.median(border, axis=0)
    marked = (np.abs(pixels - background).max(axis=2) > 60).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(marked, connectivity=8)
    for index in range(1, count):
        left, top, width, tall, area = (int(value) for value in stats[index])
        if area < 4 or width > 0.7 * height or tall > 0.7 * height:
            continue
        if not 0.5 <= width / tall <= 2.0:
            continue
        # Pixels touching the right edge belong to the line's own first letter.
        if left + width >= strip.width() - 1:
            continue
        middle = top + tall / 2
        if 0.2 * height <= middle <= 0.8 * height:
            return True
    return False


def _rgb_array(image: QImage) -> np.ndarray:
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = rgb.width(), rgb.height()
    data = np.frombuffer(rgb.constBits(), dtype=np.uint8)
    return data.reshape((height, rgb.bytesPerLine()))[:, : width * 3].reshape((height, width, 3))


def _join(first: str, second: str) -> str:
    """Join two pieces of one sentence, with a space only between Latin words."""
    if not first:
        return second
    if not second:
        return first
    if first.endswith("-") and second[:1].islower():
        return first[:-1] + second
    if _is_cjk(first[-1]) or _is_cjk(second[0]):
        return first + second
    return f"{first} {second}"


_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_KANA_HANGUL = re.compile(r"[぀-ヿᄀ-ᇿ가-힯]")
# Runs of letters from alphabetic scripts (Latin, Cyrillic, ...), not Han,
# kana, hangul, digits or underscores.
_FOREIGN_WORD = re.compile(
    r"[^\W\d_぀-ヿᄀ-ᇿ㐀-䶿一-鿿가-힯豈-﫿]+"
)


def han_count(text: str) -> int:
    """Count Chinese characters."""
    return len(_HAN.findall(text))


def source_language(text: str) -> str | None:
    """Decide how a paragraph is translated so the result is entirely Chinese.

    ``None`` means it is already Chinese (an English product name inside a
    Chinese sentence does not count) or holds no words, so it stays as is.
    ``"en"`` means English sentences mixing in Chinese terms: automatic
    language detection could call them Chinese and translate them into English.
    ``"auto"`` covers everything else, such as pure English or Japanese.
    """
    han = han_count(text)
    syllables = len(_KANA_HANGUL.findall(text))
    words = _FOREIGN_WORD.findall(text)
    # One alphabetic word carries roughly the meaning of 1.5 Chinese characters.
    foreign = syllables + 1.5 * len(words)
    if foreign < 1.5 or foreign / (foreign + han) < 0.3:
        return None
    latin_words = sum(1 for word in words if word.isascii())
    if han and not syllables and latin_words * 2 >= len(words):
        return "en"
    return "auto"


def _is_cjk(character: str) -> bool:
    code = ord(character)
    return (
        0x3000 <= code <= 0x30FF
        or 0x3400 <= code <= 0x9FFF
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF00 <= code <= 0xFFEF
    )
