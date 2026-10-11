"""Desktop snapshot implementation for Windows virtual desktops."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor

import mss
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage, QPainter


@dataclass(frozen=True, slots=True)
class MonitorSnapshot:
    """One monitor captured at native physical resolution."""

    logical_geometry: QRect
    physical_geometry: QRect
    image: QImage


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    """A physical desktop image mapped to Qt's virtual desktop geometry."""

    virtual_geometry: QRect
    image: QImage
    monitors: tuple[MonitorSnapshot, ...] = ()

    def crop(self, selection: QRect) -> QImage:
        """Return a pixel-perfect crop for a global logical selection."""
        selection = selection.intersected(self.virtual_geometry)
        if selection.isEmpty() or self.image.isNull():
            return QImage()

        intersecting = tuple(
            monitor
            for monitor in self.monitors
            if monitor.logical_geometry.intersects(selection)
        )
        if intersecting:
            return self._crop_native(selection, intersecting)

        scale_x = self.image.width() / self.virtual_geometry.width()
        scale_y = self.image.height() / self.virtual_geometry.height()
        x = floor((selection.left() - self.virtual_geometry.left()) * scale_x)
        y = floor((selection.top() - self.virtual_geometry.top()) * scale_y)
        right = ceil((selection.right() - self.virtual_geometry.left() + 1) * scale_x)
        bottom = ceil((selection.bottom() - self.virtual_geometry.top() + 1) * scale_y)
        return self.image.copy(x, y, right - x, bottom - y)

    def _crop_native(
        self,
        selection: QRect,
        monitors: tuple[MonitorSnapshot, ...],
    ) -> QImage:
        """Crop one logical selection from per-monitor native images."""
        if len(monitors) == 1 and monitors[0].logical_geometry.contains(selection):
            monitor = monitors[0]
            source = self._monitor_source_rect(selection, monitor)
            return monitor.image.copy(source)

        output_scale = max(
            max(
                monitor.image.width() / monitor.logical_geometry.width(),
                monitor.image.height() / monitor.logical_geometry.height(),
            )
            for monitor in monitors
        )
        output = QImage(
            ceil(selection.width() * output_scale),
            ceil(selection.height() * output_scale),
            QImage.Format.Format_ARGB32,
        )
        output.fill(0)
        painter = QPainter(output)
        try:
            for monitor in monitors:
                intersection = selection.intersected(monitor.logical_geometry)
                if intersection.isEmpty():
                    continue
                source = self._monitor_source_rect(intersection, monitor)
                left = floor((intersection.left() - selection.left()) * output_scale)
                top = floor((intersection.top() - selection.top()) * output_scale)
                right = ceil((intersection.right() - selection.left() + 1) * output_scale)
                bottom = ceil((intersection.bottom() - selection.top() + 1) * output_scale)
                painter.drawImage(
                    QRect(left, top, right - left, bottom - top),
                    monitor.image,
                    source,
                )
        finally:
            painter.end()
        return output

    @staticmethod
    def _monitor_source_rect(selection: QRect, monitor: MonitorSnapshot) -> QRect:
        logical = monitor.logical_geometry
        scale_x = monitor.image.width() / logical.width()
        scale_y = monitor.image.height() / logical.height()
        left = floor((selection.left() - logical.left()) * scale_x)
        top = floor((selection.top() - logical.top()) * scale_y)
        right = ceil((selection.right() - logical.left() + 1) * scale_x)
        bottom = ceil((selection.bottom() - logical.top() + 1) * scale_y)
        return QRect(left, top, right - left, bottom - top).intersected(monitor.image.rect())


class DesktopCaptureEngine:
    """Captures the complete Windows virtual desktop before any overlay exists."""

    def capture(self, virtual_geometry: QRect) -> DesktopSnapshot:
        """Capture the current virtual desktop using MSS/Windows GDI."""
        with mss.MSS() as session:
            desktop = session.monitors[0]
            shot = session.grab(desktop)
            physical_desktop = QImage(
                shot.bgra,
                shot.width,
                shot.height,
                shot.width * 4,
                QImage.Format.Format_ARGB32,
            ).copy()
            monitor_data = tuple(dict(monitor) for monitor in session.monitors[1:])

        monitor_snapshots = self._monitor_snapshots(
            virtual_geometry,
            physical_desktop,
            desktop,
            monitor_data,
        )
        if not monitor_snapshots:
            return DesktopSnapshot(QRect(virtual_geometry), physical_desktop)

        preview = QImage(virtual_geometry.size(), QImage.Format.Format_ARGB32)
        preview.fill(0)
        painter = QPainter(preview)
        try:
            for monitor in monitor_snapshots:
                target = QRect(monitor.logical_geometry)
                target.translate(-virtual_geometry.topLeft())
                painter.drawImage(target, monitor.image)
        finally:
            painter.end()
        return DesktopSnapshot(QRect(virtual_geometry), preview, monitor_snapshots)

    def capture_selection(self, virtual_geometry: QRect, selection: QRect) -> QImage:
        """Capture only one logical desktop selection for fast scroll sampling."""
        selection = selection.intersected(virtual_geometry)
        if selection.isEmpty() or virtual_geometry.isEmpty():
            return QImage()

        with mss.MSS() as session:
            desktop = session.monitors[0]
            region = self._physical_region_for_selection(
                virtual_geometry,
                selection,
                desktop,
                tuple(session.monitors[1:]),
            )
            shot = session.grab(region)
            return QImage(
                shot.bgra,
                shot.width,
                shot.height,
                shot.width * 4,
                QImage.Format.Format_ARGB32,
            ).copy()

    @staticmethod
    def _physical_region(
        virtual_geometry: QRect,
        selection: QRect,
        desktop: dict[str, int],
    ) -> dict[str, int]:
        """Map a Qt logical selection into the MSS physical desktop coordinate system."""
        scale_x = desktop["width"] / virtual_geometry.width()
        scale_y = desktop["height"] / virtual_geometry.height()
        left = floor((selection.left() - virtual_geometry.left()) * scale_x)
        top = floor((selection.top() - virtual_geometry.top()) * scale_y)
        right = ceil((selection.right() - virtual_geometry.left() + 1) * scale_x)
        bottom = ceil((selection.bottom() - virtual_geometry.top() + 1) * scale_y)
        return {
            "left": desktop["left"] + left,
            "top": desktop["top"] + top,
            "width": right - left,
            "height": bottom - top,
        }

    @classmethod
    def _physical_region_for_selection(
        cls,
        virtual_geometry: QRect,
        selection: QRect,
        desktop: dict[str, int],
        monitors: tuple[dict[str, int], ...],
    ) -> dict[str, int]:
        """Map a single-screen selection using that monitor's native scale."""
        screen = QGuiApplication.screenAt(selection.center())
        if screen is not None and screen.geometry().contains(selection) and monitors:
            monitor = cls._match_monitor(screen.geometry(), screen.devicePixelRatio(), monitors)
            if monitor is not None:
                return cls._physical_region_on_monitor(screen.geometry(), selection, monitor)
        return cls._physical_region(virtual_geometry, selection, desktop)

    @staticmethod
    def _physical_region_on_monitor(
        logical_geometry: QRect,
        selection: QRect,
        monitor: dict[str, int],
    ) -> dict[str, int]:
        scale_x = monitor["width"] / logical_geometry.width()
        scale_y = monitor["height"] / logical_geometry.height()
        left = floor((selection.left() - logical_geometry.left()) * scale_x)
        top = floor((selection.top() - logical_geometry.top()) * scale_y)
        right = ceil((selection.right() - logical_geometry.left() + 1) * scale_x)
        bottom = ceil((selection.bottom() - logical_geometry.top() + 1) * scale_y)
        return {
            "left": monitor["left"] + left,
            "top": monitor["top"] + top,
            "width": right - left,
            "height": bottom - top,
        }

    @classmethod
    def _monitor_snapshots(
        cls,
        virtual_geometry: QRect,
        physical_desktop: QImage,
        desktop: dict[str, int],
        monitors: tuple[dict[str, int], ...],
    ) -> tuple[MonitorSnapshot, ...]:
        snapshots: list[MonitorSnapshot] = []
        remaining = list(monitors)
        for screen in QGuiApplication.screens():
            monitor = cls._match_monitor(
                screen.geometry(),
                screen.devicePixelRatio(),
                tuple(remaining),
            )
            if monitor is None:
                continue
            remaining.remove(monitor)
            physical_geometry = QRect(
                monitor["left"],
                monitor["top"],
                monitor["width"],
                monitor["height"],
            )
            source = QRect(physical_geometry)
            source.translate(-desktop["left"], -desktop["top"])
            image = physical_desktop.copy(source)
            if image.isNull():
                continue
            snapshots.append(
                MonitorSnapshot(
                    QRect(screen.geometry()),
                    physical_geometry,
                    image,
                )
            )
        return tuple(snapshots)

    @staticmethod
    def _match_monitor(
        logical_geometry: QRect,
        device_pixel_ratio: float,
        monitors: tuple[dict[str, int], ...],
    ) -> dict[str, int] | None:
        """Match one Qt screen to the closest Windows physical monitor."""
        if not monitors:
            return None

        expected_width = logical_geometry.width() * device_pixel_ratio
        expected_height = logical_geometry.height() * device_pixel_ratio

        def score(monitor: dict[str, int]) -> float:
            position_error = (
                abs(monitor["left"] - logical_geometry.left())
                + abs(monitor["top"] - logical_geometry.top())
            )
            size_error = (
                abs(monitor["width"] - expected_width)
                + abs(monitor["height"] - expected_height)
            )
            return position_error * 1000 + size_error

        return min(monitors, key=score)
