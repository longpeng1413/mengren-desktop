"""Local clock alarms and their persisted next occurrence."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from app.config import RESOURCE_DIR
from app.reminder_preferences import ensure_default_alarm_sound, settings_directory


WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
REPEAT_PRESETS = (
    ("仅一次", ()),
    ("每天", tuple(range(7))),
    ("周一至周五", tuple(range(5))),
    ("周六和周日", (5, 6)),
)
DEFAULT_RINGTONE_TITLE = "我听人说思念像风一样"
_RINGTONE_TRACKS = {
    "default": (f"默认 · {DEFAULT_RINGTONE_TITLE}", "missing_like_wind.mp3"),
    "road_answer": ("答案在路上", "road_answer.mp3"),
    "cello_volcano": ("岩滩火山（大提琴纯音乐）", "cello_volcano.mp3"),
    "your_answer": ("你的答案", "your_answer.mp3"),
}
BUILTIN_SOUNDS = tuple((name, key) for key, (name, _) in _RINGTONE_TRACKS.items()) + (
    ("轻柔", "gentle"),
    ("清脆", "bright"),
)
MISSED_ALARM_GRACE_SECONDS = 600
RING_DURATIONS = (
    ("30s", 30), ("1m", 60), ("2m", 120), ("3m", 180),
    ("5m", 300), ("10m", 600), ("15m", 900), ("30m", 1800),
)
SNOOZE_DURATIONS = (("5m", 5), ("10m", 10), ("15m", 15), ("30m", 30), ("1h", 60))


@dataclass(frozen=True, slots=True)
class ClockAlarm:
    alarm_id: str
    at: time
    label: str = ""
    weekdays: tuple[int, ...] = ()
    delete_after_ring: bool = False
    ring_seconds: int = 30
    snooze_minutes: int = 5
    sound: str = "default"
    sound_path: str = ""
    sound_name: str = ""
    next_at: datetime | None = None
    snoozed_until: float | None = None
    fade_in: bool = False

    @property
    def enabled(self) -> bool:
        return self.next_at is not None or self.snoozed_until is not None

    @property
    def due_timestamp(self) -> float | None:
        if self.snoozed_until is not None:
            return self.snoozed_until
        return self.next_at.timestamp() if self.next_at is not None else None

    @property
    def repeat_label(self) -> str:
        for label, days in REPEAT_PRESETS:
            if self.weekdays == days:
                return label
        return "、".join(WEEKDAY_NAMES[day] for day in self.weekdays)

    def set_enabled(self, enabled: bool, now: datetime) -> ClockAlarm:
        if not enabled:
            return replace(self, next_at=None, snoozed_until=None)
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            if self.weekdays and day.weekday() not in self.weekdays:
                continue
            candidate = datetime.combine(day, self.at)
            if candidate.timestamp() > now.timestamp():
                return replace(self, next_at=candidate, snoozed_until=None)
        raise ValueError("alarm has no valid weekday")

    def advance(self, now: datetime) -> ClockAlarm:
        """Consume the occurrence, keeping repeating alarms armed."""
        return self.set_enabled(bool(self.weekdays), now)

    def snooze(self, now: datetime) -> ClockAlarm:
        return replace(
            self,
            next_at=None,
            snoozed_until=now.timestamp() + self.snooze_minutes * 60,
        )


def clock_alarm_sound(sound: str) -> str:
    track = _RINGTONE_TRACKS.get(sound)
    if track is not None:
        bundled = RESOURCE_DIR / "audio" / "clock_alarms" / track[1]
        if bundled.is_file():
            return str(bundled)
    return ensure_default_alarm_sound(sound, loud=True)


def new_clock_alarm(now: datetime) -> ClockAlarm:
    at = (now + timedelta(minutes=1)).time().replace(second=0, microsecond=0, fold=0)
    path = settings_directory() / "clock_alarm_defaults.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(values, dict):
            return ClockAlarm(uuid4().hex, at, **_alarm_options_from_json(values))
    except (OSError, TypeError, ValueError, OverflowError):
        pass
    return ClockAlarm(uuid4().hex, at)


def save_clock_alarm_defaults(alarm: ClockAlarm) -> None:
    path = settings_directory() / "clock_alarm_defaults.json"
    _write_json(path, _alarm_options_from_json(asdict(alarm)))


def load_clock_alarms() -> list[ClockAlarm]:
    path = settings_directory() / "clock_alarms.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    alarms: dict[str, ClockAlarm] = {}
    for item in items:
        try:
            alarm = _alarm_from_json(item)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        alarms[alarm.alarm_id] = alarm
    return list(alarms.values())


def _alarm_from_json(values: dict) -> ClockAlarm:
    alarm_id = values["alarm_id"]
    at = time.fromisoformat(values["at"])
    if not isinstance(alarm_id, str) or not alarm_id or at.tzinfo is not None:
        raise ValueError("invalid alarm ID or local time")
    next_at = datetime.fromisoformat(values["next_at"]) if values.get("next_at") else None
    if next_at is not None:
        if next_at.tzinfo is not None:
            raise ValueError("expected a local occurrence")
        next_at.timestamp()
    snoozed_until = values.get("snoozed_until")
    if snoozed_until is not None:
        if not math.isfinite(snoozed_until):
            raise ValueError("invalid snooze time")
        datetime.fromtimestamp(snoozed_until)
    return ClockAlarm(
        alarm_id,
        at.replace(second=0, microsecond=0),
        next_at=next_at,
        snoozed_until=snoozed_until,
        **_alarm_options_from_json(values),
    )


def _alarm_options_from_json(values: dict) -> dict:
    sound = values.get("sound", "default")
    if sound not in {key for _, key in BUILTIN_SOUNDS} | {"custom"}:
        sound = "default"
    return {
        "label": str(values.get("label", ""))[:60],
        "weekdays": tuple(
            sorted({day for day in values.get("weekdays", ()) if type(day) is int and 0 <= day <= 6})
        ),
        "delete_after_ring": values.get("delete_after_ring") is True,
        "ring_seconds": max(5, min(RING_DURATIONS[-1][1], int(values.get("ring_seconds", 30)))),
        "snooze_minutes": max(0, min(60, int(values.get("snooze_minutes", 5)))),
        "sound": sound,
        "sound_path": str(values.get("sound_path", "")),
        "sound_name": str(values.get("sound_name", "")),
        "fade_in": values.get("fade_in") is True,
    }


def save_clock_alarms(alarms: list[ClockAlarm]) -> None:
    path = settings_directory() / "clock_alarms.json"
    items = []
    for alarm in alarms:
        values = asdict(alarm)
        values["at"] = alarm.at.isoformat(timespec="minutes")
        values["next_at"] = alarm.next_at.isoformat() if alarm.next_at else None
        items.append(values)
    _write_json(path, items)


def _write_json(path: Path, values: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
