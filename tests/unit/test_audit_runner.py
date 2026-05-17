from trinity_pilot.audit.runner import (
    collect_recovery_context,
    exit_status_for_result,
    normalize_attempt,
    normalize_reviewer_result,
    normalize_signal,
)
from trinity_pilot.core.types import AttemptLog, FailureReason, ReviewResult
from trinity_pilot.memory.reflection import ReflectionStore
from trinity_pilot.orchestrator.signals import StepCompleted


def test_signal_normalization():
    signal = StepCompleted("task", "obj", 2, "desktop", "abc", 4)

    data = normalize_signal(signal, 1)

    assert data["type"] == "StepCompleted"
    assert data["order"] == 1
    assert data["payload_summary"]["tool_name"] == "desktop"


def test_attempt_normalization():
    log = AttemptLog(
        "attempt",
        "obj",
        "task",
        1,
        "failed",
        FailureReason.FAILED_ASSERTION,
        {"selected_action": "type", "trace_path": "trace.zip", "error": "bad"},
    )

    data = normalize_attempt(log)

    assert data["action"] == "type"
    assert data["evidence_paths"] == ["trace.zip"]
    assert data["error_summary"] == "bad"


def test_reviewer_serialization():
    data = normalize_reviewer_result(ReviewResult(False, FailureReason.WRONG_OUTPUT, "notes", "retry"))

    assert data["verdict"] == "failed"
    assert data["failure_reason"] == "wrong_output"
    assert data["recovery_hint"] == "retry"


def test_reflection_location_serialization(tmp_path):
    db = tmp_path / "audit.db"
    ReflectionStore(db).save_reflection("obj", "task", 1, "failed_assertion", "notes", "retry")

    data = collect_recovery_context(db, "task")

    assert data["reflection_storage"].startswith("sqlite:")
    assert data["reflections"][0]["recovery_hint"] == "retry"


def test_exit_status_mapping():
    assert exit_status_for_result({"final_status": "passed"}) == 0
    assert exit_status_for_result({"final_status": "failed"}) == 1
    assert exit_status_for_result({"final_status": "skipped"}) is None
