"""Windows top-level window discovery for whole-window screenshots."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

import mss
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_GA_ROOTOWNER = 3
_GW_OWNER = 4
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_DESKTOP_CLASSES = {"Progman", "WorkerW"}
_IGNORED_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Windows.UI.Composition.DesktopWindowContentBridge",
}
_IGNORED_TITLES = {
    "Program Manager",
    "Windows Input Experience",
}

_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL
_user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetLastActivePopup.argtypes = (wintypes.HWND,)
_user32.GetLastActivePopup.restype = wintypes.HWND
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetWindow.restype = wintypes.HWND



class _NativeRect(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


_EnumWindowsCallback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass(frozen=True, slots=True)
class CapturableWindow:
    """One visible top-level Windows window and its Qt desktop rectangle."""

    handle: int
    geometry: QRect
    title: str = ""


@dataclass(frozen=True, slots=True)
class DisplayMapping:
    """One physical Windows monitor paired with its Qt logical screen."""

    physical: QRect
    logical: QRect


def is_capturable_window_metadata(
    title: str,
    class_name: str,
    style: int,
    extended_style: int,
) -> bool:
    """Reject desktop helpers and invisible interaction surfaces."""
    if not title.strip():
        return False
    if title.strip() in _IGNORED_TITLES:
        return False
    if class_name in _DESKTOP_CLASSES or class_name in _IGNORED_CLASSES:
        return False
    if extended_style & (_WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE):
        return False
    if (
        extended_style & _WS_EX_LAYERED
        and extended_style & _WS_EX_TRANSPARENT
    ):
        return False
    # Desktop widgets, wallpaper helpers and shell adornments are commonly
    # visible, titled top-level windows but deliberately have no normal app
    # frame. Require the same structural flags used by task-switchable apps.
    if not (
        style & (_WS_CAPTION | _WS_THICKFRAME)
        or extended_style & _WS_EX_APPWINDOW
    ):
        return False
    return True


def map_physical_rect(
    native_rect: tuple[int, int, int, int],
    physical_desktop: QRect,
    logical_desktop: QRect,
) -> QRect:
    """Map a Win32 physical rectangle into Qt virtual-desktop coordinates."""
    if physical_desktop.isEmpty() or logical_desktop.isEmpty():
        return QRect()
    left, top, right, bottom = native_rect
    scale_x = logical_desktop.width() / physical_desktop.width()
    scale_y = logical_desktop.height() / physical_desktop.height()
    logical_left = logical_desktop.left() + round((left - physical_desktop.left()) * scale_x)
    logical_top = logical_desktop.top() + round((top - physical_desktop.top()) * scale_y)
    logical_right = logical_desktop.left() + round((right - physical_desktop.left()) * scale_x)
    logical_bottom = logical_desktop.top() + round((bottom - physical_desktop.top()) * scale_y)
    return QRect(
        logical_left,
        logical_top,
        max(0, logical_right - logical_left),
        max(0, logical_bottom - logical_top),
    ).intersected(logical_desktop)


def map_physical_rect_to_displays(
    native_rect: tuple[int, int, int, int],
    displays: tuple[DisplayMapping, ...],
    logical_desktop: QRect,
) -> QRect:
    """Map a native window through the monitor on which most of it is visible."""
    if not displays:
        return QRect()
    left, top, right, bottom = native_rect
    native = QRect(left, top, max(0, right - left), max(0, bottom - top))
    if native.isEmpty():
        return QRect()

    def overlap_area(display: DisplayMapping) -> int:
        overlap = native.intersected(display.physical)
        return max(0, overlap.width()) * max(0, overlap.height())

    display = max(displays, key=overlap_area)
    physical = display.physical
    logical = display.logical
    if physical.isEmpty() or logical.isEmpty():
        return QRect()
    scale_x = logical.width() / physical.width()
    scale_y = logical.height() / physical.height()
    logical_left = logical.left() + round((left - physical.left()) * scale_x)
    logical_top = logical.top() + round((top - physical.top()) * scale_y)
    logical_right = logical.left() + round((right - physical.left()) * scale_x)
    logical_bottom = logical.top() + round((bottom - physical.top()) * scale_y)
    return QRect(
        logical_left,
        logical_top,
        max(0, logical_right - logical_left),
        max(0, logical_bottom - logical_top),
    ).intersected(logical_desktop)


class WindowLocator:
    """Find the frontmost capturable top-level window under the mouse."""

    def __init__(self, logical_desktop: QRect) -> None:
        self._logical_desktop = QRect(logical_desktop)
        self._physical_desktop = QRect(
            _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN),
            _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN),
            _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN),
            _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN),
        )
        self._display_mappings = self._read_display_mappings()
        self._process_id = os.getpid()
        self._windows = self._enumerate_windows()

    def refresh(self) -> None:
        """Refresh the cached Z-ordered list of visible windows."""
        self._windows = self._enumerate_windows()

    def window_at(self, point: QPoint) -> QRect:
        """Return the frontmost window rectangle containing a global Qt point."""
        target = self.target_at(point)
        return QRect(target.geometry) if target is not None else QRect()

    def target_at(self, point: QPoint) -> CapturableWindow | None:
        """Return the frontmost capturable window containing a global Qt point."""
        for window in self._windows:
            if window.geometry.contains(point):
                return window
        return None

    def geometry_for_handle(self, handle: int) -> QRect:
        """Return the current logical desktop rectangle for one exact HWND."""
        return self._window_geometry(handle)

    def diagnostics_for_target(self, target: CapturableWindow | None, point: QPoint) -> str:
        """Return exact Win32 metadata for the window highlighted at ``point``."""
        lines = [
            "猛人截图 F1 幽灵窗口诊断",
            f"鼠标逻辑坐标: x={point.x()}, y={point.y()}",
            (
                "Qt 虚拟桌面: "
                f"x={self._logical_desktop.x()}, y={self._logical_desktop.y()}, "
                f"width={self._logical_desktop.width()}, "
                f"height={self._logical_desktop.height()}"
            ),
            (
                "Windows 物理桌面: "
                f"x={self._physical_desktop.x()}, y={self._physical_desktop.y()}, "
                f"width={self._physical_desktop.width()}, "
                f"height={self._physical_desktop.height()}"
            ),
            "",
        ]
        if target is None:
            lines.append("当前没有识别到候选窗口。")
            return "\n".join(lines)

        handle = int(target.handle)
        process_id = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        native = _NativeRect()
        _user32.GetWindowRect(handle, ctypes.byref(native))
        extended = _NativeRect()
        extended_result = _dwmapi.DwmGetWindowAttribute(
            handle,
            _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(extended),
            ctypes.sizeof(extended),
        )
        cloaked = wintypes.DWORD()
        cloaked_result = _dwmapi.DwmGetWindowAttribute(
            handle,
            _DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        color_key = wintypes.DWORD()
        alpha = ctypes.c_ubyte(255)
        alpha_flags = wintypes.DWORD()
        has_layered_attributes = bool(
            _user32.GetLayeredWindowAttributes(
                handle,
                ctypes.byref(color_key),
                ctypes.byref(alpha),
                ctypes.byref(alpha_flags),
            )
        )
        style = int(_user32.GetWindowLongW(handle, _GWL_STYLE)) & 0xFFFFFFFF
        extended_style = int(_user32.GetWindowLongW(handle, _GWL_EXSTYLE)) & 0xFFFFFFFF
        root_owner = int(_user32.GetAncestor(handle, _GA_ROOTOWNER) or 0)
        last_popup = int(_user32.GetLastActivePopup(root_owner or handle) or 0)
        owner = int(_user32.GetWindow(handle, _GW_OWNER) or 0)
        index = next(
            (position for position, window in enumerate(self._windows) if window.handle == handle),
            -1,
        )
        lines.extend(
            [
                f"Z 顺序索引: {index}",
                f"窗口句柄 HWND: 0x{handle:X}",
                f"标题: {self._window_title(handle)!r}",
                f"窗口类: {self._window_class(handle)!r}",
                f"进程 PID: {process_id.value}",
                f"进程路径: {self._process_path(process_id.value)!r}",
                f"样式 STYLE: 0x{style:08X}",
                f"扩展样式 EXSTYLE: 0x{extended_style:08X}",
                f"可见: {bool(_user32.IsWindowVisible(handle))}",
                f"最小化: {bool(_user32.IsIconic(handle))}",
                f"可用: {bool(_user32.IsWindowEnabled(handle))}",
                f"拥有者 HWND: 0x{owner:X}",
                f"根拥有者 HWND: 0x{root_owner:X}",
                f"最后活动弹窗 HWND: 0x{last_popup:X}",
                (
                    "Qt 识别区域: "
                    f"x={target.geometry.x()}, y={target.geometry.y()}, "
                    f"width={target.geometry.width()}, height={target.geometry.height()}"
                ),
                (
                    "GetWindowRect: "
                    f"left={native.left}, top={native.top}, right={native.right}, "
                    f"bottom={native.bottom}"
                ),
                (
                    "DWM 扩展边界: "
                    + (
                        f"left={extended.left}, top={extended.top}, right={extended.right}, "
                        f"bottom={extended.bottom}"
                        if extended_result == 0
                        else f"读取失败，错误码={extended_result}"
                    )
                ),
                (
                    f"DWM Cloaked: {cloaked.value}"
                    if cloaked_result == 0
                    else f"DWM Cloaked 读取失败，错误码={cloaked_result}"
                ),
                (
                    f"Layered 属性: alpha={alpha.value}, flags=0x{alpha_flags.value:08X}, "
                    f"color_key=0x{color_key.value:08X}"
                    if has_layered_attributes
                    else "Layered 属性: 无或读取失败"
                ),
            ]
        )
        containing = [window for window in self._windows if window.geometry.contains(point)]
        lines.extend(["", f"该坐标下候选窗口数量: {len(containing)}"])
        for position, window in enumerate(containing):
            lines.append(
                f"候选 {position}: HWND=0x{window.handle:X}, "
                f"标题={window.title!r}, 区域={window.geometry.getRect()}"
            )
        return "\n".join(lines)

    def _enumerate_windows(self) -> list[CapturableWindow]:
        windows: list[CapturableWindow] = []

        @_EnumWindowsCallback
        def collect(handle: int, _parameter: int) -> bool:
            if self._window_class(handle) in _DESKTOP_CLASSES:
                # EnumWindows is ordered from front to back. Anything behind
                # the desktop host is wallpaper infrastructure, not a window
                # the user can meaningfully capture.
                return False
            geometry = self._window_geometry(handle)
            if not geometry.isEmpty():
                windows.append(
                    CapturableWindow(
                        int(handle),
                        geometry,
                        self._window_title(handle),
                    )
                )
            return True

        _user32.EnumWindows(collect, 0)
        return windows

    def _window_geometry(self, handle: int) -> QRect:
        if not _user32.IsWindowVisible(handle) or _user32.IsIconic(handle):
            return QRect()

        process_id = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        if process_id.value == self._process_id:
            return QRect()

        title = self._window_title(handle)
        class_name = self._window_class(handle)
        style = int(_user32.GetWindowLongW(handle, _GWL_STYLE))
        extended_style = int(_user32.GetWindowLongW(handle, _GWL_EXSTYLE))
        if not is_capturable_window_metadata(
            title,
            class_name,
            style,
            extended_style,
        ):
            return QRect()

        cloaked = wintypes.DWORD()
        if _dwmapi.DwmGetWindowAttribute(
            handle,
            _DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        ) == 0 and cloaked.value:
            return QRect()

        native = _NativeRect()
        result = _dwmapi.DwmGetWindowAttribute(
            handle,
            _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(native),
            ctypes.sizeof(native),
        )
        if result != 0 and not _user32.GetWindowRect(handle, ctypes.byref(native)):
            return QRect()
        if native.right - native.left < 20 or native.bottom - native.top < 20:
            return QRect()

        native_rect = (native.left, native.top, native.right, native.bottom)
        mapped = map_physical_rect_to_displays(
            native_rect,
            self._display_mappings,
            self._logical_desktop,
        )
        if not mapped.isEmpty():
            return mapped
        return map_physical_rect(
            native_rect,
            self._physical_desktop,
            self._logical_desktop,
        )

    @staticmethod
    def _read_display_mappings() -> tuple[DisplayMapping, ...]:
        """Pair Qt's DPI-scaled screen islands with native monitor rectangles."""
        try:
            with mss.MSS() as session:
                remaining = [dict(monitor) for monitor in session.monitors[1:]]
        except Exception:
            return ()

        mappings: list[DisplayMapping] = []
        for screen in QGuiApplication.screens():
            if not remaining:
                break
            logical = QRect(screen.geometry())
            expected_width = logical.width() * screen.devicePixelRatio()
            expected_height = logical.height() * screen.devicePixelRatio()

            def score(monitor: dict[str, int]) -> float:
                position_error = (
                    abs(monitor["left"] - logical.left())
                    + abs(monitor["top"] - logical.top())
                )
                size_error = (
                    abs(monitor["width"] - expected_width)
                    + abs(monitor["height"] - expected_height)
                )
                return position_error * 1000 + size_error

            monitor = min(remaining, key=score)
            remaining.remove(monitor)
            mappings.append(
                DisplayMapping(
                    QRect(
                        monitor["left"],
                        monitor["top"],
                        monitor["width"],
                        monitor["height"],
                    ),
                    logical,
                )
            )
        return tuple(mappings)

    @staticmethod
    def _window_title(handle: int) -> str:
        length = _user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return ""
        title = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(handle, title, len(title))
        return title.value

    @staticmethod
    def _window_class(handle: int) -> str:
        class_name = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(handle, class_name, len(class_name))
        return class_name.value

    @staticmethod
    def _process_path(process_id: int) -> str:
        if not process_id:
            return ""
        process = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id,
        )
        if not process:
            return ""
        try:
            capacity = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(capacity.value)
            if _kernel32.QueryFullProcessImageNameW(
                process,
                0,
                path,
                ctypes.byref(capacity),
            ):
                return path.value
            return ""
        finally:
            _kernel32.CloseHandle(process)
