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

# A direct file marker keeps VM startup diagnosis available even when pytest's
# output capture has not yet flushed.
try:
    _IMPORT_MARKER = Path.home() / ".ai" / "tp_gui_startup.marker"
    _IMPORT_MARKER.parent.mkdir(parents=True, exist_ok=True)
    with _IMPORT_MARKER.open("a", encoding="utf-8") as _marker:
        _marker.write(f"{time.time():.3f} gui-driver-module-imported\n")
except OSError:
    pass

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


def _pyautogui() -> Any:
    """Load pyautogui only after the UIA driver is ready.

    Importing it while pytest imports this module can block in the VM's
    interactive Scheduled Task session before AppDriver.launch() has a chance
    to establish the required MTA COM context.
    """
    import pyautogui

    pyautogui.FAILSAFE = False
    return pyautogui


class ExistingProcessWrapper:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {self.pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=2
            )
            if str(self.pid) in (r.stdout or ""):
                return None
            return 0
        except Exception:
            return 0

    def wait(self, timeout: float | None = None) -> int:
        t0 = time.monotonic()
        while self.poll() is None:
            if timeout and (time.monotonic() - t0 > timeout):
                raise subprocess.TimeoutExpired(cmd="existing_proc", timeout=timeout)
            time.sleep(0.5)
        return 0

    def terminate(self) -> None:
        subprocess.run(["taskkill", "/F", "/PID", str(self.pid)], capture_output=True, timeout=5)


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
        proc: Any,
        win: Any,
        hwnd: int = 0,
        db_path: Path | None = None,
    ) -> None:
        self._proc = proc
        self._win = win
        self._hwnd = hwnd
        self._db_path = db_path  # temp DB — cleaned up in close()
        self.infra_checkpoints = {
            "app_launched": False,
            "window_connected": False,
            "prompt_submitted": False,
            "execution_started": False,
            "app_crashed": True,
            "graceful_close": False
        }

    # ------------------------------------------------------------------
    # Launch / teardown
    # ------------------------------------------------------------------

    @staticmethod
    def _send_emergency_wake(win: Any, timeout: float, *, source: str) -> str:
        """OS-level wake: send Ctrl+Shift+Q (emergency stop) and wait for STATUS_READY.

        Intentionally UIA-free on the send side — pywinauto.keyboard.send_keys
        uses SendInput, which does not depend on the target window's message
        loop being responsive. Use this BEFORE any UIA probing (set_focus /
        descendants) when the app may be stalled: UIA calls against a stalled
        Qt event loop can block for minutes even though SendInput resolves
        instantly (observed: 434.5s burned probing a frozen window before a
        keyboard shortcut unstuck it in <1s — see 2026-06-29 trace analysis).
        """
        try:
            from tests.e2e._debug_log import dbg
        except Exception:
            dbg = None
        if dbg:
            dbg("_gui_driver.py:_send_emergency_wake", "wake_sent",
                {"source": source}, hypothesis_id="H-wake-fastpath")
        try:
            from pywinauto.keyboard import send_keys
            send_keys("^+q")
        except Exception:
            pass
        status = AppDriver._wait_static(win, {STATUS_READY}, timeout)
        if dbg:
            dbg("_gui_driver.py:_send_emergency_wake", "wake_result",
                {"source": source, "status": status}, hypothesis_id="H-wake-fastpath")
        return status

    @staticmethod
    def _recover_to_ready(win: Any, timeout: float = 45.0) -> str:
        """Best-effort reset when TRINITY_CONNECT_EXISTING left app mid-task.

        Order matters: try the OS-level keyboard wake FIRST. It does not
        depend on the app's Qt event loop being responsive, whereas the UIA
        fallback below (set_focus/descendants) can block for minutes against
        a stalled window.
        """
        fast_timeout = min(timeout, 10.0)
        status = AppDriver._send_emergency_wake(win, fast_timeout, source="recover_to_ready_fast")
        if status == STATUS_READY:
            return status

        # Fallback: UIA-based Stop button + retry wake, for cases where the
        # window was genuinely idle/foreground-stolen rather than stalled.
        try:
            win.set_focus()
        except Exception:
            pass
        try:
            for btn in win.descendants(control_type="Button"):
                label = btn.window_text().strip().lower()
                if "stop" in label:
                    try:
                        btn.invoke()
                    except Exception:
                        try:
                            btn.click_input()
                        except Exception:
                            pass
                    break
        except Exception:
            pass
        remaining = max(timeout - fast_timeout, 1.0)
        return AppDriver._send_emergency_wake(win, remaining, source="recover_to_ready_fallback")

    @classmethod
    def launch(cls, *, _fresh_launch: bool = False) -> "AppDriver":
        """Start a fresh Trinity Pilot instance and wait for Ready.

        Uses the application's sole MCP orchestration mode.
        """
        startup_marker = Path.home() / ".ai" / "tp_gui_startup.marker"

        def mark_startup(stage: str) -> None:
            try:
                startup_marker.parent.mkdir(parents=True, exist_ok=True)
                with startup_marker.open("a", encoding="utf-8") as marker:
                    marker.write(f"{time.time():.3f} {stage}\n")
            except OSError:
                pass

        mark_startup("launch-enter")
        from dotenv import load_dotenv
        load_dotenv(APP_DIR / ".env", override=True)
        mark_startup("dotenv-loaded")

        # pywinauto's UIA backend must be imported from an MTA thread here.
        #
        # Do not replace this with comtypes.CoInitialize() (STA): a direct VM
        # probe proved that it hangs indefinitely while importing pywinauto in
        # the interactive Scheduled Task session.  The same probe reaches UIA
        # successfully with COINIT_MULTITHREADED.  Set pywinauto's documented
        # import-time flag as well as initializing this thread explicitly.
        try:
            sys.coinit_flags = 0  # COINIT_MULTITHREADED; read by pywinauto.
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            mark_startup("com-mta")
        except Exception:
            mark_startup("com-mta-error")
            pass

        # Import pywinauto/UIA before launching Trinity Pilot. In the VM's
        # interactive Session 1, importing pywinauto after the app process is
        # already running can hang indefinitely inside the UIA stack. Importing
        # it first avoids that re-entrant attach path entirely.
        # Import the concrete module, not pywinauto's package-level re-export.
        # The latter hangs in this VM's interactive task while this direct path
        # was verified by the bounded MTA probe.
        from pywinauto.application import Application
        mark_startup("pywinauto-imported")
        from pywinauto.findwindows import ElementAmbiguousError, ElementNotFoundError
        mark_startup("findwindows-imported")
        try:
            from pywinauto.timings import TimeoutError as _PwTimeout
        except ImportError:
            _PwTimeout = type("_PwTimeout", (Exception,), {})  # dummy

        # Warm up the UIAutomation COM server.  On a freshly-restored VM snapshot
        # UIAutomation may not be initialised in Session 1 yet; a failed connect()
        # call is enough to force initialisation so the real launch succeeds.
        # Disabled: this speculative provider call can hang in the VM.
        if False:
            Application(backend="uia").connect(
                title_re="__tp_uia_warmup_XXXX__", timeout=1
            )
        if False:
            pass  # always fails — that's fine, COM/UIA is now initialised

        connect_existing = False
        launch_t0 = time.monotonic()
        try:
            from tests.e2e._debug_log import dbg
        except Exception:
            dbg = None
        if dbg:
            dbg("_gui_driver.py:launch", "launch_start", {
                "connect_existing": connect_existing,
                "fresh_launch": _fresh_launch,
            }, hypothesis_id="H5-launch-slow")
        if not connect_existing:
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
        if not connect_existing:
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
                "tp_note_t4.txt", "tp_note_t11.txt",
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
        _db_path = None if connect_existing else Path(_tempfile.mktemp(suffix="_trinity_test.db"))
        # DPI env vars: suppress all Qt high-DPI scaling code to avoid
        # SetProcessDpiAwarenessContext(ACCESS_DENIED) C-level abort on PySide6 6.x
        # in long-session scheduled-task contexts.
        # PYTHONUNBUFFERED=1 ensures startup output is flushed before any crash.
        _env = {
            **os.environ,
            "TRINITY_TRACE": "1",
            # fontengine=freetype: DirectWrite's COM-based font enumeration has a
            # slow fallback path when there's no GPU-backed adapter (this VM has
            # accelerate3d=off + legacy vboxvga) that runs during QApplication()
            # construction before any window exists. FreeType skips that path.
            "QT_QPA_PLATFORM": "windows:fontengine=freetype,dpiawareness=0",
            "QT_ENABLE_HIGHDPI_SCALING": "0",
            "QT_SCALE_FACTOR": "1",
            "PYTHONUNBUFFERED": "1",
            # Software rendering bypasses VirtualBox SVGA3D D3D cold-start (700-950s block).
            # Without this, first Qt launch after VM boot blocks indefinitely in D3D11CreateDevice.
            "QT_OPENGL": "software",
            "QSG_RHI_BACKEND": "software",
        }
        if _db_path is not None:
            _env["DB_PATH"] = str(_db_path)

        # Retry up to 3 times: transient C-level crashes at Qt startup are rare
        # but observed in long-session scheduled-task contexts.
        _MAX_LAUNCH_ATTEMPTS = 3
        proc = None
        _stderr_path = None
        _stderr_fh = None

        hwnd_found = None
        pid_found = None
        if connect_existing:
            import win32gui
            import win32process
            def _find_tp(h, extra):
                nonlocal hwnd_found, pid_found
                if win32gui.IsWindowVisible(h) and "Trinity Pilot" in win32gui.GetWindowText(h):
                    _, p = win32process.GetWindowThreadProcessId(h)
                    hwnd_found = h
                    pid_found = p
            win32gui.EnumWindows(_find_tp, None)
            if hwnd_found and pid_found:
                proc = ExistingProcessWrapper(pid_found)

        if proc is None:
            for _attempt in range(1, _MAX_LAUNCH_ATTEMPTS + 1):
                _stderr_path = Path(_tempfile.mktemp(suffix=f"_trinity_stderr_{_attempt}.log"))
                _stderr_fh = open(_stderr_path, "w", encoding="utf-8")
                # Bypass `python -m trinity_pilot`: in the VM's Session 1 that
                # entrypoint can keep the process alive without ever surfacing a
                # top-level window. A direct run_app() bootstrap script has proven
                # reliable in the same environment.
                _launcher_path = Path(_tempfile.mktemp(suffix=f"_trinity_bootstrap_{_attempt}.py"))
                _launcher_path.write_text(
                    "\n".join([
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
                        "    _log(f'settings loaded db_path={settings.db_path}')",
                        "    bridge = WorkflowBridge(settings=settings, db_path=settings.db_path)",
                        "    _log('workflow bridge created')",
                        "    window = MainWindow(debug_mode=settings.debug_mode)",
                        "    _log('mainwindow created')",
                        "    window.set_bridge(bridge)",
                        "    window.set_settings(settings)",
                        "    window.log('[SYSTEM] Local orchestrator ready.')",
                        "    apply_app_qss(app, dark=False)",
                        "    _log('stylesheet applied')",
                        "    window.show()",
                        "    _log('window.show called')",
                        "    app.processEvents()",
                        "    _log('processEvents done')",
                        "    try:",
                        "        window.raise_()",
                        "        window.activateWindow()",
                        "        app.processEvents()",
                        "        _log('window activated')",
                        "    except Exception as exc:",
                        "        _log(f'window activation skipped: {exc!r}')",
                        "    _log('entering app.exec')",
                        "    sys.exit(app.exec())",
                        "except Exception:",
                        "    _log('bootstrap exception')",
                        "    traceback.print_exc()",
                        "    raise",
                        "",
                    ]),
                    encoding="utf-8",
                )
                _cmd = [PYTHON, str(_launcher_path)]
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
                    _stderr_fh.flush()
                    _stderr_fh.close()
                except Exception:
                    pass
                _early_log = ""
                try:
                    _early_log = _stderr_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
                print(
                    f"[AppDriver] attempt {_attempt}/{_MAX_LAUNCH_ATTEMPTS} exited "
                    f"(code {proc.poll()}): {_early_log[:200]}",
                    flush=True,
                )
                if _attempt < _MAX_LAUNCH_ATTEMPTS:
                    for _exe in ["CalculatorApp.exe", "Calculator.exe", "mspaint.exe",
                                 "notepad.exe", "chrome.exe", "chromium.exe", "msedge.exe"]:
                        try:
                            subprocess.run(["taskkill", "/F", "/IM", _exe],
                                           capture_output=True, timeout=5)
                        except Exception:
                            pass
                    time.sleep(15)
                proc = None

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

        hwnd: int | None = hwnd_found if connect_existing else None
        if connect_existing and hwnd:
            app = Application(backend="uia").connect(handle=hwnd)
        else:
            deadline2 = time.monotonic() + 1200  # 1200s: warm snapshot <30s; cold snapshot up to ~950s (SVGA3D D3D init)
            # Backstop only — actual death (proc.poll() is not None) is the primary
            # flatline signal now. 240*0.5s=120s is well past the ~30s warm-snapshot
            # baseline, so a live process won't get false-aborted mid-slow-startup.
            _STUCK_REPEAT_LIMIT = 240
            _last_exc_type: type[BaseException] | None = None
            _repeat_count = 0
            while time.monotonic() < deadline2:
                # If process died already, no point waiting
                if proc is None:
                    break
                if proc.poll() is not None:
                    break
                try:
                    # Resolve the full launcher chain: on Windows, the venv launcher
                    # may spawn a second python.exe that owns the actual UI window.
                    pid_candidates = [proc.pid]
                    real_pid = proc.pid
                    try:
                        import psutil
                        p = psutil.Process(proc.pid)
                        children = p.children(recursive=True)
                        if children:
                            pid_candidates.extend(c.pid for c in children)
                            real_pid = children[0].pid
                    except Exception:
                        pass
                    app = Application(backend="uia").connect(
                        process=real_pid,
                        timeout=1,
                    )
                    hwnd = app.top_window().handle
                    break
                except ElementAmbiguousError as exc:
                    # Qt exposes a virtual root element alongside the real window.
                    # Pick the element that has a real HWND (handle != 0) and is a Window.
                    _last_exc_type = None  # progress: different exception shape seen
                    _repeat_count = 0
                    for el in exc.elements:
                        if getattr(el, "handle", None):
                            hwnd = el.handle
                            break
                    if hwnd:
                        app = Application(backend="uia").connect(handle=hwnd)
                        break
                except (ElementNotFoundError, _PwTimeout, RuntimeError) as e:
                    # Fallback: the process-based attach can miss the real window when
                    # the venv launcher spawns a child python.exe or UIA reports a
                    # title-matched top-level window before process scoping settles.
                    try:
                        fallback = Application(backend="uia").connect(
                            title_re="Trinity Pilot",
                            visible_only=False,
                            timeout=1,
                        )
                        candidate = fallback.top_window()
                        candidate_hwnd = getattr(candidate, "handle", None)
                        if candidate_hwnd:
                            try:
                                import win32process
                                _, candidate_pid = win32process.GetWindowThreadProcessId(candidate_hwnd)
                            except Exception:
                                candidate_pid = None
                            if candidate_pid is None or candidate_pid in pid_candidates:
                                app = Application(backend="uia").connect(handle=candidate_hwnd)
                                hwnd = candidate_hwnd
                                break
                    except Exception:
                        pass
                    print(f"[UIA Connect Loop] Process {proc.pid} not ready: {e!r}", flush=True)
                    if type(e) is _last_exc_type:
                        _repeat_count += 1
                    else:
                        _last_exc_type = type(e)
                        _repeat_count = 1
                    # Only declare a real flatline if the process has actually exited.
                    # A live process producing repeated identical errors is just slow —
                    # warm-snapshot baseline alone is ~30s, well past 20 attempts*0.5s=10s,
                    # so repeat-count alone was a false-positive abort on healthy slow
                    # startups. Process death is the only reliable "never going to work"
                    # signal; _repeat_count is kept only as a generous backstop against an
                    # alive-but-truly-wedged process (e.g. permanently blocked dialog).
                    _proc_dead = proc.poll() is not None
                    if _proc_dead or _repeat_count >= _STUCK_REPEAT_LIMIT:
                        startup_log = _cleanup_proc_and_log(proc, _stderr_fh, _stderr_path)
                        reason = "process exited" if _proc_dead else f"{_repeat_count} consecutive identical failures with no progress"
                        raise RuntimeError(
                            f"Trinity Pilot window flatlined: {reason} "
                            f"({_last_exc_type.__name__}, process pid={proc.pid} alive={not _proc_dead}). "
                            f"Aborting early instead of waiting out full {1200}s deadline. "
                            f"Last error: {e!r}\n"
                            f"Startup log:\n{startup_log}"
                        ) from e
                    time.sleep(0.5)
                except Exception as exc:
                    startup_log = _cleanup_proc_and_log(proc, _stderr_fh, _stderr_path)
                    raise RuntimeError(
                        f"Trinity Pilot window not found after startup: {exc!r}\n"
                        f"Startup log:\n{startup_log}"
                    ) from exc

            # Close log file handle (the app subprocess still holds it open).
            try:
                if _stderr_fh:
                    _stderr_fh.flush()
                    _stderr_fh.close()
            except Exception:
                pass

        if not hwnd:
            # App didn't appear — terminate, read log, raise.
            if proc is not None and not connect_existing:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    pass
            startup_log = ""
            if _stderr_path is not None:
                try:
                    startup_log = _stderr_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
                try:
                    _stderr_path.unlink(missing_ok=True)
                except Exception:
                    pass
            rc = proc.poll() if proc is not None else None
            raise RuntimeError(
                f"Trinity Pilot window not found within 1200s (exit code: {rc})\n"
                f"Startup log:\n{startup_log}"
            )
        # hwnd found — clean up log file silently (process still running, may fail)
        if _stderr_path is not None:
            try:
                _stderr_path.unlink(missing_ok=True)
            except Exception:
                pass

        win = app.window(handle=hwnd)
        got = cls._wait_static(win, {STATUS_READY}, timeout=60)
        if got != STATUS_READY:
            if connect_existing:
                if dbg:
                    dbg("_gui_driver.py:launch", "recover_to_ready_start", {
                        "last_status": got,
                    }, hypothesis_id="H5-launch-slow")
                got = cls._recover_to_ready(win, timeout=45)
            if got != STATUS_READY and connect_existing:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True, timeout=10,
                    )
                except Exception:
                    pass
                return cls.launch(_fresh_launch=True)
            if got != STATUS_READY:
                if proc is not None and not connect_existing:
                    proc.terminate()
                raise RuntimeError(
                    f"App did not reach Ready within 60s; last status={got!r}"
                )
        driver = cls(proc, win, hwnd=hwnd, db_path=_db_path)
        driver.infra_checkpoints["app_launched"] = True
        driver.infra_checkpoints["window_connected"] = True
        if dbg:
            dbg("_gui_driver.py:launch", "launch_ready", {
                "elapsed_ms": int((time.monotonic() - launch_t0) * 1000),
                "connect_existing": connect_existing,
                "status": got,
            }, hypothesis_id="H5-launch-slow")
        return driver

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
            self.infra_checkpoints["graceful_close"] = True
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
                     "notepad++.exe", "chrome.exe", "chromium.exe", "msedge.exe"]:
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

    def wait_for(self, targets: set[str], timeout: float = 60.0,
                 stall_nudge_after: float = 75.0) -> str:
        """Poll status label until a target matches or timeout. Returns matched value.

        If the status string is observed completely unchanged for
        `stall_nudge_after` seconds AFTER execution has started (i.e. we are
        waiting on real work, not idling at Ready pre-submission), send a
        single one-shot OS-level wake nudge (Ctrl+Shift+Q, via
        _send_emergency_wake) and keep polling. This is a conservative
        trigger — it requires zero status change, not "slow" progress, and
        fires at most once per wait_for call. Pass stall_nudge_after<=0 to
        disable. See 2026-06-29 trace analysis: a worker stall after
        ObjectiveStarted went undetected for 360s (this timeout) plus another
        434.5s in teardown before a keyboard wake cleared it in <2s — this
        nudge lets the same kind of stall self-clear in ~stall_nudge_after
        seconds instead of waiting for the full timeout + teardown detour.

        Raises TrinityPilotCrashedError immediately if the process exits during the wait
        so callers can distinguish infra crashes from genuine task failures.
        """
        _wait_started = time.monotonic()
        deadline = _wait_started + timeout
        _last_status: str | None = None
        _last_status_change_t = _wait_started
        _nudge_sent = False
        while time.monotonic() < deadline:
            rc = self._proc.poll()
            if rc is not None:
                # True = no crash observed; False = process exited during execution.
                self.infra_checkpoints["app_crashed"] = False
                raise TrinityPilotCrashedError(
                    f"Trinity Pilot exited (code={rc}) "
                    f"while waiting for {targets!r}"
                )
            s = AppDriver._read_status(self._win)
            if s and s != STATUS_READY:
                self.infra_checkpoints["execution_started"] = True

            now = time.monotonic()
            if s != _last_status:
                _last_status = s
                _last_status_change_t = now

            matched = False
            for t in targets:
                if s == t or s.startswith(t):
                    if t == STATUS_READY:
                        if self.infra_checkpoints.get("execution_started", False):
                            matched = True
                    else:
                        matched = True

            if matched:
                try:
                    from tests.e2e._debug_log import dbg
                    dbg("_gui_driver.py:wait_for", "target_matched", {
                        "status": s, "targets": list(targets),
                        "proc_alive": self._proc.poll() is None,
                        "elapsed_ms": round((time.monotonic() - _wait_started) * 1000),
                        "nudge_sent": _nudge_sent,
                    }, hypothesis_id="B")
                except Exception:
                    pass
                return s

            # One-shot stall nudge: only once execution has genuinely started,
            # and only after a long stretch of ZERO status change (not "slow").
            if (not _nudge_sent
                    and stall_nudge_after > 0
                    and self.infra_checkpoints.get("execution_started", False)
                    and (now - _last_status_change_t) >= stall_nudge_after):
                _nudge_sent = True
                try:
                    from tests.e2e._debug_log import dbg as _dbg_nudge
                    _dbg_nudge("_gui_driver.py:wait_for", "stall_nudge_fired", {
                        "status_unchanged_for_s": round(now - _last_status_change_t, 1),
                        "status_at_nudge": s,
                        "targets": list(targets),
                        "elapsed_ms": round((now - _wait_started) * 1000),
                    }, hypothesis_id="H-wake-fastpath")
                except Exception:
                    pass
                try:
                    AppDriver._send_emergency_wake(self._win, 5.0, source="wait_for_stall_nudge")
                except Exception:
                    pass
                # Reset the change-tracking baseline so we don't immediately
                # re-evaluate against the pre-nudge timestamp on the next tick.
                _last_status_change_t = time.monotonic()

            time.sleep(0.5)
        try:
            from tests.e2e._debug_log import dbg as _dbg_timeout
            _dbg_timeout("_gui_driver.py:wait_for", "wait_timeout", {
                "targets": list(targets),
                "elapsed_ms": round((time.monotonic() - _wait_started) * 1000),
                "nudge_sent": _nudge_sent,
            }, hypothesis_id="B")
        except Exception:
            pass
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
                                _pyautogui().click(x, y)
                                approve_clicked = True
                            except Exception:
                                pass
                        if approve_clicked:
                            self.infra_checkpoints["prompt_submitted"] = True
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
                self.infra_checkpoints["prompt_submitted"] = True
                return
        except Exception:
            pass
        # Fallback: pyautogui (requires window to be foreground).
        time.sleep(0.2)
        _pyautogui().hotkey("ctrl", "a")
        time.sleep(0.1)
        _pyautogui().write(text, interval=0.02)
        time.sleep(0.2)
        _pyautogui().press("enter")
        self.infra_checkpoints["prompt_submitted"] = True

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

    def dump_text(self, name: str) -> None:
        """Save the full UIA text-widget tree to .ai/screenshots/e2e/{name}.txt.

        Unlike snap(), this reads the underlying widget tree directly, so it
        captures content scrolled out of the visible screenshot area —
        needed to see per-objective execution detail on long task plans.
        """
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            lines = self.chat_lines() + self.all_text()
            (SCREENSHOTS_DIR / f"{name}.txt").write_text(
                "\n".join(lines), encoding="utf-8", errors="replace"
            )
        except Exception:
            pass
