"""Application icon loading."""

from __future__ import annotations

from PySide6.QtGui import QIcon

from app.config import RESOURCE_DIR


def application_icon() -> QIcon:
    """Return the bundled emerald app icon, with an empty icon as a safe fallback."""
    icon_path = RESOURCE_DIR / "icons" / "mengren.ico"
    return QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
