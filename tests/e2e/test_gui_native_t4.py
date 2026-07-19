"""T4 acceptance test using real keyboard/mouse input, without UI Automation.

This is the VM fallback for environments where Windows UIA/pywinauto cannot
initialise in the interactive scheduled-task session. It still launches the
actual Trinity Pilot window and sends input to that window; it does not call
workers, MCP tools, or application internals directly.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[2]
PYTHON = str(APP_DIR / ".venv" / "Scripts" / "python.exe")
DESKTOP = Path.home() / "Desktop"
SCREENSHOTS = Path.home() / ".ai" / "screenshots" / "e2e"


def _find_window(timeout: float = 90.0):
    import win32gui

    found: list[int] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found.clear()
        win32gui.EnumWindows(
            lambda hwnd, _: found.append(hwnd)
            if win32gui.IsWindowVisible(hwnd)
            and "Trinity Pilot" in win32gui.GetWindowText(hwnd)
            else None,
            None,
        )
        if found:
            return found[0]
        time.sleep(0.5)
    raise AssertionError("Trinity Pilot window did not appear")


@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T4_desktop_notepad_multiply_native() -> None:
    """Plan/confirm T4 through the real GUI and verify its desktop artifact."""
    if sys.platform != "win32":
        pytest.skip("requires Windows desktop")

    artifact = DESKTOP / "tp_note_t4.txt"
    artifact.unlink(missing_ok=True)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        "TRINITY_TRACE": "1",
        "QT_QPA_PLATFORM": "windows:fontengine=freetype,dpiawareness=0",
        "QT_ENABLE_HIGHDPI_SCALING": "0",
        "QT_OPENGL": "software",
        "QSG_RHI_BACKEND": "software",
    }
    bootstrap = Path(tempfile.mktemp(suffix="_tp_native_bootstrap.py"))
    bootstrap.write_text(
        "\n".join([
            "import os, signal, sys",
            "from pathlib import Path",
            f"APP_DIR = Path(r'{APP_DIR}')",
            "sys.path.insert(0, str(APP_DIR.parent))",
            "from dotenv import load_dotenv",
            "load_dotenv(APP_DIR / '.env', override=True)",
            "from trinity_pilot.config import Settings",
            "from trinity_pilot.ui.bridge import WorkflowBridge",
            "from PySide6.QtWidgets import QApplication",
            "from trinity_pilot.ui.app import MainWindow",
            "from trinity_pilot.ui.theme import apply_app_qss",
            "app = QApplication(sys.argv)",
            "signal.signal(signal.SIGINT, signal.SIG_DFL)",
            "settings = Settings.from_env()",
            "bridge = WorkflowBridge(settings=settings, db_path=settings.db_path)",
            "window = MainWindow(debug_mode=settings.debug_mode)",
            "window.set_bridge(bridge)",
            "window.set_settings(settings)",
            "window.log('[SYSTEM] Local orchestrator ready.')",
            "apply_app_qss(app, dark=False)",
            "window.show()",
            "window.raise_()",
            "window.activateWindow()",
            "sys.exit(app.exec())",
            "",
        ]),
        encoding="utf-8",
    )
    proc = subprocess.Popen([PYTHON, str(bootstrap)], cwd=APP_DIR, env=env)
    try:
        # Import only after the real app process exists.  Importing pyautogui
        # during pytest collection hangs in this VM's interactive task.
        import pyautogui

        pyautogui.FAILSAFE = False
        hwnd = _find_window()
        import win32gui

        win32gui.ShowWindow(hwnd, 9)
        win32gui.SetForegroundWindow(hwnd)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        # The app's QLineEdit occupies the fixed 56px input bar at the bottom.
        input_xy = ((left + right) // 2, bottom - 35)
        prompt = (
            "Calculate 12 * 12 (answer is 144). Create the file "
            r"C:\Users\trinity\Desktop\tp_note_t4.txt containing 144, "
            "open it in Notepad, then report 144 in chat."
        )
        pyautogui.click(*input_xy)
        pyautogui.write(prompt, interval=0.002)
        pyautogui.press("enter")

        # The same input accepts confirmation once the visible confirm card is shown.
        time.sleep(35)
        pyautogui.click(*input_xy)
        pyautogui.write("yes")
        pyautogui.press("enter")

        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and not artifact.exists():
            time.sleep(2)
        pyautogui.screenshot(str(SCREENSHOTS / "T4_native_complete.png"))
        assert artifact.exists(), "Trinity Pilot did not create tp_note_t4.txt"
        assert "144" in artifact.read_text(encoding="utf-8", errors="replace")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        bootstrap.unlink(missing_ok=True)
