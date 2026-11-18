"""Save and restore Windows Explorer desktop icon positions."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import sys
import tempfile

from app.reminder_preferences import settings_directory


class LayoutError(Exception):
    """An actionable desktop layout failure."""


class LVITEM(ctypes.Structure):
    _fields_ = [("mask", wintypes.UINT), ("iItem", ctypes.c_int),
                ("iSubItem", ctypes.c_int), ("state", wintypes.UINT),
                ("stateMask", wintypes.UINT), ("pszText", ctypes.c_void_p),
                ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int),
                ("lParam", ctypes.c_ssize_t), ("iIndent", ctypes.c_int),
                ("iGroupId", ctypes.c_int), ("cColumns", wintypes.UINT),
                ("puColumns", ctypes.c_void_p), ("piColFmt", ctypes.c_void_p),
                ("iGroup", ctypes.c_int)]


def _path():
    return settings_directory() / "desktop_icon_layout.json"


def save_layout():
    with DesktopIcons() as desktop:
        icons = desktop.read()
    if not icons:
        raise LayoutError("没有找到桌面图标，请先显示桌面图标。")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as file:
            temp = file.name
            json.dump({"version": 1, "icons": icons}, file, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
    return len(icons)


def restore_layout():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        icons = data["icons"]
        if data["version"] != 1 or not isinstance(icons, dict) or not icons:
            raise ValueError()
        for name, point in icons.items():
            if not isinstance(name, str) or not isinstance(point, list) or len(point) != 2 or any(type(v) is not int or abs(v) > 100000 for v in point):
                raise ValueError()
    except FileNotFoundError:
        raise LayoutError("还没有保存图标布局，请先选择“记忆当前电脑布局”。") from None
    except (OSError, ValueError, KeyError, TypeError):
        raise LayoutError("保存的图标布局无法读取，请重新保存。") from None
    with DesktopIcons() as desktop:
        return desktop.restore(icons)


class DesktopIcons:
    def __enter__(self):
        if sys.platform != "win32":
            raise LayoutError("此功能仅支持 Windows 桌面。")
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.u.FindWindowW.restype = wintypes.HWND
        self.u.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.u.FindWindowExW.restype = wintypes.HWND
        self.u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        self.u.SendMessageTimeoutW.restype = wintypes.LPARAM
        self.u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.k.OpenProcess.restype = wintypes.HANDLE
        self.k.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
        self.k.VirtualAllocEx.restype = ctypes.c_void_p
        self.k.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
        self.k.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.k.WriteProcessMemory.argtypes = self.k.ReadProcessMemory.argtypes
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        find = self.u.FindWindowExW
        host = self.u.FindWindowW("Progman", None)
        view = find(host, None, "SHELLDLL_DefView", None)
        worker = None
        while not view:
            worker = find(None, worker, "WorkerW", None)
            if not worker:
                break
            view = find(worker, None, "SHELLDLL_DefView", None)
        self.hwnd = find(view, None, "SysListView32", "FolderView") if view else None
        if not self.hwnd:
            raise LayoutError("无法找到 Windows 桌面图标，请确认资源管理器正在运行。")
        pid = wintypes.DWORD()
        self.u.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        self.process = self.k.OpenProcess(0x438, False, pid.value)
        if not self.process:
            raise LayoutError("无法访问 Windows 桌面图标。")
        self.memory = self.k.VirtualAllocEx(self.process, None, 4096, 0x3000, 0x04)
        if not self.memory:
            self.k.CloseHandle(self.process)
            raise LayoutError("无法读取 Windows 桌面图标。")
        return self

    def __exit__(self, *_args):
        self.k.VirtualFreeEx(self.process, self.memory, 0, 0x8000)
        self.k.CloseHandle(self.process)

    def _send(self, message, wparam=0, lparam=0):
        result = ctypes.c_size_t()
        if not self.u.SendMessageTimeoutW(self.hwnd, message, wparam, lparam, 2, 3000, ctypes.byref(result)):
            raise LayoutError("Windows 桌面未响应，请稍后重试。")
        return result.value

    def _write(self, address, value):
        size = ctypes.sizeof(value)
        done = ctypes.c_size_t()
        if not self.k.WriteProcessMemory(self.process, address, ctypes.byref(value), size, ctypes.byref(done)) or done.value != size:
            raise LayoutError("无法写入桌面图标位置。")

    def _read(self, address, value):
        size = ctypes.sizeof(value)
        done = ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.process, address, ctypes.byref(value), size, ctypes.byref(done)) or done.value != size:
            raise LayoutError("无法读取桌面图标位置。")

    def read(self):
        icons = {}
        for index in range(self._send(0x1004)):
            item = LVITEM()
            item.iItem = index
            item.pszText = self.memory + 512
            item.cchTextMax = 512
            self._write(self.memory, item)
            self._send(0x1073, index, self.memory)
            name = ctypes.create_unicode_buffer(512)
            self._read(self.memory + 512, name)
            point = wintypes.POINT()
            if not self._send(0x1010, index, self.memory):
                raise LayoutError("无法读取桌面图标位置。")
            self._read(self.memory, point)
            if not name.value or name.value in icons:
                raise LayoutError("桌面存在同名图标或无法读取名称，无法可靠保存或恢复布局。")
            icons[name.value] = [point.x, point.y]
        return icons

    def restore(self, saved):
        if self.u.GetWindowLongW(self.hwnd, -16) & 0x100:
            raise LayoutError("Windows 已开启“自动排列图标”。请在桌面右键 → 查看中关闭后重试。")
        current = self.read()
        matched = set(current) & set(saved)
        if not matched:
            raise LayoutError("当前桌面没有与已保存布局匹配的图标。")
        for index, name in enumerate(current):
            if name in matched:
                point = wintypes.POINT(*saved[name])
                self._write(self.memory, point)
                self._send(0x1031, index, self.memory)
        actual = self.read()
        failed = sum(actual[name] != saved[name] for name in matched if name in actual)
        return len(matched), len(saved) - len(matched), len(current) - len(matched), failed
