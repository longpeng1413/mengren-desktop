"""Size-limited error log with automatic clean-up.

The log lives in ``%APPDATA%\\AIShot\\logs``. One file holds at most 1 MB and at
most three files are kept, so the folder never exceeds about 3 MB. Files older
than 14 days, and anything else left in the folder (for example after a crash),
are removed at start-up and every 24 hours while the tray app keeps running.
Only error causes are written: never screenshot text or API keys.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.branding import APP_DISPLAY_NAME, PRODUCT_NAME

LOG_FILE_NAME = f"{PRODUCT_NAME}.log"
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 2
MAX_AGE_DAYS = 14
CLEANUP_INTERVAL_MS = 24 * 60 * 60 * 1000

_handler: RotatingFileHandler | None = None


def log_folder() -> Path:
    """Return the folder holding the log files."""
    return Path(os.environ.get("APPDATA", Path.home())) / "AIShot" / "logs"


def _log_files_kept() -> set[str]:
    return {LOG_FILE_NAME, *(f"{LOG_FILE_NAME}.{index}" for index in range(1, BACKUP_COUNT + 1))}


def setup_logging() -> Path:
    """Clean old files, then send warnings and errors to the rotating log."""
    global _handler
    folder = log_folder()
    folder.mkdir(parents=True, exist_ok=True)
    clean_logs()
    if _handler is None:
        _handler = RotatingFileHandler(
            folder / LOG_FILE_NAME,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
        _handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s：%(message)s")
        )
        root = logging.getLogger()
        root.addHandler(_handler)
        root.setLevel(logging.INFO)
        sys.excepthook = _log_uncaught
    logging.getLogger(__name__).info("%s 启动", APP_DISPLAY_NAME)
    return folder


def clean_logs(now: float | None = None) -> int:
    """Delete expired or unexpected files in the log folder; return how many."""
    folder = log_folder()
    if not folder.is_dir():
        return 0
    current = time.time() if now is None else now
    removed = 0
    for path in folder.iterdir():
        if not path.is_file():
            continue
        expired = current - path.stat().st_mtime > MAX_AGE_DAYS * 24 * 60 * 60
        if path.name in _log_files_kept() and not expired:
            continue
        if _handler is not None and path.name == LOG_FILE_NAME:
            # The open log is emptied instead of deleted while it is in use.
            _truncate_active_log()
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def log_size() -> int:
    """Return the bytes used by the log folder."""
    folder = log_folder()
    if not folder.is_dir():
        return 0
    return sum(path.stat().st_size for path in folder.iterdir() if path.is_file())


def clear_logs() -> None:
    """Remove every log file now (the button in the main window)."""
    folder = log_folder()
    if not folder.is_dir():
        return
    for path in folder.iterdir():
        if not path.is_file():
            continue
        if _handler is not None and path.name == LOG_FILE_NAME:
            _truncate_active_log()
            continue
        try:
            path.unlink()
        except OSError:
            pass


def format_size(size: int) -> str:
    """Return a short human-readable size such as ``12 KB``."""
    if size < 1024:
        return f"{size} 字节"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _truncate_active_log() -> None:
    if _handler is None:
        return
    _handler.acquire()
    try:
        if _handler.stream is not None:
            _handler.stream.close()
            _handler.stream = None
        Path(_handler.baseFilename).write_text("", encoding="utf-8")
    finally:
        _handler.release()


def _log_uncaught(kind, value, traceback) -> None:
    logging.getLogger("未处理的错误").error("程序出现未处理的错误", exc_info=(kind, value, traceback))
    sys.__excepthook__(kind, value, traceback)
