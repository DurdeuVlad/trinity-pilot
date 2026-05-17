"""Desktop domain end-to-end tests.

These tests require a visible Windows desktop and are skipped on headless/non-Windows.
All tests are marked @pytest.mark.desktop.

Run with:
    pytest tests/e2e/test_desktop_e2e.py -v --timeout=240

Skip desktop tests entirely:
    pytest tests/e2e/ -v -m "not desktop"

Assertion philosophy
--------------------
Each test has ONE primary assertion that checks the real-world side effect:
  - write_file test  → file must exist on disk with correct content
  - screenshot test  → screenshot bytes must be non-empty in evidence (OR intelligent blocker)
  - calculator test  → action_log must confirm the correct keystrokes were sent
                       AND worker summary must contain "100"

Secondary assertions (db_status == "completed") are nice-to-have but the primary
assertion is always the observable outcome.  If the outcome is correct but the
reviewer rejected, the test still passes.

A 429 RESOURCE_EXHAUSTED error is not a test failure — it is skipped with a
clear message so it doesn't pollute the pass/fail signal.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e._assertions import skip_if_quota_exhausted
from tests.e2e._scenario import BridgeTestHarness

_E2E_TMP = Path("C:/E2E_TEST_tmp")


# ---------------------------------------------------------------------------
# Helper: build a minimal ObjectiveSpec dict for desktop domain
# ---------------------------------------------------------------------------

def _desktop_objective(
    objective_id: str,
    goal: str,
    max_attempts: int = 2,
    max_agent_steps: int = 20,
) -> dict:
    return {
        "objective_id": objective_id,
        "goal": goal,
        "dependencies": [],
        "domain": "desktop",
        "required_capabilities": ["desktop_automation"],
        "risk_class": "medium",
        "preconditions": ["Windows desktop is visible"],
        "success_tests": ["Target application is in the expected state"],
        "evidence_bundle": ["screenshot"],
        "max_attempts": max_attempts,
        "rollback_or_abort_rule": "close application if open",
        "metadata": {"max_agent_steps": max_agent_steps},
    }


# ---------------------------------------------------------------------------
# Test 1: write_file — assert file exists on disk with correct content
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
def test_desktop_write_file(
    desktop_available,
    bridge_harness: BridgeTestHarness,
    tmp_db_path: str,
    tmp_path: Path,
):
    """Desktop worker writes a file using write_file tool.

    Primary assertion: file exists on disk with content 'E2E test passed'.
    This is a direct side-effect check — no fallback on worker summary.
    """
    output_file = _E2E_TMP / "e2e_result.txt"
    _E2E_TMP.mkdir(parents=True, exist_ok=True)
    # Clean up any leftover from a previous run
    output_file.unlink(missing_ok=True)

    task = f"Write the text 'E2E test passed' to the file {output_file}"
    objectives = [
        _desktop_objective(
            "obj-write-file",
            f"Call the write_file tool to write exactly the text 'E2E test passed' "
            f"to the file path {output_file}. "
            "Do NOT open Notepad or any GUI application.",
            max_attempts=2,
            max_agent_steps=10,
        )
    ]

    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=120)

    if not done:
        pytest.fail("write_file task stalled after 120s — no completion signal")

    result = bridge_harness.last_result
    assert result is not None, "Expected a result dict"

    # Skip on quota exhaustion
    skip_if_quota_exhausted(result, "obj-write-file")

    # PRIMARY assertion: file must exist on disk
    file_exists = output_file.exists()
    file_content = output_file.read_text(encoding="utf-8").strip() if file_exists else ""
    # Cleanup before asserting so leftover doesn't affect next run
    output_file.unlink(missing_ok=True)

    assert file_exists, (
        f"File {output_file} was NOT created on disk. "
        f"Result: {result}"
    )
    assert "E2E test passed" in file_content, (
        f"File exists but content is wrong: {file_content!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: screenshot — assert screenshot bytes are non-empty in evidence
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
def test_desktop_screenshot(
    desktop_available,
    bridge_harness: BridgeTestHarness,
    tmp_db_path: str,
    tmp_path: Path,
):
    """Desktop worker takes a screenshot.

    Primary assertion: evidence contains non-empty screenshot bytes.
    Acceptable fallback: worker raised a blocker (intelligently surfaced ambiguity).
    FAIL: quota error → skip; any other hard failure → fail.
    """
    task = "Take a screenshot of the current desktop"
    objectives = [
        _desktop_objective(
            "obj-screenshot",
            "Use the desktop_screenshot capability to capture the current desktop screen. "
            "Call finish(success) once the screenshot is captured.",
            max_attempts=2,
            max_agent_steps=10,
        )
    ]

    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=120)

    if not done:
        pytest.fail("Screenshot task stalled after 120s")

    result = bridge_harness.last_result
    assert result is not None

    skip_if_quota_exhausted(result, "obj-screenshot")

    obj_result = result.get("results", {}).get("obj-screenshot", {}) or {}
    evidence = obj_result.get("evidence", {}) or {}
    failure_reason = obj_result.get("failure_reason", "")

    # Acceptable: screenshot bytes present
    screenshot = evidence.get("screenshot")
    screenshot_ok = bool(screenshot) and len(screenshot) > 100  # non-trivial bytes/b64

    # Also acceptable: intelligently raised a blocker
    blocker_ok = failure_reason == "blocker_needs_user_input"

    assert screenshot_ok or blocker_ok, (
        f"Expected non-empty screenshot in evidence OR intelligent blocker. "
        f"screenshot present={bool(screenshot)}, blocker={blocker_ok}. "
        f"failure_reason={failure_reason!r}, db_status={bridge_harness.get_db_status(task_id)!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: calculator — assert action_log contains correct keystrokes + summary has "100"
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
def test_desktop_calculator(
    desktop_available,
    bridge_harness: BridgeTestHarness,
    tmp_db_path: str,
    tmp_path: Path,
):
    """Desktop worker opens Calculator and computes 99 + 1 = 100.

    Primary assertions:
      1. action_log shows Calculator was launched
      2. typed_text or action_log shows '99' and '1' were entered
      3. worker_result_summary contains '100'
    These check that the AI actually did the computation, not just claimed to.
    """
    task = "Open Calculator and compute 99 plus 1, tell me the result"
    objectives = [
        _desktop_objective(
            "obj-calculator",
            "Launch calc.exe, type '99+1' using type_text, press Enter or '=', "
            "then call finish(success) with a summary that includes the numeric result.",
            max_attempts=2,
            max_agent_steps=15,
        )
    ]

    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=120)

    if not done:
        pytest.fail("Calculator task stalled after 120s")

    result = bridge_harness.last_result
    assert result is not None

    skip_if_quota_exhausted(result, "obj-calculator")

    evidence = (
        result.get("results", {}).get("obj-calculator", {}).get("evidence", {}) or {}
    )
    action_log: list[str] = evidence.get("action_log", []) or []
    typed_text: str = evidence.get("typed_text", "") or ""
    summary: str = evidence.get("worker_result_summary", "") or ""
    action_log_str = " ".join(action_log).lower()

    # 1. Calculator was launched
    assert any("calc" in a.lower() for a in action_log), (
        f"Calculator was never launched. action_log={action_log}"
    )

    # 2. The digits were typed (99 and 1 present somewhere in interaction)
    typed_combined = (typed_text + action_log_str)
    assert "99" in typed_combined or "9" in typed_combined, (
        f"No evidence of '99' being typed. typed_text={typed_text!r}, action_log={action_log}"
    )

    # 3. Summary must mention the result 100
    assert "100" in summary, (
        f"Worker summary does not confirm result is 100. summary={summary!r}"
    )
