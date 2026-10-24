"""Encrypted per-user translation provider settings for Windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path

from app.config import get_youdao_credentials


PROVIDER_LABELS: tuple[tuple[str, str], ...] = (
    ("youdao", "有道翻译"),
    ("deepl", "DeepL"),
    ("openai", "OpenAI"),
    ("google", "Google Cloud Translation"),
    ("microsoft", "Microsoft Translator"),
)


# Models offered in the settings dropdown, best first, with a short reason.
# Measured on real screenshots in October 2026: the small "nano" models leave
# English words untranslated, so they are not offered.
OPENAI_MODEL_CHOICES: tuple[tuple[str, str], ...] = (
    ("gpt-6.1-sol", "推荐：译文最准确自然"),
    ("gpt-6-sol", "译文好、速度快"),
    ("gpt-5.6-luna", "更省钱，译文质量不错"),
    ("gpt-6-luna", "最省钱，速度稍慢"),
)


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    """Provider choice and credentials stored only for the current Windows user."""

    provider: str = "youdao"
    youdao_app_key: str = ""
    youdao_app_secret: str = ""
    deepl_api_key: str = ""
    deepl_use_free_api: bool = True
    openai_api_key: str = ""
    openai_model: str = "gpt-6.1-sol"
    openai_base_url: str = "https://api.openai.com/v1"
    google_api_key: str = ""
    microsoft_api_key: str = ""
    microsoft_region: str = ""
    # Translate on the signed-in ChatGPT plan quota first, then the API service.
    chatgpt_preferred: bool = False
    chatgpt_model: str = "gpt-6.1-sol"


class _DataBlob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte)))


def _settings_file() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home())) / "AIShot"
    return root / "translation-settings.bin"


def load_translation_settings() -> TranslationSettings:
    """Load DPAPI-protected settings, migrating the old .env values when needed."""
    path = _settings_file()
    try:
        values = json.loads(_unprotect(path.read_bytes()).decode("utf-8"))
        allowed = TranslationSettings.__dataclass_fields__
        return TranslationSettings(**{key: value for key, value in values.items() if key in allowed})
    except (OSError, ValueError, TypeError, UnicodeError):
        credentials = get_youdao_credentials()
        return TranslationSettings(
            youdao_app_key=credentials.app_key,
            youdao_app_secret=credentials.app_secret,
        )


def save_translation_settings(settings: TranslationSettings) -> None:
    """Encrypt and persist all provider settings for the current Windows account."""
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(settings), ensure_ascii=False).encode("utf-8")
    path.write_bytes(_protect(payload))


def protect_for_user(data: bytes) -> bytes:
    """Encrypt bytes so only the current Windows account can read them."""
    return _protect(data)


def unprotect_for_user(data: bytes) -> bytes:
    """Decrypt bytes written by :func:`protect_for_user`."""
    return _unprotect(data)


def _protect(data: bytes) -> bytes:
    source, source_buffer = _make_blob(data)
    destination = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source),
        "AIShot translation credentials",
        None,
        None,
        None,
        0x1,
        ctypes.byref(destination),
    ):
        raise OSError("Windows 无法加密翻译密钥。")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)
        del source_buffer


def _unprotect(data: bytes) -> bytes:
    source, source_buffer = _make_blob(data)
    destination = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(destination),
    ):
        raise OSError("Windows 无法解密翻译密钥。")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)
        del source_buffer


def _make_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer
