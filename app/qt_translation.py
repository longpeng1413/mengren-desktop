"""Chinese text for Qt's built-in dialogs (color picker, buttons, menus)."""

from __future__ import annotations

from pathlib import Path

import PySide6
from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator

_CATALOG = "qtbase_zh_CN"


def install_chinese_translation(app: QCoreApplication) -> QTranslator | None:
    """Translate Qt's own dialog texts, such as "Basic colors" and "OK", to Chinese.

    The packaged release keeps only this one catalog. Returns the installed
    translator, or None when the catalog cannot be found.
    """
    translator = QTranslator(app)
    for folder in _translation_folders():
        if translator.load(_CATALOG, str(folder)):
            app.installTranslator(translator)
            return translator
    return None


def _translation_folders() -> list[Path]:
    folders = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))]
    # Inside the PyInstaller bundle Qt may report a path outside _internal.
    folders.append(Path(PySide6.__file__).resolve().parent / "translations")
    return folders
