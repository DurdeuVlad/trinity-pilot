"""
Smoke test: hard-browser
========================
Navigate to httpbin.org/get, extract the caller's IP from JSON, write to file.

Run:
    python tests/smoke/test_hard_browser.py
    pytest tests/smoke/test_hard_browser.py -s -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from _harness import run_smoke, kill_windows_matching

DELIVERABLE = Path(r"C:\Users\User\Desktop\my_ip.txt")

TASK = (
    "Open a browser and navigate to https://httpbin.org/get. "
    "The page returns a JSON response. "
    "Find the value of the 'origin' key in the JSON (it will be an IP address). "
    "Write only that IP address to the file C:/Users/User/Desktop/my_ip.txt. "
    "The file must contain a valid IPv4 address (e.g. 1.2.3.4)."
)

_IPV4_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")


def _extra_check(content: str) -> bool:
    return bool(_IPV4_RE.search(content))


def _verify(passed: bool, reasons: list[str]) -> tuple[bool, list[str]]:
    if not DELIVERABLE.exists():
        return passed, reasons
    content = DELIVERABLE.read_text(encoding="utf-8", errors="replace").strip()
    print(f"[check] IP file: {content!r}")
    if not _IPV4_RE.search(content):
        passed = False
        reasons.append(f"No IPv4 address found in file, got: {content!r}")
    return passed, reasons


def _close() -> None:
    kill_windows_matching("chrome", "firefox", "msedge", "edge", "chromium")


def run_smoke_test() -> bool:
    return run_smoke(
        test_name="hard-browser",
        task=TASK,
        deliverables=[DELIVERABLE],
        wait_for=DELIVERABLE,
        wait_min_size=5,
        wait_extra_check=_extra_check,
        task_timeout=150.0,
        verify=_verify,
        close_spawned=_close,
        delete_deliverables_after=True,
    )


def test_hard_browser() -> None:
    assert run_smoke_test(), "hard-browser smoke test failed"


if __name__ == "__main__":
    sys.exit(0 if run_smoke_test() else 1)
