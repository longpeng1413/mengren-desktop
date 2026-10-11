"""Tests for the user-facing display support report."""

from PySide6.QtWidgets import QApplication

from app.display_diagnostics import collect_display_diagnostics


def test_display_diagnostics_contains_coordinate_and_scale_sections() -> None:
    _app = QApplication.instance() or QApplication([])

    diagnostics = collect_display_diagnostics()

    assert "[Qt 显示器]" in diagnostics
    assert "缩放因子 DPR" in diagnostics
    assert "[Windows 虚拟桌面]" in diagnostics
    assert "[MSS 物理显示器]" in diagnostics
