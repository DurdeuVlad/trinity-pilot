"""Shared Sensor MCP — read-only cross-cutting observations for all agents.

All tools in this server are SENSORS: they read, inspect, measure, and detect.
None of them change world state. Safe to call from any agent (worker, reviewer,
orchestrator) and safe to retry or parallelize.

Run: python -m trinity_pilot.mcp.sensor_server

Tools
-----
screenshot       — capture current desktop as PNG
find_window      — find a window by title pattern, return position + element tree
locate_on_screen — find a template image on screen, return center coords
window_list      — enumerate all open windows with titles, PIDs, rects
process_list     — enumerate running processes with names and PIDs
clipboard_read   — read current clipboard text
file_stat        — check file/directory existence, size, and mtime (no content)
"""
from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP(
    name="trinity-pilot-sensor",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("health://sensor")
def health() -> str:
    return "ok"


@mcp.resource("version://sensor")
def version() -> str:
    return "0.1.0"


# ---------------------------------------------------------------------------
# Sensor tools
# ---------------------------------------------------------------------------

@mcp.tool()
def screenshot(region: dict | None = None) -> dict:
    """Capture a screenshot of the desktop or a sub-region.

    Supports multi-monitor setups including negative X coordinates (left monitors)
    and coordinates beyond the primary monitor width.

    Args:
        region: Optional dict with keys x, y, width, height for a sub-region.
                Uses virtual desktop coordinates (can be negative for left monitors,
                or > primary_width for right monitors).

    Returns:
        dict with image_b64 (PNG base64), width, height.
    """
    from PIL import ImageGrab

    if region:
        x, y, w, h = region["x"], region["y"], region["width"], region["height"]
        # all_screens=True captures from the full virtual desktop across all monitors
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    else:
        img = ImageGrab.grab(all_screens=True)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {
        "image_b64": base64.b64encode(buf.getvalue()).decode(),
        "width": img.width,
        "height": img.height,
    }


@mcp.tool()
def find_window(title_pattern: str) -> dict:
    """Find a window by partial title match and return its position, size, and element tree.

    Args:
        title_pattern: Substring to match against window titles (case-insensitive).

    Returns:
        dict with found, title, x, y, width, height, and optionally element_tree.
    """
    try:
        import win32gui

        results = []

        def _enum(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if title_pattern.lower() in t.lower():
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
        if not results:
            return {"found": False, "error": f"No window matching '{title_pattern}'"}

        best = results[0]
        result: dict = {"found": True, **best}

        # Best-effort UIA element tree snapshot
        try:
            from pywinauto import Application
            app = Application(backend="uia").connect(handle=best["hwnd"], timeout=3)
            wrapper = app.top_window()
            result["element_tree"] = str(wrapper.print_control_identifiers())
        except Exception:
            pass

        return result

    except ImportError:
        return {"found": False, "error": "win32gui not available"}


@mcp.tool()
def locate_on_screen(image_b64: str, confidence: float = 0.8) -> dict:
    """Locate a template image on screen and return its center coordinates.

    Args:
        image_b64: Base64-encoded PNG of the image to find.
        confidence: Match confidence threshold (0.0–1.0).

    Returns:
        dict with found, x, y (center coords) or error.
    """
    import tempfile
    import pyautogui as pg

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
def window_list() -> dict:
    """Enumerate all visible top-level windows.

    Returns:
        dict with windows: list of {title, pid, x, y, width, height, z_order}.
    """
    windows = []
    try:
        import ctypes
        import ctypes.wintypes

        z = 0

        def _callback(hwnd: int, _: int) -> bool:
            nonlocal z
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()
                    if title:
                        rect = ctypes.wintypes.RECT()
                        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        pid = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        windows.append({
                            "title": title,
                            "pid": pid.value,
                            "x": rect.left,
                            "y": rect.top,
                            "width": rect.right - rect.left,
                            "height": rect.bottom - rect.top,
                            "z_order": z,
                        })
                        z += 1
            return True

        _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    except Exception as exc:
        return {"windows": [], "error": str(exc)}

    return {"windows": windows}


@mcp.tool()
def process_list() -> dict:
    """Enumerate running processes.

    Returns:
        dict with processes: list of {name, pid, status}.
    """
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "status"]):
            try:
                procs.append({
                    "name": p.info["name"],
                    "pid": p.info["pid"],
                    "status": p.info["status"],
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"processes": procs}
    except ImportError:
        # Fallback: tasklist on Windows
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            procs = []
            for line in result.stdout.strip().splitlines():
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    procs.append({"name": parts[0], "pid": int(parts[1]) if parts[1].isdigit() else 0})
            return {"processes": procs}
        except Exception as exc:
            return {"processes": [], "error": str(exc)}


@mcp.tool()
def clipboard_read() -> dict:
    """Read the current clipboard text content.

    Returns:
        dict with text (clipboard content) or error.
    """
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5,
        )
        text = result.stdout.strip()
        return {"text": text, "empty": not bool(text)}
    except Exception as exc:
        return {"text": "", "empty": True, "error": str(exc)}


@mcp.tool()
def file_stat(path: str) -> dict:
    """Check file or directory metadata without reading content.

    Args:
        path: Absolute path to check.

    Returns:
        dict with exists, is_file, is_dir, size_bytes, mtime_iso, error.
    """
    p = Path(path)
    if not p.exists():
        return {"exists": False, "path": path}
    try:
        stat = p.stat()
        return {
            "exists": True,
            "path": str(p),
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "size_bytes": stat.st_size,
            "mtime_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        }
    except Exception as exc:
        return {"exists": True, "path": path, "error": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
