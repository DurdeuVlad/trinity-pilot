"""T4 acceptance test using real keyboard/mouse input, without UI Automation.

VM fallback for environments where pywinauto import hangs in the interactive
scheduled-task session (see tp_gui_startup.marker stopping before
pywinauto-imported). Launches Trinity Pilot via the same bootstrap as AppDriver.
"""
from __future__ import annotations

import json
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
TEMP_INFRA = APP_DIR / "temp_infra.json"
WINDOW_WAIT_S = 600.0


def _agent_debug_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    payload = {
        "sessionId": "6aae95",
        "runId": "post-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        log_path = Path.home() / ".ai" / "debug-6aae95.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        pass
    # #endregion


def _bootstrap_script() -> str:
    return "\n".join([
        "import faulthandler",
        "import os",
        "import sys",
        "import signal",
        "import traceback",
        "from pathlib import Path",
        "faulthandler.enable()",
        "def _log(msg):",
        "    print(f'[bootstrap] {msg}', flush=True)",
        "_log('start')",
        "try:",
        "    os.environ.setdefault('TRINITY_TRACE', '1')",
        f"    APP_DIR = Path(r'{APP_DIR}')",
        "    sys.path.insert(0, str(APP_DIR.parent))",
        "    _log('pythonpath ready')",
        "    from dotenv import load_dotenv",
        "    load_dotenv(APP_DIR / '.env', override=True)",
        "    _log('dotenv loaded')",
        "    from trinity_pilot.config import Settings",
        "    from trinity_pilot.ui.bridge import WorkflowBridge",
        "    from PySide6.QtWidgets import QApplication",
        "    from trinity_pilot.ui.app import MainWindow",
        "    from trinity_pilot.ui.theme import apply_app_qss",
        "    _log('imports done')",
        "    app = QApplication(sys.argv)",
        "    _log('qapplication created')",
        "    signal.signal(signal.SIGINT, signal.SIG_DFL)",
        "    settings = Settings.from_env()",
        "    bridge = WorkflowBridge(settings=settings, db_path=settings.db_path)",
        "    window = MainWindow(debug_mode=settings.debug_mode)",
        "    window.set_bridge(bridge)",
        "    window.set_settings(settings)",
        "    window.log('[SYSTEM] Local orchestrator ready.')",
        "    apply_app_qss(app, dark=False)",
        "    _log('stylesheet applied')",
        "    window.show()",
        "    _log('window.show called')",
        "    app.processEvents()",
        "    window.raise_()",
        "    window.activateWindow()",
        "    app.processEvents()",
        "    _log('window activated')",
        "    _log('entering app.exec')",
        "    sys.exit(app.exec())",
        "except Exception:",
        "    _log('bootstrap exception')",
        "    traceback.print_exc()",
        "    raise",
        "",
    ])


def _read_startup_log(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _find_window(proc: subprocess.Popen, stderr_path: Path | None, timeout: float = WINDOW_WAIT_S) -> int:
    import win32gui

    found: list[int] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            log = _read_startup_log(stderr_path)
            raise AssertionError(
                f"Trinity Pilot bootstrap exited early (code {rc}). Startup log:\n{log[-4000:]}"
            )
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
    log = _read_startup_log(stderr_path)
    raise AssertionError(
        f"Trinity Pilot window did not appear within {timeout:.0f}s. "
        f"proc_alive={proc.poll() is None}. Startup log:\n{log[-4000:]}"
    )


def _write_infra(checkpoints: dict) -> None:
    try:
        TEMP_INFRA.write_text(json.dumps(checkpoints), encoding="utf-8")
    except Exception:
        pass


@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_T4_desktop_notepad_multiply_native() -> None:
    """Plan/confirm T4 through the real GUI and verify its desktop artifact."""
    if sys.platform != "win32":
        pytest.skip("requires Windows desktop")

    infra = {
        "app_launched": False,
        "window_connected": False,
        "prompt_submitted": False,
        "execution_started": False,
        "no_app_crash": True,
        "graceful_close": False,
    }
    artifact = DESKTOP / "tp_note_t4.txt"
    artifact.unlink(missing_ok=True)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        "TRINITY_TRACE": "1",
        "PYTHONUNBUFFERED": "1",
        "QT_QPA_PLATFORM": "windows:fontengine=freetype,dpiawareness=0",
        "QT_ENABLE_HIGHDPI_SCALING": "0",
        "QT_SCALE_FACTOR": "1",
        "QT_OPENGL": "software",
        "QSG_RHI_BACKEND": "software",
    }
    bootstrap = Path(tempfile.mktemp(suffix="_tp_native_bootstrap.py"))
    stderr_path = Path(tempfile.mktemp(suffix="_tp_native_stderr.log"))
    bootstrap.write_text(_bootstrap_script(), encoding="utf-8")
    stderr_fh = open(stderr_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [PYTHON, str(bootstrap)],
        cwd=APP_DIR,
        env=env,
        stdout=stderr_fh,
        stderr=stderr_fh,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    # #region agent log
    _agent_debug_log(
        "test_gui_native_t4.py:launch",
        "bootstrap_started",
        {"pid": proc.pid, "stderr_path": str(stderr_path)},
        hypothesis_id="D",
    )
    # #endregion
    try:
        import pyautogui

        pyautogui.FAILSAFE = False
        hwnd = _find_window(proc, stderr_path)
        infra["app_launched"] = True
        infra["window_connected"] = True
        # #region agent log
        _agent_debug_log(
            "test_gui_native_t4.py:window",
            "window_found",
            {"hwnd": hwnd, "elapsed_probe": True},
            hypothesis_id="D",
        )
        # #endregion
        import win32gui

        win32gui.ShowWindow(hwnd, 9)
        win32gui.SetForegroundWindow(hwnd)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        input_xy = ((left + right) // 2, bottom - 35)
        prompt = (
            "Calculate 12 * 12 (answer is 144). Create the file "
            r"C:\Users\trinity\Desktop\tp_note_t4.txt containing 144, "
            "open it in Notepad, then report 144 in chat."
        )
        pyautogui.click(*input_xy)
        pyautogui.write(prompt, interval=0.002)
        pyautogui.press("enter")
        infra["prompt_submitted"] = True

        time.sleep(35)
        pyautogui.click(*input_xy)
        pyautogui.write("yes")
        pyautogui.press("enter")
        infra["execution_started"] = True

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and not artifact.exists():
            time.sleep(2)
        pyautogui.screenshot(str(SCREENSHOTS / "T4_native_complete.png"))
        assert artifact.exists(), "Trinity Pilot did not create tp_note_t4.txt"
        assert "144" in artifact.read_text(encoding="utf-8", errors="replace")
    except Exception:
        infra["no_app_crash"] = False
        raise
    finally:
        try:
            stderr_fh.flush()
            stderr_fh.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=8)
            infra["graceful_close"] = True
        except subprocess.TimeoutExpired:
            proc.kill()
        bootstrap.unlink(missing_ok=True)
        try:
            stderr_path.unlink(missing_ok=True)
        except Exception:
            pass
        _write_infra(infra)
