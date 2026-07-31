"""
Shared harness for Trinity Pilot smoke tests.

Each test defines:
  - TASK           str   — text submitted to the UI input
  - DELIVERABLES   list[Path]  — files to verify exist
  - verify(passed, reasons) -> (bool, list[str])   — extra checks
  - close_spawned()  — close apps this test opened
  - TASK_TIMEOUT   float (optional, default 150)
  - POLL_INTERVAL  float (optional, default 3)
"""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

import psutil
import pyautogui
import pyperclip
import win32con
import win32gui
import win32process

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_MODULE = "trinity_pilot"
APP_START_TIMEOUT = 35   # seconds to wait for Trinity Pilot window
VENV_PYTHON = Path(__file__).resolve().parents[2] / ".venv" / "Scripts" / "python.exe"
TRINITY_PILOT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def find_window(title_fragment: str, timeout: float = APP_START_TIMEOUT) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result: list[int] = []

        def _cb(hwnd: int, _: object) -> None:
            if win32gui.IsWindowVisible(hwnd) and title_fragment.lower() in win32gui.GetWindowText(hwnd).lower():
                result.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        if result:
            return result[0]
        time.sleep(0.4)
    return None


def window_pid(hwnd: int) -> int:
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid


def kill_pid(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=5)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
        pass


def kill_windows_matching(*fragments: str) -> None:
    """Terminate all visible windows whose titles match any fragment."""
    to_kill: list[int] = []

    def _cb(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).lower()
        if any(f.lower() in title for f in fragments):
            to_kill.append(hwnd)

    win32gui.EnumWindows(_cb, None)
    for hwnd in to_kill:
        try:
            kill_pid(window_pid(hwnd))
        except Exception:
            pass


def position_window(hwnd: int) -> None:
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        print(f"[warn] SetForegroundWindow: {e}")
    try:
        win32gui.MoveWindow(hwnd, 100, 100, 960, 720, True)
    except Exception as e:
        print(f"[warn] MoveWindow: {e}")


def input_coords(app_hwnd: int) -> tuple[int, int]:
    left, top, right, bottom = win32gui.GetWindowRect(app_hwnd)
    return (left + right) // 2, bottom - 40


# ---------------------------------------------------------------------------
# Wait helpers
# ---------------------------------------------------------------------------

def wait_for_file_stable(
    path: Path,
    min_size: int = 1,
    stable_secs: float = 5.0,
    timeout: float = 150.0,
    poll: float = 3.0,
    extra_check: "Callable[[str], bool] | None" = None,
) -> bool:
    """
    Wait until path exists, size >= min_size, unchanged for stable_secs,
    and optional extra_check(content) returns True.
    """
    deadline = time.time() + timeout
    last_size = -1
    stable_since: float | None = None

    while time.time() < deadline:
        if path.exists():
            try:
                size = path.stat().st_size
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                time.sleep(poll)
                continue

            ok = size >= min_size and (extra_check is None or extra_check(content))

            if size == last_size and size > 0:
                if stable_since is None:
                    stable_since = time.time()
                elif time.time() - stable_since >= stable_secs:
                    if ok:
                        return True
                    # content still insufficient — reset and keep waiting
                    stable_since = None
            else:
                last_size = size
                stable_since = None

        time.sleep(poll)

    return False


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_smoke(
    test_name: str,
    task: str,
    deliverables: list[Path],
    wait_for: Path,
    wait_extra_check: "Callable[[str], bool] | None" = None,
    wait_min_size: int = 10,
    task_timeout: float = 150.0,
    verify: "Callable[[bool, list[str]], tuple[bool, list[str]]] | None" = None,
    close_spawned: "Callable[[], None] | None" = None,
    delete_deliverables_after: bool = True,
) -> bool:
    """
    Full smoke test lifecycle. Returns True on PASS.

    Parameters
    ----------
    test_name   : label shown in output
    task        : text typed into Trinity Pilot input
    deliverables: files to verify exist at the end
    wait_for    : the key file to poll for completion (usually the main deliverable)
    wait_extra_check: optional fn(content: str) -> bool to gate stability check
    wait_min_size   : minimum byte size before stability is checked
    task_timeout    : total seconds before giving up
    verify      : fn(passed: bool, reasons: list) -> (passed, reasons)
                  for domain-specific content checks
    close_spawned   : fn() to close apps the test opened
    delete_deliverables_after: remove deliverable files during cleanup
    """
    print(f"\n{'='*60}")
    print(f"  SMOKE TEST: {test_name}")
    print(f"{'='*60}")

    # --- 0. Setup ---
    for d in deliverables:
        if d.exists():
            d.unlink()
            print(f"[setup] Removed old: {d}")

    # --- 1. Launch ---
    # Unique task queue isolates this test from stale local runs.
    task_queue = f"trinity-pilot-smoke-{uuid.uuid4().hex[:8]}"
    print(f"[launch] {VENV_PYTHON} (queue={task_queue})")
    proc = subprocess.Popen(
        [str(VENV_PYTHON), "-m", APP_MODULE],
        cwd=str(TRINITY_PILOT_ROOT),
        env={**os.environ, "PYTHONPATH": str(TRINITY_PILOT_ROOT), "TRINITY_TASK_QUEUE": task_queue},
    )

    # --- 2. Wait for window ---
    print("[wait] Trinity Pilot window…")
    app_hwnd = find_window("Trinity Pilot", timeout=APP_START_TIMEOUT)
    if not app_hwnd:
        print("[FAIL] Window not found")
        proc.terminate()
        return False
    print(f"[ok] HWND={app_hwnd}")
    time.sleep(3)

    # --- 3. Position ---
    position_window(app_hwnd)
    time.sleep(1)

    # --- 4. Submit task ---
    # Click first to get focus, THEN copy to clipboard (avoids Qt clearing clipboard on focus)
    cx, cy = input_coords(app_hwnd)
    print(f"[input] Click ({cx},{cy}), pasting task via clipboard…")
    pyautogui.click(cx, cy)
    time.sleep(0.5)           # wait for focus to settle
    pyautogui.hotkey("ctrl", "a")   # clear existing text
    time.sleep(0.1)
    pyperclip.copy(task)      # copy AFTER focus — prevents Qt from clearing clipboard
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "v")   # paste
    time.sleep(0.4)
    pyautogui.press("enter")
    print("[input] Submitted")

    # --- 5. Wait ---
    print(f"[wait] Up to {task_timeout}s…")
    wait_for_file_stable(
        wait_for,
        min_size=wait_min_size,
        extra_check=wait_extra_check,
        timeout=task_timeout,
    )
    time.sleep(3)  # grace period for last write to flush

    # --- 6. Verify ---
    print("[check] Verifying deliverables…")
    passed = True
    reasons: list[str] = []

    for d in deliverables:
        if not d.exists():
            passed = False
            reasons.append(f"Missing: {d}")
        elif d.stat().st_size == 0:
            passed = False
            reasons.append(f"Empty file: {d}")

    if verify:
        passed, reasons = verify(passed, reasons)

    # --- 7. Cleanup spawned apps ---
    print("[cleanup] Spawned apps…")
    if close_spawned:
        close_spawned()
    time.sleep(0.5)

    # --- 8. Remove deliverables ---
    if delete_deliverables_after:
        for d in deliverables:
            try:
                if d.exists():
                    d.unlink()
                    print(f"[cleanup] Deleted {d}")
            except Exception as e:
                print(f"[warn] Could not delete {d}: {e}")

    # --- 9. Close Trinity Pilot ---
    print("[cleanup] Trinity Pilot…")
    kill_pid(proc.pid)
    time.sleep(0.5)

    # --- 10. Report ---
    if passed:
        print(f"\n✅  SMOKE TEST PASSED — {test_name}\n")
    else:
        print(f"\n❌  SMOKE TEST FAILED — {test_name}")
        for r in reasons:
            print(f"    reason: {r}")
        print()

    return passed
