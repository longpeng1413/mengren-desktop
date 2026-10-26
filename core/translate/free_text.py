"""Translate typed or pasted text with the services set up for screenshots.

There is no offline translation model in the app (one would add hundreds of
megabytes and translate far worse), so this uses the same order as screenshot
translation: the ChatGPT account first when chosen, then the API service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.translate import languages
from core.translate.base import TranslationError, Translator
from core.translate.factory import create_translator
from core.translate.text_blocks import han_count, source_language

AUTO_PAIR = "auto"  # Chinese into English, anything else into Chinese.
MAX_CHARACTERS = 5000  # Youdao's limit for one request.


@dataclass(frozen=True, slots=True)
class FreeTextResult:
    """A finished translation and how it was made."""

    text: str
    target: str
    service: str
    seconds: float


def resolve_target(text: str, target: str) -> str:
    """Turn the automatic Chinese/English choice into a real language."""
    if target != AUTO_PAIR:
        return target
    mostly_chinese = han_count(text) > 0 and source_language(text) is None
    return "en" if mostly_chinese else "zh"


def translate_text(
    text: str,
    target: str = AUTO_PAIR,
    source: str = languages.AUTO,
    translator: Translator | None = None,
) -> FreeTextResult:
    """Translate one passage, keeping its line breaks."""
    cleaned = text.strip()
    if not cleaned:
        raise TranslationError("请先输入要翻译的文字。")
    if len(cleaned) > MAX_CHARACTERS:
        raise TranslationError(f"一次最多翻译 {MAX_CHARACTERS} 个字，请分段翻译。")
    real_target = resolve_target(cleaned, target)
    if source == real_target:
        raise TranslationError("原文语言和目标语言相同，请换一个目标语言。")
    service = translator or create_translator()
    started = time.perf_counter()
    translated = service.translate_one(cleaned, real_target, source)
    return FreeTextResult(
        translated,
        real_target,
        getattr(service, "service_name", "翻译服务"),
        time.perf_counter() - started,
    )
