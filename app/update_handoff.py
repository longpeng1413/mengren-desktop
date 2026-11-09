"""Hand over from the old copy to the freshly installed one.

The old copy starts the new EXE with ``--after-update <pid> --previous <exe>``
and quits. The new copy waits for that process to end (at most 10 seconds; an
old copy still running then is closed) before it registers any shortcut, then points desktop shortcuts at itself and moves the old version's
folder to the Recycle Bin (only a folder this updater created).
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from core.update import old_install_folder

_log = logging.getLogger(__name__)

AFTER_UPDATE = "--after-update"
PREVIOUS = "--previous"
_SYNCHRONIZE = 0x00100000
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DETACHED_PROCESS = 0x00000008
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True, slots=True)
class Handoff:
    """What the new copy learns from the old one."""

    old_pid: int
    previous_exe: Path


def launch_new_version(new_exe: Path, old_exe: Path) -> None:
    """Start the new copy; the caller quits right after.

    The new copy leaves any Windows job the old one runs in, so it is not
    closed together with the old copy; where that is not allowed it starts
    normally.
    """
    arguments = [str(new_exe), AFTER_UPDATE, str(os.getpid()), PREVIOUS, str(old_exe)]
    try:
        subprocess.Popen(
            arguments,
            cwd=str(new_exe.parent),
            creationflags=_DETACHED_PROCESS | _CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
        )
    except OSError:
        subprocess.Popen(arguments, cwd=str(new_exe.parent), creationflags=_DETACHED_PROCESS, close_fds=True)


def parse_handoff(arguments: list[str]) -> Handoff | None:
    """Read ``--after-update <pid> --previous <exe>`` from the command line."""
    try:
        pid = int(arguments[arguments.index(AFTER_UPDATE) + 1])
        previous = Path(arguments[arguments.index(PREVIOUS) + 1])
    except (ValueError, IndexError):
        return None
    return Handoff(pid, previous)


# The developer's limit: the new copy appears within about 10 seconds.
OLD_COPY_TIMEOUT_SECONDS = 10.0


def _kernel32():
    # A private instance, so these prototypes never change ctypes.windll for others.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def wait_for_exit(pid: int, timeout_seconds: float = OLD_COPY_TIMEOUT_SECONDS) -> bool:
    """Wait until the old copy has quit; return whether it did in time."""
    try:
        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        if not handle:
            return True  # Already gone.
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000)) == 0
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return True


def _same_file(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def end_old_copy(handoff: Handoff, timeout_seconds: float = OLD_COPY_TIMEOUT_SECONDS) -> str:
    """Wait for the old copy; if it still runs after the timeout, close it.

    Only the process running the previous version's EXE is ever closed: a
    process id can be reused, so anything else is left alone. Returns a short
    description for the log (logging is not set up yet when this runs).
    """
    if wait_for_exit(handoff.old_pid, timeout_seconds):
        return "旧版本已退出"
    try:
        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(
            _PROCESS_TERMINATE | _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, handoff.old_pid
        )
        if not handle:
            return "旧版本已退出"
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return f"旧版本 {timeout_seconds:g} 秒内没有退出，且无法确认进程，未强制关闭"
            if not _same_file(Path(buffer.value), handoff.previous_exe):
                return "旧版本已退出（原进程号已被其他程序使用）"
            if not kernel32.TerminateProcess(handle, 1):
                return f"旧版本 {timeout_seconds:g} 秒内没有退出，强制关闭失败"
            kernel32.WaitForSingleObject(handle, 5000)
            return f"旧版本 {timeout_seconds:g} 秒内没有退出，已强制关闭"
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError) as error:
        return f"等待旧版本退出时出错：{error!r}"


def finish_update(handoff: Handoff, new_exe: Path) -> list[str]:
    """Repoint desktop shortcuts and recycle the old folder; return what was done."""
    done = []
    changed = repoint_shortcuts(handoff.previous_exe, new_exe)
    if changed:
        done.append(f"已更新 {changed} 个桌面快捷方式")
    folder = old_install_folder(handoff.previous_exe)
    if folder is not None and folder.exists() and folder != old_install_folder(new_exe):
        if move_to_recycle_bin(folder):
            done.append(f"旧版本文件夹已移到回收站：{folder}")
    _log.info("更新后的整理：%s", "；".join(done) or "无需整理")
    return done


def repoint_shortcuts(old_exe: Path, new_exe: Path) -> int:
    """Point desktop shortcuts aimed at the old EXE to the new one."""
    script = (
        "$old = $args[0]; $new = $args[1]; $count = 0;"
        "$shell = New-Object -ComObject WScript.Shell;"
        "$folders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory'));"
        "foreach ($folder in $folders) { if (-not $folder) { continue };"
        " Get-ChildItem -LiteralPath $folder -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {"
        "  $link = $shell.CreateShortcut($_.FullName);"
        "  if ($link.TargetPath -ieq $old) {"
        "   $link.TargetPath = $new; $link.WorkingDirectory = Split-Path $new;"
        "   $link.IconLocation = $new + ',0'; $link.Save(); $count++ } } };"
        "Write-Output $count"
    )
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"& {{ {script} }}",
                str(old_exe),
                str(new_exe),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_CREATE_NO_WINDOW,
        )
        return int((completed.stdout or "0").strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as error:
        _log.warning("更新桌面快捷方式失败：%r", error)
        return 0


class _FileOperation(ctypes.Structure):
    _fields_ = (
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    )


def move_to_recycle_bin(path: Path) -> bool:
    """Send a folder to the Recycle Bin so it can still be restored."""
    operation = _FileOperation()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = str(path) + "\0"
    # FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    except (AttributeError, OSError) as error:
        _log.warning("移到回收站失败：%r", error)
        return False
    if result != 0 or operation.fAnyOperationsAborted:
        _log.warning("移到回收站失败，错误码 %s：%s", result, path)
        return False
    return True
