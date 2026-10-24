"""Youdao text and batch-translation client using official v3 signing."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import YoudaoCredentials, get_youdao_credentials
from core.translate.base import (
    BatchTranslationUnavailable,
    TranslationError,
    TranslationRateLimitError,
    TranslationResult,
)


class YoudaoTranslator:
    """Translates text to Simplified Chinese through Youdao."""

    endpoint = "https://openapi.youdao.com/api"
    batch_endpoint = "https://openapi.youdao.com/v2/api"

    def __init__(self, credentials: YoudaoCredentials | None = None) -> None:
        self._credentials = credentials or get_youdao_credentials()

    def translate_to_chinese(self, text: str, source_language: str = "auto") -> TranslationResult:
        """Translate one source string through Youdao's standard text API."""
        source_text = text.strip()
        self._require_credentials(source_text)

        salt = uuid.uuid4().hex
        curtime = str(int(time.time()))
        payload = self._common_fields(source_text, salt, curtime, source_language)
        payload.append(("q", source_text))
        body = self._post(self.endpoint, payload)
        self._raise_for_error(body)

        translated_parts = body.get("translation", [])
        translated_text = "\n".join(str(part) for part in translated_parts).strip()
        if not translated_text:
            raise TranslationError("有道翻译没有返回结果。")
        return TranslationResult(source_text, translated_text)

    def translate_many_to_chinese(
        self,
        texts: tuple[str, ...],
        source_language: str = "auto",
    ) -> tuple[str, ...]:
        """Translate many OCR lines in one request for responsive image overlays."""
        source_texts = tuple(text.strip() for text in texts if text.strip())
        if not source_texts:
            raise TranslationError("没有可翻译的文字。")
        self._require_credentials(source_texts[0])

        salt = uuid.uuid4().hex
        curtime = str(int(time.time()))
        signature_input = "".join(source_texts)
        payload = self._common_fields(signature_input, salt, curtime, source_language)
        payload.extend(("q", text) for text in source_texts)
        body = self._post(self.batch_endpoint, payload)

        error_code = str(body.get("errorCode", ""))
        if error_code in {"104", "110", "112"}:
            raise BatchTranslationUnavailable(_error_message(error_code))
        self._raise_for_error(body)

        results = body.get("translateResults", [])
        if len(results) != len(source_texts):
            raise BatchTranslationUnavailable("有道批量翻译返回不完整，正在切换兼容模式。")

        translations = tuple(str(item.get("translation", "")).strip() for item in results)
        if any(not translation for translation in translations):
            raise BatchTranslationUnavailable("有道批量翻译返回不完整，正在切换兼容模式。")
        return translations

    def _require_credentials(self, source_text: str) -> None:
        """Validate the local credentials and source text before a request."""
        if not source_text:
            raise TranslationError("没有可翻译的文字。")
        if not self._credentials.is_configured:
            raise TranslationError("未找到有道凭证，请检查项目根目录的 .env 文件。")

    def _common_fields(
        self,
        signature_input: str,
        salt: str,
        curtime: str,
        source_language: str = "auto",
    ) -> list[tuple[str, str]]:
        """Build the shared official v3 request form fields."""
        return [
            ("from", "en" if source_language == "en" else "auto"),
            ("to", "zh-CHS"),
            ("appKey", self._credentials.app_key),
            ("salt", salt),
            ("signType", "v3"),
            ("curtime", curtime),
            ("sign", self._sign(signature_input, salt, curtime)),
        ]

    def _post(self, endpoint: str, payload: list[tuple[str, str]]) -> dict[str, object]:
        """Send a form request and return its decoded JSON body."""
        try:
            request = Request(
                endpoint,
                data=urlencode(payload).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
                method="POST",
            )
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise TranslationError(f"有道翻译请求失败（HTTP {error.code}）。") from error
        except URLError as error:
            raise TranslationError("无法连接有道翻译服务，请检查网络后重试。") from error

    def _raise_for_error(self, body: dict[str, object]) -> None:
        """Translate Youdao error codes into typed local exceptions."""
        error_code = str(body.get("errorCode", ""))
        if error_code == "0":
            return
        if error_code == "411":
            raise TranslationRateLimitError(_error_message(error_code))
        raise TranslationError(_error_message(error_code))

    def _sign(self, query: str, salt: str, curtime: str) -> str:
        value = (
            self._credentials.app_key
            + _truncate(query)
            + salt
            + curtime
            + self._credentials.app_secret
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _truncate(query: str) -> str:
    """Apply Youdao's v3 query truncation rule."""
    if len(query) <= 20:
        return query
    return f"{query[:10]}{len(query)}{query[-10:]}"


def _error_message(error_code: str) -> str:
    """Convert common Youdao API errors into actionable local messages."""
    messages = {
        "101": "有道翻译请求缺少参数。",
        "104": "当前应用不支持有道批量翻译接口。",
        "108": "有道应用 ID 无效：.env 的 AISHOT_YOUDAO_APP_KEY 必须填写“应用ID”，不能填写 APIKey。",
        "110": "当前应用尚未开通文本翻译（NMT）服务。",
        "112": "有道翻译服务不可用。",
        "202": "有道签名校验失败，请检查 .env 中的应用密钥。",
        "205": "有道应用接入方式不匹配，请确认应用创建时选择了 API。",
        "401": "有道账户已欠费，请检查有道智云账户余额。",
        "411": "有道翻译访问频率受限，请稍后重试。",
    }
    return messages.get(error_code, f"有道翻译失败（错误码 {error_code}）。")
