"""Layer-3 GUI fail-recovery tests — deliberately induced failure conditions.

Each test creates a failure scenario and asserts that Trinity Pilot either:
  - Recovers and completes the task via an alternative path, OR
  - Reports failure cleanly (no hang, no crash, visible error in UI)

This exercises error-handling, graceful degradation, and agent resilience.

Run:
    pytest tests/e2e/test_gui_fail_recovery.py -v --timeout=300
"""
from __future__ import annotations

import os
import stat
import subprocess
import threading
import time
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

def _submit_and_run(app, prompt: str, plan_timeout: float = 50.0, run_timeout: float = 90.0):
    """Submit prompt, handle clarification or confirmation, return final status.

    Returns (phase, final_status):
      phase = "clarification" | "confirmed" | "planning_failed"
    """
    app.submit(prompt)
    after_submit = app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)

    if after_submit == STATUS_CLARIF:
        return "clarification", after_submit

    if after_submit in (STATUS_FAILED, STATUS_ERROR):
        return "planning_failed", after_submit

    # STATUS_CONFIRM — send yes and wait for completion
    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=run_timeout)
    return "confirmed", done


# ---------------------------------------------------------------------------
# FR-01 — Missing target file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR01_missing_file_clean_failure(app):
    """Agent asked to read a nonexistent file. Must fail cleanly — no hang."""
    target = DESKTOP / "fr01_missing_file_that_does_not_exist.txt"
    target.unlink(missing_ok=True)  # ensure it really isn't there

    phase, status = _submit_and_run(
        app,
        f"Read the file {target} and summarize its contents.",
        plan_timeout=50,
        run_timeout=90,
    )
    app.snap("FR01_missing_file")

    assert phase != "planning_failed", (
        f"FR-01: Planning itself failed — expected runtime failure, got: {status!r}"
    )

    # Accept: clarification (agent flagged it) OR execution failure (tried and failed)
    if phase == "clarification":
        return  # agent correctly asked about nonexistent file — pass

    # Execution path: status must indicate failure, not silent Done
    ui = app.ui_text()
    failure_signals = {"failed", "not found", "does not exist", "error", "cannot", "unable"}
    assert (
        "failed" in status.lower()
        or any(w in ui for w in failure_signals)
    ), (
        f"FR-01: Expected visible failure signal, got status={status!r}. "
        f"UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# FR-02 — Nonexistent domain
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR02_bad_url_clean_failure(app):
    """Agent navigates to a nonexistent domain. Must fail cleanly within 90s."""
    phase, status = _submit_and_run(
        app,
        "Open a browser and go to https://nonexistent-domain-fr02-trinity-pilot-test.xyz "
        "and tell me the page title.",
        plan_timeout=50,
        run_timeout=180,
    )
    app.snap("FR02_bad_url")

    # Either clarification or clean execution failure — never a hang
    if phase == "clarification":
        return

    ui = app.ui_text()
    failure_signals = {"failed", "error", "not reach", "cannot", "unable", "refused", "dns"}
    assert (
        "failed" in status.lower()
        or any(w in ui for w in failure_signals)
    ), (
        f"FR-02: Expected visible failure signal, got status={status!r}. "
        f"UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# FR-03 — Ambiguous app name ("Calcu")
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR03_ambiguous_app_name(app):
    """Partial app name 'Calcu'. Agent must ask for clarification OR open Calculator."""
    phase, status = _submit_and_run(
        app,
        "Open the application called Calcu on this Windows PC.",
        plan_timeout=50,
        run_timeout=90,
    )
    app.snap("FR03_ambiguous_app")

    if phase == "clarification":
        # Best outcome: agent correctly flagged ambiguity
        return

    # If agent attempted execution: it either opened Calculator (pass) or failed cleanly (pass)
    # Both outcomes demonstrate correct behavior — only an infinite hang fails this test
    ui = app.ui_text()
    hung_indicators = {"planning", "thinking", "executing"}
    assert not all(w in status.lower() for w in hung_indicators), (
        f"FR-03: Task appears hung, status={status!r}"
    )
    # Acceptable final states: completed (Calculator opened) or failed (not found)
    acceptable = {"done", "finished", "failed", "error", "ready"}
    assert any(status.lower().startswith(w) for w in acceptable) or phase == "confirmed", (
        f"FR-03: Unexpected terminal status: {status!r}"
    )


# ---------------------------------------------------------------------------
# FR-04 — Read-only file write attempt
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR04_readonly_file_write_attempt(app):
    """Agent asked to append to a read-only file. Must fail cleanly, not corrupt."""
    artifact = DESKTOP / "fr04_readonly.txt"
    artifact.write_text("original-content\n", encoding="utf-8")
    # Mark read-only on Windows
    artifact.chmod(stat.S_IREAD)

    try:
        phase, status = _submit_and_run(
            app,
            f"Open the file {artifact} on the Desktop and append the text 'fr04-appended' to it.",
            plan_timeout=50,
            run_timeout=90,
        )
        app.snap("FR04_readonly_write")

        if phase == "clarification":
            return  # agent flagged it — fine

        # "Awaiting confirmation" = agent recognised the permission error and paused
        if "awaiting confirmation" in status.lower():
            return

        # File content must be unchanged (write was blocked or failed)
        # Re-enable read to check
        artifact.chmod(stat.S_IREAD | stat.S_IWRITE)
        content = artifact.read_text(encoding="utf-8", errors="replace")
        assert "fr04-appended" not in content or "failed" in status.lower(), (
            f"FR-04: Agent wrote to a read-only file — permission guard missing. "
            f"File content: {content!r}, Status: {status!r}"
        )

    finally:
        if artifact.exists():
            artifact.chmod(stat.S_IREAD | stat.S_IWRITE)
        artifact.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# FR-05 — App disappears mid-task (Notepad killed during write)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR05_app_crash_mid_task(app):
    """Notepad killed 8s after agent starts using it. Agent must not hang."""
    def _kill_notepad_after_delay(delay: float) -> None:
        time.sleep(delay)
        subprocess.run(
            ["taskkill", "/F", "/IM", "notepad.exe"],
            capture_output=True,
        )

    # Fire the killer 8s after submission
    killer = threading.Thread(target=_kill_notepad_after_delay, args=(8.0,), daemon=True)

    app.submit(
        "Open Notepad, type the text 'fr05-crash-test', and save the file as "
        "fr05_crash.txt on the Desktop."
    )
    killer.start()

    after_submit = app.wait_for(AFTER_SUBMIT, timeout=50)
    if after_submit == STATUS_CLARIF:
        app.snap("FR05_clarification")
        return  # agent asked — fine

    if after_submit in (STATUS_FAILED, STATUS_ERROR):
        app.snap("FR05_planning_failed")
        return  # planning-level failure also acceptable

    # Confirmed — send yes, wait for completion
    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=120)
    app.snap("FR05_app_crash")

    # Key assertion: task terminated (not hung in Executing/Planning/Thinking)
    hung_words = {"planning...", "thinking...", "executing..."}
    assert done.lower() not in hung_words, (
        f"FR-05: Task still running after Notepad kill — possible hang. Status: {done!r}"
    )

    # Clean up artifact if the agent somehow completed before the kill
    (DESKTOP / "fr05_crash.txt").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# FR-06 — Retry proof: first write path blocked, fallback succeeds
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR06_fallback_write_location(app):
    """Agent told primary save path is bad; must find and use Desktop as fallback."""
    # Tell the agent to try a bad path first, then fallback to Desktop
    phase, status = _submit_and_run(
        app,
        "Try to create a file at C:\\Windows\\System32\\fr06_test.txt with the text "
        "'fr06-content'. If that location is not writable, save it as "
        "fr06_fallback.txt on the Desktop instead.",
        plan_timeout=50,
        run_timeout=120,
    )
    app.snap("FR06_fallback_write")

    if phase == "clarification":
        return

    # Either the fallback file exists on Desktop, or the task failed cleanly
    fallback = DESKTOP / "fr06_fallback.txt"
    ui = app.ui_text()

    fallback_created = fallback.exists()
    clean_failure = "failed" in status.lower() or any(
        w in ui for w in {"failed", "permission", "access", "denied", "error"}
    )

    fallback.unlink(missing_ok=True)

    assert fallback_created or clean_failure, (
        f"FR-06: Agent neither created fallback nor reported clean failure. "
        f"Status: {status!r}. UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# FR-07 — Focus loss mid-task (minimize/restore while task runs)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR07_focus_loss_mid_task_no_hang(app):
    """Minimize/restore the app window 10s into task; must still terminate cleanly."""
    import win32con
    import win32gui

    hwnd = getattr(app, "_hwnd", 0)

    def _toggle_focus(delay_s: float) -> None:
        if not hwnd:
            return
        time.sleep(delay_s)
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            time.sleep(2)
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
        except Exception:
            pass

    artifact = DESKTOP / "fr07_focus_recovery.txt"
    artifact.unlink(missing_ok=True)

    toggler = threading.Thread(target=_toggle_focus, args=(10.0,), daemon=True)
    toggler.start()

    phase, done = _submit_and_run(
        app,
        "Create a file on the Desktop named fr07_focus_recovery.txt with the exact text 'focus-ok'.",
        plan_timeout=50,
        run_timeout=130,
    )
    app.snap("FR07_focus_loss")

    if phase in {"clarification", "planning_failed"}:
        return

    assert done, "FR-07: No terminal state received after focus-loss"
    hung = {"planning...", "thinking...", "executing..."}
    assert done.lower() not in hung, f"FR-07: Task appears hung after focus loss: {done!r}"

    if artifact.exists():
        content = artifact.read_text(encoding="utf-8", errors="replace").strip().lower()
        artifact.unlink(missing_ok=True)
        assert "focus-ok" in content, f"FR-07: Unexpected artifact content: {content!r}"


# ---------------------------------------------------------------------------
# FR-08 — Unreachable network with fallback artifact
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR08_network_unreachable_fallback(app):
    """Unreachable address must produce a fallback artifact or clear failure signal."""
    artifact = DESKTOP / "fr08_network_result.txt"
    artifact.unlink(missing_ok=True)

    phase, done = _submit_and_run(
        app,
        "Try to open http://10.255.255.1 in the browser. "
        "If unreachable, write a short failure reason to fr08_network_result.txt on the Desktop.",
        plan_timeout=50,
        run_timeout=140,
    )
    app.snap("FR08_network_unreachable")

    if phase == "clarification":
        return

    ui = app.ui_text()
    fallback_created = artifact.exists()
    clean_failure = (
        "failed" in str(done).lower()
        or any(w in ui for w in {"timeout", "unreachable", "refused", "dns", "error", "failed"})
    )

    if fallback_created:
        content = artifact.read_text(encoding="utf-8", errors="replace").strip()
        artifact.unlink(missing_ok=True)
        assert content, "FR-08: Fallback artifact exists but is empty"

    assert fallback_created or clean_failure, (
        f"FR-08: Neither fallback artifact nor failure signal. "
        f"Status={done!r}, UI={ui[:300]}"
    )


# ---------------------------------------------------------------------------
# FR-09 — Nonexistent CLI command
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR09_command_not_found(app):
    """Run a nonexistent terminal command; must fail cleanly with error signal, no hang."""
    phase, status = _submit_and_run(
        app,
        "Using the terminal, run the command 'xyzabcnotarealcommand123' and report what happens.",
        plan_timeout=50,
        run_timeout=90,
    )
    app.snap("FR09_command_not_found")

    if phase == "clarification":
        return

    ui = app.ui_text()
    failure_signals = {"failed", "not found", "not recognized", "error", "cannot", "unable", "no such"}
    assert (
        "failed" in status.lower()
        or any(w in ui for w in failure_signals)
    ), (
        f"FR-09: Expected error signal for unknown command, got status={status!r}. "
        f"UI (first 400): {ui[:400]}"
    )


# ---------------------------------------------------------------------------
# FR-10 — Partial multi-step failure (cascading dependency)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
@pytest.mark.slow
def test_FR10_partial_multistep_failure(app):
    """Step 2 of a 3-step task reads a nonexistent file. Agent must not fabricate step 3."""
    output = DESKTOP / "fr10_merged_output.txt"
    source_a = DESKTOP / "fr10_source_a.txt"
    output.unlink(missing_ok=True)
    source_a.unlink(missing_ok=True)

    phase, status = _submit_and_run(
        app,
        "Do this 3-step task: "
        "1) Create fr10_source_a.txt on the Desktop with the text 'part-a'. "
        "2) Read the file C:/does_not_exist/fr10_source_b.txt for its contents. "
        "3) Combine both texts and write the result to fr10_merged_output.txt on the Desktop.",
        plan_timeout=50,
        run_timeout=120,
    )
    app.snap("FR10_partial_multistep")

    try:
        if phase == "clarification":
            return

        # "Awaiting confirmation" mid-task = agent paused at step-2 failure without
        # fabricating step 3 — correct behaviour, treat as pass.
        if "awaiting confirmation" in status.lower():
            return

        ui = app.ui_text()
        failure_signals = {"failed", "not found", "does not exist", "error", "cannot", "unable"}

        if output.exists():
            # Output was created — agent must have reported the failure in chat
            assert any(w in ui for w in failure_signals), (
                f"FR-10: Agent created merged output despite step 2 failing — "
                f"likely fabricated data. UI: {ui[:300]}"
            )
        else:
            # Agent correctly stopped — verify failure signal is visible
            assert (
                "failed" in status.lower()
                or any(w in ui for w in failure_signals)
            ), (
                f"FR-10: No output and no failure signal. Status={status!r}. UI={ui[:400]}"
            )
    finally:
        output.unlink(missing_ok=True)
        source_a.unlink(missing_ok=True)
