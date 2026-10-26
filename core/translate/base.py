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
    """Interface used by screenshot and free-text translation.

    Languages are short codes from :mod:`core.translate.languages`; ``source``
    may also be ``"auto"``. Screenshots pass English as the source for text
    that mixes Chinese terms into English sentences: automatic detection may
    call such text Chinese and translate it into English instead.
    """

    service_name: str

    def translate_many(
        self,
        texts: tuple[str, ...],
        target: str = "zh",
        source: str = "auto",
    ) -> tuple[str, ...]:
        """Translate several strings into ``target``, preserving their order."""

    def translate_one(self, text: str, target: str = "zh", source: str = "auto") -> str:
        """Translate one passage (it may hold several lines) into ``target``."""

    def translate_to_chinese(self, text: str, source_language: str = "auto") -> TranslationResult:
        """Translate one string to Simplified Chinese."""

    def translate_many_to_chinese(
        self,
        texts: tuple[str, ...],
        source_language: str = "auto",
    ) -> tuple[str, ...]:
        """Translate multiple strings to Simplified Chinese."""


class BatchTranslator:
    """Base class for providers whose native API accepts text batches."""

    service_name = "翻译服务"

    def translate_many(
        self,
        texts: tuple[str, ...],
        target: str = "zh",
        source: str = "auto",
    ) -> tuple[str, ...]:
        raise NotImplementedError

    def translate_one(self, text: str, target: str = "zh", source: str = "auto") -> str:
        source_text = text.strip()
        if not source_text:
            raise TranslationError("没有可翻译的文字。")
        return self.translate_many((source_text,), target, source)[0]

    def translate_to_chinese(self, text: str, source_language: str = "auto") -> TranslationResult:
        source_text = text.strip()
        if not source_text:
            raise TranslationError("没有可翻译的文字。")
        return TranslationResult(source_text, self.translate_one(source_text, "zh", source_language))

    def translate_many_to_chinese(
        self,
        texts: tuple[str, ...],
        source_language: str = "auto",
    ) -> tuple[str, ...]:
        return self.translate_many(texts, "zh", source_language)
