"""
Smoke test: easy-terminal
=========================
Submits a terminal task: write current date + hostname to a text file.

Run:
    python tests/smoke/test_easy_terminal.py
    pytest tests/smoke/test_easy_terminal.py -s -v
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

from _harness import run_smoke, kill_windows_matching

DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
DELIVERABLE = DESKTOP / "sysinfo.txt"

TASK = (
    "Open a terminal (cmd or PowerShell). "
    "Run a command that writes the current date and hostname to "
    f"{DELIVERABLE}. "
    "The file must exist and contain today's date and the machine hostname."
)

TODAY_YEAR = str(date.today().year)


def _verify(passed: bool, reasons: list[str]) -> tuple[bool, list[str]]:
    if not DELIVERABLE.exists():
        return passed, reasons
    content = DELIVERABLE.read_text(encoding="utf-8", errors="replace")
    print(f"[check] Content: {content.strip()!r}")
    if TODAY_YEAR not in content:
        passed = False
        reasons.append(f"Today's year ({TODAY_YEAR}) not found in file")
    if len(content.strip()) < 5:
        passed = False
        reasons.append("File content too short")
    return passed, reasons


def _close() -> None:
    kill_windows_matching("cmd", "powershell", "windows powershell", "sysinfo")


def run_smoke_test() -> bool:
    return run_smoke(
        test_name="easy-terminal",
        task=TASK,
        deliverables=[DELIVERABLE],
        wait_for=DELIVERABLE,
        wait_min_size=5,
        task_timeout=120.0,
        verify=_verify,
        close_spawned=_close,
        delete_deliverables_after=True,
    )


def test_easy_terminal() -> None:
    assert run_smoke_test(), "easy-terminal smoke test failed"


if __name__ == "__main__":
    sys.exit(0 if run_smoke_test() else 1)
