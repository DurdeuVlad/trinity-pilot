"""Desktop runtime implementing executor-reviewer loop."""

from __future__ import annotations

import time

from ..adapters.desktop import DesktopAdapter
from ..llm.llm_provider import LLMProvider
from ..structured_logging import get_logger
from ..metrics import get_collector
from ..models import TaskInput, TaskResult, failure_code, is_retriable
from ..session import Session
from ..tools.base import Tool
from ..tools.desktop_tools import build_desktop_tools
from .desktop_reviewer import DesktopReviewer

_log = get_logger("trinity_core.orchestrators.desktop_runtime")
_DOMAIN = "desktop"


class DesktopRuntime:
    def __init__(
        self,
        adapter: DesktopAdapter,
        llm_provider: LLMProvider | None = None,
        reviewer: DesktopReviewer | None = None,
        max_iterations: int = 50,
    ) -> None:
        self.adapter = adapter
        self.tools: dict[str, Tool] = build_desktop_tools(adapter)
        self.reviewer = reviewer or DesktopReviewer(adapter)
        self.llm = llm_provider or LLMProvider()
        self.max_iterations = max_iterations

    async def _tool_loop(self, session: Session) -> str:
        _log.debug("Tool loop started", task_id=session.session_id, domain=_DOMAIN)
        metrics = get_collector()
        for _ in range(self.max_iterations):
            llm_t0 = time.monotonic()
            response = await self.llm.call(messages=session.messages, tools=self.tools)
            metrics.record_llm_call(_DOMAIN, tokens_used=0, duration_ms=(time.monotonic() - llm_t0) * 1000)
            if response.is_text():
                session.append_assistant_message(response.text)
                _log.debug("Tool loop finished with text response", task_id=session.session_id)
                return response.text
            for call in response.tool_calls:
                tool = self.tools.get(call.name)
                if tool is None:
                    _log.warning("Unknown tool requested", tool=call.name, task_id=session.session_id)
                    session.append_assistant_message(f"Unknown tool requested: {call.name}")
                    continue
                tool_t0 = time.monotonic()
                result = await tool.execute(**call.arguments)
                tool_ms = (time.monotonic() - tool_t0) * 1000
                metrics.record_tool_call(call.name, _DOMAIN, result.status, tool_ms)
                _log.debug("Tool executed", tool=call.name, status=result.status, task_id=session.session_id)
                session.append_tool_result(call.id, result)
        _log.warning("Tool loop exceeded max iterations", task_id=session.session_id)
        return "Tool loop exceeded max iterations."

    async def execute(self, task: TaskInput) -> TaskResult:
        metrics = get_collector()
        t0 = time.monotonic()
        with _log.context(task_id=task.task_id, domain=_DOMAIN):
            _log.info("Task started", description=task.description)
            session = Session(session_id=task.task_id)
            session.append_user_message(task.description)
            if task.expected_outcome:
                session.append_user_message(f"Definition of done: {task.expected_outcome}")

            for attempt in range(3):
                output = await self._tool_loop(session)
                _log.debug("Review started", attempt=attempt)
                review = await self.reviewer.review(task.description, task.expected_outcome or "", session.messages)
                metrics.record_review(_DOMAIN, approved=review.approved, attempt_number=attempt + 1)
                _log.info("Review completed", approved=review.approved, feedback=review.feedback)
                if review.approved:
                    duration_ms = (time.monotonic() - t0) * 1000
                    metrics.record_task(task.task_id, _DOMAIN, "success", duration_ms)
                    _log.info("Task succeeded", duration_ms=duration_ms)
                    return TaskResult(
                        task_id=task.task_id,
                        status="success",
                        category="success",
                        code=None,
                        retriable=False,
                        error=None,
                        execution_log=[],
                        artifacts=[],
                        metadata={"session_id": session.session_id, "output": output, "review": review.feedback},
                    )
                session.append_assistant_message(f"Reviewer feedback: {review.feedback}")

            duration_ms = (time.monotonic() - t0) * 1000
            metrics.record_task(task.task_id, _DOMAIN, "failure", duration_ms)
            _log.error("Task failed after 3 review attempts", duration_ms=duration_ms)
            return TaskResult(
                task_id=task.task_id,
                status="failure",
                category="backend_error",
                code=failure_code("backend_error"),
                retriable=is_retriable("backend_error"),
                error="Reviewer rejected execution after 3 attempts.",
                execution_log=[],
                artifacts=[],
                metadata={"session_id": session.session_id},
            )
