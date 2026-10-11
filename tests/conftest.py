"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_settings(tmp_path, monkeypatch) -> None:
    """Keep every test away from the real %APPDATA%\\AIShot settings.

    Without this, a test that saves preferences would overwrite the
    developer's own shortcuts, reminders and translation settings.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
