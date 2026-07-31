"""
Smoke test: hard-terminal
=========================
Write a Python fib script to Desktop, run it, capture output to a second file.
Both files must exist; output must contain the 10th Fibonacci number (55).

Run:
    python tests/smoke/test_hard_terminal.py
    pytest tests/smoke/test_hard_terminal.py -s -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from _harness import kill_windows_matching, run_smoke

DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
SCRIPT_FILE = DESKTOP / "fib.py"
OUTPUT_FILE = DESKTOP / "fib_output.txt"

TASK = (
    "Do the following in a terminal (cmd or PowerShell), step by step:\n"
    f"1. Write a Python script to {SCRIPT_FILE} that prints the "
    "first 10 Fibonacci numbers, one per line (1 1 2 3 5 8 13 21 34 55).\n"
    f"2. Run that script with Python and save the output to {OUTPUT_FILE}.\n"
    "Both files must exist when done."
)


def _extra_check(content: str) -> bool:
    """fib_output.txt must contain '55' (10th Fibonacci)."""
    return "55" in content


def _verify(passed: bool, reasons: list[str]) -> tuple[bool, list[str]]:
    # script file
    if not SCRIPT_FILE.exists():
        passed = False
        reasons.append(f"Missing script: {SCRIPT_FILE}")
    # output file
    if not OUTPUT_FILE.exists():
        passed = False
        reasons.append(f"Missing output: {OUTPUT_FILE}")
    else:
        content = OUTPUT_FILE.read_text(encoding="utf-8", errors="replace")
        print(f"[check] fib_output: {content.strip()!r}")
        if "55" not in content:
            passed = False
            reasons.append("10th Fibonacci number (55) not found in fib_output.txt")
    return passed, reasons


def _close() -> None:
    kill_windows_matching("cmd", "powershell", "windows powershell")


def run_smoke_test() -> bool:
    return run_smoke(
        test_name="hard-terminal",
        task=TASK,
        deliverables=[SCRIPT_FILE, OUTPUT_FILE],
        wait_for=OUTPUT_FILE,
        wait_min_size=5,
        wait_extra_check=_extra_check,
        task_timeout=150.0,
        verify=_verify,
        close_spawned=_close,
        delete_deliverables_after=True,
    )


def test_hard_terminal() -> None:
    assert run_smoke_test(), "hard-terminal smoke test failed"


if __name__ == "__main__":
    sys.exit(0 if run_smoke_test() else 1)
