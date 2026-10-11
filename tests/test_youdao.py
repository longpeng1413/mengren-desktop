"""Tests for Youdao request signing without using real credentials."""

from app.config import YoudaoCredentials
from core.translate.youdao import YoudaoTranslator, _truncate


def test_query_truncation() -> None:
    assert _truncate("short text") == "short text"
    query = "abcdefghijklmnopqrstuvwxyz"
    assert _truncate(query) == "abcdefghij26qrstuvwxyz"


def test_v3_signature_is_stable() -> None:
    translator = YoudaoTranslator(YoudaoCredentials("app-key", "app-secret"))
    signature = translator._sign("hello", "salt", "123")
    assert signature == "6e45874bc44ed2889f37077afc864021f5cf28ab082f9fe307c6b41081f68755"
