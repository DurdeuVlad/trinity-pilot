"""Desktop automation MCP server — low-level click, type, key actions.

Provides Copilot with tools to drive the Trinity Pilot UI for automated testing.
ACTION tools only. Cross-cutting sensors (screenshot, find_window, locate_on_screen)
have been moved to sensor_server.py.

Run: python -m trinity_pilot.mcp.desktop_automation_server
"""
from __future__ import annotations

import time

import pyautogui as pg
from fastmcp import FastMCP

mcp = FastMCP("desktop-automation")

# Fail-safe: move mouse to corner to abort
pg.FAILSAFE = True
pg.PAUSE = 0.05



@mcp.tool()
def click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Click at screen coordinates.

    Args:
        x: X coordinate.
        y: Y coordinate.
        button: 'left', 'right', or 'middle'.
        clicks: Number of clicks (2 for double-click).

    Returns:
        Confirmation string.
    """
    pg.click(x, y, button=button, clicks=clicks)
    return f"Clicked ({x}, {y}) with {button} button × {clicks}"


@mcp.tool()
def move_to(x: int, y: int) -> str:
    """Move mouse to coordinates without clicking."""
    pg.moveTo(x, y)
    return f"Moved to ({x}, {y})"


@mcp.tool()
def type_text(text: str, interval: float = 0.02) -> str:
    """Type text at the current cursor position.

    Args:
        text: Text to type.
        interval: Seconds between keystrokes.

    Returns:
        Confirmation string.
    """
    pg.typewrite(text, interval=interval)
    return f"Typed {len(text)} characters"


@mcp.tool()
def press_key(key: str) -> str:
    """Press a keyboard key (e.g. 'enter', 'tab', 'escape', 'ctrl+a').

    Args:
        key: Key name or hotkey combo like 'ctrl+a'.

    Returns:
        Confirmation string.
    """
    if "+" in key:
        parts = key.split("+")
        pg.hotkey(*parts)
    else:
        pg.press(key)
    return f"Pressed {key}"



@mcp.tool()
def focus_window(title_contains: str) -> str:
    """Bring a window to the foreground by partial title match.

    Args:
        title_contains: Substring to match against window titles.

    Returns:
        Confirmation or error string.
    """
    try:
        import win32con
        import win32gui

        found_hwnd = None

        def _enum(hwnd, _):
            nonlocal found_hwnd
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if title_contains.lower() in t.lower():
                    found_hwnd = hwnd

        win32gui.EnumWindows(_enum, None)
        if found_hwnd:
            win32gui.ShowWindow(found_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(found_hwnd)
            time.sleep(0.2)
            return f"Focused window: {win32gui.GetWindowText(found_hwnd)}"
        return f"No window matching '{title_contains}'"
    except ImportError:
        return "win32gui not available"



@mcp.tool()
def sleep(seconds: float) -> str:
    """Wait for a number of seconds.

    Args:
        seconds: How long to wait.
    """
    time.sleep(seconds)
    return f"Waited {seconds}s"


if __name__ == "__main__":
    mcp.run(transport="stdio")
