from trinity_pilot.audit.runner import desktop_typing_objective, run_orchestrator_audit
from trinity_pilot.core.types import FailureReason, ObjectiveSpec, ReviewResult


class _ChangingWorker:
    async def execute(self, spec: ObjectiveSpec) -> dict:
        steering = spec.metadata.get("steering_context")
        changed = bool(steering)
        return {
            "domain": spec.domain.value,
            "objective_id": spec.objective_id,
            "screenshot": None,
            "element_tree_snapshot": None,
            "action_log": ["type visible text"],
            "selected_action": "type",
            "typed_text": "fixed" if changed else "bad",
            "visible_text": spec.metadata.get("expected_text", "") if changed else "",
            "written_files": [],
            "degraded_mode": False,
            "error": None,
            "intentional_failure": not changed,
            "action_signature": {
                "action": "type",
                "args": ["fixed" if changed else "bad"],
                "steering_context": steering,
            },
        }


class _RecoveryReviewer:
    def __init__(self, provider: object) -> None:
        pass

    async def review(self, spec: ObjectiveSpec, evidence: dict) -> ReviewResult:
        if evidence.get("intentional_failure"):
            return ReviewResult(
                False,
                FailureReason.FAILED_ASSERTION,
                "intentional first-attempt audit failure",
                "change typed text using reflection hint",
            )
        return ReviewResult(True, notes="changed attempt passed")


async def test_active_orchestrator_audit_with_stubs(tmp_path, monkeypatch):
    import trinity_pilot.orchestrator.engine as engine
    from trinity_pilot.config import Settings

    monkeypatch.setattr(engine, "GeminiProvider", lambda **kwargs: object())
    monkeypatch.setattr(engine, "ObjectiveReviewer", _RecoveryReviewer)
    monkeypatch.setattr(engine.WorkerRouter, "route", lambda self, spec: _ChangingWorker())

    stub_settings = Settings(gemini_api_key="stub-key-for-testing")

    record = await run_orchestrator_audit(
        desktop_typing_objective("visible audit text"),
        output_root=tmp_path / "runs",
        db_path=tmp_path / "audit.db",
        settings=stub_settings,
    )

    assert record["execution_path"] == "AsyncTaskOrchestrator"
    assert record["final_status"] == "passed"
    assert any(signal["type"] == "SteeringMessage" for signal in record["signals"])
    assert len(record["attempts"]) == 2
    assert record["attempts"][0]["evidence"]["intentional_failure"] is True
    assert record["recovery"]["second_attempt_changed"] is True
    assert record["recovery"]["reflection_storage"].startswith("sqlite:")
    assert record["artifact_checks"][0]["visible_text_match"] is True
    run_dir = tmp_path / "runs" / record["run_id"]
    assert (run_dir / "flight-record.json").exists()
    assert (run_dir / "flight-summary.md").exists()
