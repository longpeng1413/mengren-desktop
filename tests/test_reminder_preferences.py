"""Tests for durable reminder content and managed attachment copies."""

from __future__ import annotations

import wave

from app import reminder_preferences
from app.reminder_preferences import DesktopToolSettings, ReminderSettings


def test_reminder_settings_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        reminder_preferences,
        "settings_directory",
        lambda: tmp_path,
    )
    expected = ReminderSettings(
        enabled=True,
        text="明天交材料",
        image_path="C:/example.png",
        font_size=34,
        text_color="#12ab34",
        show_status=True,
        completed=True,
        x=120,
        y=88,
        schedule_mode="countdown",
        countdown_seconds=90,
        countdown_remaining=90,
        countdown_running=True,
        target_at="2099-01-01T12:00:00",
        sound_path="C:/alarm.mp3",
    )

    reminder_preferences.save_reminder_settings(expected)

    assert reminder_preferences.load_reminder_settings() == expected


def test_selected_attachment_is_copied_to_managed_storage(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        reminder_preferences,
        "settings_directory",
        lambda: tmp_path / "config",
    )
    source = tmp_path / "photo.png"
    source.write_bytes(b"\x89PNG\r\nmanaged reminder test")

    first = reminder_preferences.import_reminder_asset(str(source), "image")
    second = reminder_preferences.import_reminder_asset(str(source), "image")

    assert first == second
    assert (tmp_path / "config") in reminder_preferences.Path(first).parents
    assert reminder_preferences.Path(first).read_bytes() == source.read_bytes()


def test_bundled_song_is_the_default_alarm_sound(tmp_path, monkeypatch) -> None:
    resources = tmp_path / "resources"
    bundled = resources / "audio" / "default_reminder.mp3"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"bundled-song" * 100)
    monkeypatch.setattr(reminder_preferences, "RESOURCE_DIR", resources)

    output = reminder_preferences.ensure_default_alarm_sound()

    assert output == str(bundled)


def test_missing_bundled_song_falls_back_to_valid_wave(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        reminder_preferences,
        "settings_directory",
        lambda: tmp_path,
    )
    monkeypatch.setattr(reminder_preferences, "RESOURCE_DIR", tmp_path / "missing")

    output = reminder_preferences.ensure_default_alarm_sound()

    with wave.open(output, "rb") as sound:
        assert sound.getnchannels() == 1
        assert sound.getframerate() == 22050
        assert sound.getnframes() > 10000


def test_invalid_persisted_values_fall_back_safely(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        reminder_preferences,
        "settings_directory",
        lambda: tmp_path,
    )
    (tmp_path / "reminder.json").write_text(
        '{"enabled": true, "font_size": 999, "schedule_mode": "bad"}',
        encoding="utf-8",
    )

    loaded = reminder_preferences.load_reminder_settings()

    assert loaded.enabled
    assert loaded.font_size == 96
    assert loaded.schedule_mode == "none"


def test_independent_f4_items_round_trip_as_a_collection(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        reminder_preferences,
        "settings_directory",
        lambda: tmp_path,
    )
    text = reminder_preferences.new_reminder("text")
    alarm = reminder_preferences.new_reminder("alarm")
    stopwatch = reminder_preferences.new_reminder("stopwatch")

    reminder_preferences.save_reminders([text, alarm, stopwatch])
    loaded = reminder_preferences.load_reminders()

    assert [item.kind for item in loaded] == ["text", "alarm", "stopwatch"]
    assert len({item.reminder_id for item in loaded}) == 3


def test_desktop_tool_display_mode_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        reminder_preferences,
        "settings_directory",
        lambda: tmp_path,
    )
    expected = DesktopToolSettings(always_on_top=True)

    reminder_preferences.save_desktop_tool_settings(expected)

    assert reminder_preferences.load_desktop_tool_settings() == expected


def test_legacy_running_countdown_is_migrated_without_losing_target(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        reminder_preferences,
        "settings_directory",
        lambda: tmp_path,
    )
    (tmp_path / "reminders.json").write_text(
        """[
          {
            "reminder_id": "legacy-countdown",
            "kind": "countdown",
            "enabled": true,
            "schedule_mode": "countdown",
            "countdown_seconds": 120,
            "target_at": "2099-01-01T12:00:00",
            "alarm_fired": false
          }
        ]""",
        encoding="utf-8",
    )

    loaded = reminder_preferences.load_reminders()[0]

    assert loaded.countdown_running
    assert loaded.countdown_remaining == 120
    assert loaded.target_at == "2099-01-01T12:00:00"
