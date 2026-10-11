"""Tests for Windows actions exposed by the F3 desktop toolbar."""

from __future__ import annotations

from types import SimpleNamespace

from app import system_actions


def test_open_calculator_starts_windows_calculator(monkeypatch) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(system_actions.sys, "platform", "win32")
    monkeypatch.setattr(
        system_actions.subprocess,
        "Popen",
        lambda command, **options: calls.append((command, options)),
    )

    assert system_actions.open_calculator()
    assert calls[0][0] == ["calc.exe"]


def test_toggle_calculator_opens_when_not_running(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(system_actions.sys, "platform", "win32")
    monkeypatch.setattr(system_actions, "_running_calculator_images", lambda: ())
    monkeypatch.setattr(
        system_actions,
        "open_calculator",
        lambda: calls.append("open") or True,
    )

    assert system_actions.toggle_calculator()
    assert calls == ["open"]


def test_toggle_calculator_closes_running_windows_calculator(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(system_actions.sys, "platform", "win32")
    monkeypatch.setattr(
        system_actions,
        "_running_calculator_images",
        lambda: ("CalculatorApp.exe",),
    )

    def run(command, **_options):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(system_actions.subprocess, "run", run)

    assert system_actions.toggle_calculator()
    assert calls == [
        ["taskkill.exe", "/IM", "CalculatorApp.exe", "/T", "/F"]
    ]


def test_running_calculator_detection_parses_tasklist_csv(monkeypatch) -> None:
    monkeypatch.setattr(
        system_actions.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                '"explorer.exe","100","Console","1","1 K"\n'
                '"CalculatorApp.exe","200","Console","1","2 K"\n'
            ),
        ),
    )

    assert system_actions._running_calculator_images() == ("CalculatorApp.exe",)


def test_sleep_requests_normal_windows_suspend(monkeypatch) -> None:
    calls: list[tuple[bool, bool, bool]] = []

    class FakeSuspendState:
        argtypes = None
        restype = None

        def __call__(self, hibernate, force_critical, disable_wake_event):
            calls.append((hibernate, force_critical, disable_wake_event))
            return True

    monkeypatch.setattr(system_actions.sys, "platform", "win32")
    monkeypatch.setattr(
        system_actions.ctypes,
        "windll",
        SimpleNamespace(
            PowrProf=SimpleNamespace(SetSuspendState=FakeSuspendState())
        ),
        raising=False,
    )

    assert system_actions.put_computer_to_sleep()
    assert calls == [(False, False, False)]
