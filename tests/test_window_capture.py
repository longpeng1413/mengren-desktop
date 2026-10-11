"""Tests for physical-to-logical window coordinate mapping."""

from PySide6.QtCore import QPoint, QRect

from core.capture.window_capture import (
    CapturableWindow,
    DisplayMapping,
    WindowLocator,
    is_capturable_window_metadata,
    map_physical_rect,
    map_physical_rect_to_displays,
)


def test_window_metadata_rejects_desktop_and_ghost_surfaces() -> None:
    normal_style = 0x00C00000
    assert not is_capturable_window_metadata("", "GhostSurface", normal_style, 0)
    assert not is_capturable_window_metadata(
        "Program Manager",
        "Progman",
        normal_style,
        0,
    )
    assert not is_capturable_window_metadata(
        "Wallpaper",
        "WallpaperHost",
        normal_style,
        0x80,
    )
    assert not is_capturable_window_metadata(
        "Overlay",
        "OverlayHost",
        normal_style,
        0x00080000 | 0x00000020,
    )
    assert not is_capturable_window_metadata(
        "Bing Wallpaper",
        "WallpaperHost",
        0,
        0,
    )


def test_window_metadata_keeps_normal_application_windows() -> None:
    assert is_capturable_window_metadata(
        "Browser",
        "Chrome_WidgetWin_1",
        0x00C00000,
        0,
    )


def test_map_physical_rect_handles_scale_and_negative_origin() -> None:
    physical = QRect(-1920, -1080, 5760, 3240)
    logical = QRect(-1536, -864, 4608, 2592)

    result = map_physical_rect((-1920, -1080, 0, 0), physical, logical)

    assert result == QRect(-1536, -864, 1536, 864)


def test_map_physical_rect_uses_each_monitor_own_dpi_island() -> None:
    displays = (
        DisplayMapping(QRect(0, 0, 3840, 2160), QRect(0, 0, 2560, 1440)),
        DisplayMapping(
            QRect(-3822, -2167, 3840, 2160),
            QRect(-3822, -2167, 2560, 1440),
        ),
    )

    result = map_physical_rect_to_displays(
        (-3500, -2000, -2000, -1200),
        displays,
        QRect(-3822, -2167, 6382, 3607),
    )

    assert result == QRect(-3607, -2056, 1000, 534)


def test_window_locator_returns_exact_target_handle() -> None:
    locator = object.__new__(WindowLocator)
    locator._windows = [
        CapturableWindow(101, QRect(10, 10, 400, 300), "Target"),
    ]

    target = locator.target_at(QPoint(100, 80))

    assert target is not None
    assert target.handle == 101
    assert locator.window_at(QPoint(100, 80)) == QRect(10, 10, 400, 300)


def test_window_locator_refreshes_geometry_for_exact_handle(monkeypatch) -> None:
    locator = object.__new__(WindowLocator)
    expected = QRect(900, 120, 800, 600)
    monkeypatch.setattr(locator, "_window_geometry", lambda handle: expected)

    assert locator.geometry_for_handle(5150) == expected
