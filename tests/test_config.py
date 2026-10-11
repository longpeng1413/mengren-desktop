"""Tests for non-sensitive configuration parsing."""

from app.config import _parse_environment_lines


def test_parse_environment_lines() -> None:
    values = _parse_environment_lines(
        [
            "# AIShot credentials",
            "AISHOT_YOUDAO_APP_KEY=demo-key",
            "AISHOT_YOUDAO_APP_SECRET=demo=secret",
            "",
        ]
    )

    assert values == {
        "AISHOT_YOUDAO_APP_KEY": "demo-key",
        "AISHOT_YOUDAO_APP_SECRET": "demo=secret",
    }
