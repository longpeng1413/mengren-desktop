"""Local application configuration without exposing private values."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _application_root() -> Path:
    """Return the source root or the directory containing the packaged EXE."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_root() -> Path:
    """Return the PyInstaller data directory while retaining local source behavior."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", _application_root()))
    return _application_root()


ROOT_DIR = _application_root()
RESOURCE_DIR = _resource_root() / "resources"
ENV_FILE = ROOT_DIR / ".env"


@dataclass(frozen=True, slots=True)
class YoudaoCredentials:
    """Private credentials required by Youdao Text Translation."""

    app_key: str
    app_secret: str

    @property
    def is_configured(self) -> bool:
        """Return whether both required credential values are present."""
        return bool(self.app_key and self.app_secret)


def get_youdao_credentials() -> YoudaoCredentials:
    """Load credentials locally, without logging or displaying their values."""
    values = _read_environment_file(ENV_FILE)
    return YoudaoCredentials(
        app_key=os.environ.get("AISHOT_YOUDAO_APP_KEY", values.get("AISHOT_YOUDAO_APP_KEY", "")).strip(),
        app_secret=os.environ.get(
            "AISHOT_YOUDAO_APP_SECRET",
            values.get("AISHOT_YOUDAO_APP_SECRET", ""),
        ).strip(),
    )


def _read_environment_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE lines from a local environment file."""
    if not path.is_file():
        return {}

    return _parse_environment_lines(path.read_text(encoding="utf-8-sig").splitlines())


def _parse_environment_lines(lines: list[str]) -> dict[str, str]:
    """Parse only non-empty, non-comment KEY=VALUE lines."""
    values: dict[str, str] = {}
    for line in lines:
        item = line.strip()
        if not item or item.startswith("#") or "=" not in item:
            continue
        key, value = item.split("=", 1)
        values[key.strip()] = value.strip()
    return values
