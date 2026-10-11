"""Tests for encrypted translation settings."""

from app.translation_preferences import (
    TranslationSettings,
    load_translation_settings,
    save_translation_settings,
)


def test_translation_settings_are_encrypted_at_rest(tmp_path, monkeypatch) -> None:
    path = tmp_path / "translation-settings.bin"
    monkeypatch.setattr("app.translation_preferences._settings_file", lambda: path)
    settings = TranslationSettings(provider="deepl", deepl_api_key="private-test-key")

    save_translation_settings(settings)
    loaded = load_translation_settings()

    assert loaded == settings
    assert b"private-test-key" not in path.read_bytes()
