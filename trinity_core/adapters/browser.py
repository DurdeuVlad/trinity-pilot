"""Browser automation adapter.

Uses generalistic Playwright-based browser automation for all tasks.
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from browser_agent.core.io_models import BrowserAgentOutput
from browser_agent.main import run_browser_task

try:
    from browser_agent.main import close_browser_session
except ImportError:
    async def close_browser_session(session_id: str) -> None:
        """Best-effort fallback when the resolved browser module lacks session teardown."""
        logger.warning(
            "Resolved browser_agent.main does not export close_browser_session; "
            "skipping teardown for session %s",
            session_id,
        )

from ..adapter import TaskAdapter
from ..models import ExecutionLog, TaskInput, TaskResult, failure_code, is_retriable
from ..telemetry import (
    TASK_CANCELLED,
    TASK_FAILED,
    TASK_STARTED,
    TASK_SUCCEEDED,
    emit_event,
    make_event_payload,
)
from ..verification import build_failure_verification, build_verification

logger = logging.getLogger(__name__)

DEFAULT_CONTRACT_TIMEOUT_SECONDS = 600.0
_FLIGHT_REPORT_ROOT = Path(__file__).resolve().parents[2] / "unified-app" / "_runtime" / "flight_reports"
AUTH_TOKENS = (
    "api_key_invalid",
    "invalid api key",
    "api key not valid",
    "unauthenticated",
    "authentication failed",
)
USER_ERROR_TOKENS = (
    "verification failed",
    "clarify",
    "need assistance",
    "unable to verify",
    "not visually confirmed",
)


class BrowserAdapter(TaskAdapter):
    """Generalistic browser automation adapter."""

    def __init__(self) -> None:
        self.module_name = "browser-gui-automation"
        self.page = None
        self._last_url: str = ""
        self._last_text_snapshot: str = ""

    def _effective_timeout(self, task: TaskInput) -> float:
        return float(task.timeout) if task.timeout is not None else DEFAULT_CONTRACT_TIMEOUT_SECONDS

    def _is_cancelled(self, task: TaskInput) -> bool:
        cancel_event = getattr(task, "cancel_event", None)
        return bool(cancel_event is not None and cancel_event.is_set())

    def _contract_metadata(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
        raw_result: dict | None = None,
    ) -> dict:
        metadata = {
            "module": self.module_name,
            "effective_timeout_seconds": effective_timeout,
            "effective_max_retries": task.max_retries,
        }
        if raw_result is not None:
            metadata["raw_result"] = raw_result
        return metadata

    def _flight_report_metadata(self, *, session_id: str | None, objective_id: str | None) -> dict[str, str]:
        if not session_id or not objective_id:
            return {}
        return {
            "flight_report_session_id": session_id,
            "flight_report_objective_id": objective_id,
            "flight_report_path": str(_FLIGHT_REPORT_ROOT / session_id / objective_id / "report.json"),
        }

    def _contract_failure(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
        category: str,
        error: str,
    ) -> TaskResult:
        logger.warning(
            "Browser task failed before successful completion: task_id=%s category=%s error=%s",
            task.task_id,
            category,
            error,
        )
        metadata = self._contract_metadata(task, effective_timeout=effective_timeout)
        metadata["adapter_name"] = self.module_name
        metadata["domain"] = task.domain
        verification = build_failure_verification(
            module="browser",
            error=error,
            evidence={"category": category},
        )
        metadata["verification"] = verification.model_dump()
        return TaskResult(
            task_id=task.task_id,
            status="failure",
            category=category,
            code=failure_code(category),
            retriable=is_retriable(category),
            error=error,
            execution_log=[],
            artifacts=[],
            verification=verification,
            metadata=metadata,
        )

    def _normalize_category(self, status: str, error: str | None) -> str:
        if status == "success":
            return "success"
        if status == "need_assistance":
            return "user_error"

        lowered = (error or "").lower()
        if any(token in lowered for token in AUTH_TOKENS):
            return "auth_failure"
        if any(token in lowered for token in USER_ERROR_TOKENS):
            return "user_error"
        return "backend_error"

    async def _run_with_contract(
        self,
        task: TaskInput,
        *,
        effective_timeout: float,
    ) -> BrowserAgentOutput | TaskResult:
        """Run browser task with timeout and cancellation support."""
        prior_results = task.context.get("_prior_results")
        browser_session_id = str(task.context.get("_browser_session_id") or task.task_id)
        reuse_session = bool(task.context.get("_reuse_browser_session"))
        logger.info(
            "Launching browser automation: task_id=%s browser_session_id=%s reuse_session=%s timeout=%.1fs expected_outcome=%s",
            task.task_id,
            browser_session_id,
            reuse_session,
            effective_timeout,
            task.expected_outcome,
        )
        browser_task = asyncio.create_task(
            run_browser_task(
                objective=task.description,
                session_id=browser_session_id,
                expected_outcome=task.expected_outcome,
                max_retries=task.max_retries,
                prior_results=prior_results,
                reuse_session=reuse_session,
                ws_url=os.environ.get("BROWSER_CDP_URL") or None,
            )
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + effective_timeout

        while True:
            if self._is_cancelled(task):
                logger.info("Cancelling browser task before completion: %s", task.task_id)
                browser_task.cancel()
                await asyncio.gather(browser_task, return_exceptions=True)
                return self._contract_failure(
                    task,
                    effective_timeout=effective_timeout,
                    category="cancelled",
                    error="Task cancelled before completion.",
                )

            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning("Browser task timed out: %s", task.task_id)
                browser_task.cancel()
                await asyncio.gather(browser_task, return_exceptions=True)
                return self._contract_failure(
                    task,
                    effective_timeout=effective_timeout,
                    category="timeout",
                    error=f"Browser task timed out after {int(effective_timeout)}s.",
                )

            done, _ = await asyncio.wait({browser_task}, timeout=min(0.1, remaining))
            if done:
                return await browser_task

    async def execute(self, task: TaskInput) -> TaskResult:
        """Execute a browser task using full browser automation only."""
        effective_timeout = self._effective_timeout(task)
        if self._is_cancelled(task):
            emit_event(TASK_CANCELLED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name))
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="cancelled",
                error="Task cancelled before execution started.",
            )

        logger.info("Browser task started: task_id=%s description=%s", task.task_id, task.description)
        _t0 = time.monotonic()
        emit_event(TASK_STARTED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name))

        try:
            typed_result = await self._run_with_contract(task, effective_timeout=effective_timeout)
            if isinstance(typed_result, TaskResult):
                return typed_result

            status = self._map_status(typed_result.result)
            category = self._normalize_category(status, typed_result.error_details)
            raw_result = typed_result.model_dump()
            result_session_id = getattr(typed_result, "session_id", None) or raw_result.get("session_id") or task.task_id
            result_objective_id = getattr(typed_result, "objective_id", None) or raw_result.get("objective_id") or task.task_id
            metadata = self._contract_metadata(
                task,
                effective_timeout=effective_timeout,
                raw_result=raw_result,
            )
            metadata.update(
                self._flight_report_metadata(
                    session_id=result_session_id,
                    objective_id=result_objective_id,
                )
            )
            if typed_result.extracted_text:
                metadata["text_output"] = typed_result.extracted_text
                self._last_text_snapshot = typed_result.extracted_text
            self._last_url = str(metadata.get("raw_result", {}).get("current_url", "") or self._last_url)
            execution_log = self._build_execution_log(typed_result)
            verification = build_verification(
                task=task,
                module="browser",
                backend_result=raw_result,
                task_status=status,
                execution_log=execution_log,
                output_text=typed_result.extracted_text,
            )
            metadata["verification"] = verification.model_dump()

            _duration = (time.monotonic() - _t0) * 1000
            logger.info(
                "Browser task completed: task_id=%s status=%s category=%s actions=%d",
                task.task_id,
                status,
                category,
                len(typed_result.attempt_log.actions),
            )
            event_type = TASK_SUCCEEDED if status == "success" else TASK_FAILED
            emit_event(event_type, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name, duration_ms=_duration, extra={"status": status, "category": category}))
            return TaskResult(
                task_id=task.task_id,
                status=status,
                category=category,
                error=typed_result.error_details,
                execution_log=execution_log,
                artifacts=self._extract_artifacts(typed_result),
                verification=verification,
                metadata=metadata,
            )
        except Exception as exc:
            _duration = (time.monotonic() - _t0) * 1000
            emit_event(TASK_FAILED, make_event_payload(task_id=task.task_id, domain=task.domain, adapter_name=self.module_name, duration_ms=_duration, extra={"error": str(exc)}))
            logger.exception("Browser adapter error for task %s", task.task_id)
            return self._contract_failure(
                task,
                effective_timeout=effective_timeout,
                category="backend_error",
                error=f"Browser adapter error: {exc}",
            )

    def _build_execution_log(self, result: BrowserAgentOutput) -> List[ExecutionLog]:
        # Prefer structured history for accurate per-step result
        history = getattr(result, "history", None) or []
        if history:
            return [
                ExecutionLog(
                    step=i + 1,
                    action=f"{item.action.action}: {item.action.selector or ''} {item.action.value or ''}".strip(),
                    result=item.result,
                    details=item.error_details or item.action.reasoning,
                    timestamp=datetime.now().isoformat(),
                )
                for i, item in enumerate(history)
            ]
        # Fallback to flat attempt_log strings
        entries: List[ExecutionLog] = []
        for index, action in enumerate(result.attempt_log.actions, start=1):
            observation = (
                result.attempt_log.observations[index - 1]
                if index - 1 < len(result.attempt_log.observations)
                else None
            )
            step_failed = observation and "fail" in observation.lower()
            entries.append(
                ExecutionLog(
                    step=index,
                    action=str(action),
                    result="failure" if step_failed else "success",
                    details=observation,
                    timestamp=datetime.now().isoformat(),
                )
            )
        return entries

    async def health_check(self) -> bool:
        """Check whether the browser module is importable."""
        try:
            from browser_agent.core.agent import BrowserAgent
        except ImportError:
            return False
        return BrowserAgent is not None

    async def close_session(self, session_id: str) -> None:
        """Release a reusable browser session once an objective is done."""
        await close_browser_session(session_id)

    async def wait_for_selector(self, selector: str, timeout: float, state: str = "visible") -> None:
        """Wait for a selector using Playwright page object when available."""
        if self.page is None:
            raise RuntimeError("Browser page handle is not available for wait_for_selector")
        await self.page.wait_for_selector(selector, timeout=timeout * 1000, state=state)

    async def wait_for_load_state(self, wait_until: str = "load", timeout: float = 30) -> None:
        """Wait for page load state using Playwright page object when available."""
        if self.page is None:
            raise RuntimeError("Browser page handle is not available for wait_for_load_state")
        await self.page.wait_for_load_state(wait_until, timeout=timeout * 1000)

    async def get_current_url(self) -> str:
        """Return current URL from active page or last known metadata."""
        if self.page is not None:
            return str(getattr(self.page, "url", ""))
        return self._last_url

    def get_capabilities(self) -> Dict:
        """Return browser module capabilities conforming to schema v1."""
        return {
            "schema_version": "1.0",
            "domain": "web",
            "actions": ["navigate", "click", "type", "scroll", "screenshot", "extract"],
            "limits": {
                "timeout_seconds": DEFAULT_CONTRACT_TIMEOUT_SECONDS,
                "max_concurrent_sessions": 3,
            },
            "constraints": {
                "thread_safe": True,
                "async": True,
                "platforms": ["Windows", "macOS", "Linux"],
            },
            "flight_reports": True,
        }

    def _map_status(self, result: str) -> str:
        """Map browser result to unified status."""
        mapping = {
            "success": "success",
            "failure": "failure",
            "need_assistance": "need_assistance",
        }
        return mapping.get(result.lower(), "failure")

    def _extract_artifacts(self, result: BrowserAgentOutput) -> List[str]:
        """Extract artifact paths from result."""
        artifacts: List[str] = []
        if result.screenshot_path:
            artifacts.append(result.screenshot_path)
        return artifacts
