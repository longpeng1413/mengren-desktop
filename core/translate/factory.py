"""Create the configured translation provider without coupling it to the UI."""

from __future__ import annotations

from app.config import YoudaoCredentials
from app.translation_preferences import TranslationSettings, load_translation_settings
from core.translate.base import TranslationError, Translator
from core.translate.providers import (
    DeepLTranslator,
    GoogleTranslator,
    MicrosoftTranslator,
    OpenAITranslator,
)
from core.translate.youdao import YoudaoTranslator


def create_translator(settings: TranslationSettings | None = None) -> Translator:
    """Return the provider selected in the encrypted local settings."""
    current = settings or load_translation_settings()
    if current.provider == "youdao":
        return YoudaoTranslator(
            YoudaoCredentials(current.youdao_app_key, current.youdao_app_secret)
        )
    if current.provider == "deepl":
        return DeepLTranslator(current.deepl_api_key, current.deepl_use_free_api)
    if current.provider == "openai":
        return OpenAITranslator(
            current.openai_api_key,
            current.openai_model,
            current.openai_base_url,
        )
    if current.provider == "google":
        return GoogleTranslator(current.google_api_key)
    if current.provider == "microsoft":
        return MicrosoftTranslator(current.microsoft_api_key, current.microsoft_region)
    raise TranslationError("翻译服务设置无效，请重新选择翻译服务。")
