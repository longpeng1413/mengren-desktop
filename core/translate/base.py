"""Shared contracts and errors for pluggable translation providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TranslationError(RuntimeError):
    """Raised when text cannot be translated."""


class TranslationRateLimitError(TranslationError):
    """Raised when a provider temporarily limits request frequency."""


class BatchTranslationUnavailable(TranslationError):
    """Raised when a provider cannot translate a batch in one request."""


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """A successful text translation result."""

    source_text: str
    translated_text: str


class Translator(Protocol):
    """Interface used by the OCR translation worker."""

    def translate_to_chinese(self, text: str) -> TranslationResult:
        """Translate one string to Simplified Chinese."""

    def translate_many_to_chinese(self, texts: tuple[str, ...]) -> tuple[str, ...]:
        """Translate multiple strings while preserving their order."""


class BatchTranslator:
    """Base class for providers whose native API accepts text batches."""

    def translate_to_chinese(self, text: str) -> TranslationResult:
        source_text = text.strip()
        if not source_text:
            raise TranslationError("没有可翻译的文字。")
        translated = self.translate_many_to_chinese((source_text,))[0]
        return TranslationResult(source_text, translated)

    def translate_many_to_chinese(self, texts: tuple[str, ...]) -> tuple[str, ...]:
        raise NotImplementedError
