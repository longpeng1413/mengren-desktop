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


class _Response:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def test_deepl_batch_translation(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.translate.providers.urlopen",
        lambda *_args, **_kwargs: _Response(
            {"translations": [{"text": "你好"}, {"text": "世界"}]}
        ),
    )

    result = DeepLTranslator("secret").translate_many_to_chinese(("hello", "world"))

    assert result == ("你好", "世界")


def test_google_batch_translation(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.translate.providers.urlopen",
        lambda *_args, **_kwargs: _Response(
            {"data": {"translations": [{"translatedText": "你好"}]}}
        ),
    )

    result = GoogleTranslator("secret").translate_many_to_chinese(("hello",))

    assert result == ("你好",)


def test_microsoft_batch_translation(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.translate.providers.urlopen",
        lambda *_args, **_kwargs: _Response(
            [{"translations": [{"text": "你好", "to": "zh-Hans"}]}]
        ),
    )

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


def _capture_requests(monkeypatch, body: object) -> list:
    requests = []

    def fake_urlopen(request, *_args, **_kwargs):
        requests.append(request)
        return _Response(body)

    monkeypatch.setattr("core.translate.providers.urlopen", fake_urlopen)
    return requests


def test_english_source_is_named_for_mixed_chinese_text(monkeypatch) -> None:
    requests = _capture_requests(monkeypatch, {"translations": [{"text": "从这里开始"}]})
    DeepLTranslator("secret").translate_many_to_chinese(("Start at 老师",), "en")
    assert json.loads(requests[-1].data)["source_lang"] == "EN"

    DeepLTranslator("secret").translate_many_to_chinese(("hello",))
    assert "source_lang" not in json.loads(requests[-1].data)

    requests = _capture_requests(monkeypatch, {"data": {"translations": [{"translatedText": "你好"}]}})
    GoogleTranslator("secret").translate_many_to_chinese(("Start at 老师",), "en")
    assert json.loads(requests[-1].data)["source"] == "en"

    requests = _capture_requests(monkeypatch, [{"translations": [{"text": "你好"}]}])
    MicrosoftTranslator("secret", "").translate_many_to_chinese(("Start at 老师",), "en")
    assert "from=en" in requests[-1].full_url
