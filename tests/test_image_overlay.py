"""Tests for translated text rendered into an image."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from core.translate.image_overlay import ImageTranslationRenderer, OverlayTranslation


def test_overlay_preserves_image_size_and_changes_target_area() -> None:
    source = QImage(240, 80, QImage.Format.Format_ARGB32)
    source.fill(QColor("#202020"))

    translated = ImageTranslationRenderer().apply(
        source,
        (OverlayTranslation(QRect(20, 20, 180, 34), "开始使用"),),
    )

    assert translated.size() == source.size()
    assert translated != source
