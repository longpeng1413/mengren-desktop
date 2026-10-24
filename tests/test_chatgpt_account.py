"""Tests for ChatGPT-account translation, network fallback and log clean-up."""

import base64
import io
import json
import os
import time
from urllib.error import HTTPError

import pytest

from app import logs
from app.config import YoudaoCredentials
from app.translation_preferences import TranslationSettings
from core.translate import chatgpt_account, factory, http
from core.translate.base import BatchTranslator, TranslationError
from core.translate.chatgpt_account import (
    AccountQuotaExhausted,
    AccountSignedOut,
    AccountTokens,
    ChatGPTAccountTranslator,
    LoginSession,
)
from core.translate.youdao import YoudaoTranslator


def _jwt(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.signature"


def _signed_in(expires_in: float = 3600) -> AccountTokens:
    tokens = AccountTokens("access", "refresh", time.time() + expires_in, "acct", "me@example.com", "plus")
    chatgpt_account.save_tokens(tokens)
    return tokens


# ---------------------------------------------------------------- network ----


def test_direct_route_falls_back_to_the_proxy_when_cut_off(monkeypatch) -> None:
    routes = []

    def fake_open(opener, _request, _timeout):
        routes.append(opener)
        if opener is http._DIRECT:
            raise ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接。")
        return b"ok"

    monkeypatch.setattr(http, "_open", fake_open)

    body = http.read_response(http.Request("https://openapi.youdao.com/api"), 5, prefer_direct=True)

    assert body == b"ok"
    assert routes == [http._DIRECT, http._SYSTEM_PROXY]


def test_an_answer_from_the_service_is_not_retried(monkeypatch) -> None:
    calls = []

    def fake_open(_opener, request, _timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 500, "error", {}, io.BytesIO(b""))

    monkeypatch.setattr(http, "_open", fake_open)

    with pytest.raises(HTTPError):
        http.read_response(http.Request("https://example.com"), 5)
    assert len(calls) == 1


def test_youdao_reports_a_dropped_connection_in_plain_chinese(monkeypatch) -> None:
    def fake_open(*_args):
        raise ConnectionResetError(10054, "reset")

    monkeypatch.setattr(http, "_open", fake_open)
    translator = YoudaoTranslator(YoudaoCredentials("key", "secret"))

    with pytest.raises(TranslationError, match="网络被中断"):
        translator.translate_many_to_chinese(("hello",))


# ------------------------------------------------------------------- logs ----


def test_old_and_leftover_log_files_are_cleaned() -> None:
    folder = logs.log_folder()
    folder.mkdir(parents=True)
    current = folder / logs.LOG_FILE_NAME
    backup = folder / f"{logs.LOG_FILE_NAME}.1"
    leftover = folder / f"{logs.LOG_FILE_NAME}.7"
    expired = folder / f"{logs.LOG_FILE_NAME}.2"
    for path in (current, backup, leftover, expired):
        path.write_text("x", encoding="utf-8")
    old = time.time() - (logs.MAX_AGE_DAYS + 1) * 24 * 3600
    os.utime(expired, (old, old))

    removed = logs.clean_logs()

    assert removed == 2
    assert sorted(path.name for path in folder.iterdir()) == sorted([current.name, backup.name])


def test_log_size_is_shown_and_can_be_cleared() -> None:
    folder = logs.log_folder()
    folder.mkdir(parents=True)
    (folder / logs.LOG_FILE_NAME).write_text("a" * 2048, encoding="utf-8")

    assert logs.log_size() == 2048
    assert logs.format_size(2048) == "2 KB"

    logs.clear_logs()

    assert logs.log_size() == 0


def test_log_files_are_size_limited() -> None:
    assert logs.MAX_BYTES * (logs.BACKUP_COUNT + 1) <= 3 * 1024 * 1024


# --------------------------------------------------------- ChatGPT account ----


def test_sign_in_is_stored_encrypted_and_forgotten_on_sign_out() -> None:
    tokens = _signed_in()

    raw = chatgpt_account._token_file().read_bytes()
    assert b"me@example.com" not in raw
    assert chatgpt_account.load_tokens() == tokens

    chatgpt_account.sign_out()

    assert chatgpt_account.load_tokens() is None


def test_login_callback_is_checked_and_exchanged(monkeypatch) -> None:
    exchanged = []

    def fake_token(fields):
        exchanged.append(fields)
        return {
            "access_token": _jwt({"exp": time.time() + 3600}),
            "refresh_token": "refresh",
            "id_token": _jwt(
                {
                    "email": "me@example.com",
                    "https://api.openai.com/auth": {"chatgpt_plan_type": "plus", "chatgpt_account_id": "acct"},
                }
            ),
        }

    monkeypatch.setattr(chatgpt_account, "_post_token", fake_token)
    session = LoginSession()

    assert not session.accept("http://localhost:1455/auth/callback?code=abc&state=wrong")
    assert session.status == "failed"

    session = LoginSession()
    assert session.accept(f"http://localhost:1455/auth/callback?code=abc&state={session._state}")
    deadline = time.time() + 5
    while session.status == "exchanging" and time.time() < deadline:
        time.sleep(0.01)

    assert session.status == "done"
    assert exchanged[0]["code"] == "abc"
    saved = chatgpt_account.load_tokens()
    assert (saved.email, saved.plan, saved.account_id) == ("me@example.com", "plus", "acct")


def test_tokens_are_refreshed_shortly_before_they_expire(monkeypatch) -> None:
    _signed_in(expires_in=60)
    monkeypatch.setattr(
        chatgpt_account,
        "_post_token",
        lambda fields: {"access_token": "new-access", "expires_in": 3600, "refresh_token": "new-refresh"},
    )

    tokens = chatgpt_account.fresh_tokens()

    assert (tokens.access, tokens.refresh, tokens.email) == ("new-access", "new-refresh", "me@example.com")
    assert chatgpt_account.load_tokens().access == "new-access"


def test_account_translation_reads_the_event_stream(monkeypatch) -> None:
    _signed_in()
    answer = json.dumps({"translations": ["你好", "世界"]}, ensure_ascii=False)
    stream = "\n".join(
        f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': piece}, ensure_ascii=False)}"
        for piece in (answer[:10], answer[10:])
    )
    sent = []

    def fake_open(_opener, request, _timeout):
        sent.append(request)
        return stream.encode("utf-8")

    monkeypatch.setattr(http, "_open", fake_open)

    result = ChatGPTAccountTranslator("gpt-6.1-sol").translate_many_to_chinese(("hello", "world"))

    assert result == ("你好", "世界")
    body = json.loads(sent[0].data)
    assert body["model"] == "gpt-6.1-sol"
    assert sent[0].headers["Chatgpt-account-id"] == "acct"


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, AccountQuotaExhausted), (401, AccountSignedOut)],
)
def test_account_quota_and_sign_in_errors_are_recognised(monkeypatch, status, error) -> None:
    _signed_in()

    def fake_open(_opener, request, _timeout):
        raise HTTPError(request.full_url, status, "error", {}, io.BytesIO(b'{"detail": "usage limit reached"}'))

    monkeypatch.setattr(http, "_open", fake_open)

    with pytest.raises(error):
        ChatGPTAccountTranslator("gpt-6.1-sol").translate_many_to_chinese(("hello",))


def test_quota_reported_inside_the_stream_is_recognised() -> None:
    event = {"type": "response.failed", "response": {"error": {"code": "usage_limit_reached", "message": "limit"}}}

    with pytest.raises(AccountQuotaExhausted):
        chatgpt_account._stream_text(f"data: {json.dumps(event)}")


# ------------------------------------------------------- translation order ----


class _Fixed(BatchTranslator):
    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.calls = 0
        self._reply = reply
        self._error = error

    def translate_many_to_chinese(self, texts, source_language="auto"):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return tuple(self._reply for _text in texts)


def test_api_takes_over_when_the_plan_quota_runs_out(monkeypatch) -> None:
    monkeypatch.setattr(factory, "_account_paused_until", 0.0)
    account = _Fixed(error=AccountQuotaExhausted("用完了"))
    api = _Fixed("接口译文")
    translator = factory.AccountFirstTranslator(account, api)

    assert translator.translate_many_to_chinese(("a",)) == ("接口译文",)
    assert translator.translate_many_to_chinese(("b",)) == ("接口译文",)
    # The account is skipped for a while instead of being refused every time.
    assert account.calls == 1
    assert api.calls == 2


def test_account_is_used_first_while_it_has_quota(monkeypatch) -> None:
    monkeypatch.setattr(factory, "_account_paused_until", 0.0)
    account = _Fixed("账号译文")
    api = _Fixed("接口译文")

    assert factory.AccountFirstTranslator(account, api).translate_to_chinese("a").translated_text == "账号译文"
    assert api.calls == 0


def test_account_comes_first_only_when_chosen_and_signed_in() -> None:
    settings = TranslationSettings(provider="openai", openai_api_key="key", chatgpt_preferred=True)

    assert not isinstance(factory.create_translator(settings), factory.AccountFirstTranslator)

    _signed_in()

    assert isinstance(factory.create_translator(settings), factory.AccountFirstTranslator)
    assert not isinstance(
        factory.create_translator(TranslationSettings(provider="openai", openai_api_key="key")),
        factory.AccountFirstTranslator,
    )


def test_errors_are_written_to_the_log_file(monkeypatch) -> None:
    import logging

    monkeypatch.setattr(logs, "_handler", None)
    monkeypatch.setattr("sys.excepthook", __import__("sys").excepthook)
    root = logging.getLogger()
    level = root.level
    try:
        folder = logs.setup_logging()
        logging.getLogger("测试").warning("截图翻译失败：网络被中断")
        logs._handler.flush()
        text = (folder / logs.LOG_FILE_NAME).read_text(encoding="utf-8")
    finally:
        if logs._handler is not None:
            root.removeHandler(logs._handler)
            logs._handler.close()
        root.setLevel(level)

    assert "截图翻译失败：网络被中断" in text
