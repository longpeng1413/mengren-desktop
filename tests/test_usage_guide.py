"""Tests for the usage-guide window opened from the main window."""

from PySide6.QtWidgets import QApplication

from ui.usage_guide_dialog import UsageGuideDialog, guide_html, guide_path


def test_source_run_shows_the_project_guide() -> None:
    _app = QApplication.instance() or QApplication([])

    dialog = UsageGuideDialog()

    assert guide_path().name == "使用说明.txt"
    assert "一、普通截图（F1）" in dialog._browser.toPlainText()
    dialog.deleteLater()


def test_section_headings_are_emphasised_and_text_is_escaped() -> None:
    page = guide_html("标题\n\n一、普通截图（F1）\n按 <F1> 开始")

    assert "font-weight:600;color:#6cc59a" in page
    assert "&lt;F1&gt;" in page
