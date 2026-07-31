"""
Smoke test: easy-desktop
========================
Launches Trinity Pilot, submits a desktop task via the GUI input, waits for
completion, verifies the deliverable, then closes every app that was opened.

Run:
    python tests/smoke/test_easy_desktop.py
    pytest tests/smoke/test_easy_desktop.py -s -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from _harness import kill_windows_matching, run_smoke

DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
DELIVERABLE = DESKTOP / "spring_poem.txt"

TASK = (
    "Open Notepad. Write a poem about spring. "
    "The poem MUST have EXACTLY 4 stanzas, each stanza with 4 lines, "
    "separated by a blank line. "
    f"Save the complete poem (all 4 stanzas) to {DELIVERABLE}"
)

MIN_STANZAS = 4


def _count_stanzas(text: str) -> int:
    return len([b for b in text.split("\n\n") if b.strip()])


def _stanza_check(content: str) -> bool:
    return _count_stanzas(content) >= MIN_STANZAS


def _verify(passed: bool, reasons: list[str]) -> tuple[bool, list[str]]:
    if not DELIVERABLE.exists():
        return passed, reasons
    content = DELIVERABLE.read_text(encoding="utf-8", errors="replace")
    stanzas = _count_stanzas(content)
    print(f"[check] size={len(content)} bytes, stanzas={stanzas}")
    if stanzas < MIN_STANZAS:
        passed = False
        reasons.append(f"Only {stanzas} stanzas (expected >= {MIN_STANZAS})")
    if len(content.strip()) < 80:
        passed = False
        reasons.append("File content too short (< 80 chars)")
    return passed, reasons


def _close() -> None:
    kill_windows_matching("notepad", "spring_poem")


def run_smoke_test() -> bool:
    return run_smoke(
        test_name="easy-desktop",
        task=TASK,
        deliverables=[DELIVERABLE],
        wait_for=DELIVERABLE,
        wait_min_size=80,
        wait_extra_check=_stanza_check,
        task_timeout=150.0,
        verify=_verify,
        close_spawned=_close,
        delete_deliverables_after=True,
    )


def test_easy_desktop() -> None:
    assert run_smoke_test(), "easy-desktop smoke test failed"


if __name__ == "__main__":
    sys.exit(0 if run_smoke_test() else 1)
