"""Layer-3 GUI happy-path tests — golden-path scenarios through the real Qt app.

Each test:
  1. Submits a natural-language prompt via the input box.
  2. Waits for the deterministic checkpoint "Awaiting confirmation".
  3. Confirms with "yes".
  4. Waits for terminal status (Done / Finished:*).
  5. Checks a concrete real-world side-effect (file on disk, text in chat).

Run:
    pytest tests/e2e/test_gui_happy_path.py -v --timeout=300
    pytest tests/e2e/test_gui_happy_path.py -v -m "e2e and not slow"
"""
from __future__ import annotations

import pytest

from tests.e2e._gui_driver import (
    AFTER_CONFIRM,
    AFTER_SUBMIT,
    DESKTOP,
    STATUS_CONFIRM,
)

pytestmark = [pytest.mark.e2e, pytest.mark.desktop, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ARTIFACTS = [
    DESKTOP / "tp_e2e.txt",
    DESKTOP / "cross_e2e.txt",
]


@pytest.fixture(autouse=True)
def _cleanup_artifacts():
    """Remove known test artifacts before each test so checks are clean."""
    for p in _ARTIFACTS:
        if p.exists():
            p.unlink(missing_ok=True)
    yield


def _plan_and_confirm(app, prompt: str, plan_timeout: float = 50.0) -> str:
    """Submit prompt, assert planning completes, send 'yes'. Returns plan status."""
    app.submit(prompt)
    plan_s = app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)
    assert plan_s == STATUS_CONFIRM, (
        f"Expected 'Awaiting confirmation' but got {plan_s!r}. "
        "The task may have been flagged as vague or planning failed."
    )
    app.submit("yes")
    return plan_s


# ---------------------------------------------------------------------------
# Terminal — create a file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_terminal_create_file(app):
    """Create a file on the Desktop and verify its content."""
    _plan_and_confirm(
        app,
        "Create a file called tp_e2e.txt on the Desktop "
        "containing exactly the text 'hello-e2e'",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=90)
    app.snap("happy_terminal_create_file")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    artifact = DESKTOP / "tp_e2e.txt"
    assert artifact.exists(), "tp_e2e.txt was not created on the Desktop"
    content = artifact.read_text(encoding="utf-8", errors="replace").strip()
    assert "hello-e2e" in content, f"Expected 'hello-e2e' in file, got: {content!r}"


# ---------------------------------------------------------------------------
# Browser — fetch page title
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_browser_fetch_title(app):
    """Navigate to example.com and verify the page title is mentioned in chat."""
    _plan_and_confirm(
        app,
        "Open a browser, go to https://example.com, and tell me the page title.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("happy_browser_title")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    ui = app.ui_text()
    assert "example" in ui, (
        "Page title not mentioned in chat. "
        f"Status: {done!r}. Visible text (first 300): {ui[:300]}"
    )


# ---------------------------------------------------------------------------
# Desktop — Windows Calculator
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_desktop_calculator(app):
    """Open Calculator, compute 12 * 12, verify result 144 appears in chat."""
    _plan_and_confirm(
        app,
        "Open the Windows Calculator, compute 12 multiplied by 12, "
        "and tell me the result.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("happy_desktop_calculator")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    ui = app.ui_text()
    assert "144" in ui, (
        f"Expected '144' in chat but not found. "
        f"Status: {done!r}. Visible text (first 300): {ui[:300]}"
    )


# ---------------------------------------------------------------------------
# Cross-domain — Notepad write then terminal read-back
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_cross_domain_notepad_terminal(app):
    """Write to Notepad, save to Desktop, read back via terminal. Both workers used."""
    _plan_and_confirm(
        app,
        "Open Notepad, type the text 'e2e-cross-test', save the file as "
        "cross_e2e.txt on the Desktop, then use the terminal to read the file "
        "back and print its contents.",
    )
    done = app.wait_for(AFTER_CONFIRM, timeout=180)
    app.snap("happy_cross_domain")

    assert "failed" not in done.lower(), f"Task ended with failure status: {done!r}"

    artifact = DESKTOP / "cross_e2e.txt"
    assert artifact.exists(), "cross_e2e.txt was not created on the Desktop"
    content = artifact.read_text(encoding="utf-8", errors="replace").strip()
    assert "e2e-cross-test" in content, (
        f"Expected 'e2e-cross-test' in file content, got: {content!r}"
    )
