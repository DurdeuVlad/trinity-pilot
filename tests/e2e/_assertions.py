"""Assertion helpers for e2e tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from trinity_pilot.core.types import TaskStatus
from trinity_pilot.memory.store import TaskStore
from trinity_pilot.orchestrator.signals import ObjectiveDone, StuckSignal


def skip_if_quota_exhausted(result: dict, obj_id: str) -> None:
    """Skip the test (not fail) if the Gemini API returned 429 RESOURCE_EXHAUSTED.

    429 means the monthly spend cap was hit — not a code bug.  Tests should be
    re-run when quota resets rather than being counted as failures.
    """
    error: str = (
        (result.get("results", {}).get(obj_id, {}).get("evidence", {}) or {})
        .get("error", "") or ""
    )
    if "429" in error or "RESOURCE_EXHAUSTED" in error:
        pytest.skip(
            f"Gemini API quota exhausted (429) — re-run when quota resets. "
            f"obj={obj_id} error={error[:160]}"
        )


def assert_file_exists(path: Path, msg: str | None = None) -> None:
    """Assert that a file or directory exists at path."""
    assert path.exists(), msg or f"Expected path to exist: {path}"


def assert_db_status(db_path: str, task_id: str, expected_status: str) -> None:
    """Assert the task in the DB has the expected status string."""
    store = TaskStore(db_path)
    record = store.get_task(task_id)
    assert record is not None, f"Task {task_id} not found in DB at {db_path}"
    assert record.status.value == expected_status, (
        f"Expected task status '{expected_status}' but got '{record.status.value}'"
    )


def assert_signal_in_queue(signals: list[Any], signal_type: type, msg: str | None = None) -> Any:
    """Assert that at least one signal of the given type exists in the list; return the first match."""
    matches = [s for s in signals if isinstance(s, signal_type)]
    assert matches, (
        msg or f"Expected signal of type {signal_type.__name__} in queue, got: {[type(s).__name__ for s in signals]}"
    )
    return matches[0]


def assert_no_signal_type(signals: list[Any], signal_type: type, msg: str | None = None) -> None:
    """Assert that no signal of the given type appears in the list."""
    matches = [s for s in signals if isinstance(s, signal_type)]
    assert not matches, (
        msg or f"Expected no {signal_type.__name__} signals, but found {len(matches)}"
    )


def assert_stuck_signal(signals: list[Any], reason_contains: str = "") -> StuckSignal:
    """Assert a StuckSignal is present and optionally that its reason contains a substring."""
    stuck_list = [s for s in signals if isinstance(s, StuckSignal)]
    assert stuck_list, f"Expected StuckSignal but found none. Signals: {[type(s).__name__ for s in signals]}"
    stuck = stuck_list[0]
    if reason_contains:
        assert reason_contains in stuck.reason, (
            f"Expected StuckSignal.reason to contain '{reason_contains}', got '{stuck.reason}'"
        )
    return stuck


def assert_objective_done(signals: list[Any], objective_id: str | None = None) -> ObjectiveDone:
    """Assert an ObjectiveDone signal is present; optionally match objective_id."""
    done_list = [s for s in signals if isinstance(s, ObjectiveDone)]
    assert done_list, "Expected ObjectiveDone signal but found none"
    if objective_id is not None:
        matching = [s for s in done_list if s.objective_id == objective_id]
        assert matching, f"No ObjectiveDone for objective_id={objective_id}"
        return matching[0]
    return done_list[0]


def assert_db_completed(db_path: str, task_id: str) -> None:
    """Assert the task status is COMPLETED in the DB."""
    assert_db_status(db_path, task_id, TaskStatus.COMPLETED.value)


def assert_db_not_completed(db_path: str, task_id: str) -> None:
    """Assert the task status is NOT COMPLETED in the DB."""
    store = TaskStore(db_path)
    record = store.get_task(task_id)
    assert record is not None, f"Task {task_id} not found in DB"
    assert record.status != TaskStatus.COMPLETED, (
        f"Expected task to NOT be completed, but status is {record.status.value}"
    )
