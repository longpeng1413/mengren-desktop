"""Tests for keeping reminder windows below ordinary application windows."""

from app import desktop_visibility


class _BottomApi:
    def __init__(self) -> None:
        self.calls = []

    def SetWindowPos(self, *arguments):
        self.calls.append(arguments)
        return 1


def test_non_windows_bottom_request_is_a_safe_noop(monkeypatch) -> None:
    monkeypatch.setattr(desktop_visibility.sys, "platform", "linux")

    assert desktop_visibility.send_window_to_bottom(88)


def test_windows_bottom_request_uses_set_window_pos(monkeypatch) -> None:
    api = _BottomApi()
    monkeypatch.setattr(desktop_visibility.sys, "platform", "win32")
    monkeypatch.setattr(desktop_visibility, "_user32", lambda: api)

    assert desktop_visibility.send_window_to_bottom(88)
    assert len(api.calls) == 1
