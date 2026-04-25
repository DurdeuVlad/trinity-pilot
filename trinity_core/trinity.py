"""Unified Trinity executor using desktop-selected MCP server targets."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from .config import TrinityConfig
from .executor import TaskQueue
from .llm import build_runtime_llm_provider
from .llm.llm_provider import LLMProvider
from .mcp_strategy_runtime import MCPStrategyRuntime
from .models import TaskInput, TaskResult, failure_code, is_retriable
from .strategy_registry import StrategyRegistry
from .telemetry import (
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_STARTED,
    TASK_SUCCEEDED,
    emit_event,
    make_event_payload,
)

logger = logging.getLogger(__name__)


class TrinityExecutor:
    """Unified executor for a desktop-selected MCP server/toolset."""

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

        self.task_queue = TaskQueue(name="serial_strategy_queue")
        self.browser_semaphore = asyncio.Semaphore(config.max_concurrent_browser_tasks)
        self.initialized = False

    def _build_runtime(self, strategy_id: str) -> MCPStrategyRuntime:
        strategy = self.strategy_registry.get(strategy_id)
        return MCPStrategyRuntime(strategy, llm_provider=self._llm_provider)

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
            logger.warning("TrinityExecutor already initialized")
            return
        await self.task_queue.start_worker()
        self.initialized = True
        logger.info("TrinityExecutor initialized")

    async def shutdown(self):
        if not self.initialized:
            return
        await self.task_queue.stop_worker()
        self.initialized = False
        logger.info("TrinityExecutor shutdown complete")

    async def execute(self, task: TaskInput) -> TaskResult:
        if not self.initialized:
            await self.initialize()

        target_server = self._resolve_target_server(task)
        strategy = self.strategy_registry.get(target_server)
        adapter_name = target_server
        logger.info("Executing task %s via desktop-selected target '%s'", task.task_id, target_server)

        emit_event(TASK_STARTED, make_event_payload(
            task_id=task.task_id, domain=task.domain, adapter_name=adapter_name
        ))
        t0 = time.monotonic()

        health_runtime = self._build_runtime(target_server)
        try:
            is_healthy, health_error = await health_runtime.health_check()
        finally:
            await health_runtime.close()

        if not is_healthy:
            duration_ms = (time.monotonic() - t0) * 1000
            emit_event(TASK_FAILED, make_event_payload(
                task_id=task.task_id,
                domain=task.domain,
                adapter_name=adapter_name,
                duration_ms=duration_ms,
                extra={"reason": "health_check_failed"},
            ))
            
            # Format error message with details from StructuredError
            error_message = f"{strategy.strategy_id} strategy is not available"
            if health_error:
                error_message = health_error.format_for_user()
            
            metadata = {
                "reason": "health_check_failed",
                "adapter_name": adapter_name,
                "domain": task.domain,
                "strategy_id": strategy.strategy_id,
                "target_server": target_server,
            }
            
            # Include full error details in metadata
            if health_error:
                metadata["health_check_error"] = health_error.model_dump()
            
            return TaskResult(
                task_id=task.task_id,
                status="failure",
                category="health_check_failed",
                code=failure_code("health_check_failed"),
                retriable=is_retriable("health_check_failed"),
                error=error_message,
                execution_log=[],
                artifacts=[],
                metadata=metadata,
            )

        if strategy.serial_execution:
            default_timeout = self._timeout_for_domain(task)
            timeout = task.timeout if task.timeout is not None else default_timeout
            runtime = self._build_runtime(target_server)
            result = await self.task_queue.submit(task.task_id, runtime, task, timeout=float(timeout))
        else:
            async with self.browser_semaphore:
                runtime = self._build_runtime(target_server)
                try:
                    result = await runtime.execute(task)
                finally:
                    await runtime.close()

        duration_ms = (time.monotonic() - t0) * 1000
        if result.status == "failure" and result.category == "cancelled":
            emit_event(TASK_CANCELLED, make_event_payload(
                task_id=task.task_id, domain=task.domain, adapter_name=adapter_name, duration_ms=duration_ms
            ))
        elif result.status == "failure":
            emit_event(TASK_FAILED, make_event_payload(
                task_id=task.task_id,
                domain=task.domain,
                adapter_name=adapter_name,
                duration_ms=duration_ms,
                extra={"category": result.category, "code": result.code, "strategy_id": strategy.strategy_id, "target_server": target_server},
            ))
        else:
            emit_event(TASK_SUCCEEDED, make_event_payload(
                task_id=task.task_id, domain=task.domain, adapter_name=adapter_name, duration_ms=duration_ms
            ))
        if isinstance(result.metadata, dict):
            result.metadata.setdefault("target_server", target_server)
            result.metadata.setdefault("strategy_id", strategy.strategy_id)
        return result

    async def health_check_all(self) -> Dict[str, bool]:
        results = {}
        for strategy in self.strategy_registry.list():
            runtime = self._build_runtime(strategy.strategy_id)
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
        results = {}
        for strategy in self.strategy_registry.list():
            runtime = self._build_runtime(strategy.strategy_id)
            try:
                descriptors = await runtime.client.list_tools()
                results[strategy.strategy_id] = {
                    "strategy_id": strategy.strategy_id,
                    "target_server": strategy.strategy_id,
                    "domain": strategy.domain,
                    "description": strategy.description,
                    "serial_execution": strategy.serial_execution,
                    "tools": [descriptor.name for descriptor in descriptors],
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
