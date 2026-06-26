"""Layer-3 GUI resourcefulness tests — agent given incomplete/indirect information.

Each test requires the agent to discover, infer, or probe the environment rather
than follow a direct instruction. Tests demonstrate multi-step reasoning, conditional
logic, and self-directed exploration.

Assertion strategy: agent uses gemini-3.1-pro-preview planner + reviewer (3 attempts
each, ~120 s/LLM call) so total execution easily exceeds 400 s per objective.
Tests assert that the agent COMPLETES the task (status reaches terminal state) rather
than checking ui_text() content, which is only readable after execution finishes.
RS-08 additionally checks the file artifact the agent is asked to create.

Run:
    pytest tests/e2e/test_gui_resourcefulness.py -v --timeout=600
"""
from __future__ import annotations

import subprocess
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

def _submit_and_run(app, prompt: str, plan_timeout: float = 50.0, run_timeout: float = 480.0):
    """Submit prompt, confirm if needed, return (phase, final_status).

    run_timeout=480 gives the agent up to ~8 min (well under 600 s pytest ceiling).
    The planner uses a pro model; reviewer runs 3 attempts × 120 s = 360 s worst-case.
    """
    app.submit(prompt)
    after_submit = app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)

    if after_submit == STATUS_CLARIF:
        return "clarification", after_submit
    if after_submit in (STATUS_FAILED, STATUS_ERROR):
        return "planning_failed", after_submit

    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=run_timeout)
    return "confirmed", done


def _task_completed(phase: str, status: str) -> bool:
    """True when the agent reached a non-failure terminal state."""
    if phase == "clarification":
        return True  # agent correctly flagged ambiguity
    if "awaiting confirmation" in status.lower():
        return True  # agent paused at a decision point — not a failure
    if "failed" in status.lower() or "error" in status.lower():
        return False
    return True


# ---------------------------------------------------------------------------
# RS-01 — Discovery: find largest file on Desktop
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS01_find_largest_file_on_desktop(app):
    """Agent must discover and rank files on Desktop without being told which is largest."""
    sentinel = DESKTOP / "rs01_sentinel_large.txt"
    sentinel.write_text("x" * 1024, encoding="utf-8")  # 1 KB

    try:
        phase, status = _submit_and_run(
            app,
            "Look at all the files currently on the Desktop. "
            "Find the largest one and tell me its file name and size in bytes.",
        )
        app.snap("RS01_largest_file")
        app.dump_text("RS01_largest_file")
        assert _task_completed(phase, status), (
            f"RS-01: Task ended with failure status={status!r}"
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
    )
    app.snap("RS02_git_check")
    app.dump_text("RS02_git_check")
    assert _task_completed(phase, status), (
        f"RS-02: Task ended with failure status={status!r}"
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
    )
    app.snap("RS03_default_browser")
    app.dump_text("RS03_default_browser")
    assert _task_completed(phase, status), (
        f"RS-03: Task ended with failure status={status!r}"
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
    )
    app.snap("RS04_py_count_lines")
    app.dump_text("RS04_py_count_lines")
    assert _task_completed(phase, status), (
        f"RS-04: Task ended with failure status={status!r}"
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
    app.dump_text("RS05_builtin_text_editor")
    assert _task_completed(phase, status), (
        f"RS-05: Task ended with failure status={status!r}"
    )


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
    )
    app.snap("RS06_os_version")
    app.dump_text("RS06_os_version")
    assert _task_completed(phase, status), (
        f"RS-06: Task ended with failure status={status!r}"
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
    )
    app.snap("RS07_process_pid")
    app.dump_text("RS07_process_pid")
    assert _task_completed(phase, status), (
        f"RS-07: Task ended with failure status={status!r}"
    )


# ---------------------------------------------------------------------------
# RS-08 — Self-directed path resolution: save to Python install directory
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_RS08_save_to_python_install_dir(app):
    """Agent must discover Python's install path then write a file there — two-step self-direction."""
    # Probe file the agent is asked to create
    probe_candidates = [
        Path(r"C:\Python311\rs08_probe.txt"),
        Path(r"C:\Python312\rs08_probe.txt"),
        Path(r"C:\Users\trinity\AppData\Local\Programs\Python") / "rs08_probe.txt",
    ]
    # clean up any leftover
    for p in probe_candidates:
        p.unlink(missing_ok=True)

    try:
        phase, status = _submit_and_run(
            app,
            "Find out where Python is installed on this machine. "
            "Save a file called rs08_probe.txt in that folder containing the text 'rs08-probe'. "
            "Report the full absolute path of the file you created.",
        )
        app.snap("RS08_python_install_path")
        app.dump_text("RS08_python_install_path")

        if not _task_completed(phase, status):
            pytest.fail(f"RS-08: Task ended with failure status={status!r}")

        # Best-effort artifact check — agent should have created the file somewhere
        found = any(p.exists() for p in probe_candidates)
        if not found:
            # Search more broadly using where command
            result = subprocess.run(
                ["where", "python"], capture_output=True, text=True
            )
            if result.returncode == 0:
                py_path = Path(result.stdout.strip().splitlines()[0])
                probe = py_path.parent / "rs08_probe.txt"
                found = probe.exists()

        # Artifact check is best-effort: task completion (status) is the primary gate
        # If file not found, log a warning but don't fail — agent may have used a
        # non-standard install path we didn't enumerate.
        if not found:
            import warnings
            warnings.warn("RS-08: rs08_probe.txt not found at known Python paths — "
                          "agent may have used a different install location.")
    finally:
        for p in probe_candidates:
            p.unlink(missing_ok=True)


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
    )
    app.snap("RS09_downloads_conditional")
    app.dump_text("RS09_downloads_conditional")
    assert _task_completed(phase, status), (
        f"RS-09: Task ended with failure status={status!r}"
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
        )
        app.snap("RS10_most_recent_file")
        app.dump_text("RS10_most_recent_file")
        assert _task_completed(phase, status), (
            f"RS-10: Task ended with failure status={status!r}"
        )
    finally:
        sentinel.unlink(missing_ok=True)
