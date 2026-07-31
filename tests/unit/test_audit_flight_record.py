import pytest

from trinity_pilot.audit.flight_record import (
    FlightRecorder,
    render_markdown_summary,
    validate_record,
)


def _record(run_id="placeholder"):
    return {
        "run_id": run_id,
        "task_id": "task-1",
        "execution_path": "AsyncTaskOrchestrator",
        "objectives": [{"objective_id": "obj", "goal": "do it"}],
        "signals": [],
        "attempts": [{"attempt_number": 1, "status": "passed", "action": "type", "evidence_keys": ["typed_text"], "error_summary": ""}],
        "evidence": {"typed_text": "hello"},
        "reviewer": {"verdict": "passed", "failure_reason": None, "recovery_hint": ""},
        "recovery": {"intentional_failure": False, "second_attempt_changed": None},
        "artifact_checks": [{"name": "visible_text", "passed": True}],
        "started_at": "2026-05-13T00:00:00+00:00",
        "ended_at": "2026-05-13T00:00:01+00:00",
        "final_status": "passed",
    }


def test_primary_files_are_exactly_one_pair(tmp_path):
    recorder = FlightRecorder.start(tmp_path)
    json_path, md_path = recorder.finalize(_record(recorder.run_id))

    assert json_path.name == "flight-record.json"
    assert md_path.name == "flight-summary.md"
    assert len(list(recorder.run_dir.glob("*.json"))) == 1
    assert len(list(recorder.run_dir.glob("*.md"))) == 1


def test_required_json_schema_validation():
    validate_record(_record())
    bad = _record()
    bad.pop("attempts")

    with pytest.raises(ValueError, match="attempts"):
        validate_record(bad)


def test_markdown_summary_required_fields():
    summary = render_markdown_summary(_record())

    assert "Execution path" in summary
    assert "Objectives" in summary
    assert "Attempts" in summary
    assert "Reviewer" in summary
    assert "Recovery" in summary
    assert "Artifact Checks" in summary


def test_unique_run_ids(tmp_path):
    first = FlightRecorder.start(tmp_path)
    second = FlightRecorder.start(tmp_path)

    assert first.run_id != second.run_id
    assert first.run_dir != second.run_dir
