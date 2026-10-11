"""Qt's built-in dialogs, such as the color picker, are shown in Chinese."""

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.qt_translation import install_chinese_translation


def test_color_dialog_texts_are_translated_to_chinese() -> None:
    app = QApplication.instance() or QApplication([])
    translator = install_chinese_translation(app)
    try:
        assert translator is not None
        assert QCoreApplication.translate("QColorDialog", "&Basic colors") == "基本颜色(&B)"
        assert QCoreApplication.translate("QPlatformTheme", "OK") == "确定"
    finally:
        if translator is not None:
            app.removeTranslator(translator)
