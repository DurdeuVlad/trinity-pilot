"""Desktop automation MCP server — screenshot, click, type, find window.

Provides Copilot with tools to drive the Trinity Pilot UI for automated testing.

Run: python -m trinity_pilot.mcp.desktop_automation_server
"""
from __future__ import annotations

import base64
import io
import subprocess
import sys
import time

import pyautogui
import pyautogui as pg
from fastmcp import FastMCP

mcp = FastMCP("desktop-automation")

# Fail-safe: move mouse to corner to abort
pg.FAILSAFE = True
pg.PAUSE = 0.05


@mcp.tool()
def take_screenshot(region: dict | None = None) -> dict:
    """Take a screenshot of the desktop or a region.

    Args:
        region: Optional dict with keys x, y, width, height to capture a sub-region.

    Returns:
        dict with 'image_b64' (PNG base64) and 'width', 'height'.
    """
    if region:
        img = pg.screenshot(region=(region["x"], region["y"], region["width"], region["height"]))
    else:
        img = pg.screenshot()

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {
        "image_b64": base64.b64encode(buf.getvalue()).decode(),
        "width": img.width,
        "height": img.height,
    }


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
def find_window(title_contains: str) -> dict:
    """Find a window by partial title match and return its position/size.

    Args:
        title_contains: Substring to match against window titles.

    Returns:
        dict with 'found', 'title', 'x', 'y', 'width', 'height', or error message.
    """
    try:
        import win32gui

        results = []

        def _enum(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if title_contains.lower() in t.lower():
                    rect = win32gui.GetWindowRect(hwnd)
                    results.append({
                        "hwnd": hwnd,
                        "title": t,
                        "x": rect[0],
                        "y": rect[1],
                        "width": rect[2] - rect[0],
                        "height": rect[3] - rect[1],
                    })

        win32gui.EnumWindows(_enum, None)
        if results:
            return {"found": True, **results[0]}
        return {"found": False, "error": f"No window matching '{title_contains}'"}
    except ImportError:
        return {"found": False, "error": "win32gui not available"}


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
def locate_on_screen(image_b64: str, confidence: float = 0.8) -> dict:
    """Locate an image on screen and return its center coordinates.

    Args:
        image_b64: Base64-encoded PNG of the image to find.
        confidence: Match confidence threshold (0.0–1.0).

    Returns:
        dict with 'found', 'x', 'y' (center) or error.
    """
    import tempfile
    import os

    data = base64.b64decode(image_b64)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        loc = pg.locateOnScreen(tmp, confidence=confidence)
        if loc:
            center = pg.center(loc)
            return {"found": True, "x": center.x, "y": center.y}
        return {"found": False}
    except Exception as exc:
        return {"found": False, "error": str(exc)}
    finally:
        os.unlink(tmp)


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
