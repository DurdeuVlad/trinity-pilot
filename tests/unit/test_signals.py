"""Tests for typed signal dataclasses."""
import time
import typing

from trinity_pilot.orchestrator.signals import (
    BudgetWarning,
    ObjectiveDone,
    ObjectiveFailed,
    ObjectiveStarted,
    Signal,
    SteeringMessage,
    StepCompleted,
    StuckSignal,
    WorkerStepSignal,
)


def test_all_signals_frozen():
    sig = ObjectiveStarted(task_id="t1", objective_id="o1")
    try:
        sig.task_id = "modified"  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except Exception as e:
        assert "frozen" in str(e).lower() or "can't" in str(e).lower() or "cannot" in str(e).lower()


def test_step_completed_fields():
    sig = StepCompleted(
        task_id="t1", objective_id="o1", step_num=2,
        tool_name="browser", args_hash="abc123", token_count=50
    )
    assert sig.step_num == 2
    assert sig.token_count == 50


def test_stuck_signal_has_user_question():
    sig = StuckSignal(task_id="t1", objective_id="o1", reason="identical_steps", consecutive_count=5, user_question="help?")
    assert sig.user_question == "help?"


def test_signal_union_covers_all_types():
    type_args = typing.get_args(Signal)
    expected = {
        ObjectiveStarted, StepCompleted, StuckSignal, BudgetWarning,
        ObjectiveDone, ObjectiveFailed, SteeringMessage, WorkerStepSignal
    }
    assert set(type_args) == expected, f"Signal union missing types: {expected - set(type_args)}"


def test_ts_auto_populated():
    before = time.time()
    sig = ObjectiveDone(task_id="t", objective_id="o")
    after = time.time()
    assert before <= sig.ts <= after
