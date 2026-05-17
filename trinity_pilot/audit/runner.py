from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from trinity_pilot.audit.desktop_probe import verify_visible_text
from trinity_pilot.audit.flight_record import FlightRecorder, utc_now
from trinity_pilot.audit.recovery_drill import compare_attempts
from trinity_pilot.config import Settings
from trinity_pilot.core.types import AttemptLog, DomainType, ObjectiveSpec, ReviewResult, RiskClass
from trinity_pilot.memory.reflection import ReflectionStore
from trinity_pilot.memory.store import AttemptStore
from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def normalize_signal(signal: Any, order: int = 0) -> dict[str, Any]:
    payload = asdict(signal) if is_dataclass(signal) else dict(getattr(signal, "__dict__", {}))
    ts = payload.pop("ts", None)
    return {
        "order": order,
        "type": type(signal).__name__,
        "timestamp": ts,
        "source": "AsyncTaskOrchestrator",
        "payload_summary": {k: _json_safe(v) for k, v in payload.items()},
    }


def normalize_attempt(log: AttemptLog) -> dict[str, Any]:
    evidence = log.evidence or {}
    action = evidence.get("selected_action") or evidence.get("action") or evidence.get("action_signature", {}).get("action")
    paths = []
    for key, value in evidence.items():
        if key.endswith("_path") or key in {"path", "trace_path"}:
            paths.append(str(value))
    return {
        "attempt_id": log.attempt_id,
        "task_id": log.task_id,
        "objective_id": log.objective_id,
        "attempt_number": log.attempt_number,
        "action": action,
        "status": log.status,
        "failure_reason": log.failure_reason.value if log.failure_reason else None,
        "evidence_keys": sorted(evidence.keys()),
        "evidence_paths": paths,
        "error_summary": str(evidence.get("error") or "")[:500],
        "evidence": evidence,
    }


def normalize_reviewer_result(result: ReviewResult | dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {"verdict": "unavailable", "failure_reason": None, "recovery_hint": "", "notes": ""}
    if isinstance(result, ReviewResult):
        return {
            "verdict": "passed" if result.passed else "failed",
            "failure_reason": result.failure_reason.value if result.failure_reason else None,
            "recovery_hint": result.recovery_hint,
            "notes": result.notes,
        }
    return {
        "verdict": result.get("verdict") or ("passed" if result.get("passed") else "failed"),
        "failure_reason": result.get("failure_reason"),
        "recovery_hint": result.get("recovery_hint", ""),
        "notes": result.get("notes", ""),
    }


def collect_recovery_context(db_path: str | Path, task_id: str) -> dict[str, Any]:
    rows = ReflectionStore(db_path).get_all_reflections(task_id)
    if not rows:
        return {
            "reflections": [],
            "reflection_storage": None,
            "reflection_unavailable_reason": "no reflection rows for task",
        }
    return {
        "reflections": rows,
        "reflection_storage": f"sqlite:{Path(db_path)}#reflections/task_id={task_id}",
        "reflection_unavailable_reason": None,
    }


def exit_status_for_result(result: dict[str, Any]) -> int | None:
    status = result.get("final_status") or result.get("status")
    if status == "passed" or status == "completed":
        return 0
    if status == "skipped":
        return None
    return 1


async def drain_signals(queue: asyncio.Queue, stop: asyncio.Event, sink: list[dict[str, Any]]) -> None:
    order = 0
    while not stop.is_set() or not queue.empty():
        try:
            signal = await asyncio.wait_for(queue.get(), timeout=0.05)
        except asyncio.TimeoutError:
            continue
        order += 1
        sink.append(normalize_signal(signal, order))


def desktop_typing_objective(expected_text: str) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="desktop-visible-typing",
        goal=f"Open Notepad and type this exact text visibly: {expected_text}",
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop", "typing"],
        risk_class=RiskClass.LOW,
        preconditions=["Windows interactive desktop"],
        success_tests=["expected text is visible in Notepad or screenshot-backed text"],
        evidence_bundle=["action_log", "screenshot", "visible_text"],
        max_attempts=2,
        rollback_or_abort_rule="close spawned editor",
        metadata={"expected_text": expected_text, "audit_requires_visible_text": True},
    )


async def run_orchestrator_audit(
    objective: ObjectiveSpec,
    *,
    output_root: str | Path = ".audit-runs",
    db_path: str | Path | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    recorder = FlightRecorder.start(output_root)
    started_at = utc_now()
    db = Path(db_path or recorder.run_dir / "audit.db")
    queue: asyncio.Queue = asyncio.Queue()
    active_settings = settings or Settings.from_env()
    active_settings.db_path = str(db)
    orchestrator = AsyncTaskOrchestrator(
        active_settings,
        db_path=str(db),
        signals=queue,
    )
    signals: list[dict[str, Any]] = []
    stop = asyncio.Event()
    collector = asyncio.create_task(drain_signals(queue, stop, signals))
    result: dict[str, Any]
    try:
        result = await orchestrator.run(objective.goal, task_id=recorder.run_id, objectives=[objective])
    finally:
        stop.set()
        await collector

    attempts = [normalize_attempt(a) for a in AttemptStore(db).get_attempts_by_task(recorder.run_id)]
    recovery_context = collect_recovery_context(db, recorder.run_id)
    artifact_checks = []
    evidence = attempts[-1]["evidence"] if attempts else {}
    if objective.metadata.get("audit_requires_visible_text"):
        probe = verify_visible_text(
            str(objective.metadata.get("expected_text", "")),
            uia_text=str(evidence.get("visible_text", "")),
            screenshot_text=str(evidence.get("screenshot_text", "")),
            file_paths=[str(p) for p in evidence.get("written_files", [])],
            observed_actions=evidence.get("action_log", []),
        )
        artifact_checks.append({"name": "visible_text", "passed": probe.passed, **probe.to_dict()})
    recovery = {**recovery_context, "intentional_failure": False, "second_attempt_changed": None}
    if len(attempts) >= 2:
        drill = compare_attempts(attempts[0], attempts[1], reflections=recovery_context["reflections"])
        recovery.update(drill.to_dict())
    reviewer_payload = next(
        (attempt["evidence"].get("reviewer") for attempt in reversed(attempts) if attempt["evidence"].get("reviewer")),
        evidence.get("reviewer"),
    )

    final_status = "passed" if result.get("status") == "completed" and all(c.get("passed", True) for c in artifact_checks) and recovery.get("passed", True) else "failed"
    record = {
        "run_id": recorder.run_id,
        "task_id": recorder.run_id,
        "execution_path": "AsyncTaskOrchestrator",
        "objectives": [objective.to_dict()],
        "signals": signals,
        "attempts": attempts,
        "evidence": evidence,
        "reviewer": normalize_reviewer_result(reviewer_payload),
        "recovery": recovery,
        "artifact_checks": artifact_checks,
        "started_at": started_at,
        "ended_at": utc_now(),
        "final_status": final_status,
    }
    recorder.finalize(record)
    return record
