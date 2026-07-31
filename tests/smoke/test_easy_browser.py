"""
Smoke test: easy-browser
========================
Navigate to example.com, save the page title to Desktop.

Run:
    python tests/smoke/test_easy_browser.py
    pytest tests/smoke/test_easy_browser.py -s -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from _harness import kill_windows_matching, run_smoke

DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
DELIVERABLE = DESKTOP / "browser_title.txt"

TASK = (
    "Open a browser and navigate to https://example.com. "
    "Find the page title (it should be 'Example Domain'). "
    "Write the exact page title text to the file "
    f"{DELIVERABLE}. "
    "The file must contain the text 'Example Domain'."
)


def _extra_check(content: str) -> bool:
    return "example" in content.lower()


def _verify(passed: bool, reasons: list[str]) -> tuple[bool, list[str]]:
    if not DELIVERABLE.exists():
        return passed, reasons
    content = DELIVERABLE.read_text(encoding="utf-8", errors="replace").strip()
    print(f"[check] Title file: {content!r}")
    if "example" not in content.lower():
        passed = False
        reasons.append(f"Expected 'Example Domain' in file, got: {content!r}")
    return passed, reasons


def _close() -> None:
    kill_windows_matching("chrome", "firefox", "msedge", "edge", "chromium")


def run_smoke_test() -> bool:
    return run_smoke(
        test_name="easy-browser",
        task=TASK,
        deliverables=[DELIVERABLE],
        wait_for=DELIVERABLE,
        wait_min_size=5,
        wait_extra_check=_extra_check,
        task_timeout=120.0,
        verify=_verify,
        close_spawned=_close,
        delete_deliverables_after=True,
    )


def test_easy_browser() -> None:
    assert run_smoke_test(), "easy-browser smoke test failed"


if __name__ == "__main__":
    sys.exit(0 if run_smoke_test() else 1)
