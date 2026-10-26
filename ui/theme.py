"""The shared dark look of 猛人桌面助手 (the main window's style).

Every toolbar (F1 editor, F2 long capture, F3 desktop tools, F4 presentation)
and the translator window use these colours so the app looks like one piece:
quiet dark panels with thin borders, rounded corners, the Microsoft YaHei UI
font and the emerald of the app icon for the selected state.
"""

from __future__ import annotations

import ctypes

from PySide6.QtWidgets import QWidget

BACKGROUND = "#0e0e10"
PANEL = "#151518"
RAISED = "#1c1c21"
HOVER = "#23232a"
PRESSED = "#2b2b33"
LINE = "#2a2a31"
TEXT = "#ebe8e1"
MUTED = "#8f8c85"
DISABLED = "#5c5a55"
ACCENT = "#6cc59a"
ACCENT_INK = "#0b1a12"
DANGER = "#ff6b5e"
WARNING = "#e8b04a"
FONT = '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif'

MENU_STYLE = f"""
QMenu {{
    color: {TEXT};
    background-color: {RAISED};
    border: 1px solid {LINE};
    padding: 4px;
    font-family: {FONT};
    font-size: 13px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background-color: {ACCENT}; color: {ACCENT_INK}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
"""


def toolbar_style(object_name: str, font_size: int = 13) -> str:
    """Style a floating toolbar and every button inside it."""
    selector = f"#{object_name}"
    buttons = f"{selector} QPushButton, {selector} QToolButton"
    return f"""
{selector} {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 10px;
}}
{selector} QLabel {{ color: {TEXT}; font-family: {FONT}; font-size: {font_size}px; }}
{buttons} {{
    color: {TEXT};
    background-color: {RAISED};
    border: 1px solid {LINE};
    border-radius: 7px;
    font-family: {FONT};
    font-size: {font_size}px;
    font-weight: 600;
    padding: 0px;
}}
{selector} QPushButton:hover, {selector} QToolButton:hover {{
    background-color: {HOVER};
    border-color: {ACCENT};
}}
{selector} QPushButton:pressed, {selector} QToolButton:pressed {{ background-color: {PRESSED}; }}
{selector} QPushButton:checked, {selector} QToolButton:checked {{
    color: {ACCENT_INK};
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
{selector} QPushButton:disabled, {selector} QToolButton:disabled {{
    color: {DISABLED};
    background-color: {PANEL};
    border-color: #1e1e23;
}}
{selector} QPushButton#dragHandle {{
    color: {MUTED};
    background-color: transparent;
    border: 1px dashed {LINE};
}}
{selector} QPushButton#dragHandle:hover {{ color: {TEXT}; border-color: {MUTED}; }}
{selector} QPushButton#primaryButton {{
    color: {ACCENT_INK};
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
{selector} QPushButton#primaryButton:hover {{ background-color: #7fd3aa; }}
{selector} QPushButton#dangerButton {{ color: {DANGER}; }}
{selector} QPushButton#dangerButton:hover {{ border-color: {DANGER}; }}
{selector} QToolButton::menu-indicator {{ image: none; }}
""" + MENU_STYLE


def round_corners(widget: QWidget) -> None:
    """Ask Windows 11 to round a frameless window and match its border colour."""
    try:
        handle = int(widget.winId())
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle, 33, ctypes.byref(preference), ctypes.sizeof(preference)
        )
        # COLORREF is 0x00BBGGRR.
        border = ctypes.c_uint(0x00312A2A)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle, 34, ctypes.byref(border), ctypes.sizeof(border)
        )
    except (AttributeError, OSError, ValueError):
        pass


def dark_title_bar(widget: QWidget) -> None:
    """Ask Windows 10/11 for a dark title bar on a normal window."""
    try:
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(widget.winId()), 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except (AttributeError, OSError, ValueError):
        pass
