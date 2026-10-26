"""Tests for the F3 text translator and translating into any language."""

import json
import time

import pytest
from PySide6.QtWidgets import QApplication

from app.config import YoudaoCredentials
from core.translate import factory, http, languages
from core.translate.base import BatchTranslator, TranslationError
from core.translate.free_text import AUTO_PAIR, resolve_target, translate_text
from core.translate.providers import (
    DeepLTranslator,
    GoogleTranslator,
    MicrosoftTranslator,
    OpenAITranslator,
    translation_instructions,
)
from core.translate.youdao import YoudaoTranslator
from ui import reminder_widget
from ui.translator_window import TranslatorWindow


def _reply(monkeypatch, body: object) -> list:
    requests = []

    def fake_open(_opener, request, _timeout):
        requests.append(request)
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    monkeypatch.setattr(http, "_open", fake_open)
    return requests


class _Echo(BatchTranslator):
    service_name = "测试服务"

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self._error = error

    def translate_many(self, texts, target="zh", source="auto"):
        self.calls.append((texts, target, source))
        if self._error is not None:
            raise self._error
        return tuple(f"[{target}]{text}" for text in texts)


# ------------------------------------------------------------ languages ----


def test_each_service_gets_its_own_language_codes(monkeypatch) -> None:
    requests = _reply(monkeypatch, {"translations": [{"text": "hello"}]})
    DeepLTranslator("key").translate_many(("你好",), "en", "zh")
    body = json.loads(requests[-1].data)
    assert (body["target_lang"], body["source_lang"]) == ("EN-US", "ZH")

    requests = _reply(monkeypatch, {"data": {"translations": [{"translatedText": "hola"}]}})
    GoogleTranslator("key").translate_many(("hello",), "es")
    body = json.loads(requests[-1].data)
    assert body["target"] == "es" and "source" not in body

    requests = _reply(monkeypatch, [{"translations": [{"text": "bonjour"}]}])
    MicrosoftTranslator("key", "").translate_many(("hello",), "fr", "en")
    assert "to=fr" in requests[-1].full_url and "from=en" in requests[-1].full_url

    fields = dict(YoudaoTranslator(YoudaoCredentials("k", "s"))._common_fields("q", "salt", "1", "auto", "ja"))
    assert (fields["from"], fields["to"]) == ("auto", "ja")
    fields = dict(YoudaoTranslator(YoudaoCredentials("k", "s"))._common_fields("q", "salt", "1"))
    assert fields["to"] == "zh-CHS"


def test_language_models_are_told_the_target_language(monkeypatch) -> None:
    requests = _reply(monkeypatch, {"output_text": json.dumps({"translations": ["Hello"]})})

    OpenAITranslator("key", "gpt-6.1-sol", "https://api.openai.com/v1").translate_many(("你好",), "en")

    assert "into English" in json.loads(requests[-1].data)["instructions"]
    assert "Simplified Chinese" in translation_instructions("zh")
    assert "from Japanese into Korean" in translation_instructions("ko", "ja")


def test_screenshot_translation_still_targets_chinese() -> None:
    echo = _Echo()

    assert echo.translate_many_to_chinese(("hello",), "en") == ("[zh]hello",)
    assert echo.calls == [(("hello",), "zh", "en")]


# ------------------------------------------------------------ free text ----


@pytest.mark.parametrize(
    ("text", "target", "expected"),
    [
        ("今天天气很好。", AUTO_PAIR, "en"),
        ("The weather is nice today.", AUTO_PAIR, "zh"),
        ("これは日本語です。", AUTO_PAIR, "zh"),
        ("今天天气很好。", "ja", "ja"),
    ],
)
def test_chinese_and_english_translate_into_each_other(text, target, expected) -> None:
    assert resolve_target(text, target) == expected


def test_free_text_reports_service_and_keeps_lines() -> None:
    echo = _Echo()

    result = translate_text("第一行\n第二行", AUTO_PAIR, languages.AUTO, echo)

    assert result.text == "[en]第一行\n第二行"
    assert (result.target, result.service) == ("en", "测试服务")


@pytest.mark.parametrize(
    ("text", "source", "target", "message"),
    [
        ("   ", "auto", "zh", "请先输入"),
        ("hello", "en", "en", "相同"),
        ("字" * 5001, "auto", "en", "最多"),
    ],
)
def test_free_text_explains_what_to_fix(text, source, target, message) -> None:
    with pytest.raises(TranslationError, match=message):
        translate_text(text, target, source, _Echo())


def test_api_takes_over_and_is_named_when_the_account_fails(monkeypatch) -> None:
    monkeypatch.setattr(factory, "_account_paused_until", 0.0)
    account = _Echo(error=TranslationError("账号出错"))
    account.service_name = "ChatGPT 账号"
    api = _Echo()
    translator = factory.AccountFirstTranslator(account, api)

    assert translator.translate_one("hello", "ja") == "[ja]hello"
    assert translator.service_name == "测试服务"


# --------------------------------------------------------------- window ----


def _wait_for(condition, seconds: float = 5.0) -> bool:
    app = QApplication.instance()
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_window_translates_in_the_background(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "core.translate.free_text.create_translator",
        lambda: _Echo(),
    )
    window = TranslatorWindow()
    window.source_edit.setPlainText("你好")

    window.translate()

    assert _wait_for(lambda: window.result_edit.toPlainText() == "[en]你好")
    assert "测试服务" in window.status_label.text()
    assert window.copy_button.isEnabled()
    assert _wait_for(lambda: window.translate_button.isEnabled())
    window.close()


def test_swap_turns_the_result_into_the_new_source() -> None:
    _app = QApplication.instance() or QApplication([])
    window = TranslatorWindow()
    window.source_language.setCurrentIndex(window.source_language.findData("zh"))
    window.target_language.setCurrentIndex(window.target_language.findData("ja"))
    window.result_edit.setPlainText("こんにちは")

    window.swap_languages()

    assert window.source_language.currentData() == "ja"
    assert window.target_language.currentData() == "zh"
    assert window.source_edit.toPlainText() == "こんにちは"
    assert window.result_edit.toPlainText() == ""
    window.close()


def test_f3_translate_button_opens_the_translator(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda _items: None)
    manager = reminder_widget.DesktopReminderManager()

    manager.launcher.buttons["translate"].click()
    QApplication.processEvents()

    assert manager._translator is not None
    assert manager._translator.isVisible()
    manager._translator.close()
    manager.shutdown()
