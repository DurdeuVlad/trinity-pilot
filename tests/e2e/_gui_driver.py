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
SCREENSHOTS_DIR = Path(os.path.expanduser("~")) / ".ai" / "screenshots" / "e2e"
DESKTOP = Path(os.path.expanduser("~")) / "Desktop"

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_READY        = "Ready"
STATUS_CLARIF       = "Awaiting clarification"
STATUS_CONFIRM      = "Awaiting confirmation"
STATUS_FAILED       = "Planning failed"
STATUS_TASK_FAILED  = "Failed"   # pipeline ran but task could not be completed
STATUS_DONE         = "Done"
STATUS_ERROR        = "Error"    # framework/infrastructure exception only

# Polling target sets used across tests
AFTER_SUBMIT  = {STATUS_CLARIF, STATUS_CONFIRM, STATUS_FAILED, STATUS_ERROR}
AFTER_CONFIRM = {STATUS_DONE, "Finished:", STATUS_ERROR, STATUS_FAILED,
                 STATUS_TASK_FAILED, STATUS_READY}

_KNOWN = {
    STATUS_READY, STATUS_DONE, STATUS_CLARIF, STATUS_CONFIRM,
    STATUS_FAILED, STATUS_TASK_FAILED, STATUS_ERROR,
    "Crashed", "Cancelled",
    "Planning...", "Planning…",
    "Thinking...", "Thinking…",
    "Executing...", "Executing…",
}

# Words that indicate an error/failure message is visible in the UI
ERROR_WORDS = {
    "error", "fail", "not found", "cannot", "could not",
    "does not exist", "unable", "missing", "invalid", "refused",
}


class TrinityPilotCrashedError(RuntimeError):
    """Trinity Pilot process exited unexpectedly during a test (infra failure, not task failure)."""


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

    def __init__(
        self,
        proc: subprocess.Popen,
        win: Any,
        hwnd: int = 0,
        db_path: Path | None = None,
    ) -> None:
        self._proc = proc
        self._win = win
        self._hwnd = hwnd
        self._db_path = db_path  # temp DB — cleaned up in close()

    # ------------------------------------------------------------------
    # Launch / teardown
    # ------------------------------------------------------------------

    @classmethod
    def launch(cls, mode: str | None = None) -> "AppDriver":
        """Start a fresh Trinity Pilot instance and wait for Ready.

        mode: None or "multi" for normal multi-agent mode; "single_agent" for ablation.
        """
        from dotenv import load_dotenv
        load_dotenv(APP_DIR / ".env", override=True)

        # Initialize COM in STA mode before any UIA/pywinauto calls.
        # Without this, pytest's thread context can cause RPC_E_WRONG_THREAD (0x8001010d).
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass

        # Warm up the UIAutomation COM server.  On a freshly-restored VM snapshot
        # UIAutomation may not be initialised in Session 1 yet; a failed connect()
        # call is enough to force initialisation so the real launch succeeds.
        try:
            from pywinauto import Application as _PwApp
            from pywinauto.findwindows import ElementNotFoundError as _ENFE
            _PwApp(backend="uia").connect(
                title_re="__tp_uia_warmup_XXXX__", timeout=1
            )
        except Exception:
            pass  # always fails — that's fine, COM/UIA is now initialised

        # Kill any stale Trinity Pilot processes left by previous tests.
        # Step 1: kill by window title (visible windows).
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
        # Step 2: kill any python.exe process with "trinity_pilot" in cmdline
        # (catches windowless or minimised instances that step 1 misses).
        try:
            subprocess.run(
                [
                    "powershell", "-NonInteractive", "-Command",
                    "Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*trinity_pilot*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
                ],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass
        # Kill all desktop apps that could linger from previous tests.
        # Calculator.exe covers Win11 new app; CalculatorApp.exe covers UWP legacy.
        # Keep cmd.exe / python.exe / powershell.exe (test runner infrastructure).
        _STALE_APPS = [
            "CalculatorApp.exe", "Calculator.exe",
            "mspaint.exe", "notepad.exe", "notepad++.exe",
            "chrome.exe", "chromium.exe", "msedge.exe",
        ]
        for _exe in _STALE_APPS:
            try:
                subprocess.run(["taskkill", "/F", "/IM", _exe], capture_output=True, timeout=5)
            except Exception:
                pass
        time.sleep(7)  # let Windows reclaim handles and ports

        # Delete Desktop test artifacts from prior test in same session.
        # Prevents "file already exists" overwrite dialogs on repeated test runs.
        _desktop = Path(os.environ.get("USERPROFILE", "C:/Users/trinity")) / "Desktop"
        _ARTIFACT_NAMES = [
            "tp_e2e.txt", "cross_e2e.txt", "disk_report.txt", "date_note.txt",
            "py_procs.txt", "tp_source.txt", "tp_source_copy.txt", "sysinfo.txt",
            "uuid_result.txt", "python_version.txt", "tp_script.py",
            "fr04_readonly.txt", "fr05_crash.txt", "fr06_fallback.txt",
            "fr07_focus_recovery.txt", "fr08_network_result.txt", "fr10_merged_output.txt",
            "rs01_sentinel_large.txt", "rs08_probe.txt", "rs10_recent_marker.txt",
            "retry_test.txt", "crash_test.txt",
            "sc01_result.txt", "sc02_data.txt", "sc03_corrected.txt", "sc03_original.txt",
            "sc05_original.txt", "sc05_variant.txt", "sc06_final.txt",
            "hh01_summary.txt", "hh02_webnote.txt", "hh03_uuid.txt", "hh03_uuid_backup.txt",
            "hh04_numbers.csv", "hh04_metrics.txt", "hh05_process_report.txt",
            "hh06_tree_report.txt", "hh07_time_report.txt", "hh08_python_title.txt",
            "hh08_python_title_copy.txt", "hh09_input.json", "hh09_json_report.txt",
            "hh10_final_report.txt",
        ]
        _ARTIFACT_DIRS = ["tp_test_dir", "hh01", "hh06", "hh10"]
        import shutil as _shutil
        for _name in _ARTIFACT_NAMES:
            try:
                (_desktop / _name).unlink(missing_ok=True)
            except Exception:
                pass
        for _dname in _ARTIFACT_DIRS:
            try:
                _shutil.rmtree(_desktop / _dname, ignore_errors=True)
            except Exception:
                pass

        import tempfile as _tempfile
        _db_path = Path(_tempfile.mktemp(suffix="_trinity_test.db"))
        # DPI env vars: suppress all Qt high-DPI scaling code to avoid
        # SetProcessDpiAwarenessContext(ACCESS_DENIED) C-level abort on PySide6 6.x
        # in long-session scheduled-task contexts.
        # PYTHONUNBUFFERED=1 ensures startup output is flushed before any crash.
        _env = {
            **os.environ,
            "DB_PATH": str(_db_path),
            "QT_QPA_PLATFORM": "windows:dpiawareness=0",
            "QT_ENABLE_HIGHDPI_SCALING": "0",
            "QT_SCALE_FACTOR": "1",
            "PYTHONUNBUFFERED": "1",
        }

        # Retry up to 3 times: transient C-level crashes at Qt startup are rare
        # but observed in long-session scheduled-task contexts.
        _MAX_LAUNCH_ATTEMPTS = 3
        proc = None
        _stderr_path = None
        _stderr_fh = None
        for _attempt in range(1, _MAX_LAUNCH_ATTEMPTS + 1):
            _stderr_path = Path(_tempfile.mktemp(suffix=f"_trinity_stderr_{_attempt}.log"))
            _stderr_fh = open(_stderr_path, "w", encoding="utf-8")
            _cmd = [PYTHON, "-m", "trinity_pilot", "--test-mode"]
            if mode and mode != "multi":
                _cmd += ["--mode", mode]
            proc = subprocess.Popen(
                _cmd,
                cwd=str(APP_DIR),
                stdout=_stderr_fh,
                stderr=_stderr_fh,
                env=_env,
                # Isolate from the parent console so that taskkill on this process
                # does not propagate a CTRL_BREAK/CLOSE event up to eval_multirun.py.
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            for _poll_t in range(10):
                if proc.poll() is not None:
                    break
                time.sleep(1)
            if proc.poll() is None:
                break  # process is alive — proceed to window search
            # Process died immediately — log and retry
            try:
                _stderr_fh.flush(); _stderr_fh.close()
            except Exception:
                pass
            _early_log = ""
            try:
                _early_log = _stderr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
            print(f"[AppDriver] attempt {_attempt}/{_MAX_LAUNCH_ATTEMPTS} exited "
                  f"(code {proc.poll()}): {_early_log[:200]}", flush=True)
            if _attempt < _MAX_LAUNCH_ATTEMPTS:
                # Clean up any UWP/browser children the crashed attempt may have spawned.
                for _exe in ["CalculatorApp.exe", "Calculator.exe", "mspaint.exe",
                             "notepad.exe", "chrome.exe", "chromium.exe", "msedge.exe"]:
                    try:
                        subprocess.run(["taskkill", "/F", "/IM", _exe],
                                       capture_output=True, timeout=5)
                    except Exception:
                        pass
                time.sleep(15)  # give Windows time to release DPI/COM state after crash
        time.sleep(0)  # all sleep already done above

        from pywinauto import Application
        from pywinauto.findwindows import ElementAmbiguousError, ElementNotFoundError
        try:
            from pywinauto.timings import TimeoutError as _PwTimeout
        except ImportError:
            _PwTimeout = type("_PwTimeout", (Exception,), {})  # dummy

        def _cleanup_proc_and_log(proc, fh, path):
            """Terminate proc, close file handle, read log, unlink log file."""
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                # Wait up to 3s for the subprocess to release the log file.
                proc.wait(timeout=3)
            except Exception:
                pass
            try:
                fh.flush()
                fh.close()
            except Exception:
                pass
            log_text = ""
            try:
                log_text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass  # File still locked — not critical
            return log_text

        hwnd: int | None = None
        deadline2 = time.monotonic() + 1200  # 1200s: warm snapshot <30s; cold snapshot up to ~950s (SVGA3D D3D init)
        while time.monotonic() < deadline2:
            # If process died already, no point waiting
            if proc.poll() is not None:
                break
            try:
                # visible_only=True uses Win32 EnumWindows internally, which finds
                # windows across virtual desktops (unlike UIA-only enumeration).
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
            except (ElementNotFoundError, _PwTimeout):
                time.sleep(0.5)
            except Exception as exc:
                startup_log = _cleanup_proc_and_log(proc, _stderr_fh, _stderr_path)
                raise RuntimeError(
                    f"Trinity Pilot window not found after startup: {exc!r}\n"
                    f"Startup log:\n{startup_log}"
                ) from exc

        # Close log file handle (the app subprocess still holds it open).
        try:
            _stderr_fh.flush()
            _stderr_fh.close()
        except Exception:
            pass

        if not hwnd:
            # App didn't appear — terminate, read log, raise.
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                pass
            startup_log = ""
            try:
                startup_log = _stderr_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
            try:
                _stderr_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                rc = proc.poll()
            except Exception:
                rc = None
            raise RuntimeError(
                f"Trinity Pilot window not found within 1200s (exit code: {rc})\n"
                f"Startup log:\n{startup_log}"
            )
        # hwnd found — clean up log file silently (process still running, may fail)
        try:
            _stderr_path.unlink(missing_ok=True)
        except Exception:
            pass

        win = app.window(handle=hwnd)
        got = cls._wait_static(win, {STATUS_READY}, timeout=60)
        if got != STATUS_READY:
            proc.terminate()
            raise RuntimeError(
                f"App did not reach Ready within 30s; last status={got!r}"
            )
        return cls(proc, win, hwnd=hwnd, db_path=_db_path)

    def close(self) -> None:
        """Close Trinity Pilot gracefully via WM_CLOSE, force-kill only as fallback."""
        # Try graceful close first: send WM_CLOSE so Qt can clean up.
        if self._hwnd:
            try:
                import win32gui
                import win32con
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        # Give the process up to 5s to exit on its own.
        try:
            self._proc.wait(timeout=5)
            time.sleep(1)
            return
        except Exception:
            pass
        # Fallback: force-kill the process tree.
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
        # Kill all desktop apps that may linger after the Trinity Pilot process exits.
        for _exe in ["CalculatorApp.exe", "Calculator.exe", "mspaint.exe", "notepad.exe",
                     "chrome.exe", "chromium.exe", "msedge.exe"]:
            try:
                subprocess.run(["taskkill", "/F", "/IM", _exe], capture_output=True, timeout=5)
            except Exception:
                pass
        time.sleep(1)
        # Clean up the temp DB created for this test run.
        if self._db_path:
            for suffix in ("", "-wal", "-shm"):
                try:
                    Path(str(self._db_path) + suffix).unlink(missing_ok=True)
                except Exception:
                    pass

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
        """Poll status label until a target matches or timeout. Returns matched value.

        Raises TrinityPilotCrashedError immediately if the process exits during the wait
        so callers can distinguish infra crashes from genuine task failures.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise TrinityPilotCrashedError(
                    f"Trinity Pilot exited (code={self._proc.poll()}) "
                    f"while waiting for {targets!r}"
                )
            s = AppDriver._read_status(self._win)
            if any(s == t or s.startswith(t) for t in targets):
                return s
            time.sleep(0.5)
        return AppDriver._read_status(self._win)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def submit(self, text: str) -> None:
        """Type text into the input box and submit (or click Approve for confirmation).

        For "yes"/"y"/"ok" when in Awaiting confirmation state, tries to click
        the Approve button first (more reliable than typing into the input box).
        Uses pywinauto type_keys() as primary method, pyautogui as fallback.
        """
        _YES = {"yes", "y", "ok", "okay", "sure", "yep", "run", "go"}

        # If confirming, try to find and click the Approve button first.
        if text.lower().strip() in _YES:
            approve_clicked = False
            try:
                # Focus the window so UIA events land in the right thread.
                try:
                    self._win.set_focus()
                except Exception:
                    pass
                time.sleep(0.2)
                buttons = self._win.descendants(control_type="Button")
                for btn in buttons:
                    label = btn.window_text().strip()
                    if "approve" in label.lower() or label == "✔" or "Approve" in label:
                        # Try invoke() (UIA InvokePattern) first — more reliable
                        # than click_input() for Qt buttons across session boundary.
                        try:
                            btn.invoke()
                            approve_clicked = True
                        except Exception:
                            pass
                        if not approve_clicked:
                            # Fallback: pyautogui click at button screen coordinates.
                            try:
                                rect = btn.rectangle()
                                x = (rect.left + rect.right) // 2
                                y = (rect.top + rect.bottom) // 2
                                pyautogui.click(x, y)
                                approve_clicked = True
                            except Exception:
                                pass
                        if approve_clicked:
                            return
            except Exception:
                pass

        # Primary: type into the Edit control and press Enter.
        try:
            edits = self._win.descendants(control_type="Edit")
            if edits:
                edits[0].click_input()
                time.sleep(0.2)
                # Clear any stale text first (Ctrl+A then Delete)
                edits[0].type_keys("^a{DELETE}", with_spaces=False)
                time.sleep(0.1)
                edits[0].type_keys(
                    text.replace("{", "{{").replace("}", "}}") + "{ENTER}",
                    with_spaces=True,
                )
                return
        except Exception:
            pass
        # Fallback: pyautogui (requires window to be foreground).
        time.sleep(0.2)
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
