"""Background OCR, batch translation, and image overlay work for the editor."""

from __future__ import annotations

from time import sleep

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from core.ocr.ocr_service import OcrLine, OcrService
from core.translate.base import (
    BatchTranslationUnavailable,
    TranslationError,
    TranslationRateLimitError,
    Translator,
)
from core.translate.factory import create_translator
from core.translate.image_overlay import ImageTranslationRenderer, OverlayTranslation


class TranslationWorker(QObject):
    """Replaces source text with Chinese directly in a screenshot image."""

    _FALLBACK_INTERVAL_SECONDS = 0.6
    _RETRY_DELAYS_SECONDS = (1.5, 3.0, 4.5)

    succeeded = Signal(QImage)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, image: QImage) -> None:
        super().__init__()
        self._image = QImage(image)

    @Slot()
    def run(self) -> None:
        """Recognize, batch-translate, and render every recognized text line."""
        try:
            ocr_result = OcrService().recognize(self._image)
            if not ocr_result.lines:
                raise TranslationError("没有识别到可翻译的文字，请重新选择更清晰的区域。")

            translator = create_translator()
            translations = self._translate_all(translator, ocr_result.lines)
            translated_image = ImageTranslationRenderer().apply(self._image, translations)
            self.succeeded.emit(translated_image)
        except TranslationError as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit("识别或翻译失败，请重试。")
        finally:
            self.finished.emit()

    def _translate_all(
        self,
        translator: Translator,
        lines: tuple[OcrLine, ...],
    ) -> tuple[OverlayTranslation, ...]:
        """Use one batch request, with a throttled compatibility fallback."""
        source_texts = tuple(line.text for line in lines)
        try:
            translated_texts = self._translate_batch_with_retry(translator, source_texts)
            return tuple(
                OverlayTranslation(bounds=line.bounds, text=translated_text)
                for line, translated_text in zip(lines, translated_texts)
            )
        except BatchTranslationUnavailable:
            return tuple(
                self._translate_one_with_retry(translator, line, index)
                for index, line in enumerate(lines)
            )

    def _translate_batch_with_retry(
        self,
        translator: Translator,
        texts: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Retry a batched request only if the provider briefly rate-limits it."""
        for retry_delay in self._RETRY_DELAYS_SECONDS:
            try:
                return translator.translate_many_to_chinese(texts)
            except TranslationRateLimitError:
                sleep(retry_delay)
        return translator.translate_many_to_chinese(texts)

    def _translate_one_with_retry(
        self,
        translator: Translator,
        line: OcrLine,
        index: int,
    ) -> OverlayTranslation:
        """Keep old applications usable when the batch endpoint is unavailable."""
        if index:
            sleep(self._FALLBACK_INTERVAL_SECONDS)

        for retry_delay in self._RETRY_DELAYS_SECONDS:
            try:
                result = translator.translate_to_chinese(line.text)
                return OverlayTranslation(bounds=line.bounds, text=result.translated_text)
            except TranslationRateLimitError:
                sleep(retry_delay)

        result = translator.translate_to_chinese(line.text)
        return OverlayTranslation(bounds=line.bounds, text=result.translated_text)
