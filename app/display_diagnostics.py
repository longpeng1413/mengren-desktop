"""Collect non-sensitive display and DPI information for support."""

from __future__ import annotations

import ctypes
import os
import platform
import sys

import PySide6
from PySide6.QtCore import qVersion
from PySide6.QtGui import QCursor, QGuiApplication

from app.branding import APP_DISPLAY_NAME, APP_VERSION


def collect_display_diagnostics() -> str:
    """Return display geometry, scale, and native-monitor data as plain text."""
    lines = [
        f"{APP_DISPLAY_NAME} 显示器诊断",
        f"软件版本: {APP_VERSION}",
        f"系统: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        f"Qt: {qVersion()}",
        f"PySide6: {PySide6.__version__}",
        f"QT_SCALE_FACTOR_ROUNDING_POLICY: {os.environ.get('QT_SCALE_FACTOR_ROUNDING_POLICY', '')}",
        f"鼠标全局坐标: {_point_text(QCursor.pos())}",
        "",
        "[Qt 显示器]",
    ]

    primary = QGuiApplication.primaryScreen()
    screens = QGuiApplication.screens()
    for index, screen in enumerate(screens, start=1):
        geometry = screen.geometry()
        available = screen.availableGeometry()
        physical = screen.physicalSize()
        lines.extend(
            [
                f"屏幕 {index}: {screen.name()}",
                f"  主屏: {'是' if screen is primary else '否'}",
                f"  逻辑区域: {_rect_text(geometry)}",
                f"  可用区域: {_rect_text(available)}",
                f"  缩放因子 DPR: {screen.devicePixelRatio():.4f}",
                f"  逻辑 DPI: {screen.logicalDotsPerInchX():.2f} x {screen.logicalDotsPerInchY():.2f}",
                f"  物理 DPI: {screen.physicalDotsPerInchX():.2f} x {screen.physicalDotsPerInchY():.2f}",
                f"  物理尺寸毫米: {physical.width():.2f} x {physical.height():.2f}",
                f"  刷新率: {screen.refreshRate():.2f}",
                f"  厂商/型号: {screen.manufacturer()} / {screen.model()}",
            ]
        )

    lines.extend(["", "[Windows 虚拟桌面]"])
    lines.extend(_windows_metrics())
    lines.extend(["", "[MSS 物理显示器]"])
    lines.extend(_mss_metrics())
    return "\n".join(lines) + "\n"


def _windows_metrics() -> list[str]:
    if sys.platform != "win32":
        return ["非 Windows 系统"]
    user32 = ctypes.windll.user32
    metrics = {
        "虚拟桌面左": 76,
        "虚拟桌面上": 77,
        "虚拟桌面宽": 78,
        "虚拟桌面高": 79,
        "显示器数量": 80,
        "主屏宽": 0,
        "主屏高": 1,
    }
    result = [f"{name}: {user32.GetSystemMetrics(code)}" for name, code in metrics.items()]
    try:
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
        context = user32.GetThreadDpiAwarenessContext()
        awareness = user32.GetAwarenessFromDpiAwarenessContext(context)
        result.append(f"线程 DPI Awareness: {awareness} (0未知/1系统/2每显示器)")
    except (AttributeError, OSError):
        result.append("线程 DPI Awareness: 无法读取")
    try:
        result.append(f"系统 DPI: {user32.GetDpiForSystem()}")
    except (AttributeError, OSError):
        result.append("系统 DPI: 无法读取")
    return result


def _mss_metrics() -> list[str]:
    try:
        import mss

        with mss.MSS() as session:
            monitors = tuple(session.monitors)
        return [
            f"区域 {index}: left={monitor['left']}, top={monitor['top']}, "
            f"width={monitor['width']}, height={monitor['height']}"
            for index, monitor in enumerate(monitors)
        ]
    except Exception as error:
        return [f"读取失败: {error}"]


def _rect_text(rect) -> str:
    return f"x={rect.x()}, y={rect.y()}, width={rect.width()}, height={rect.height()}"


def _point_text(point) -> str:
    return f"x={point.x()}, y={point.y()}"
