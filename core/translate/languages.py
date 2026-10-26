"""Languages offered for text translation and each service's code for them."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Language:
    """One language: its short code, Chinese label and English name."""

    code: str
    label: str
    english: str


LANGUAGES: tuple[Language, ...] = (
    Language("zh", "中文", "Simplified Chinese"),
    Language("en", "英文", "English"),
    Language("ja", "日语", "Japanese"),
    Language("ko", "韩语", "Korean"),
    Language("fr", "法语", "French"),
    Language("de", "德语", "German"),
    Language("ru", "俄语", "Russian"),
    Language("es", "西班牙语", "Spanish"),
    Language("pt", "葡萄牙语", "Portuguese"),
)

AUTO = "auto"
_BY_CODE = {language.code: language for language in LANGUAGES}

# Codes that differ from the short code above; others are used unchanged.
YOUDAO_CODES = {"zh": "zh-CHS"}
DEEPL_TARGET_CODES = {"zh": "ZH-HANS", "en": "EN-US", "pt": "PT-BR"}
GOOGLE_CODES = {"zh": "zh-CN"}
MICROSOFT_CODES = {"zh": "zh-Hans"}


def language(code: str) -> Language:
    """Return a known language; unknown codes raise ``KeyError``."""
    return _BY_CODE[code]


def label(code: str) -> str:
    return "自动检测" if code == AUTO else _BY_CODE[code].label


def english_name(code: str) -> str:
    return _BY_CODE[code].english


def youdao_code(code: str) -> str:
    return code if code == AUTO else YOUDAO_CODES.get(code, code)


def deepl_target(code: str) -> str:
    return DEEPL_TARGET_CODES.get(code, code.upper())


def deepl_source(code: str) -> str | None:
    return None if code == AUTO else code.upper()


def google_code(code: str) -> str | None:
    return None if code == AUTO else GOOGLE_CODES.get(code, code)


def microsoft_code(code: str) -> str | None:
    return None if code == AUTO else MICROSOFT_CODES.get(code, code)
