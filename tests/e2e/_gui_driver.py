"""AppDriver — pywinauto-based GUI driver for Trinity Pilot E2E tests.

Layer-3 driver: controls the actual Qt app via Windows UI Automation.
All status polling uses wait_for() — no wall-clock sleep except the
unavoidable 12s Qt startup window.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pyautogui

pyautogui.FAILSAFE = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parents[2]          # trinity-pilot/
VENV_PY = str(APP_DIR / ".venv" / "Scripts" / "python.exe")
PYTHON = VENV_PY if Path(VENV_PY).exists() else sys.executable
SCREENSHOTS_DIR = APP_DIR.parent.parent / ".ai" / "screenshots" / "e2e"
DESKTOP = Path(os.path.expanduser("~")) / "Desktop"

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_READY   = "Ready"
STATUS_CLARIF  = "Awaiting clarification"
STATUS_CONFIRM = "Awaiting confirmation"
STATUS_FAILED  = "Planning failed"
STATUS_DONE    = "Done"
STATUS_ERROR   = "Error"

# Polling target sets used across tests
AFTER_SUBMIT  = {STATUS_CLARIF, STATUS_CONFIRM, STATUS_FAILED, STATUS_ERROR}
AFTER_CONFIRM = {STATUS_DONE, "Finished:", STATUS_ERROR, STATUS_FAILED, STATUS_READY}

_KNOWN = {
    STATUS_READY, STATUS_DONE, STATUS_CLARIF, STATUS_CONFIRM,
    STATUS_FAILED, STATUS_ERROR,
    "Planning...", "Planning…",
    "Thinking...", "Thinking…",
    "Executing...", "Executing…",
}

# Words that indicate an error/failure message is visible in the UI
ERROR_WORDS = {
    "error", "fail", "not found", "cannot", "could not",
    "does not exist", "unable", "missing", "invalid", "refused",
}


# ---------------------------------------------------------------------------
# AppDriver
# ---------------------------------------------------------------------------

class AppDriver:
    """Drives the Trinity Pilot Qt GUI via pywinauto for E2E tests.

    Usage:
        driver = AppDriver.launch()   # starts app, waits for Ready
        driver.submit("create foo.txt on Desktop with 'hello'")
        plan_s = driver.wait_for(AFTER_SUBMIT, timeout=50)
        driver.submit("yes")
        done_s = driver.wait_for(AFTER_CONFIRM, timeout=90)
        driver.snap("test_name")
        driver.close()
    """

    def __init__(self, proc: subprocess.Popen, win: Any) -> None:
        self._proc = proc
        self._win = win

    # ------------------------------------------------------------------
    # Launch / teardown
    # ------------------------------------------------------------------

    @classmethod
    def launch(cls) -> "AppDriver":
        """Start a fresh Trinity Pilot instance and wait for Ready."""
        from dotenv import load_dotenv
        load_dotenv(APP_DIR / ".env", override=True)

        # Initialize COM in STA mode before any UIA/pywinauto calls.
        # Without this, pytest's thread context can cause RPC_E_WRONG_THREAD (0x8001010d).
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass

        # Kill any stale Trinity Pilot windows left by previous tests.
        # Use win32gui to enumerate exactly which PIDs own "Trinity Pilot" windows.
        try:
            import win32gui
            import win32process

            def _find_tp_pids(h, pids):
                if win32gui.IsWindowVisible(h) and "Trinity Pilot" in win32gui.GetWindowText(h):
                    _, pid = win32process.GetWindowThreadProcessId(h)
                    pids.add(pid)

            stale_pids: set = set()
            win32gui.EnumWindows(_find_tp_pids, stale_pids)
            for pid in stale_pids:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
        except Exception:
            pass
        time.sleep(2)  # let Windows reclaim the window handles

        proc = subprocess.Popen(
            [PYTHON, "-m", "trinity_pilot"],
            cwd=str(APP_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(12)  # Qt startup

        from pywinauto import Application
        from pywinauto.findwindows import ElementAmbiguousError, ElementNotFoundError

        hwnd: int | None = None
        deadline2 = time.monotonic() + 25
        while time.monotonic() < deadline2:
            try:
                app = Application(backend="uia").connect(
                    title_re="Trinity Pilot",
                    visible_only=True,
                    timeout=1,
                )
                hwnd = app.top_window().handle
                break
            except ElementAmbiguousError as exc:
                # Qt exposes a virtual root element alongside the real window.
                # Pick the element that has a real HWND (handle != 0) and is a Window.
                for el in exc.elements:
                    if getattr(el, "handle", None):
                        hwnd = el.handle
                        break
                if hwnd:
                    app = Application(backend="uia").connect(handle=hwnd)
                    break
            except ElementNotFoundError:
                time.sleep(0.5)
            except Exception as exc:
                proc.terminate()
                raise RuntimeError(
                    f"Trinity Pilot window not found after startup: {exc}"
                ) from exc

        if not hwnd:
            proc.terminate()
            raise RuntimeError("Trinity Pilot window not found within 25s")

        win = app.window(handle=hwnd)
        got = cls._wait_static(win, {STATUS_READY}, timeout=15)
        if got != STATUS_READY:
            proc.terminate()
            raise RuntimeError(
                f"App did not reach Ready within 15s; last status={got!r}"
            )
        return cls(proc, win)

    def close(self) -> None:
        """Kill the Trinity Pilot process tree."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                capture_output=True, timeout=8,
            )
        except Exception:
            pass
        try:
            self._proc.wait(timeout=5)
        except Exception:
            pass
        time.sleep(3)  # let Windows fully reclaim the process/window before the next test

    # ------------------------------------------------------------------
    # Status reading
    # ------------------------------------------------------------------

    @staticmethod
    def _read_status(win: Any) -> str:
        try:
            for c in win.descendants(control_type="Text"):
                t = c.window_text().strip()
                if t in _KNOWN or t.startswith("Finished:") or t.startswith("Status:"):
                    return t
        except Exception:
            pass
        return ""

    @staticmethod
    def _wait_static(win: Any, targets: set[str], timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            s = AppDriver._read_status(win)
            if any(s == t or s.startswith(t) for t in targets):
                return s
            time.sleep(0.5)
        return AppDriver._read_status(win)

    def status(self) -> str:
        return self._read_status(self._win)

    def wait_for(self, targets: set[str], timeout: float = 60.0) -> str:
        """Poll status label until a target matches or timeout. Returns matched value."""
        return self._wait_static(self._win, targets, timeout)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def submit(self, text: str) -> None:
        """Click input box, type text, press Enter."""
        try:
            edits = self._win.descendants(control_type="Edit")
            if edits:
                edits[0].click_input()
        except Exception:
            pass
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.write(text, interval=0.02)
        time.sleep(0.2)
        pyautogui.press("enter")

    # ------------------------------------------------------------------
    # Output reading
    # ------------------------------------------------------------------

    def chat_lines(self) -> list[str]:
        """Read chat bubble text (Document controls)."""
        try:
            return [
                c.window_text().strip()
                for c in self._win.descendants(control_type="Document")
                if c.window_text().strip()
            ]
        except Exception:
            return []

    def all_text(self) -> list[str]:
        """All visible Text widget values (status, labels, chat, etc.)."""
        try:
            return [
                c.window_text().strip()
                for c in self._win.descendants(control_type="Text")
                if c.window_text().strip()
            ]
        except Exception:
            return []

    def ui_text(self) -> str:
        """Joined + lowercased text from all chat bubbles and Text widgets."""
        return " ".join(self.chat_lines() + self.all_text()).lower()

    def has_error_message(self) -> bool:
        """True if any error/failure word appears anywhere in the visible UI."""
        joined = self.ui_text()
        return any(w in joined for w in ERROR_WORDS)

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------

    def snap(self, name: str) -> None:
        """Save a full-screen screenshot to .ai/screenshots/e2e/."""
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(str(SCREENSHOTS_DIR / f"{name}.png"))
        except Exception:
            pass
