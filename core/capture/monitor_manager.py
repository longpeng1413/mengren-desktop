from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication


@dataclass(slots=True)
class MonitorInfo:
    name: str
    geometry: QRect
    available_geometry: QRect
    device_pixel_ratio: float


class MonitorManager:
    """负责管理所有显示器信息。"""

    def __init__(self) -> None:
        self._screens: list[MonitorInfo] = []
        self.refresh()

    def refresh(self) -> None:
        """重新读取所有显示器。"""
        self._screens.clear()

        for screen in QGuiApplication.screens():
            self._screens.append(
                MonitorInfo(
                    name=screen.name(),
                    geometry=screen.geometry(),
                    available_geometry=screen.availableGeometry(),
                    device_pixel_ratio=screen.devicePixelRatio(),
                )
            )

    @property
    def screens(self) -> list[MonitorInfo]:
        return self._screens

    @property
    def virtual_geometry(self) -> QRect:
        """整个虚拟桌面区域（支持多屏）。"""

        if not self._screens:
            return QRect()

        left = min(s.geometry.left() for s in self._screens)
        top = min(s.geometry.top() for s in self._screens)
        right = max(s.geometry.right() for s in self._screens)
        bottom = max(s.geometry.bottom() for s in self._screens)

        return QRect(
            left,
            top,
            right - left + 1,
            bottom - top + 1,
        )