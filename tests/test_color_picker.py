"""Tests for the color picker that must open above full-screen editing layers."""

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog, QWidget

from ui.color_picker import dialog_position, pick_color


def test_picker_opens_below_the_toolbar_when_there_is_room() -> None:
    bounds = QRect(0, 0, 1920, 1040)
    toolbar = QRect(600, 500, 700, 36)

    position = dialog_position(toolbar, QSize(520, 400), bounds)

    assert position.y() > toolbar.bottom()
    assert bounds.contains(QRect(position, QSize(520, 400)))


def test_picker_flips_above_a_toolbar_near_the_screen_bottom() -> None:
    bounds = QRect(-1920, 0, 1920, 1040)
    toolbar = QRect(-1500, 990, 700, 36)

    position = dialog_position(toolbar, QSize(520, 400), bounds)

    assert position.y() + 400 <= toolbar.top()
    assert bounds.contains(QRect(position, QSize(520, 400)))


def test_picker_is_a_top_most_qt_dialog_and_returns_the_choice() -> None:
    _app = QApplication.instance() or QApplication([])
    anchor = QWidget()
    anchor.resize(200, 30)
    anchor.show()
    seen: dict[str, bool] = {}

    def choose() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QColorDialog)
        seen["top_most"] = bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        seen["qt_dialog"] = dialog.testOption(
            QColorDialog.ColorDialogOption.DontUseNativeDialog
        )
        dialog.setCurrentColor(QColor("#00c853"))
        dialog.accept()

    QTimer.singleShot(50, choose)
    color = pick_color(QColor("#ff3b30"), anchor, "test")

    assert seen == {"top_most": True, "qt_dialog": True}
    assert color == QColor("#00c853")
    anchor.close()


def test_cancelled_picker_returns_an_invalid_color() -> None:
    _app = QApplication.instance() or QApplication([])
    anchor = QWidget()
    anchor.show()
    QTimer.singleShot(50, lambda: QApplication.activeModalWidget().reject())

    assert not pick_color(QColor("#ff3b30"), anchor, "test").isValid()
    anchor.close()
