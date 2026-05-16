"""Extended signal tests for WorkerStepSignal (Story 7)."""
from __future__ import annotations

import time
from typing import get_args

import pytest

from trinity_pilot.orchestrator.signals import Signal, WorkerStepSignal


def test_worker_step_signal_in_union():
    assert WorkerStepSignal in get_args(Signal)


def test_worker_step_signal_is_frozen():
    sig = WorkerStepSignal(
        task_id="t1",
        objective_id="o1",
        step_num=1,
        tool_name="run_command",
        tokens_this_step=42,
    )
    try:
        sig.task_id = "modified"  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except Exception as e:
        assert "frozen" in str(e).lower() or "can't" in str(e).lower() or "cannot" in str(e).lower()


def test_worker_step_signal_fields():
    before = time.time()
    sig = WorkerStepSignal(
        task_id="t1",
        objective_id="o1",
        step_num=3,
        tool_name="write_file",
        tokens_this_step=100,
    )
    after = time.time()
    assert sig.task_id == "t1"
    assert sig.objective_id == "o1"
    assert sig.step_num == 3
    assert sig.tool_name == "write_file"
    assert sig.tokens_this_step == 100
    assert before <= sig.ts <= after
