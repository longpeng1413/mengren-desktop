import sys

from app import autostart
from app.autostart import startup_command
from app.branding import APP_AUTOSTART_NAME, LEGACY_AUTOSTART_NAMES


def test_source_startup_command_launches_main_module() -> None:
    command = startup_command()

    assert command.startswith('"')
    assert command.endswith('main.py"')


def test_old_product_names_are_migrated() -> None:
    assert APP_AUTOSTART_NAME == "猛人桌面助手"
    assert "猛人软件" in LEGACY_AUTOSTART_NAMES
    assert "猛人截图" in LEGACY_AUTOSTART_NAMES


def test_refresh_registration_skips_source_runs(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    monkeypatch.setattr(autostart, "set_enabled", calls.append)

    assert not autostart.refresh_registration()
    assert calls == []


def test_refresh_registration_reregisters_enabled_packaged_exe(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    monkeypatch.setattr(
        autostart,
        "set_enabled",
        lambda enabled: calls.append(enabled) or True,
    )

    assert autostart.refresh_registration()
    assert calls == [True]


def test_refresh_registration_leaves_disabled_autostart_alone(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "set_enabled", calls.append)

    assert not autostart.refresh_registration()
    assert calls == []
