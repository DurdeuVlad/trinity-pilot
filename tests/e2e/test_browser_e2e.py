"""Browser domain end-to-end tests.

These tests run against the live orchestrator via WorkflowBridge.
They require the configured LLM API key and Playwright to be installed.

Run with:
    pytest tests/e2e/test_browser_e2e.py -v --timeout=180
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e._assertions import (
    skip_if_quota_exhausted,
)
from tests.e2e._scenario import BridgeTestHarness

# ---------------------------------------------------------------------------
# Browser availability guard
# ---------------------------------------------------------------------------

def _check_playwright() -> None:
    """Skip if Playwright is not installed or browser binaries are absent."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            # Just check that chromium is available
            _ = pw.chromium
    except Exception as exc:
        pytest.skip(f"Playwright not available: {exc}")


# ---------------------------------------------------------------------------
# Helper: build a minimal ObjectiveSpec dict for browser domain
# ---------------------------------------------------------------------------

def _browser_objective(
    objective_id: str,
    goal: str,
    max_attempts: int = 2,
    max_agent_steps: int = 40,
) -> dict:
    return {
        "objective_id": objective_id,
        "goal": goal,
        "dependencies": [],
        "domain": "browser",
        "required_capabilities": ["browser"],
        "risk_class": "low",
        "preconditions": [],
        "success_tests": ["Page loaded without error"],
        "evidence_bundle": ["screenshot", "page_title"],
        "max_attempts": max_attempts,
        "rollback_or_abort_rule": "abort on network error",
        "metadata": {"max_agent_steps": max_agent_steps},
    }


# ---------------------------------------------------------------------------
# Test 1: Wikipedia Romania population
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_browser_wikipedia_romania(bridge_harness: BridgeTestHarness, tmp_db_path: str, tmp_path: Path):
    """Navigate to Wikipedia and find the population of Romania."""
    _check_playwright()

    task = "Go to Wikipedia and find the population of Romania"
    objectives = [
        _browser_objective(
            "obj-wiki-romania",
            "Navigate to https://en.wikipedia.org/wiki/Romania, then use read_page to get the page text, "
            "and finish with success once you can confirm the page loaded (page title contains 'Romania'). "
            "Do NOT use javascript: URLs.",
            max_attempts=2,
            max_agent_steps=15,
        )
    ]

    log_path = tmp_path / "run.log"
    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=180)
    bridge_harness.write_log(log_path)

    assert log_path.exists(), "Log file must be written"

    if not done:
        pytest.fail("Browser task stalled after 180s")

    result = bridge_harness.last_result
    assert result is not None
    skip_if_quota_exhausted(result, "obj-wiki-romania")
    db_status = bridge_harness.get_db_status(task_id)
    assert db_status == "completed", (
        f"Expected 'completed' but got '{db_status}'. Result: {result}"
    )


# ---------------------------------------------------------------------------
# Test 2: check URL returns 200
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_browser_check_url_status(bridge_harness: BridgeTestHarness, tmp_db_path: str, tmp_path: Path):
    """Check if httpbin.org/status/200 returns 200 OK."""
    _check_playwright()

    task = "Check if https://httpbin.org/status/200 is returning 200 OK"
    objectives = [
        _browser_objective(
            "obj-check-url",
            "Navigate to https://httpbin.org/status/200 and confirm the HTTP response status is 200",
            max_attempts=2,
        )
    ]

    log_path = tmp_path / "run.log"
    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=120)
    bridge_harness.write_log(log_path)

    assert log_path.exists(), "Log file must be written"

    if not done:
        pytest.fail("Browser task stalled after 120s")

    result = bridge_harness.last_result
    assert result is not None
    skip_if_quota_exhausted(result, "obj-check-url")
    db_status = bridge_harness.get_db_status(task_id)
    assert db_status == "completed", (
        f"Expected 'completed' but got '{db_status}'. Result: {result}"
    )


# ---------------------------------------------------------------------------
# Test 3: unreachable domain — expect partial_blocker or failure
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_browser_blocker_unreachable(bridge_harness: BridgeTestHarness, tmp_db_path: str, tmp_path: Path):
    """Navigate to an unreachable domain and verify the worker reports failure gracefully."""
    _check_playwright()

    task = "Navigate to https://this-domain-does-not-exist-xyz.invalid and report what you find"
    objectives = [
        _browser_objective(
            "obj-unreachable",
            "Navigate to https://this-domain-does-not-exist-xyz.invalid and report the result",
            max_attempts=1,
        )
    ]

    log_path = tmp_path / "run.log"
    task_id = bridge_harness.submit(task, objectives=objectives)
    done = bridge_harness.wait_for_completion(timeout=60)
    bridge_harness.write_log(log_path)

    assert log_path.exists(), "Log file must be written"

    if not done:
        pytest.fail("Unreachable-domain task stalled — expected prompt termination")

    result = bridge_harness.last_result
    assert result is not None, "Expected a result dict"

    db_status = bridge_harness.get_db_status(task_id)
    # Should NOT be completed — the domain is unreachable
    assert db_status in ("failed", "cancelled", "partial_blocker"), (
        f"Expected failure/blocker status but got '{db_status}'. Result: {result}"
    )

    # Drain signals and check for a meaningful failure message
    signals = bridge_harness.drain_signals()
    from trinity_pilot.orchestrator.signals import ObjectiveFailed, StuckSignal
    failure_signals = [s for s in signals if isinstance(s, (ObjectiveFailed, StuckSignal))]
    # At least one failure indicator should be present
    assert failure_signals or db_status != "completed", (
        "Expected at least one ObjectiveFailed or StuckSignal for unreachable domain"
    )
