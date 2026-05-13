"""Tests for ObjectiveState FSM (AC-6.1)."""
from pathlib import Path
import pytest
from trinity_pilot.orchestrator.fsm import ObjectiveState, transition, VALID_TRANSITIONS


def test_valid_transitions_pending_to_running():
    assert transition(ObjectiveState.PENDING, ObjectiveState.RUNNING) == ObjectiveState.RUNNING


def test_valid_transitions_running_to_done():
    assert transition(ObjectiveState.RUNNING, ObjectiveState.DONE) == ObjectiveState.DONE


def test_valid_transitions_running_to_stuck():
    assert transition(ObjectiveState.RUNNING, ObjectiveState.STUCK) == ObjectiveState.STUCK


def test_valid_transitions_running_to_failed():
    assert transition(ObjectiveState.RUNNING, ObjectiveState.FAILED) == ObjectiveState.FAILED


def test_valid_transitions_stuck_to_steered():
    assert transition(ObjectiveState.STUCK, ObjectiveState.STEERED) == ObjectiveState.STEERED


def test_valid_transitions_stuck_to_failed():
    assert transition(ObjectiveState.STUCK, ObjectiveState.FAILED) == ObjectiveState.FAILED


def test_valid_transitions_steered_to_running():
    assert transition(ObjectiveState.STEERED, ObjectiveState.RUNNING) == ObjectiveState.RUNNING


def test_invalid_transition_raises():
    with pytest.raises(ValueError, match="Invalid transition"):
        transition(ObjectiveState.PENDING, ObjectiveState.DONE)


def test_invalid_transition_from_running_to_pending():
    with pytest.raises(ValueError):
        transition(ObjectiveState.RUNNING, ObjectiveState.PENDING)


def test_terminal_done_rejects_all():
    for state in ObjectiveState:
        if state != ObjectiveState.DONE:
            with pytest.raises(ValueError):
                transition(ObjectiveState.DONE, state)


def test_terminal_failed_rejects_all():
    for state in ObjectiveState:
        if state != ObjectiveState.FAILED:
            with pytest.raises(ValueError):
                transition(ObjectiveState.FAILED, state)


def test_fsm_line_count():
    """AC-6.1: fsm.py must be 60 lines or fewer."""
    fsm_path = Path(__file__).parent.parent.parent / "trinity_pilot" / "orchestrator" / "fsm.py"
    lines = fsm_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 60, f"fsm.py has {len(lines)} lines, expected <= 60"
