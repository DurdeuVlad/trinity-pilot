"""
Smoke test: launch unified desktop, submit a CLI task, approve objectives,
wait for completion, close app, print latest flight record.

Usage:
    python test_smoke.py
    python test_smoke.py "echo hello world"
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pywinauto
from pywinauto import Desktop
from pywinauto.application import Application

# ── Config ────────────────────────────────────────────────────────────────────

TASK = sys.argv[1] if len(sys.argv) > 1 else "print the current date and time to the terminal"
APP_DIR = Path(__file__).parent
PYTHON = sys.executable
STARTUP_TIMEOUT = 15      # seconds to wait for window
PLAN_TIMEOUT = 40         # seconds to wait for plan generation
EXEC_TIMEOUT = 120        # seconds to wait for execution to finish
POLL = 0.5

# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[smoke] {msg}", flush=True)


def wait_for(condition, timeout: float, label: str, poll: float = POLL):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = condition()
            if result:
                return result
        except Exception:
            pass
        time.sleep(poll)
    raise TimeoutError(f"Timed out waiting for: {label}")


def latest_flight_report() -> dict | None:
    base = APP_DIR / "_runtime" / "flight_reports"
    if not base.exists():
        return None
    reports = sorted(
        base.rglob("report.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not reports:
        return None
    with open(reports[0], encoding="utf-8") as f:
        data = json.load(f)
    data["_file"] = str(reports[0])
    return data


def latest_crash_report() -> str | None:
    base = APP_DIR / "_runtime" / "crash_reports"
    if not base.exists():
        return None
    reports = sorted(base.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return None
    return reports[0].read_text(encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    log(f"Task: {TASK!r}")
    log("Launching app…")

    proc = subprocess.Popen(
        [PYTHON, "main.py"],
        cwd=str(APP_DIR),
    )

    # ── Wait for window ──────────────────────────────────────────────────────
    log("Waiting for TrinityPilot window…")
    app = wait_for(
        lambda: Application(backend="uia").connect(title="TrinityPilot", timeout=2),
        timeout=STARTUP_TIMEOUT,
        label="TrinityPilot window",
    )
    log("Window found.")
    time.sleep(1)  # let Qt finish painting

    dlg = app.window(title="TrinityPilot")
    dlg.set_focus()

    # ── Find input box and type task ─────────────────────────────────────────
    log("Finding input box…")
    input_box = wait_for(
        lambda: dlg.child_window(auto_id="QApplication.MainWindow.QSplitter.ChatPanel._InputBox"),
        timeout=10,
        label="_InputBox",
    )
    input_box.click_input()
    time.sleep(0.3)
    input_box.type_keys(TASK, with_spaces=True)
    log(f"Typed task. Pressing Enter…")
    input_box.type_keys("{ENTER}")

    # ── Wait for Run button to become enabled ────────────────────────────────
    log("Waiting for plan generation…")

    def run_btn_ready():
        btn = dlg.child_window(title="Run", control_type="Button")
        return btn.is_enabled()

    wait_for(run_btn_ready, timeout=PLAN_TIMEOUT, label="Run button enabled")
    log("Plan ready. Clicking Run…")

    run_btn = dlg.child_window(title="Run", control_type="Button")
    run_btn.click_input()

    # ── Wait for execution to finish ─────────────────────────────────────────
    log("Waiting for execution to complete…")

    # Run button disappears (set_executing hides it) and Cancel appears.
    # When done, Run re-appears.
    def execution_done():
        btn = dlg.child_window(title="Run", control_type="Button")
        return btn.is_visible() and btn.is_enabled()

    # Give it a moment to enter executing state first
    time.sleep(2)
    wait_for(execution_done, timeout=EXEC_TIMEOUT, label="execution done (Run re-enabled)")
    log("Execution complete.")

    # ── Close app ────────────────────────────────────────────────────────────
    log("Closing app…")
    dlg.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
    log("App closed.")

    # ── Check crash reports ──────────────────────────────────────────────────
    crash = latest_crash_report()
    if crash:
        # Only show if it's recent (modified after we launched)
        base = APP_DIR / "_runtime" / "crash_reports"
        reports = sorted(base.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if reports and reports[0].stat().st_mtime > (time.time() - (STARTUP_TIMEOUT + PLAN_TIMEOUT + EXEC_TIMEOUT)):
            print("\n" + "=" * 60)
            print("CRASH REPORT FOUND:")
            print("=" * 60)
            print(crash[:3000])
            return 1

    # ── Check flight record ──────────────────────────────────────────────────
    report = latest_flight_report()
    if report:
        print("\n" + "=" * 60)
        print("LATEST FLIGHT RECORD:")
        print("=" * 60)
        print(f"File:      {report.get('_file')}")
        print(f"Status:    {report.get('status')}")
        print(f"Objective: {report.get('objective', {}).get('description')}")
        print(f"Module:    {report.get('module')}")
        print(f"Duration:  {report.get('duration_ms')}ms")
        attempts = report.get("attempts", [])
        if attempts:
            last = attempts[-1]
            print(f"Actions:   {last.get('actions', [])}")
            print(f"Outcome:   {last.get('outcome')}")
        print("=" * 60)
        return 0 if report.get("status") == "success" else 1
    else:
        print("\n[smoke] No flight record found — execution may not have reached trinity_core.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
