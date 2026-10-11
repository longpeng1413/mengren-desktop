"""Windows high-DPI startup configuration."""

from __future__ import annotations

import ctypes
import os
import sys


def configure_process_dpi() -> None:
    """Enable per-monitor DPI awareness before Qt or capture libraries load."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    try:
        pointer_bits = ctypes.sizeof(ctypes.c_void_p) * 8
        per_monitor_v2 = ctypes.c_void_p((-4) & ((1 << pointer_bits) - 1))
        if user32.SetProcessDpiAwarenessContext(per_monitor_v2):
            return
    except (AttributeError, OSError):
        pass

    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) in (0, 1):
            return
    except (AttributeError, OSError):
        pass

    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass
