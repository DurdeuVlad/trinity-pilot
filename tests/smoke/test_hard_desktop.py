"""
Smoke test: hard-desktop
========================
Open Notepad, write a structured to-do list with 3 categories (Work, Personal,
Health), each with 3 items. Save to Desktop as todo_list.txt.
Also create a second file Desktop/todo_summary.txt containing just a one-line
count summary: "3 categories, 9 items total".

Run:
    python tests/smoke/test_hard_desktop.py
    pytest tests/smoke/test_hard_desktop.py -s -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from _harness import run_smoke, kill_windows_matching

DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
TODO_FILE = DESKTOP / "todo_list.txt"
SUMMARY_FILE = DESKTOP / "todo_summary.txt"

TASK = (
    "Use write_file to create TWO files on the Desktop. "
    f"First file {TODO_FILE} must contain a structured to-do list "
    "with EXACTLY 3 categories: Work, Personal, and Health. "
    "Under each category write EXACTLY 3 numbered items. "
    "Example structure:\nWork:\n1. item\n2. item\n3. item\nPersonal:\n1. item\n2. item\n3. item\nHealth:\n1. item\n2. item\n3. item\n"
    f"Second file {SUMMARY_FILE} must contain EXACTLY this text: "
    "'3 categories, 9 items total'. "
    "Do NOT open Notepad. Use write_file actions directly for both files. Both files must exist when done."
)


def _todo_extra_check(content: str) -> bool:
    c = content.lower()
    return "work" in c and "personal" in c and "health" in c


def _verify(passed: bool, reasons: list[str]) -> tuple[bool, list[str]]:
    # todo_list.txt
    if TODO_FILE.exists():
        content = TODO_FILE.read_text(encoding="utf-8", errors="replace").lower()
        print(f"[check] todo_list size={TODO_FILE.stat().st_size}")
        for cat in ("work", "personal", "health"):
            if cat not in content:
                passed = False
                reasons.append(f"Category '{cat}' missing from todo_list.txt")
    # summary file
    if SUMMARY_FILE.exists():
        summary = SUMMARY_FILE.read_text(encoding="utf-8", errors="replace").strip()
        print(f"[check] todo_summary: {summary!r}")
        if "3" not in summary or "9" not in summary:
            passed = False
            reasons.append(f"Summary file doesn't contain expected counts, got: {summary!r}")
    return passed, reasons


def _close() -> None:
    kill_windows_matching("notepad", "todo_list", "todo_summary")


def run_smoke_test() -> bool:
    return run_smoke(
        test_name="hard-desktop",
        task=TASK,
        deliverables=[TODO_FILE, SUMMARY_FILE],
        wait_for=SUMMARY_FILE,   # poll on the second (harder) file
        wait_min_size=5,
        wait_extra_check=lambda c: "3" in c and "9" in c,
        task_timeout=180.0,
        verify=_verify,
        close_spawned=_close,
        delete_deliverables_after=True,
    )


def test_hard_desktop() -> None:
    assert run_smoke_test(), "hard-desktop smoke test failed"


if __name__ == "__main__":
    sys.exit(0 if run_smoke_test() else 1)
