"""Persistent executor agent: one instance per task run, tool-changes per domain.

Implements the MCP "Dynamic Server Management" pattern from the official spec:
connect to a server only when needed, reuse the connection across objectives on
the same domain, disconnect when the run ends.

Within one asyncio.run() context, a SingleExecutorAgent caches one SubObjectiveExecutor
per strategy_id. The executor's MCPStrategyClient connects lazily on first use and
stays connected for the rest of the run. No health checks. No rebuilds.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from .models import TaskInput, TaskResult, failure_code, is_retriable
from .strategy_registry import StrategyRegistry
from .sub_objective_executor import SubObjectiveExecutor
from .llm.llm_provider import LLMProvider


class SingleExecutorAgent:
    """Persistent, in-process executor that swaps MCP domain servers between objectives.

    Usage pattern (per task run):
        agent = SingleExecutorAgent(registry, llm_provider)
        try:
            result = await agent.run_objectives(
                task_id="t1",
                task_description="Do X then Y",
                objectives=["Do X", "Do Y"],
                domain="cli",
            )
        finally:
            await agent.close()

    On same-domain objectives, the MCP subprocess is reused (no reconnect).
    On domain change, a new executor is created with its own lazy connection.
    """

    def __init__(
        self,
        strategy_registry: StrategyRegistry,
        llm_provider: LLMProvider,
    ) -> None:
        self._registry = strategy_registry
        self._llm = llm_provider
        self._executors: dict[str, SubObjectiveExecutor] = {}

    def suggest_domain(self, task: str) -> str:
        """Suggest a domain based on task description keywords."""
        return self._registry.suggest_domain(task)

    def _get_executor(self, strategy_id: str) -> SubObjectiveExecutor:
        """Return cached executor for strategy, creating it on first call."""
        if strategy_id not in self._executors:
            strategy = self._registry.get(strategy_id)
            self._executors[strategy_id] = SubObjectiveExecutor(
                strategy,
                llm_provider=self._llm,
            )
            logger.info("Created executor for strategy '%s'", strategy_id)
        return self._executors[strategy_id]

    async def run_objectives(
        self,
        task_id: str,
        task_description: str,
        objectives: list[str],
        domain: str,
    ) -> TaskResult:
        """Execute objectives sequentially, reusing domain connections within the run.

        Advisory verification: if the LLM executed >=1 successful tool call, the
        objective is considered done regardless of the verification gate verdict.
        Hard-fail only on unhandled exception or zero tool-call completions.
        """
        prior_results: list[dict[str, Any]] = []
        all_logs: list[Any] = []
        all_artifacts: list[str] = []

        for i, obj in enumerate(objectives):
            strategy_id = self._registry.suggest_strategy_for_objective(obj)
            executor = self._get_executor(strategy_id)

            merged_context: dict[str, Any] = {
                "parent_description": task_description,
                "approved_plan": list(objectives),
            }
            if prior_results:
                merged_context["prior_results"] = prior_results

            sub_task = TaskInput(
                task_id=f"{task_id}-obj{i}",
                description=obj,
                domain=executor.strategy.domain,
                target_server=strategy_id,
                context=merged_context,
            )

            try:
                result = await executor.execute(sub_task)
            except Exception as exc:
                logger.error(
                    "Objective %d ('%s') raised exception: %s",
                    i,
                    obj[:60],
                    exc,
                    exc_info=True,
                )
                return TaskResult(
                    task_id=task_id,
                    status="failure",
                    category="sub_objective_failed",
                    code=failure_code("sub_objective_failed"),
                    retriable=is_retriable("sub_objective_failed"),
                    error=str(exc),
                    execution_log=all_logs,
                    artifacts=all_artifacts,
                    metadata={"output": str(exc), "sub_results": prior_results},
                )

            payload = result.model_dump()
            meta = payload.get("metadata") or {}
            output = str(meta.get("output") or payload.get("error") or "")

            exec_log = payload.get("execution_log") or []
            had_successful_tool_call = any(
                entry.get("result") == "success" for entry in exec_log
            )

            if payload.get("status") == "failure" and not had_successful_tool_call:
                logger.warning(
                    "Objective %d ('%s') failed with no successful tool calls.",
                    i,
                    obj[:60],
                )
                return TaskResult(
                    task_id=task_id,
                    status="failure",
                    category="sub_objective_failed",
                    code=failure_code("sub_objective_failed"),
                    retriable=is_retriable("sub_objective_failed"),
                    error=output or "Sub-objective failed without completing any tool actions.",
                    execution_log=all_logs,
                    artifacts=all_artifacts,
                    metadata={"output": output, "sub_results": prior_results},
                )

            if payload.get("status") == "failure" and had_successful_tool_call:
                logger.info(
                    "Objective %d ('%s'): verification advisory — tool work was done, continuing.",
                    i,
                    obj[:60],
                )

            prior_results.append({
                "sub_objective_id": f"obj{i}",
                "domain": executor.strategy.domain,
                "objective": obj,
                "output": output,
            })
            all_logs.extend(result.execution_log)
            all_artifacts.extend(payload.get("artifacts") or [])

        final_output = prior_results[-1]["output"] if prior_results else "Done."
        return TaskResult(
            task_id=task_id,
            status="success",
            category="success",
            code=None,
            retriable=False,
            error=None,
            execution_log=all_logs,
            artifacts=all_artifacts,
            metadata={"output": final_output, "sub_results": prior_results},
        )

    async def close(self) -> None:
        """Disconnect all cached MCP clients cleanly."""
        for strategy_id, executor in list(self._executors.items()):
            try:
                await executor.close()
                logger.info("Closed executor for strategy '%s'", strategy_id)
            except Exception as exc:
                logger.warning(
                    "Error closing executor for '%s': %s", strategy_id, exc
                )
        self._executors.clear()
