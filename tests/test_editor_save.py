"""Tests for editor save completion behavior."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

from core.capture.desktop_capture import DesktopSnapshot
from ui.editor import Editor
from ui.overlay_editor import OverlayEditor


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _image() -> QImage:
    image = QImage(120, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020"))
    return image


def test_windowed_editor_closes_after_successful_save(monkeypatch, tmp_path) -> None:
    _application()
    output = tmp_path / "saved.png"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PNG 图片 (*.png)"),
    )
    editor = Editor(_image())

    editor._save()

    assert output.exists()
    assert editor.result() == QDialog.DialogCode.Accepted


def test_pinned_editor_stays_open_after_save(monkeypatch, tmp_path) -> None:
    _application()
    output = tmp_path / "pinned.png"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PNG 图片 (*.png)"),
    )
    editor = Editor(_image(), apply_mode=True)

    editor._save()

    assert output.exists()
    assert editor.result() == QDialog.DialogCode.Rejected


def test_overlay_editor_closes_after_successful_save(monkeypatch, tmp_path) -> None:
    _application()
    output = tmp_path / "overlay.png"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PNG 图片 (*.png)"),
    )
    image = _image()
    snapshot = DesktopSnapshot(QRect(0, 0, image.width(), image.height()), image)
    editor = OverlayEditor(snapshot, QRect(10, 10, 80, 50))

    editor._save()

    assert output.exists()
    assert editor.result() == QDialog.DialogCode.Accepted
