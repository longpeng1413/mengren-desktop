"""Persistent desktop-reminder content, appearance, timer, and attachments."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import wave
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import RESOURCE_DIR


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


@dataclass(frozen=True, slots=True)
class ReminderSettings:
    """One persistent desktop reminder card."""

    reminder_id: str = ""
    kind: str = "text"
    enabled: bool = False
    text: str = ""
    image_path: str = ""
    font_size: int = 26
    text_width: int = 360
    text_height: int = 90
    image_width: int = 360
    image_height: int = 240
    text_color: str = "#fff4d6"
    show_status: bool = True
    completed: bool = False
    x: int | None = None
    y: int | None = None
    schedule_mode: str = "none"
    alarm_at: str = ""
    countdown_seconds: int = 0
    countdown_remaining: int = 0
    countdown_running: bool = False
    target_at: str = ""
    sound_path: str = ""
    alarm_fired: bool = False
    stopwatch_elapsed: int = 0
    stopwatch_started_at: str = ""
    stopwatch_running: bool = False


@dataclass(frozen=True, slots=True)
class DesktopToolSettings:
    """Persistent behavior shared by all desktop reminder cards."""

    always_on_top: bool = False


def settings_directory() -> Path:
    """Return the per-user application configuration directory."""
    return Path(os.environ.get("APPDATA", Path.home())) / "AIShot"


def _reminder_file() -> Path:
    return settings_directory() / "reminder.json"


def _reminders_file() -> Path:
    return settings_directory() / "reminders.json"


def _desktop_tools_file() -> Path:
    return settings_directory() / "desktop_tools.json"


def load_desktop_tool_settings() -> DesktopToolSettings:
    """Load the desktop/always-on-top choice, defaulting to desktop mode."""
    try:
        values = json.loads(_desktop_tools_file().read_text(encoding="utf-8"))
        if isinstance(values, dict):
            return DesktopToolSettings(
                always_on_top=bool(values.get("always_on_top", False))
            )
    except (OSError, ValueError, TypeError):
        pass
    return DesktopToolSettings()


def save_desktop_tool_settings(settings: DesktopToolSettings) -> None:
    """Persist desktop toolbar behavior atomically."""
    path = _desktop_tools_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_reminder_settings() -> ReminderSettings:
    """Load a reminder while safely ignoring corrupt or older values."""
    try:
        values = json.loads(_reminder_file().read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            return ReminderSettings()
        return _settings_from_values(values)
    except (OSError, ValueError, TypeError):
        return ReminderSettings()


def save_reminder_settings(settings: ReminderSettings) -> None:
    """Persist the complete reminder card for the current Windows user."""
    path = _reminder_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def clear_reminder_settings() -> None:
    """Delete the reminder and only the attachment copies owned by this feature."""
    try:
        _reminder_file().unlink(missing_ok=True)
        _reminders_file().unlink(missing_ok=True)
    except OSError:
        pass
    assets = settings_directory() / "reminder_assets"
    try:
        if assets.exists():
            shutil.rmtree(assets)
    except OSError:
        pass


def load_reminders() -> list[ReminderSettings]:
    """Load every independent sticker, alarm, stopwatch, and countdown."""
    try:
        values = json.loads(_reminders_file().read_text(encoding="utf-8"))
        if isinstance(values, list):
            reminders = [
                _settings_from_values(item)
                for item in values
                if isinstance(item, dict)
            ]
            return [
                item
                if item.reminder_id
                else ReminderSettings(
                    **{**asdict(item), "reminder_id": uuid.uuid4().hex}
                )
                for item in reminders
                if item.enabled
            ]
    except (OSError, ValueError, TypeError):
        pass
    legacy = load_reminder_settings()
    if not legacy.enabled:
        return []
    inferred_kind = (
        legacy.schedule_mode
        if legacy.schedule_mode in {"alarm", "countdown"}
        else "image"
        if legacy.image_path and not legacy.text
        else "text"
    )
    migrated = ReminderSettings(
        **{
            **asdict(legacy),
            "reminder_id": legacy.reminder_id or uuid.uuid4().hex,
            "kind": inferred_kind,
        }
    )
    try:
        save_reminders([migrated])
    except OSError:
        pass
    return [migrated]


def save_reminders(reminders: list[ReminderSettings]) -> None:
    """Persist the complete independent desktop-item collection atomically."""
    path = _reminders_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps([asdict(item) for item in reminders], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def new_reminder(kind: str) -> ReminderSettings:
    """Return a new independent desktop item with a stable identifier."""
    if kind not in {"text", "image", "alarm", "stopwatch", "countdown"}:
        raise ValueError("unsupported reminder kind")
    return ReminderSettings(
        reminder_id=uuid.uuid4().hex,
        kind=kind,
        enabled=True,
        show_status=kind in {"text", "image"},
        schedule_mode=kind if kind in {"alarm", "countdown"} else "none",
    )


def _settings_from_values(values: dict) -> ReminderSettings:
    mode = str(values.get("schedule_mode", "none"))
    if mode not in {"none", "alarm", "countdown"}:
        mode = "none"
    kind = str(values.get("kind", "text"))
    if kind not in {"text", "image", "alarm", "stopwatch", "countdown"}:
        kind = "text"
    color = str(values.get("text_color", "#fff4d6"))
    if len(color) != 7 or not color.startswith("#"):
        color = "#fff4d6"
    font_size = max(10, min(96, int(values.get("font_size", 26))))
    countdown_seconds = max(0, int(values.get("countdown_seconds", 0)))
    target_at = str(values.get("target_at", ""))
    alarm_fired = bool(values.get("alarm_fired", False))
    persisted_countdown_running = values.get("countdown_running")
    countdown_running = (
        kind == "countdown" and bool(target_at) and not alarm_fired
        if persisted_countdown_running is None
        else bool(persisted_countdown_running)
    )
    return ReminderSettings(
        reminder_id=str(values.get("reminder_id", "")),
        kind=kind,
        enabled=bool(values.get("enabled", False)),
        text=str(values.get("text", "")),
        image_path=str(values.get("image_path", "")),
        font_size=font_size,
        text_width=max(140, min(760, int(values.get("text_width", 360)))),
        text_height=max(48, min(420, int(values.get("text_height", font_size * 3)))),
        image_width=max(120, min(760, int(values.get("image_width", 360)))),
        image_height=max(90, min(600, int(values.get("image_height", 240)))),
        text_color=color,
        show_status=bool(values.get("show_status", kind in {"text", "image"})),
        completed=bool(values.get("completed", False)),
        x=_optional_int(values.get("x")),
        y=_optional_int(values.get("y")),
        schedule_mode=mode,
        alarm_at=str(values.get("alarm_at", "")),
        countdown_seconds=countdown_seconds,
        countdown_remaining=max(
            0,
            int(values.get("countdown_remaining", countdown_seconds)),
        ),
        countdown_running=countdown_running,
        target_at=target_at,
        sound_path=str(values.get("sound_path", "")),
        alarm_fired=alarm_fired,
        stopwatch_elapsed=max(0, int(values.get("stopwatch_elapsed", 0))),
        stopwatch_started_at=str(values.get("stopwatch_started_at", "")),
        stopwatch_running=bool(values.get("stopwatch_running", False)),
    )
def import_reminder_asset(source: str, kind: str) -> str:
    """Copy a chosen image or audio file into stable application storage."""
    source_path = Path(source).expanduser()
    extensions = IMAGE_EXTENSIONS if kind == "image" else AUDIO_EXTENSIONS
    if (
        kind not in {"image", "audio"}
        or not source_path.is_file()
        or source_path.suffix.lower() not in extensions
    ):
        raise ValueError("unsupported reminder attachment")
    assets = settings_directory() / "reminder_assets" / kind
    assets.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
    destination = assets / f"{digest}{source_path.suffix.lower()}"
    if source_path.resolve() != destination.resolve() and not destination.exists():
        shutil.copy2(source_path, destination)
    return str(destination)


def ensure_default_alarm_sound() -> str:
    """Return optional bundled audio, with a generated tone as fallback."""
    bundled = RESOURCE_DIR / "audio" / "default_reminder.mp3"
    if bundled.is_file() and bundled.stat().st_size > 1000:
        return str(bundled)
    output = settings_directory() / "reminder_alarm.wav"
    if output.is_file() and output.stat().st_size > 1000:
        return str(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 22050
    samples: list[bytes] = []
    pattern = (
        (880.0, 0.28),
        (0.0, 0.10),
        (1174.66, 0.32),
        (0.0, 0.16),
        (880.0, 0.28),
        (1174.66, 0.42),
    )
    for frequency, duration in pattern:
        count = int(sample_rate * duration)
        for index in range(count):
            envelope = min(1.0, index / 180, (count - index) / 220)
            value = (
                0
                if frequency == 0
                else int(
                    14500
                    * max(0.0, envelope)
                    * math.sin(2 * math.pi * frequency * index / sample_rate)
                )
            )
            samples.append(struct.pack("<h", value))
    with wave.open(str(output), "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(sample_rate)
        sound.writeframes(b"".join(samples))
    return str(output)


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
