import json

import pytest

from app import desktop_layout


class FakeDesktop:
    icons = {"A": [10, 20], "B": [30, 40]}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return self.icons

    def restore(self, icons):
        assert icons == self.icons
        return 2, 0, 0, 0


def test_save_and_restore_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop_layout, "DesktopIcons", FakeDesktop)
    monkeypatch.setattr(desktop_layout, "settings_directory", lambda: tmp_path)
    assert desktop_layout.save_layout() == 2
    assert desktop_layout.restore_layout() == (2, 0, 0, 0)


def test_invalid_or_missing_layout_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop_layout, "settings_directory", lambda: tmp_path)
    with pytest.raises(desktop_layout.LayoutError):
        desktop_layout.restore_layout()
    (tmp_path / "desktop_icon_layout.json").write_text(json.dumps({"version": 1, "icons": {"A": ["bad", 2]}}))
    with pytest.raises(desktop_layout.LayoutError):
        desktop_layout.restore_layout()


def test_empty_desktop_does_not_replace_saved_layout(monkeypatch, tmp_path):
    class EmptyDesktop(FakeDesktop):
        icons = {}

    monkeypatch.setattr(desktop_layout, "DesktopIcons", EmptyDesktop)
    monkeypatch.setattr(desktop_layout, "settings_directory", lambda: tmp_path)
    path = tmp_path / "desktop_icon_layout.json"
    path.write_text("original")
    with pytest.raises(desktop_layout.LayoutError):
        desktop_layout.save_layout()
    assert path.read_text() == "original"


def test_restore_matches_names_and_leaves_new_icons_alone():
    desktop = desktop_layout.DesktopIcons()
    desktop.hwnd = 1
    desktop.memory = 123
    desktop.u = type("Api", (), {"GetWindowLongW": lambda *_: 0})()
    states = iter([{"B": [1, 1], "new": [5, 5], "A": [2, 2]},
                   {"B": [30, 40], "new": [5, 5], "A": [10, 20]}])
    desktop.read = lambda: next(states)
    points = []
    moves = []
    desktop._write = lambda _address, point: points.append((point.x, point.y))
    desktop._send = lambda message, index, address: moves.append((message, index, address))
    assert desktop.restore({"A": [10, 20], "B": [30, 40], "gone": [0, 0]}) == (2, 1, 1, 0)
    assert points == [(30, 40), (10, 20)]
    assert [move[1] for move in moves] == [0, 2]


def test_restore_rejects_automatic_arrangement():
    desktop = desktop_layout.DesktopIcons()
    desktop.hwnd = 1
    desktop.u = type("Api", (), {"GetWindowLongW": lambda *_: 0x100})()
    with pytest.raises(desktop_layout.LayoutError, match="自动排列"):
        desktop.restore({"A": [1, 2]})
