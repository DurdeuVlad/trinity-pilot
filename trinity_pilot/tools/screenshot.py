"""Shared screenshot capture utility for Trinity Pilot workers.

Modes
-----
screen      — capture one monitor by index (0 = primary).
all_screens — capture all monitors stitched into a single image.
app         — capture a specific window by title regex.

Returns (jpeg_bytes: bytes, description: str).

No imports from trinity_pilot.* — zero circular-dependency risk.
"""
from __future__ import annotations

import io
import time


def _get_monitor_bbox(screen_index: int) -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) for the given monitor index via Win32 API."""
    try:
        import win32api
        monitors = win32api.EnumDisplayMonitors()
        if screen_index < len(monitors):
            return monitors[screen_index][2]
        return monitors[0][2]
    except Exception:
        return None


def capture_screenshot(
    mode: str = "screen",
    screen_index: int = 0,
    app_title: str = "",
) -> tuple[bytes, str]:
    """Capture a screenshot and return (jpeg_bytes, description).

    Parameters
    ----------
    mode:
        ``"screen"``      — one monitor by index (default primary).
        ``"all_screens"`` — all monitors combined into one image.
        ``"app"``         — specific window matched by title regex.
    screen_index:
        Monitor index (0 = primary). Used only when mode="screen".
    app_title:
        Window title regex. Used only when mode="app".
    """
    from PIL import Image  # noqa: F401 — ensure Pillow is importable

    img = None
    desc = ""

    if mode == "app" and app_title:
        img, desc = _capture_app_window(app_title)

    if img is None and mode == "all_screens":
        img, desc = _capture_all_screens()

    if img is None and mode == "screen":
        img, desc = _capture_screen(screen_index)

    if img is None:
        img, desc = _capture_screen(0)

    assert img is not None
    img.thumbnail((1280, 720))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=60)
    return buf.getvalue(), desc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _capture_screen(screen_index: int) -> tuple[object, str]:
    """Capture a single monitor by index."""
    if screen_index == 0:
        try:
            from PIL import ImageGrab
            return ImageGrab.grab(), "primary screen"
        except Exception:
            return None, ""

    bbox = _get_monitor_bbox(screen_index)
    if bbox is not None:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
            return img, f"screen index={screen_index}"
        except Exception:
            pass

    try:
        from PIL import ImageGrab
        return ImageGrab.grab(), f"primary screen (monitor {screen_index} not found)"
    except Exception:
        return None, ""


def _capture_all_screens() -> tuple[object, str]:
    """Capture all monitors as one virtual desktop image."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
        return img, "all screens"
    except Exception:
        return None, ""


def _capture_app_window(app_title: str) -> tuple[object, str]:
    """Focus and capture a specific window by title regex."""
    try:
        import ctypes
        from pywinauto import findwindows
        wins = findwindows.find_windows(title_re=app_title)
        if not wins:
            return None, ""
        hwnd = wins[0]
        ctypes.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        try:
            from pywinauto import Application
            app = Application(backend="uia").connect(handle=hwnd)
            win = app.top_window()
            img = win.capture_as_image()
            return img, f"window={app_title!r}"
        except Exception:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True)
            return img, f"full screen (app={app_title!r} focus fallback)"
    except Exception:
        return None, ""
