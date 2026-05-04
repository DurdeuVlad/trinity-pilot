"""Trinity Core objective orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib.request import Request, urlopen

from .config import TrinityConfig
from .executor import TaskQueue
from .llm import build_runtime_llm_provider
from .llm.llm_provider import LLMProvider
from .models import (
    ObjectiveEvidence,
    ObjectivePlan,
    ObjectivePreflightResult,
    SubObjective,
    SubObjectiveResult,
    TaskInput,
    TaskResult,
    failure_code,
    is_retriable,
)
from .objective_planner import ObjectivePlanner
from .strategy_registry import StrategyRegistry
from .sub_objective_executor import SubObjectiveExecutor
from .telemetry import (
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_STARTED,
    TASK_SUCCEEDED,
    emit_event,
    make_event_payload,
)
from .verification import _extract_desktop_file_target

logger = logging.getLogger(__name__)


class ObjectiveOrchestrator:
    """Owns one objective until it is completed, blocked, or proven impossible."""

    def __init__(
        self,
        config: Optional[TrinityConfig] = None,
        llm_provider_factory: Callable[[], LLMProvider] | None = None,
    ):
        if config is None:
            config = TrinityConfig.from_env()
        self.config = config

        if config.debug_mode:
            logging.basicConfig(level=logging.DEBUG)

        self.project_root = Path(__file__).resolve().parents[1]
        self.strategy_registry = StrategyRegistry.create_default(self.project_root)
        self._llm_provider = (llm_provider_factory or (lambda: build_runtime_llm_provider(config)))()

        self.task_queue = TaskQueue(name="serial_sub_objective_queue")
        self.browser_semaphore = asyncio.Semaphore(config.max_concurrent_browser_tasks)
        self.initialized = False

    def _build_sub_objective_executor(self, strategy_id: str) -> SubObjectiveExecutor:
        strategy = self.strategy_registry.get(strategy_id)
        _audit_config = None
        try:
            from audit_debugger import AuditConfig
            _audit_config = AuditConfig(output_dir=self.config.flight_reports_dir)
        except ImportError:
            pass
        return SubObjectiveExecutor(strategy, llm_provider=self._llm_provider, audit_config=_audit_config)

    def _resolve_target_server(self, task: TaskInput) -> str:
        explicit = (task.target_server or "").strip()
        if explicit:
            return explicit

        compat_context = str(task.context.get("target_server", "") or "").strip()
        if compat_context:
            return compat_context

        # Dynamic fallback: find the first strategy that matches the domain
        for strategy in self.strategy_registry.list():
            if strategy.domain == task.domain:
                logger.warning(
                    "Task %s did not provide target_server; falling back to domain default '%s'.",
                    task.task_id,
                    strategy.strategy_id,
                )
                return strategy.strategy_id

        raise KeyError(f"No MCP target configured for domain '{task.domain}'")

    def _timeout_for_domain(self, task: TaskInput) -> int:
        if task.domain == "desktop":
            return self.config.desktop.timeout
        if task.domain == "web":
            return self.config.browser.timeout
        if task.domain == "cli":
            return self.config.cli.timeout
        return self.config.default_timeout

    async def initialize(self):
        if self.initialized:
            logger.warning("ObjectiveOrchestrator already initialized")
            return
        await self.task_queue.start_worker()
        self.initialized = True
        logger.info("ObjectiveOrchestrator initialized")

    async def shutdown(self):
        if not self.initialized:
            return
        await self.task_queue.stop_worker()
        self.initialized = False
        logger.info("ObjectiveOrchestrator shutdown complete")

    async def execute(self, task: TaskInput) -> TaskResult:
        if not self.initialized:
            await self.initialize()

        logger.info("Executing objective %s", task.task_id)

        emit_event(TASK_STARTED, make_event_payload(
            task_id=task.task_id, domain=task.domain, adapter_name="objective_orchestrator"
        ))
        t0 = time.monotonic()

        try:
            result = await self._execute_objective(task, started_at=t0)
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            emit_event(TASK_FAILED, make_event_payload(
                task_id=task.task_id,
                domain=task.domain,
                adapter_name="objective_orchestrator",
                duration_ms=duration_ms,
                extra={"category": "planning_failed"},
            ))
            return self._failure_result(
                task=task,
                category="planning_failed",
                error=str(exc),
                objective_plan=None,
                sub_objective_results=[],
                evidence=ObjectiveEvidence(),
                duration_ms=duration_ms,
            )

        target_server = str(result.metadata.get("target_server") or "objective_orchestrator")
        duration_ms = (time.monotonic() - t0) * 1000
        if result.status == "failure" and result.category == "cancelled":
            emit_event(TASK_CANCELLED, make_event_payload(
                task_id=task.task_id, domain=task.domain, adapter_name=target_server, duration_ms=duration_ms
            ))
        elif result.status == "failure":
            emit_event(TASK_FAILED, make_event_payload(
                task_id=task.task_id,
                domain=task.domain,
                adapter_name=target_server,
                duration_ms=duration_ms,
                extra={"category": result.category, "code": result.code, "target_server": target_server},
            ))
        else:
            emit_event(TASK_SUCCEEDED, make_event_payload(
                task_id=task.task_id, domain=task.domain, adapter_name=target_server, duration_ms=duration_ms
            ))
        return result

    async def _execute_objective(self, task: TaskInput, *, started_at: float) -> TaskResult:
        planner = ObjectivePlanner(
            strategy_registry=self.strategy_registry,
            llm_provider=self._llm_provider,
        )
        try:
            objective_plan = await planner.plan(task)
        except Exception as first_exc:
            try:
                objective_plan = await planner.plan(task, validation_errors=[str(first_exc)])
            except Exception as second_exc:
                return self._failure_result(
                    task=task,
                    category="planning_failed",
                    error=str(second_exc),
                    objective_plan=None,
                    sub_objective_results=[],
                    evidence=ObjectiveEvidence(),
                    duration_ms=(time.monotonic() - started_at) * 1000,
                )

        sub_results: list[SubObjectiveResult] = []
        objective_evidence = ObjectiveEvidence()
        all_logs = []
        all_artifacts: list[str] = []
        final_outputs: list[str] = []
        run_context: list[dict] = []

        for sub_objective in objective_plan.sub_objectives:
            preflight = await self._preflight_sub_objective(sub_objective)
            if preflight.status == "failure":
                sub_result = SubObjectiveResult(
                    sub_objective_id=sub_objective.sub_objective_id,
                    status="failure",
                    category=preflight.category or "preflight_failed",
                    output="",
                    error=preflight.message,
                    target_server=sub_objective.target_server,
                    domain=sub_objective.domain,
                    evidence=preflight.evidence,
                )
                sub_results.append(sub_result)
                objective_evidence.failed_sub_objectives += 1
                return self._failure_result(
                    task=task,
                    category=preflight.category or "preflight_failed",
                    error=preflight.message,
                    objective_plan=objective_plan,
                    sub_objective_results=sub_results,
                    evidence=objective_evidence,
                    failed_sub_objective_id=sub_objective.sub_objective_id,
                    duration_ms=(time.monotonic() - started_at) * 1000,
                )

            sub_result, logs, artifacts = await self._execute_sub_objective(task, sub_objective, run_context=run_context)
            sub_results.append(sub_result)
            all_logs.extend(logs)
            all_artifacts.extend(artifacts)
            if sub_result.output:
                final_outputs.append(sub_result.output)
                objective_evidence.outputs.append(sub_result.output)
                run_context.append({
                    "sub_objective_id": sub_objective.sub_objective_id,
                    "objective": sub_objective.objective,
                    "domain": sub_objective.domain,
                    "output": sub_result.output,
                })
            objective_evidence.artifacts.extend(sub_result.artifacts)
            if sub_result.status == "success":
                objective_evidence.successful_sub_objectives += 1
            else:
                objective_evidence.failed_sub_objectives += 1
                return self._failure_result(
                    task=task,
                    category=sub_result.category or "sub_objective_failed",
                    error=sub_result.error or sub_result.output or "Sub-objective failed.",
                    objective_plan=objective_plan,
                    sub_objective_results=sub_results,
                    evidence=objective_evidence,
                    failed_sub_objective_id=sub_objective.sub_objective_id,
                    duration_ms=(time.monotonic() - started_at) * 1000,
                    execution_log=all_logs,
                    artifacts=all_artifacts,
                )

        output = "\n\n".join(final_outputs).strip() or "Objective completed."
        expected_sub_objectives = len(objective_plan.sub_objectives)
        if objective_evidence.successful_sub_objectives != expected_sub_objectives:
            missing = [
                sub.sub_objective_id
                for sub in objective_plan.sub_objectives
                if sub.sub_objective_id not in {result.sub_objective_id for result in sub_results}
            ]
            return self._failure_result(
                task=task,
                category="verification_failed",
                error=(
                    "Objective completed only "
                    f"{objective_evidence.successful_sub_objectives}/{expected_sub_objectives} "
                    f"sub-objectives. Missing: {', '.join(missing) if missing else 'none'}."
                ),
                objective_plan=objective_plan,
                sub_objective_results=sub_results,
                evidence=objective_evidence,
                duration_ms=(time.monotonic() - started_at) * 1000,
                execution_log=all_logs,
                artifacts=all_artifacts,
            )
        metadata = self._objective_metadata(
            objective_plan=objective_plan,
            sub_objective_results=sub_results,
            evidence=objective_evidence,
            failed_sub_objective_id=None,
            failure_reason=None,
            duration_ms=(time.monotonic() - started_at) * 1000,
        )
        metadata["output"] = output
        metadata["target_server"] = "objective_orchestrator"
        self._promote_single_sub_objective_metadata(metadata, sub_results)
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            code=None,
            retriable=False,
            error=None,
            execution_log=all_logs,
            artifacts=all_artifacts,
            metadata=metadata,
        )

    async def _execute_sub_objective(
        self,
        task: TaskInput,
        sub_objective: SubObjective,
        *,
        run_context: list[dict] | None = None,
    ) -> tuple[SubObjectiveResult, list, list[str]]:
        strategy = self.strategy_registry.get(sub_objective.target_server)
        health_runtime = self._build_sub_objective_executor(sub_objective.target_server)
        try:
            is_healthy, health_error = await health_runtime.health_check()
        finally:
            await health_runtime.close()
        if not is_healthy:
            message = health_error.format_for_user() if health_error else f"{sub_objective.target_server} strategy is not available"
            return (
                SubObjectiveResult(
                    sub_objective_id=sub_objective.sub_objective_id,
                    status="failure",
                    category="health_check_failed",
                    error=message,
                    target_server=sub_objective.target_server,
                    domain=sub_objective.domain,
                    evidence={"health_check_error": health_error.model_dump() if health_error else None},
                ),
                [],
                [],
            )

        merged_context = dict(task.context or {})
        merged_context.setdefault("parent_description", task.description)
        if task.sub_objectives:
            merged_context.setdefault("approved_plan", list(task.sub_objectives))
        if run_context:
            merged_context["prior_results"] = run_context
        expected_outcome = "\n".join(sub_objective.postconditions)
        if sub_objective.domain == "desktop":
            file_target = _extract_desktop_file_target(expected_outcome or sub_objective.objective)
            if file_target:
                expected_outcome = (
                    f"{expected_outcome}\n"
                    f"The file must exist at this exact absolute path: {file_target}\n"
                    "When typing a save path in a desktop dialog, type the absolute path literally. "
                    "Do not type environment variables such as %USERPROFILE%."
                )
        sub_task = task.model_copy(
            update={
                "task_id": f"{task.task_id}-{sub_objective.sub_objective_id}",
                "description": sub_objective.objective,
                "domain": sub_objective.domain,
                "target_server": sub_objective.target_server,
                "sub_objectives": [],
                "expected_outcome": expected_outcome,
                "timeout": sub_objective.timeout,
                "context": merged_context,
            }
        )
        timeout = sub_objective.timeout or self._timeout_for_domain(sub_task)
        if strategy.serial_execution:
            executor = self._build_sub_objective_executor(sub_objective.target_server)
            result = await self.task_queue.submit(sub_task.task_id, executor, sub_task, timeout=float(timeout))
        else:
            async with self.browser_semaphore:
                executor = self._build_sub_objective_executor(sub_objective.target_server)
                try:
                    result = await executor.execute(sub_task)
                finally:
                    await executor.close()

        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        metadata = payload.get("metadata") or {}
        output = str(metadata.get("output") or payload.get("error") or "")
        evidence = {
            "metadata": metadata,
            "verification": payload.get("verification"),
            "execution_log_count": len(payload.get("execution_log") or []),
        }
        return (
            SubObjectiveResult(
                sub_objective_id=sub_objective.sub_objective_id,
                status="success" if payload.get("status") == "success" else "failure",
                category=payload.get("category"),
                output=output,
                error=payload.get("error"),
                target_server=sub_objective.target_server,
                domain=sub_objective.domain,
                evidence=evidence,
                artifacts=list(payload.get("artifacts") or []),
                verification=payload.get("verification"),
            ),
            list(payload.get("execution_log") or []),
            list(payload.get("artifacts") or []),
        )

    async def _preflight_sub_objective(self, sub_objective: SubObjective) -> ObjectivePreflightResult:
        urls = _localhost_urls(sub_objective.objective)
        for url in urls:
            if not await asyncio.to_thread(_url_reachable, url):
                return ObjectivePreflightResult(
                    status="failure",
                    category="prerequisite_missing",
                    message=f"Required localhost service is not reachable: {url}",
                    evidence={"url": url},
                )
        return ObjectivePreflightResult(status="success")

    def _objective_metadata(
        self,
        *,
        objective_plan: ObjectivePlan | None,
        sub_objective_results: list[SubObjectiveResult],
        evidence: ObjectiveEvidence,
        failed_sub_objective_id: str | None,
        failure_reason: str | None,
        duration_ms: float,
    ) -> dict:
        total = len(sub_objective_results)
        successful = sum(1 for result in sub_objective_results if result.status == "success")
        planned = len(objective_plan.sub_objectives) if objective_plan else total
        completed_ids = {result.sub_objective_id for result in sub_objective_results}
        missing = [
            sub.sub_objective_id
            for sub in (objective_plan.sub_objectives if objective_plan else [])
            if sub.sub_objective_id not in completed_ids
        ]
        return {
            "objective_plan": objective_plan.model_dump() if objective_plan else None,
            "sub_objective_results": [result.model_dump() for result in sub_objective_results],
            "objective_evidence": evidence.model_dump(),
            "planned_sub_objectives": planned,
            "completed_sub_objectives": total,
            "successful_sub_objectives": successful,
            "failed_sub_objectives": sum(1 for result in sub_objective_results if result.status == "failure"),
            "missing_sub_objective_ids": missing,
            "failed_sub_objective_id": failed_sub_objective_id,
            "failure_reason": failure_reason,
            "completion_confidence": successful / planned if planned else 0.0,
            "duration_ms": duration_ms,
        }

    def _failure_result(
        self,
        *,
        task: TaskInput,
        category: str,
        error: str,
        objective_plan: ObjectivePlan | None,
        sub_objective_results: list[SubObjectiveResult],
        evidence: ObjectiveEvidence,
        duration_ms: float,
        failed_sub_objective_id: str | None = None,
        execution_log: list | None = None,
        artifacts: list[str] | None = None,
    ) -> TaskResult:
        metadata = self._objective_metadata(
            objective_plan=objective_plan,
            sub_objective_results=sub_objective_results,
            evidence=evidence,
            failed_sub_objective_id=failed_sub_objective_id,
            failure_reason=error,
            duration_ms=duration_ms,
        )
        metadata["target_server"] = "objective_orchestrator"
        metadata["reason"] = category
        self._promote_single_sub_objective_metadata(metadata, sub_objective_results)
        return TaskResult(
            task_id=task.task_id,
            status="failure",
            category=category,
            code=failure_code(category),
            retriable=is_retriable(category),
            error=error,
            execution_log=execution_log or [],
            artifacts=artifacts or [],
            metadata=metadata,
        )

    def _promote_single_sub_objective_metadata(
        self,
        metadata: dict,
        sub_objective_results: list[SubObjectiveResult],
    ) -> None:
        if len(sub_objective_results) != 1:
            return
        sub_result = sub_objective_results[0]
        metadata["strategy_id"] = sub_result.target_server
        metadata["target_server"] = sub_result.target_server
        metadata["domain"] = sub_result.domain
        metadata["sub_objective_category"] = sub_result.category
        sub_meta = sub_result.evidence.get("metadata")
        if not isinstance(sub_meta, dict):
            return
        for key in ("strategy_id", "target_server", "visible_tools", "visible_tool_metadata", "verification_status", "verification_summary"):
            if key in sub_meta:
                metadata[key] = sub_meta[key]

    async def health_check_all(self) -> Dict[str, bool]:
        results = {}
        for strategy in self.strategy_registry.list():
            runtime = self._build_sub_objective_executor(strategy.strategy_id)
            try:
                is_healthy, health_error = await runtime.health_check()
                results[strategy.strategy_id] = is_healthy
                if not is_healthy and health_error:
                    logger.error(f"Health check failed for {strategy.strategy_id}: {health_error.format_for_log()}")
            except Exception as exc:
                logger.error("Health check failed for %s: %s", strategy.strategy_id, exc, exc_info=True)
                results[strategy.strategy_id] = False
            finally:
                await runtime.close()
        return results

    async def get_capabilities_all(self) -> Dict[str, Dict]:
        """Return capability map for all registered strategies.

        Uses cached live_tools from enrichment if available (no subprocess needed).
        Falls back to live list_tools() query for unenriched strategies.
        """
        results = {}
        for strategy in self.strategy_registry.list():
            live_tools = strategy.metadata.get("live_tools")
            if live_tools is not None:
                results[strategy.strategy_id] = {
                    "strategy_id": strategy.strategy_id,
                    "target_server": strategy.strategy_id,
                    "domain": strategy.domain,
                    "description": strategy.description,
                    "serial_execution": strategy.serial_execution,
                    "tools": live_tools,
                    "enriched": True,
                }
            else:
                runtime = self._build_sub_objective_executor(strategy.strategy_id)
                try:
                    descriptors = await runtime.client.list_tools()
                    results[strategy.strategy_id] = {
                        "strategy_id": strategy.strategy_id,
                        "target_server": strategy.strategy_id,
                        "domain": strategy.domain,
                        "description": strategy.description,
                        "serial_execution": strategy.serial_execution,
                        "tools": [d.name for d in descriptors],
                        "enriched": False,
                    }
                except Exception as exc:
                    logger.warning(
                        "Capability query failed for %s; returning empty tool list: %s",
                        strategy.strategy_id,
                        exc,
                    )
                    results[strategy.strategy_id] = {
                        "strategy_id": strategy.strategy_id,
                        "target_server": strategy.strategy_id,
                        "domain": strategy.domain,
                        "description": strategy.description,
                        "serial_execution": strategy.serial_execution,
                        "tools": [],
                        "enriched": False,
                        "error": str(exc),
                    }
                finally:
                    await runtime.close()
        return results

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        llm_close = getattr(self._llm_provider, "close", None)
        if callable(llm_close):
            await llm_close()
        await self.shutdown()


def _localhost_urls(text: str) -> list[str]:
    matches = re.findall(r"https?://localhost:\d+(?:/[^\s,)]*)?", text or "", flags=re.IGNORECASE)
    normalized: list[str] = []
    for url in matches:
        cleaned = url.rstrip(".,;")
        if cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _url_reachable(url: str) -> bool:
    try:
        request = Request(url, method="GET")
        with urlopen(request, timeout=3) as response:
            return 200 <= response.status < 500
    except Exception:
        return False
