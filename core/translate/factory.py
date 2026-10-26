"""Create the configured translation provider without coupling it to the UI."""

from __future__ import annotations

import logging
import time

from app.config import YoudaoCredentials
from app.translation_preferences import TranslationSettings, load_translation_settings
from core.translate.base import TranslationError, TranslationResult, Translator
from core.translate.chatgpt_account import (
    AccountQuotaExhausted,
    AccountSignedOut,
    ChatGPTAccountTranslator,
    load_tokens,
)
from core.translate.providers import (
    DeepLTranslator,
    GoogleTranslator,
    MicrosoftTranslator,
    OpenAITranslator,
)
from core.translate.youdao import YoudaoTranslator


_log = logging.getLogger(__name__)

# After the plan quota runs out, skip the account for a while instead of
# waiting for the same refusal on every screenshot.
QUOTA_PAUSE_SECONDS = 30 * 60
_account_paused_until = 0.0


class AccountFirstTranslator:
    """Translate on the ChatGPT plan quota; use the API service when that fails."""

    def __init__(self, account: Translator, api: Translator) -> None:
        self._account = account
        self._api = api
        # The service that produced the latest result, shown to the user.
        self.service_name = getattr(account, "service_name", "ChatGPT 账号")

    def translate_many(
        self,
        texts: tuple[str, ...],
        target: str = "zh",
        source: str = "auto",
    ) -> tuple[str, ...]:
        return self._call("translate_many", texts, target, source)

    def translate_one(self, text: str, target: str = "zh", source: str = "auto") -> str:
        return self._call("translate_one", text, target, source)

    def translate_to_chinese(self, text: str, source_language: str = "auto") -> TranslationResult:
        return self._call("translate_to_chinese", text, source_language)

    def translate_many_to_chinese(
        self,
        texts: tuple[str, ...],
        source_language: str = "auto",
    ) -> tuple[str, ...]:
        return self._call("translate_many_to_chinese", texts, source_language)

    def _call(self, method: str, *arguments):
        if self._account_available():
            try:
                result = getattr(self._account, method)(*arguments)
                self.service_name = getattr(self._account, "service_name", "ChatGPT 账号")
                return result
            except TranslationError as error:
                self._note_failure(error)
        result = getattr(self._api, method)(*arguments)
        self.service_name = getattr(self._api, "service_name", "翻译服务")
        return result

    @staticmethod
    def _account_available() -> bool:
        return time.time() >= _account_paused_until

    @staticmethod
    def _note_failure(error: TranslationError) -> None:
        global _account_paused_until
        if isinstance(error, (AccountQuotaExhausted, AccountSignedOut)):
            _account_paused_until = time.time() + QUOTA_PAUSE_SECONDS
        _log.warning("ChatGPT 账号翻译失败，改用 API 翻译服务：%s", error)


def create_translator(settings: TranslationSettings | None = None) -> Translator:
    """Return the configured service, preceded by the ChatGPT account if chosen."""
    current = settings or load_translation_settings()
    api = _api_translator(current)
    if current.chatgpt_preferred and load_tokens() is not None:
        return AccountFirstTranslator(ChatGPTAccountTranslator(current.chatgpt_model), api)
    return api


def _api_translator(current: TranslationSettings) -> Translator:
    """Return the API service selected in the encrypted local settings."""
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
