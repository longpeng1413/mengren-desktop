"""Tests for provider response parsing without external network calls."""

import json

from app.translation_preferences import TranslationSettings
from core.translate.factory import create_translator
from core.translate.providers import (
    DeepLTranslator,
    GoogleTranslator,
    MicrosoftTranslator,
    OpenAITranslator,
    _openai_output_text,
)


def _reply(monkeypatch, body: object) -> list:
    """Answer every request with ``body`` and return the requests sent."""
    requests = []

    def fake_open(_opener, request, _timeout):
        requests.append(request)
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    monkeypatch.setattr("core.translate.http._open", fake_open)
    return requests


def test_deepl_batch_translation(monkeypatch) -> None:
    _reply(monkeypatch, {"translations": [{"text": "你好"}, {"text": "世界"}]})

    result = DeepLTranslator("secret").translate_many_to_chinese(("hello", "world"))

    assert result == ("你好", "世界")


def test_google_batch_translation(monkeypatch) -> None:
    _reply(monkeypatch, {"data": {"translations": [{"translatedText": "你好"}]}})

    result = GoogleTranslator("secret").translate_many_to_chinese(("hello",))

    assert result == ("你好",)


def test_microsoft_batch_translation(monkeypatch) -> None:
    _reply(monkeypatch, [{"translations": [{"text": "你好", "to": "zh-Hans"}]}])

    result = MicrosoftTranslator("secret", "eastasia").translate_many_to_chinese(
        ("hello",)
    )

    assert result == ("你好",)


def test_openai_output_text_is_extracted_from_responses_api() -> None:
    body = {
        "output": [
            {"content": [{"type": "output_text", "text": '{"translations":["你好"]}'}]}
        ]
    }

    assert _openai_output_text(body) == '{"translations":["你好"]}'


def test_factory_creates_selected_provider() -> None:
    translator = create_translator(
        TranslationSettings(
            provider="openai",
            openai_api_key="secret",
            openai_model="model",
            openai_base_url="https://example.test/v1",
        )
    )

    assert isinstance(translator, OpenAITranslator)


def test_english_source_is_named_for_mixed_chinese_text(monkeypatch) -> None:
    requests = _reply(monkeypatch, {"translations": [{"text": "从这里开始"}]})
    DeepLTranslator("secret").translate_many_to_chinese(("Start at 老师",), "en")
    assert json.loads(requests[-1].data)["source_lang"] == "EN"

    DeepLTranslator("secret").translate_many_to_chinese(("hello",))
    assert "source_lang" not in json.loads(requests[-1].data)

    requests = _reply(monkeypatch, {"data": {"translations": [{"translatedText": "你好"}]}})
    GoogleTranslator("secret").translate_many_to_chinese(("Start at 老师",), "en")
    assert json.loads(requests[-1].data)["source"] == "en"

    requests = _reply(monkeypatch, [{"translations": [{"text": "你好"}]}])
    MicrosoftTranslator("secret", "").translate_many_to_chinese(("Start at 老师",), "en")
    assert "from=en" in requests[-1].full_url
