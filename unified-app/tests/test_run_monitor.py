import json
from pathlib import Path

from mcp_server.run_monitor import RunEventRecorder
from orchestrator.database import HistoryManager, TaskStatus


def test_build_artifact_bundle_collects_prompt_response_and_screenshot_paths(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "_runtime"
    flight_dir = runtime_dir / "flight_reports" / "run_1"
    flight_dir.mkdir(parents=True)
    report_json = flight_dir / "report.json"
    report_json.write_text(
        json.dumps(
            {
                "artifacts": [
                    {"path": "ai_reasoning/prompts/001.txt", "type": "ai_reasoning_prompt"},
                    {"path": "ai_reasoning/responses/001.txt", "type": "ai_reasoning_response"},
                    {"path": "screenshot_end.jpg", "type": "screenshot"},
                ]
            }
        ),
        encoding="utf-8",
    )

    db_path = runtime_dir / "orchestrator_history.db"
    history = HistoryManager(db_path)
    history.create_task("run_1", "example", "web", plan_steps=["step"])
    history.start_task("run_1")
    history.add_step("run_1", 1, "first step")
    history.update_step_status(
        "run_1",
        1,
        TaskStatus.COMPLETED,
        result_data={"status": "success"},
        flight_report_path=str(report_json),
    )
    history.complete_task("run_1", result_data={"status": "success"})

    recorder = RunEventRecorder(history, runtime_dir)
    recorder.record_event("status_update", {"message": "started", "level": "info"}, task_id="run_1")
    bundle = recorder.build_artifact_bundle("run_1")

    assert bundle["task"]["task_id"] == "run_1"
    assert bundle["final_disposition"]["final_status"] == "success"
    assert any(path.endswith("001.txt") for path in bundle["prompt_paths"])
    assert any(path.endswith("001.txt") for path in bundle["response_paths"])
    assert any(path.endswith("screenshot_end.jpg") for path in bundle["screenshot_paths"])


def test_run_monitor_tracks_drift_state_and_terminal_sessions(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "_runtime"
    terminal_dir = runtime_dir / "terminal_sessions"
    terminal_dir.mkdir(parents=True)

    db_path = runtime_dir / "orchestrator_history.db"
    history = HistoryManager(db_path)
    history.create_task("run_2", "example", "web", plan_steps=["step"])
    history.start_task("run_2")
    history.add_step("run_2", 1, "first step")
    history.update_step_status("run_2", 1, TaskStatus.FAILED, error_message="selector not found")
    history.complete_task(
        "run_2",
        error_message="selector not found",
        result_data={"status": "failed"},
        status=TaskStatus.FAILED,
    )

    (terminal_dir / "session_abc.json").write_text(
        json.dumps(
            {
                "id": "session_abc",
                "cwd": str(tmp_path),
                "purpose": "case-runner run_2",
                "created_at": 0,
                "updated_at": 9999999999,
                "status": "running",
                "events": [],
            }
        ),
        encoding="utf-8",
    )

    recorder = RunEventRecorder(history, runtime_dir)
    recorder._bind_task("run_2")
    recorder.record_event("status_update", {"message": "starting", "level": "info"}, task_id="run_2")
    recorder.record_event("policy_stop", {"reason": "bounded drift exceeded"}, task_id="run_2", status="policy_terminated")
    recorder._record_step_failure(1, {"error": "selector not found"})
    recorder._record_execution_complete({"status": "failed", "category": "failure"})
    bundle = recorder.build_artifact_bundle("run_2")

    assert bundle["final_disposition"]["drift_state"] == "terminal_failure"
    assert any(event["payload"]["state"] == "suspected_drift" for event in bundle["drift_history"])
    assert any(ref["session_id"] == "session_abc" for ref in bundle["terminal_session_references"])
