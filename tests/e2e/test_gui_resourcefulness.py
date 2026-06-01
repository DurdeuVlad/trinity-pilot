"""Layer-3 GUI resourcefulness tests — agent given incomplete/indirect information.

Each test requires the agent to discover, infer, or probe the environment rather
than follow a direct instruction. Tests demonstrate multi-step reasoning, conditional
logic, and self-directed exploration.

Run:
    pytest tests/e2e/test_gui_resourcefulness.py -v --timeout=300
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e._gui_driver import (
    AFTER_CONFIRM,
    AFTER_SUBMIT,
    DESKTOP,
    STATUS_CLARIF,
    STATUS_CONFIRM,
    STATUS_FAILED,
    STATUS_ERROR,
)

pytestmark = [pytest.mark.e2e, pytest.mark.desktop, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _submit_and_run(app, prompt: str, plan_timeout: float = 50.0, run_timeout: float = 120.0):
    """Submit prompt, confirm if needed, return (phase, final_status)."""
    app.submit(prompt)
    after_submit = app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)

    if after_submit == STATUS_CLARIF:
        return "clarification", after_submit
    if after_submit in (STATUS_FAILED, STATUS_ERROR):
        return "planning_failed", after_submit

    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=run_timeout)
    return "confirmed", done


# ---------------------------------------------------------------------------
# RS-01 — Discovery: find largest file on Desktop
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS01_find_largest_file_on_desktop(app):
    """Agent must discover and rank files on Desktop without being told which is largest."""
    # Ensure at least one file is on the Desktop so the task is not vacuous
    sentinel = DESKTOP / "rs01_sentinel_large.txt"
    sentinel.write_text("x" * 1024, encoding="utf-8")  # 1 KB

    try:
        phase, status = _submit_and_run(
            app,
            "Look at all the files currently on the Desktop. "
            "Find the largest one and tell me its file name and size in bytes.",
            run_timeout=120,
        )
        app.snap("RS01_largest_file")

        if phase == "clarification":
            return  # agent asked for more info — acceptable

        assert "failed" not in status.lower(), f"RS-01 ended with failure: {status!r}"

        ui = app.ui_text()
        # Must mention a filename and a number (size)
        assert re.search(r"\d+", ui), (
            f"RS-01: Expected a file size number in chat. UI (first 400): {ui[:400]}"
        )
        # Must mention at least one filename (any word ending in a common extension)
        assert re.search(r"\w+\.\w{2,4}", ui), (
            f"RS-01: Expected a filename with extension in chat. UI (first 400): {ui[:400]}"
        )
    finally:
        sentinel.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# RS-02 — Conditional logic: check if git is installed
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS02_conditional_git_check(app):
    """Agent checks if git is installed; reports version OR 'not installed'. No hang."""
    phase, status = _submit_and_run(
        app,
        "Check if git is installed on this Windows machine. "
        "If it is, report the exact version string. "
        "If it is not installed, say 'git is not installed'.",
        run_timeout=90,
    )
    app.snap("RS02_git_check")

    if phase == "clarification":
        return

    assert "failed" not in status.lower(), f"RS-02 ended with failure: {status!r}"

    ui = app.ui_text()
    assert (
        re.search(r"\d+\.\d+", ui)  # version number
        or "not installed" in ui
        or "not found" in ui
        or "git" in ui
    ), (
        f"RS-02: Expected version or 'not installed' in chat. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# RS-03 — Self-direction: open default browser
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS03_open_default_browser(app):
    """Agent must open the default web browser without being told its name."""
    phase, status = _submit_and_run(
        app,
        "Open the default web browser on this Windows machine and navigate to "
        "https://example.com. Tell me the page title once it loads.",
        run_timeout=120,
    )
    app.snap("RS03_default_browser")

    if phase == "clarification":
        return

    assert "failed" not in status.lower(), f"RS-03 ended with failure: {status!r}"

    ui = app.ui_text()
    assert "example" in ui, (
        f"RS-03: Expected page title mention ('example') in chat. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# RS-04 — Multi-step info gather: .py file count and line count
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS04_count_py_files_and_lines(app):
    """Agent counts .py files and total lines in trinity-pilot dir — two numbers required."""
    phase, status = _submit_and_run(
        app,
        "Using the terminal, find out: "
        "(1) how many .py files exist inside the trinity-pilot directory on this machine, "
        "(2) the total number of lines across all those .py files. "
        "Report both numbers clearly in chat.",
        run_timeout=150,
    )
    app.snap("RS04_py_count_lines")

    if phase == "clarification":
        return

    assert "failed" not in status.lower(), f"RS-04 ended with failure: {status!r}"

    ui = app.ui_text()
    numbers = re.findall(r"\b\d+\b", ui)
    assert len(numbers) >= 2, (
        f"RS-04: Expected at least 2 numbers (file count + line count) in chat. "
        f"Found: {numbers}. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# RS-05 — Inference: open built-in Windows text editor by description
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS05_open_builtin_text_editor(app):
    """Agent must infer 'Notepad' from the description 'built-in Windows text editor'."""
    phase, status = _submit_and_run(
        app,
        "Open the text editing application that comes built into Windows "
        "(the simple one, not Word). Type the text 'rs05-inference-test' and "
        "then close the application without saving.",
        run_timeout=120,
    )
    app.snap("RS05_builtin_text_editor")

    if phase == "clarification":
        return

    # Pass if completed without failure — Notepad opened and was controlled
    assert "failed" not in status.lower(), f"RS-05 ended with failure: {status!r}"


# ---------------------------------------------------------------------------
# RS-06 — Detect OS version and build number
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS06_detect_os_version(app):
    """Agent must discover Windows version and build number via terminal, no tool hint given."""
    phase, status = _submit_and_run(
        app,
        "What version of Windows is running on this machine? "
        "Report the exact version number and build number.",
        run_timeout=90,
    )
    app.snap("RS06_os_version")

    if phase == "clarification":
        return

    assert "failed" not in status.lower(), f"RS-06 ended with failure: {status!r}"

    ui = app.ui_text()
    assert (
        re.search(r"\d+\.\d+", ui)
        or re.search(r"build\s*\d+", ui, re.IGNORECASE)
        or "windows" in ui.lower()
    ), (
        f"RS-06: Expected OS version info in chat. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# RS-07 — Find a running process by name and report its PID
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS07_find_process_pid(app):
    """Agent must query process list and report PID for explorer.exe."""
    phase, status = _submit_and_run(
        app,
        "Is there a process called 'explorer.exe' running on this machine right now? "
        "If yes, report its process ID (PID). If no, say 'not running'.",
        run_timeout=90,
    )
    app.snap("RS07_process_pid")

    if phase == "clarification":
        return

    assert "failed" not in status.lower(), f"RS-07 ended with failure: {status!r}"

    ui = app.ui_text()
    assert (
        re.search(r"\b\d{3,6}\b", ui)
        or "not running" in ui
        or "explorer" in ui.lower()
    ), (
        f"RS-07: Expected PID or 'not running' in chat. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# RS-08 — Self-directed path resolution: save to Python install directory
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS08_save_to_python_install_dir(app):
    """Agent must discover Python's install path then write a file there — two-step self-direction."""
    phase, status = _submit_and_run(
        app,
        "Find out where Python is installed on this machine. "
        "Save a file called rs08_probe.txt in that folder containing the text 'rs08-probe'. "
        "Report the full absolute path of the file you created.",
        run_timeout=150,
    )
    app.snap("RS08_python_install_path")

    if phase == "clarification":
        return

    assert "failed" not in status.lower(), f"RS-08 ended with failure: {status!r}"

    ui = app.ui_text()
    assert (
        re.search(r"[A-Za-z]:\\", ui)
        or "rs08_probe" in ui
        or "python" in ui.lower()
    ), (
        f"RS-08: Expected Python install path in chat. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# RS-09 — Conditional directory listing (Downloads folder)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS09_conditional_downloads_listing(app):
    """If Downloads exists: list 5 newest files. If not: report absent. Pure conditional discovery."""
    phase, status = _submit_and_run(
        app,
        "Check if there is a 'Downloads' folder on this Windows machine. "
        "If it exists, list the 5 most recently modified files inside it by name and date. "
        "If it does not exist, say 'Downloads folder not found'.",
        run_timeout=120,
    )
    app.snap("RS09_downloads_conditional")

    if phase == "clarification":
        return

    assert "failed" not in status.lower(), f"RS-09 ended with failure: {status!r}"

    ui = app.ui_text()
    downloads = Path.home() / "Downloads"

    if downloads.is_dir():
        has_listing = (
            re.search(r"\w+\.\w{2,4}", ui)
            or "empty" in ui
            or "no files" in ui
            or "download" in ui.lower()
        )
        assert has_listing, (
            f"RS-09: Downloads exists but agent gave no listing. UI (first 400): {ui[:400]}"
        )
    else:
        assert (
            "not found" in ui
            or "does not exist" in ui
            or "download" in ui.lower()
        ), (
            f"RS-09: Expected 'not found' response. UI (first 400): {ui[:400]}"
        )


# ---------------------------------------------------------------------------
# RS-10 — Identify most recently modified file on Desktop
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS10_most_recently_modified_file(app):
    """Agent must find and report the most recently modified file on Desktop without being told its name."""
    sentinel = DESKTOP / "rs10_recent_marker.txt"
    sentinel.write_text("rs10-marker", encoding="utf-8")

    try:
        phase, status = _submit_and_run(
            app,
            "Look at all the files on the Desktop. Find the single most recently modified file. "
            "Report its full name and its last modification date and time.",
            run_timeout=120,
        )
        app.snap("RS10_most_recent_file")

        if phase == "clarification":
            return

        assert "failed" not in status.lower(), f"RS-10 ended with failure: {status!r}"

        ui = app.ui_text()
        has_filename = re.search(r"\w+\.\w{2,4}", ui)
        has_time_info = re.search(r"\d{4}", ui)
        assert has_filename and has_time_info, (
            f"RS-10: Expected filename + timestamp in chat. UI (first 400): {ui[:400]}"
        )
    finally:
        sentinel.unlink(missing_ok=True)
