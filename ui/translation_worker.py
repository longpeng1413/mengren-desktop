"""Background OCR, paragraph translation, and image overlay work for the editor."""

from __future__ import annotations

import logging
from time import sleep

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from core.ocr.ocr_service import OcrService
from core.translate.base import (
    BatchTranslationUnavailable,
    TranslationError,
    TranslationRateLimitError,
    Translator,
)
from core.translate.factory import create_translator
from core.translate.image_overlay import ImageTranslationRenderer, OverlayTranslation
from core.translate.text_blocks import TextBlock, group_text_blocks, han_count, source_language


_log = logging.getLogger(__name__)


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
        """Recognize text, translate it paragraph by paragraph, and render it."""
        try:
            ocr_result = OcrService().recognize(self._image)
            if not ocr_result.lines:
                raise TranslationError("没有识别到可翻译的文字，请重新选择更清晰的区域。")

            # Whole paragraphs translate correctly; single OCR lines are often
            # half sentences that a translator cannot understand.
            blocks = group_text_blocks(ocr_result.lines, self._image)
            translator = create_translator()
            translations = self._translate_all(translator, blocks)
            translated_image = ImageTranslationRenderer().apply(self._image, translations)
            self.succeeded.emit(translated_image)
        except TranslationError as error:
            _log.warning("截图翻译失败：%s", error, exc_info=error.__cause__ is not None)
            self.failed.emit(str(error))
        except Exception:
            _log.exception("截图翻译出现意外错误")
            self.failed.emit("识别或翻译失败，请重试。详细原因已写入日志，可在主窗口点“打开日志文件夹”查看。")
        finally:
            self.finished.emit()

    def _translate_all(
        self,
        translator: Translator,
        blocks: tuple[TextBlock, ...],
    ) -> tuple[OverlayTranslation, ...]:
        """Translate every non-Chinese paragraph so the whole image reads Chinese.

        Paragraphs that are already Chinese are left untouched in the image.
        English mixed with Chinese terms is sent as English, one request per
        source language, and a result that came back less Chinese than its
        source (translated the wrong way) is dropped, keeping the original.
        """
        groups: dict[str, list[int]] = {}
        for index, block in enumerate(blocks):
            language = source_language(block.text)
            if language is not None:
                groups.setdefault(language, []).append(index)
        if not groups:
            raise TranslationError("截图里的文字已经是中文，不需要翻译。")

        translated: dict[int, str] = {}
        for language, indexes in groups.items():
            texts = tuple(blocks[index].text for index in indexes)
            try:
                results = self._translate_batch_with_retry(translator, texts, language)
            except BatchTranslationUnavailable:
                results = tuple(
                    self._translate_one_with_retry(translator, text, position, language)
                    for position, text in enumerate(texts)
                )
            translated.update(zip(indexes, results))

        return tuple(
            OverlayTranslation(
                bounds=blocks[index].bounds,
                text=blocks[index].prefix + text,
                line_height=blocks[index].line_height,
            )
            for index, text in sorted(translated.items())
            if han_count(text) > han_count(blocks[index].text)
        )

    def _translate_batch_with_retry(
        self,
        translator: Translator,
        texts: tuple[str, ...],
        language: str = "auto",
    ) -> tuple[str, ...]:
        """Retry a batched request only if the provider briefly rate-limits it."""
        for retry_delay in self._RETRY_DELAYS_SECONDS:
            try:
                return translator.translate_many_to_chinese(texts, language)
            except TranslationRateLimitError:
                sleep(retry_delay)
        return translator.translate_many_to_chinese(texts, language)

    def _translate_one_with_retry(
        self,
        translator: Translator,
        text: str,
        index: int,
        language: str = "auto",
    ) -> str:
        """Keep old applications usable when the batch endpoint is unavailable."""
        if index:
            sleep(self._FALLBACK_INTERVAL_SECONDS)

        for retry_delay in self._RETRY_DELAYS_SECONDS:
            try:
                return translator.translate_to_chinese(text, language).translated_text
            except TranslationRateLimitError:
                sleep(retry_delay)

        return translator.translate_to_chinese(text, language).translated_text
