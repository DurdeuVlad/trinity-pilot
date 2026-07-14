from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from trinity_pilot.config import Settings
from trinity_pilot.core.types import (
    AttemptLog,
    FailureReason,
    ObjectiveSpec,
    RiskClass,
    TaskRecord,
    TaskStatus,
)
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.mcp.client_pool import MCPClientPool
from trinity_pilot.memory.reflection import ReflectionStore
from trinity_pilot.memory.store import AttemptStore, ObjectiveStateStore, TaskStore
from trinity_pilot.orchestrator.analyser import OrchestratorAnalyser, SteerDecision
from trinity_pilot.orchestrator.budget import BudgetExceeded, ObjectiveBudget
from trinity_pilot.orchestrator.fsm import ObjectiveState
from trinity_pilot.orchestrator.scheduler import DAGScheduler
from trinity_pilot.orchestrator.signals import (
    BudgetWarning,
    ObjectiveDone,
    ObjectiveFailed,
    ObjectiveStarted,
    Signal,
    SteeringMessage,
    StepCompleted,
    StuckSignal,
)
from trinity_pilot.planner.dag import infer_cross_domain_independence, resolve_execution_order
from trinity_pilot.planner.planner import ObjectivePlanner
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.router import WorkerRouter
from trinity_pilot.workers.worker_result import WorkerResult

# Evidence keys safe to forward into a dependent objective's prompt context —
# small, text-only facts a downstream worker needs (e.g. a captured page title).
# Excludes large/binary fields (screenshot, dom_snapshot) that would bloat the
# next objective's LLM context without adding anything it can act on.
_PORTABLE_EVIDENCE_KEYS = (
    "page_title",
    "page_url",
    "written_files",
    "written_files_verified",
    "worker_result_summary",
    "visible_text",
    "stdout",
    "exit_code",
    "workspace",
)


def _resolve_dependency_templates(value: Any, dependency_evidence: dict[str, dict[str, Any]]) -> Any:
    """Resolve planner references to output from prerequisite objectives."""
    if isinstance(value, dict):
        return {key: _resolve_dependency_templates(item, dependency_evidence) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_dependency_templates(item, dependency_evidence) for item in value]
    if not isinstance(value, str):
        return value

    import re

    def replace(match: re.Match[str]) -> str:
        objective_id, field = match.group(1), match.group(2)
        found = dependency_evidence.get(objective_id, {}).get(field)
        return str(found) if found is not None else match.group(0)

    return re.sub(r"\{\{dependency:([^:}]+):([^}]+)\}\}", replace, value)


def _portable_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Extract the small, text-only subset of an objective's evidence that's
    safe and useful to forward into a dependent objective's prompt context."""
    portable: dict[str, Any] = {
        k: v for k, v in evidence.items()
        if k in _PORTABLE_EVIDENCE_KEYS or k.startswith("file_content_")
    }
    return portable


@dataclass
class OrchestratorSnapshot:
    current_objective: str | None = None
    completed_objectives: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING


class AsyncTaskOrchestrator:
    """Local asyncio task orchestrator."""

    def __init__(
        self,
        settings: Settings,
        *,
        db_path: str | None = None,
        signals: asyncio.Queue[Signal] | None = None,
    ) -> None:
        self._settings = settings
        self._db_path = db_path or settings.db_path
        self.signals: asyncio.Queue[Signal] = signals or asyncio.Queue()
        self._task_store = TaskStore(self._db_path)
        self._attempt_store = AttemptStore(self._db_path)
        self._reflection_store = ReflectionStore(self._db_path)
        self._objective_store = ObjectiveStateStore(self._db_path)
        self._router = WorkerRouter()
        self._mcp_pool = MCPClientPool()
        self._cancel_requested = asyncio.Event()
        self._snapshot = OrchestratorSnapshot()

    @property
    def snapshot(self) -> OrchestratorSnapshot:
        return OrchestratorSnapshot(
            current_objective=self._snapshot.current_objective,
            completed_objectives=list(self._snapshot.completed_objectives),
            status=self._snapshot.status,
        )

    def cancel(self) -> None:
        self._cancel_requested.set()

    async def plan(self, user_request: str) -> list[ObjectiveSpec]:
        provider = GeminiProvider(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_planner_model,
        )
        return await ObjectivePlanner(provider).plan(user_request)

    async def run(
        self,
        user_request: str,
        *,
        task_id: str | None = None,
        objectives: list[ObjectiveSpec] | None = None,
    ) -> dict[str, Any]:
        from trinity_pilot.telemetry.trace import emit

        task_id = task_id or str(uuid.uuid4())
        emit(
            "engine.py:run",
            "orchestrator_run_start",
            {"task_id": task_id, "request_preview": user_request[:120]},
            span="orchestrator",
        )
        self._snapshot.status = TaskStatus.RUNNING
        self._task_store.save_task(
            TaskRecord(
                task_id=task_id,
                user_request=user_request,
                objectives=objectives or [],
                status=TaskStatus.RUNNING,
            )
        )

        try:
            raw_plan = objectives if objectives is not None else await self.plan(user_request)
            planned = infer_cross_domain_independence(resolve_execution_order(raw_plan))
            self._task_store.save_task(
                TaskRecord(
                    task_id=task_id,
                    user_request=user_request,
                    objectives=planned,
                    status=TaskStatus.RUNNING,
                )
            )
            results: dict[str, Any] = {}

            async def run_scheduled_objective(spec: ObjectiveSpec) -> dict[str, Any]:
                if self._cancel_requested.is_set():
                    return {"status": "cancelled", "failure_reason": "cancelled"}
                dep_ids = list(spec.dependencies or [])
                if dep_ids:
                    # Safe under concurrent dispatch: the scheduler only starts
                    # this objective after dependencies are complete, and each
                    # objective writes exclusively to results[objective_id].
                    dep_evidence = {
                        dep_id: _portable_evidence(results[dep_id].get("evidence", {}))
                        for dep_id in dep_ids
                        if dep_id in results
                    }
                    if dep_evidence:
                        spec.metadata["dependency_evidence"] = dep_evidence
                        spec.metadata = _resolve_dependency_templates(spec.metadata, dep_evidence)
                return await self._run_objective(task_id, spec)

            scheduler = DAGScheduler(planned, run_scheduled_objective, results=results)
            await scheduler.run()
            if any(result.get("status") == "cancelled" for result in results.values()):
                return self._finish(task_id, TaskStatus.CANCELLED, results)
            if any(result.get("status") != "passed" for result in results.values()):
                return self._finish(task_id, TaskStatus.FAILED, results)
            return self._finish(task_id, TaskStatus.COMPLETED, results)
        except asyncio.CancelledError:
            self.cancel()
            return self._finish(task_id, TaskStatus.CANCELLED, {})
        except Exception as exc:  # noqa: BLE001
            self._task_store.update_status(task_id, TaskStatus.FAILED)
            self._snapshot.status = TaskStatus.FAILED
            return {"task_id": task_id, "status": "failed", "error": str(exc)}
        finally:
            await self._mcp_pool.aclose()

    async def _run_objective(self, task_id: str, spec: ObjectiveSpec) -> dict[str, Any]:
        from trinity_pilot.telemetry.trace import emit

        budget = ObjectiveBudget.default()
        objective_id = spec.objective_id
        self._snapshot.current_objective = objective_id
        emit(
            "engine.py:_run_objective",
            "objective_start",
            {"task_id": task_id, "objective_id": objective_id, "domain": spec.domain.value},
            span="orchestrator",
        )
        self._objective_store.upsert(task_id, objective_id, ObjectiveState.RUNNING)
        await self.signals.put(ObjectiveStarted(task_id, objective_id))

        mcp_dispatch = getattr(self._settings, "mcp_dispatch_enabled", False)
        worker = None
        if not mcp_dispatch:
            worker = self._router.route(spec)
            worker._signals_queue = self.signals
            worker._task_id = task_id
        reviewer_provider = GeminiProvider(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_worker_model,
        )
        reviewer = ObjectiveReviewer(reviewer_provider)
        analyser_provider = GeminiProvider(
            api_key=self._settings.gemini_api_key,
            model=self._settings.gemini_worker_model,
        )
        analyser = OrchestratorAnalyser(analyser_provider)
        last_evidence: dict[str, Any] = {}
        retry_context: list[dict[str, Any]] = []

        for attempt_number in range(1, spec.max_attempts + 1):
            if self._cancel_requested.is_set():
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    failure_reason="cancelled",
                )
                return {"status": "cancelled", "attempts": attempt_number - 1}

            attempt_id = str(uuid.uuid4())
            if retry_context:
                spec.metadata["retry_context"] = retry_context
                spec.metadata["steering_context"] = {
                    "source": "reviewer_reflection",
                    "latest_recovery_hint": retry_context[-1].get("recovery_hint", ""),
                    "latest_reflection_id": retry_context[-1].get("reflection_id", ""),
                }
            self._attempt_store.log_attempt(
                AttemptLog(attempt_id, objective_id, task_id, attempt_number, "running")
            )
            try:
                budget.charge_step()
                if mcp_dispatch:
                    evidence = await self._mcp_pool.dispatch(spec.domain, spec)
                else:
                    evidence = await worker.execute(spec)
                last_evidence = dict(evidence)
                # If worker definitively failed, skip reviewer -- no need to retry
                if evidence.get("worker_result_status") == "failure":
                    failure_summary = evidence.get("worker_result_summary", "Worker declared definitive failure")
                    self._attempt_store.log_attempt(
                        AttemptLog(
                            attempt_id, objective_id, task_id, attempt_number, "failed",
                            FailureReason.FAILED_ASSERTION,
                            {**evidence, "worker_declared_failure": True},
                        )
                    )
                    self._objective_store.upsert(
                        task_id, objective_id, ObjectiveState.FAILED,
                        step_count=budget.steps_used(), token_count=budget.tokens_used(),
                        failure_reason="worker_declared_failure",
                    )
                    await self.signals.put(ObjectiveFailed(task_id, objective_id, "worker_declared_failure"))
                    return {"status": "failed", "failure_reason": "worker_declared_failure", "evidence": evidence}
                await self.signals.put(
                    StepCompleted(
                        task_id,
                        objective_id,
                        attempt_number,
                        spec.domain.value,
                        str(hash(repr(sorted(last_evidence.items())))),
                        0,
                    )
                )
                review = await reviewer.review(spec, last_evidence)
                if review.passed:
                    self._attempt_store.log_attempt(
                        AttemptLog(
                            attempt_id,
                            objective_id,
                            task_id,
                            attempt_number,
                            "passed",
                            evidence={**last_evidence, "notes": review.notes},
                        )
                    )
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.DONE,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                    )
                    self._snapshot.completed_objectives.append(objective_id)
                    await self.signals.put(ObjectiveDone(task_id, objective_id))
                    return {
                        "status": "passed",
                        "attempts": attempt_number,
                        "evidence": last_evidence,
                        # Bubble worker finish-summary up so the UI can synthesise a reply.
                        "summary": last_evidence.get("worker_result_summary", ""),
                    }

                reason = review.failure_reason or FailureReason.FAILED_ASSERTION
                reflection_id = self._reflection_store.save_reflection(
                    objective_id=objective_id,
                    task_id=task_id,
                    attempt_number=attempt_number,
                    failure_reason=reason.value,
                    notes=review.notes,
                    recovery_hint=review.recovery_hint,
                )
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id,
                        objective_id,
                        task_id,
                        attempt_number,
                        "failed",
                        reason,
                        {
                            **last_evidence,
                            "notes": review.notes,
                            "reviewer": {
                                "passed": review.passed,
                                "failure_reason": reason.value,
                                "notes": review.notes,
                                "recovery_hint": review.recovery_hint,
                            },
                            "recovery_hint": review.recovery_hint,
                            "reflection_id": reflection_id,
                            "reflection_storage": f"sqlite:{self._db_path}#reflections/{reflection_id}",
                        },
                    )
                )
                retry_context = self._reflection_store.get_reflections(objective_id)
                await self.signals.put(
                    SteeringMessage(
                        task_id,
                        objective_id,
                        review.recovery_hint or "Retry with reviewer reflection context",
                    )
                )
            except BudgetExceeded as exc:
                await self.signals.put(BudgetWarning(task_id, objective_id, exc.budget_type))
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    failure_reason=exc.budget_type,
                )
                await self.signals.put(ObjectiveFailed(task_id, objective_id, exc.budget_type))
                return {"status": "failed", "failure_reason": exc.budget_type}
            except asyncio.TimeoutError:
                await self.signals.put(ObjectiveFailed(task_id, objective_id, "worker_timeout"))
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    failure_reason="worker_timeout",
                )
                return {"status": "failed", "failure_reason": "worker_timeout"}
            except WorkerBlocker as exc:
                last_evidence = {**exc.result.evidence, "blocker_reason": str(exc)}
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id,
                        objective_id,
                        task_id,
                        attempt_number,
                        "failed",
                        FailureReason.ENVIRONMENT_DIVERGENCE,
                        last_evidence,
                    )
                )
                retry_context = self._reflection_store.get_reflections(objective_id)
                steer: SteerDecision = await self._analyse_and_steer(
                    analyser, spec, retry_context, str(exc)
                )
                if steer.action == "auto_steer":
                    spec.metadata.setdefault("steering_context", {})
                    if isinstance(spec.metadata["steering_context"], dict):
                        spec.metadata["steering_context"]["latest_recovery_hint"] = steer.guidance
                    else:
                        spec.metadata["steering_context"] = {"latest_recovery_hint": steer.guidance}
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.STUCK,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                    )
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.STEERED,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                    )
                    await self.signals.put(
                        SteeringMessage(
                            task_id,
                            objective_id,
                            steer.guidance or "Retrying with auto-steer guidance",
                        )
                    )
                    continue  # next iteration of for attempt_number loop
                else:  # ask_user
                    question = steer.question or "The worker encountered a blocker. Please advise on how to proceed."
                    self._objective_store.upsert(
                        task_id,
                        objective_id,
                        ObjectiveState.STUCK,
                        step_count=budget.steps_used(),
                        token_count=budget.tokens_used(),
                        user_question=question,
                    )
                    await self.signals.put(
                        StuckSignal(
                            task_id,
                            objective_id,
                            "worker_blocker",
                            attempt_number,
                            question,
                        )
                    )
                    return {"status": "failed", "failure_reason": "blocker_needs_user_input"}
            except WorkerError as exc:
                # Preserve any evidence built before the error; add error field.
                last_evidence = {**last_evidence, "error": str(exc)}
                self._attempt_store.log_attempt(
                    AttemptLog(
                        attempt_id,
                        objective_id,
                        task_id,
                        attempt_number,
                        "failed",
                        FailureReason.ENVIRONMENT_DIVERGENCE,
                        last_evidence,
                    )
                )
                err_lower = str(exc).lower()
                reason = "worker_timeout" if "timeout" in err_lower or "timed out" in err_lower else "worker_error"
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.FAILED,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    failure_reason=reason,
                )
                await self.signals.put(ObjectiveFailed(task_id, objective_id, reason))
                return {
                    "status": "failed",
                    "failure_reason": reason,
                    "evidence": last_evidence,
                }

            stuck = attempt_number >= getattr(self._settings, "stuck_threshold_steps", 5)
            if stuck:
                question = "The objective is not making progress. Adjust the objective or stop?"
                self._objective_store.upsert(
                    task_id,
                    objective_id,
                    ObjectiveState.STUCK,
                    step_count=budget.steps_used(),
                    token_count=budget.tokens_used(),
                    user_question=question,
                )
                await self.signals.put(
                    StuckSignal(task_id, objective_id, "repeated_failed_attempts", attempt_number, question)
                )

        self._objective_store.upsert(
            task_id,
            objective_id,
            ObjectiveState.FAILED,
            step_count=budget.steps_used(),
            token_count=budget.tokens_used(),
            failure_reason="max_attempts_exceeded",
        )
        await self.signals.put(ObjectiveFailed(task_id, objective_id, "max_attempts_exceeded"))
        return {"status": "failed", "attempts": spec.max_attempts, "evidence": last_evidence}

    async def _analyse_and_steer(
        self,
        analyser: OrchestratorAnalyser,
        spec: ObjectiveSpec,
        retry_context: list[dict],
        blocker_reason: str,
    ) -> SteerDecision:
        """Call the analyser with a risk-tier timeout; fall back to auto_steer on any failure."""
        timeout = 8.0 if spec.risk_class == RiskClass.LOW else 15.0
        try:
            return await asyncio.wait_for(
                analyser.analyse(spec, retry_context, blocker_reason),
                timeout=timeout,
            )
        except Exception:
            return SteerDecision(action="auto_steer", guidance=blocker_reason)

    def _finish(
        self,
        task_id: str,
        status: TaskStatus,
        results: dict[str, Any],
    ) -> dict[str, Any]:
        from trinity_pilot.telemetry.trace import emit, export_attempts_json, _trace_dir
        import sys
        from pathlib import Path

        self._task_store.update_status(task_id, status)
        self._snapshot.current_objective = None
        self._snapshot.status = status
        attempts_path = export_attempts_json(
            task_id, self._attempt_store.get_attempts_by_task(task_id)
        )
        emit(
            "engine.py:_finish",
            "orchestrator_run_finish",
            {
                "task_id": task_id,
                "status": status.value,
                "attempts_file": str(attempts_path) if attempts_path else None,
            },
            span="orchestrator",
        )

        try:
            write_run_reports(task_id, status.value, results, _trace_dir())
        except Exception as e:
            print(f"[orchestrator] Failed to write reports: {e}", file=sys.stderr)

        out: dict[str, Any] = {"task_id": task_id, "status": status.value, "results": results}
        if attempts_path:
            out["attempts_file"] = str(attempts_path)
        return out


def write_run_reports(task_id: str, status: str, results: dict[str, Any], trace_dir: Path) -> None:
    import json
    from datetime import datetime
    
    trace_path = trace_dir / "trinity-trace.jsonl"
    events = []
    if trace_path.exists():
        try:
            with open(trace_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        data = entry.get("data", {})
                        matches = False
                        if isinstance(data, dict):
                            if data.get("task_id") == task_id or data.get("taskId") == task_id:
                                matches = True
                        if matches:
                            events.append(entry)
                    except Exception:
                        continue
        except Exception as e:
            import sys
            print(f"[trace] Error reading trace file: {e}", file=sys.stderr)

    # Build report dict
    report_json = {
        "task_id": task_id,
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "events": events,
    }
    
    # Write to unique file and also static filename (for easy E2E pull)
    for name in (f"run_report_{task_id}.json", "run_report.json"):
        report_json_path = trace_dir / name
        try:
            report_json_path.write_text(json.dumps(report_json, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            import sys
            print(f"[trace] Error writing {name}: {e}", file=sys.stderr)

    # Build run_report.md
    md = []
    md.append(f"# Trinity Pilot Task Report — {task_id}")
    md.append("")
    md.append(f"- **Status:** {status}")
    md.append(f"- **Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md.append("")
    
    md.append("## Objectives Results")
    if results:
        for obj_id, res in results.items():
            st = res.get("status", "unknown")
            md.append(f"### Objective: `{obj_id}` — **{st.upper()}**")
            for k, v in res.items():
                if k not in ("status", "objective_id"):
                    md.append(f"- **{k}:** `{v}`")
            md.append("")
    else:
        md.append("No objective results logged.")
        md.append("")

    md.append("## Execution Timeline")
    if events:
        md.append("| Timestamp | Location | Event | Details |")
        md.append("|---|---|---|---|")
        for ev in sorted(events, key=lambda x: x.get("ts", 0)):
            ts_str = datetime.fromtimestamp(ev.get("ts", 0) / 1000.0).strftime('%H:%M:%S.%f')[:-3]
            loc = ev.get("location", "")
            msg = ev.get("message", "")
            data_str = json.dumps(ev.get("data", {}))
            md.append(f"| {ts_str} | `{loc}` | {msg} | `{data_str}` |")
    else:
        md.append("No trace events found for this task.")
        
    for name in (f"run_report_{task_id}.md", "run_report.md"):
        report_md_path = trace_dir / name
        try:
            report_md_path.write_text("\n".join(md), encoding="utf-8")
        except Exception as e:
            import sys
            print(f"[trace] Error writing {name}: {e}", file=sys.stderr)

