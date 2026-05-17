from pathlib import Path

import pytest

from trinity_pilot.audit.flight_record import FlightRecorder, utc_now
from trinity_pilot.audit.prerequisites import check_live_prerequisites
from trinity_pilot.audit.runner import desktop_typing_objective, run_orchestrator_audit


def _write_skipped_record(output_root: Path, prereq_result) -> None:
    recorder = FlightRecorder.start(output_root, prefix="audit-skip")
    now = utc_now()
    recorder.finalize(
        {
            "run_id": recorder.run_id,
            "task_id": recorder.run_id,
            "execution_path": "prerequisite-check",
            "objectives": [],
            "signals": [],
            "attempts": [],
            "evidence": {"prerequisites": prereq_result.to_dict()},
            "reviewer": {"verdict": "skipped", "failure_reason": None, "recovery_hint": ""},
            "recovery": {"intentional_failure": False, "second_attempt_changed": None},
            "artifact_checks": [
                {
                    "name": "live_prerequisites",
                    "passed": False,
                    "reason": ",".join(issue.code for issue in prereq_result.missing),
                }
            ],
            "started_at": now,
            "ended_at": now,
            "final_status": "skipped",
        }
    )


@pytest.mark.real
@pytest.mark.live_audit
async def test_live_desktop_visible_typing_audit(tmp_path):
    output_root = Path(".audit-runs")
    prereqs = check_live_prerequisites(output_root)
    if not prereqs.passed:
        _write_skipped_record(output_root, prereqs)
        pytest.skip(f"live audit prerequisites missing: {','.join(issue.code for issue in prereqs.missing)}")

    record = await run_orchestrator_audit(
        desktop_typing_objective(f"trinity live audit {tmp_path.name}"),
        output_root=output_root,
        db_path=tmp_path / "live-audit.db",
    )

    assert record["final_status"] == "passed"
    assert record["execution_path"] == "AsyncTaskOrchestrator"
    assert record["artifact_checks"][0]["visible_text_match"] is True
