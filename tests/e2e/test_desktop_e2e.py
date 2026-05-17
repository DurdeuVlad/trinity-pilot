"""Desktop domain end-to-end tests.

These tests require a visible Windows desktop and are skipped on headless/non-Windows.
All tests are marked @pytest.mark.desktop.

Run with:
    pytest tests/e2e/test_desktop_e2e.py -v --timeout=240

Skip desktop tests entirely:
    pytest tests/e2e/ -v -m "not desktop"
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.e2e._assertions import assert_db_completed, assert_no_signal_type
from tests.e2e._scenario import BridgeTestHarness

_E2E_TMP = Path("C:/E2E_TEST_tmp")


# ---------------------------------------------------------------------------
# Helper: build a minimal ObjectiveSpec dict for desktop domain
# ---------------------------------------------------------------------------

def _desktop_objective(objective_id: str, goal: str, max_attempts: int = 2) -> dict:
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
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Test 1: open Notepad, type text, save file
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
def test_desktop_open_notepad_write_save(
    desktop_available,
    bridge_harness: BridgeTestHarness,
    tmp_db_path: str,
    tmp_path: Path,
):
    """Open Notepad, type 'E2E test passed', and save to a temp file."""
    output_file = _E2E_TMP / "e2e_result.txt"
    _E2E_TMP.mkdir(parents=True, exist_ok=True)

    task = f"Open Notepad, type 'E2E test passed', save as {output_file}"
    objectives = [
        _desktop_objective(
            "obj-notepad-write",
            f"Open Notepad via Start menu or Run dialog, type the text 'E2E test passed', then save the file to {output_file} using File > Save As",
            max_attempts=2,
        )
    ]

    log_path = tmp_path / "run.log"
    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=240)
    bridge_harness.write_log(log_path)

    assert log_path.exists(), "Log file must be written"

    if not done:
        pytest.fail("Notepad task stalled after 240s")

    result = bridge_harness.last_result
    assert result is not None

    # Check file exists
    file_created = output_file.exists()
    if file_created:
        output_file.unlink(missing_ok=True)

    db_status = bridge_harness.get_db_status(task_id)
    assert db_status == "completed", (
        f"Expected 'completed' but got '{db_status}'. Result: {result}"
    )
    assert file_created, f"Expected file {output_file} to be created by Notepad"


# ---------------------------------------------------------------------------
# Test 2: take a screenshot
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
def test_desktop_screenshot(
    desktop_available,
    bridge_harness: BridgeTestHarness,
    tmp_db_path: str,
    tmp_path: Path,
):
    """Take a screenshot and describe visible apps."""
    task = "Take a screenshot and describe what apps are currently visible"
    objectives = [
        _desktop_objective(
            "obj-screenshot",
            "Take a screenshot of the current desktop using pyautogui or the desktop worker, then describe the visible windows and applications",
            max_attempts=2,
        )
    ]

    log_path = tmp_path / "run.log"
    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=120)
    bridge_harness.write_log(log_path)

    assert log_path.exists(), "Log file must be written"

    if not done:
        pytest.fail("Screenshot task stalled after 120s")

    result = bridge_harness.last_result
    assert result is not None

    db_status = bridge_harness.get_db_status(task_id)
    assert db_status == "completed", (
        f"Expected 'completed' but got '{db_status}'. Result: {result}"
    )


# ---------------------------------------------------------------------------
# Test 3: open Calculator and compute
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.desktop
def test_desktop_calculator(
    desktop_available,
    bridge_harness: BridgeTestHarness,
    tmp_db_path: str,
    tmp_path: Path,
):
    """Open Calculator and compute 99 + 1."""
    task = "Open Calculator and compute 99 plus 1"
    objectives = [
        _desktop_objective(
            "obj-calculator",
            "Open the Windows Calculator application, enter 99 + 1, and confirm the result is 100",
            max_attempts=2,
        )
    ]

    log_path = tmp_path / "run.log"
    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=120)
    bridge_harness.write_log(log_path)

    assert log_path.exists(), "Log file must be written"

    if not done:
        pytest.fail("Calculator task stalled after 120s")

    result = bridge_harness.last_result
    assert result is not None

    db_status = bridge_harness.get_db_status(task_id)
    assert db_status == "completed", (
        f"Expected 'completed' but got '{db_status}'. Result: {result}"
    )
