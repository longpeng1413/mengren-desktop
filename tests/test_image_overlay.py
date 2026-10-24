"""Tests for translated text rendered into an image."""

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.translate.image_overlay import ImageTranslationRenderer, OverlayTranslation


@pytest.fixture(autouse=True)
def _application():
    """Drawing text needs a running Qt application."""
    return QApplication.instance() or QApplication([])


def test_overlay_preserves_image_size_and_changes_target_area() -> None:
    source = QImage(240, 80, QImage.Format.Format_ARGB32)
    source.fill(QColor("#202020"))

    translated = ImageTranslationRenderer().apply(
        source,
        (OverlayTranslation(QRect(20, 20, 180, 34), "开始使用"),),
    )

    assert translated.size() == source.size()
    assert translated != source


def _drawn_sizes(monkeypatch, source, translations):
    sizes = []
    monkeypatch.setattr(
        "core.translate.image_overlay._draw_paragraph",
        lambda _painter, text, _rect, size, color, _height: sizes.append((text, size, color.name())),
    )
    ImageTranslationRenderer().apply(source, translations)
    return sizes


def test_body_text_of_similar_height_shares_one_size(monkeypatch) -> None:
    source = QImage(800, 300, QImage.Format.Format_ARGB32)
    source.fill(QColor("#151515"))
    translations = (
        OverlayTranslation(QRect(20, 20, 700, 38), "你说得对：跨屏拖动只有在第一次选区已经跨屏时才有效。", 18),
        OverlayTranslation(QRect(20, 70, 700, 54), "修复：编辑画面现在从一开始就覆盖所有缩放相同的屏幕。", 16),
        OverlayTranslation(QRect(20, 140, 60, 17), "检查：", 17),
        OverlayTranslation(QRect(20, 200, 600, 40), "大标题", 36),
    )

    sizes = {text: size for text, size, _color in _drawn_sizes(monkeypatch, source, translations)}

    assert sizes["你说得对：跨屏拖动只有在第一次选区已经跨屏时才有效。"] == sizes["检查："]
    assert sizes["修复：编辑画面现在从一开始就覆盖所有缩放相同的屏幕。"] == sizes["检查："]
    assert sizes["大标题"] > sizes["检查："]


def test_only_a_paragraph_that_cannot_fit_is_drawn_smaller(monkeypatch) -> None:
    source = QImage(800, 200, QImage.Format.Format_ARGB32)
    source.fill(QColor("white"))
    translations = (
        OverlayTranslation(QRect(20, 20, 300, 18), "第一段", 18),
        OverlayTranslation(QRect(20, 60, 300, 18), "第二段", 18),
        OverlayTranslation(QRect(20, 100, 120, 18), "这一段的译文很长很长很长很长很长很长很长很长", 18),
    )

    sizes = [size for _text, size, _color in _drawn_sizes(monkeypatch, source, translations)]

    assert sizes[0] == sizes[1]
    assert sizes[2] < sizes[0]


def test_coloured_source_text_keeps_its_colour(monkeypatch) -> None:
    source = QImage(400, 60, QImage.Format.Format_RGB32)
    source.fill(QColor("#fafafa"))
    painter = QPainter(source)
    painter.fillRect(QRect(30, 25, 200, 6), QColor("#1a73e8"))
    painter.end()

    drawn = _drawn_sizes(monkeypatch, source, (OverlayTranslation(QRect(20, 15, 260, 26), "提示", 26),))

    assert drawn[0][2] == "#1a73e8"
