"""Small Windows system actions exposed by the desktop tools launcher."""

from __future__ import annotations

import csv
import ctypes
import subprocess
import sys


_CALCULATOR_IMAGE_NAMES = {
    "calculator.exe",
    "calculatorapp.exe",
    "win32calc.exe",
}


def open_calculator() -> bool:
    """Open the Windows Calculator as an independent process."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.Popen(
            ["calc.exe"],
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return True
    except OSError:
        return False


def _running_calculator_images() -> tuple[str, ...] | None:
    """Return active Calculator executable names, or None if detection failed."""
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="ignore",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    running = {
        row[0]
        for row in csv.reader(result.stdout.splitlines())
        if row and row[0].casefold() in _CALCULATOR_IMAGE_NAMES
    }
    return tuple(sorted(running, key=str.casefold))


def toggle_calculator() -> bool:
    """Open Calculator when absent, or close all Calculator instances when open."""
    if sys.platform != "win32":
        return False
    running = _running_calculator_images()
    if running is None:
        return False
    if not running:
        return open_calculator()
    closed = False
    for image_name in running:
        try:
            result = subprocess.run(
                ["taskkill.exe", "/IM", image_name, "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            continue
        closed = result.returncode == 0 or closed
    return closed


def put_computer_to_sleep() -> bool:
    """Ask Windows to enter normal sleep (not hibernation)."""
    if sys.platform != "win32":
        return False
    try:
        set_suspend_state = ctypes.windll.PowrProf.SetSuspendState
        set_suspend_state.argtypes = [ctypes.c_bool, ctypes.c_bool, ctypes.c_bool]
        set_suspend_state.restype = ctypes.c_bool
        return bool(set_suspend_state(False, False, False))
    except (AttributeError, OSError, TypeError, ValueError):
        return False
