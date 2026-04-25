"""Shared MCP-first runtime with full visible tool catalogs."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

from .llm.llm_provider import LLMProvider
from .mcp_client import MCPStrategyClient, MCPToolDescriptor
from .models import TaskInput, TaskResult, failure_code, is_retriable, create_structured_error, StructuredError, VerificationEnvelope
from .session import Session
from .strategy_registry import MCPStrategy
from .tools.base import Tool, ToolResult
from .verification import build_failure_verification, build_verification


class _MCPVisibleTool(Tool):
    def __init__(self, client: MCPStrategyClient, descriptor: MCPToolDescriptor) -> None:
        self.client = client
        self.descriptor = descriptor

    def name(self) -> str:
        return self.descriptor.name

    def description(self) -> str:
        return self.descriptor.description

    def parameters(self) -> dict[str, Any]:
        return self.descriptor.input_schema

    def annotations(self) -> dict[str, Any]:
        return dict(self.descriptor.metadata)

    async def execute(self, **kwargs: Any) -> ToolResult:
        result = await self.client.call_tool(self.descriptor.name, kwargs)
        return ToolResult(
            status=str(result.get("status", "success")),
            output=str(result.get("output", "")),
            error=result.get("error"),
            metadata=dict(result.get("metadata", {})),
            error_code=result.get("error_code"),
            retryable=bool(result.get("retryable", True)),
        )


class MCPStrategyRuntime:
    """Single shared runtime for the MCP server selected by the desktop."""

    def __init__(
        self,
        strategy: MCPStrategy,
        llm_provider: LLMProvider | None = None,
        max_iterations: int = 50,
    ) -> None:
        self.strategy = strategy
        self.client = MCPStrategyClient(
            command=strategy.server_command,
            args=strategy.server_args,
            env=strategy.env,
        )
        if llm_provider is None:
            raise ValueError("MCPStrategyRuntime requires a real tool-calling LLM provider.")
        self.llm = llm_provider
        self.max_iterations = max_iterations
        self._cached_descriptors: list[MCPToolDescriptor] = []
        self._server_context_cache: str = ""  # populated once at first connect

    async def close(self) -> None:
        await self.client.disconnect()

    async def _ensure_server_context(self) -> None:
        """Fetch server self-documentation once at connect time. Idempotent."""
        if self._server_context_cache:
            return
        self._server_context_cache = await self._fetch_server_context()

    async def _fetch_server_context(self) -> str:
        """Pull server briefing + capability manifest. 5s timeout per call."""
        parts: list[str] = []

        try:
            briefing = await asyncio.wait_for(
                self.client.get_prompt("capability_briefing"), timeout=5.0
            )
            if briefing:
                parts.append(f"[SERVER BRIEFING]\n{briefing}")
        except Exception:
            pass  # server may not have FastMCP prompts yet

        try:
            manifest = await asyncio.wait_for(
                self.client.read_resource("server://capabilities"), timeout=5.0
            )
            if manifest:
                parts.append(f"[CAPABILITY MANIFEST]\n{manifest}")
        except Exception:
            pass

        return "\n\n".join(parts)

    async def _discover_tools(self) -> dict[str, Tool]:
        descriptors = await self.client.list_tools()
        self._cached_descriptors = descriptors
        await self._ensure_server_context()  # fetch once, cache for system prompt
        tools = {
            descriptor.name: _MCPVisibleTool(self.client, descriptor)
            for descriptor in descriptors
        }
        return tools

    def _build_system_prompt(self, task: TaskInput) -> str:
        sections: list[str] = [
            "You are Trinity Core, the only execution orchestrator.",
            f"The desktop already selected MCP server '{self.strategy.strategy_id}'.",
            "Use only tools visible below. Do not assume hidden tools exist.",
            f"Objective domain: {task.domain}",
            f"Strategy description: {self.strategy.description}",
        ]

        if task.objective_steps:
            sections.append(
                "Desktop-approved objectives:\n- " + "\n- ".join(task.objective_steps)
            )

        if self._server_context_cache:
            # Server is self-documenting via FastMCP -- use its own briefing
            sections.append(self._server_context_cache)
        else:
            # Fallback: registry-based guidance (pre-FastMCP or legacy servers)
            fallback = self.strategy.prompt_contribution.render()
            if fallback:
                sections.append(fallback)

        visible_tools = "\n".join(
            self._format_tool_summary(descriptor) for descriptor in self._cached_descriptors
        ) or "- No tools discovered"
        sections.append("Visible tools:\n" + visible_tools)

        return "\n\n".join(s for s in sections if s)

    def _format_tool_summary(self, descriptor: MCPToolDescriptor) -> str:
        summary = f"- {descriptor.name}: {descriptor.description}"
        if descriptor.metadata:
            metadata_bits = ", ".join(
                f"{key}={value}" for key, value in sorted(descriptor.metadata.items()) if value is not None
            )
            if metadata_bits:
                summary += f" [annotations: {metadata_bits}]"
        return summary

    async def health_check(self) -> Tuple[bool, Optional[StructuredError]]:
        """Check if MCP server is healthy.

        Returns:
            Tuple of (is_healthy, error_details)
            - is_healthy: True if server is operational
            - error_details: StructuredError if health check failed, None otherwise
        """
        try:
            await self.client.connect()
            tools = await self.client.list_tools()
            prompts, resources = [], []
            try:
                prompts = await self.client.list_prompts()
                resources = await self.client.list_resources()
            except Exception:
                pass  # pre-FastMCP servers don't expose prompts/resources
            logger.info(
                "Health OK for %s: %d tools, %d prompts, %d resources",
                self.strategy.strategy_id,
                len(tools),
                len(prompts),
                len(resources),
            )
            return True, None
        except Exception as exc:
            error = create_structured_error(
                exc,
                layer="mcp_runtime",
                phase="health_check",
                context={
                    "strategy_id": self.strategy.strategy_id,
                    "command": self.strategy.server_command,
                    "args": self.strategy.server_args,
                }
            )
            logger.error(f"Health check failed for {self.strategy.strategy_id}: {exc}", exc_info=True)
            return False, error

    def _verification_module(self, task: TaskInput) -> str:
        # Standardize synonyms so verification logic (e.g. browser vs web) stays consistent
        synonyms = {"web": "browser"}
        return synonyms.get(task.domain, task.domain)

    def _task_with_runtime_verification(self, task: TaskInput) -> TaskInput:
        checks = list(task.verification_checks)
        checks.append(
            {
                "kind": "visible_tool_execution",
                "target": "mcp_visible_tools",
                "expected": True,
                "message": "No successful visible MCP tool calls were executed.",
            }
        )
        return task.model_copy(update={"verification_checks": checks})

    def _build_backend_result(
        self,
        *,
        execution_log: list[dict[str, Any]],
        artifacts: list[str],
        final_text: str,
    ) -> dict[str, Any]:
        merged_metadata: dict[str, Any] = {}
        elements: dict[str, Any] = {}
        extracted_text_parts: list[str] = []
        failure_details: list[str] = []
        for entry in execution_log:
            if entry.get("result") == "failure" and entry.get("details"):
                failure_details.append(str(entry["details"]))
            metadata = entry.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if isinstance(metadata.get("elements"), dict):
                elements.update(metadata["elements"])
            extracted_text = metadata.get("extracted_text")
            if extracted_text:
                extracted_text_parts.append(str(extracted_text))
            merged_metadata.update(metadata)

        backend_result: dict[str, Any] = {
            "status": "success",
            "metadata": merged_metadata,
            "successful_actions": sum(1 for entry in execution_log if entry.get("result") == "success"),
            "total_actions": len(execution_log),
            "artifacts": list(artifacts),
        }
        if elements:
            backend_result["elements"] = elements
        if extracted_text_parts:
            backend_result["extracted_text"] = "\n".join(extracted_text_parts)
        elif isinstance(merged_metadata.get("items"), list):
            item_text = "\n".join(str(item).strip() for item in merged_metadata["items"] if str(item).strip())
            if item_text:
                backend_result["extracted_text"] = item_text
        if failure_details:
            backend_result["error"] = failure_details[-1]
        if merged_metadata.get("url") and not merged_metadata.get("current_url"):
            backend_result["current_url"] = merged_metadata["url"]
        if merged_metadata.get("title") and not merged_metadata.get("page_title"):
            backend_result["page_title"] = merged_metadata["title"]
        if merged_metadata.get("app") and not merged_metadata.get("app_context"):
            backend_result["app_context"] = merged_metadata["app"]
        if merged_metadata.get("app_name") and not merged_metadata.get("app_context"):
            backend_result["app_context"] = merged_metadata["app_name"]
        if merged_metadata.get("title") and not merged_metadata.get("active_window"):
            backend_result["active_window"] = merged_metadata["title"]
        for key in ("current_url", "page_title", "verification_status", "plan_state", "app_context", "active_window"):
            value = merged_metadata.get(key)
            if value not in (None, ""):
                backend_result[key] = value
        if final_text:
            backend_result["output"] = final_text
        return backend_result

    def _result_from_verification(
        self,
        *,
        task: TaskInput,
        execution_log: list[dict[str, Any]],
        artifacts: list[str],
        final_text: str,
        verification: Any,
        duration_ms: float,
    ) -> TaskResult:
        metadata = {
            "strategy_id": self.strategy.strategy_id,
            "target_server": self.strategy.strategy_id,
            "output": final_text,
            "visible_tools": [descriptor.name for descriptor in self._cached_descriptors],
            "visible_tool_metadata": {descriptor.name: dict(descriptor.metadata) for descriptor in self._cached_descriptors},
            "verification_status": verification.status,
            "verification_summary": verification.summary,
            "duration_ms": duration_ms,
        }
        if verification.status == "success":
            return TaskResult(
                task_id=task.task_id,
                status="success",
                category="success",
                code=None,
                retriable=False,
                error=None,
                execution_log=execution_log,
                artifacts=artifacts,
                verification=verification,
                metadata=metadata,
            )

        error = verification.summary or "Execution did not satisfy deterministic verification."
        return TaskResult(
            task_id=task.task_id,
            status="failure",
            category="backend_error",
            code=failure_code("backend_error"),
            retriable=is_retriable("backend_error"),
            error=error,
            execution_log=execution_log,
            artifacts=artifacts,
            verification=verification,
            metadata=metadata,
        )

    async def execute(self, task: TaskInput) -> TaskResult:
        t0 = time.monotonic()
        try:
            tools = await self._discover_tools()
            verification_task = self._task_with_runtime_verification(task)
            session = Session(session_id=task.task_id)
            if task.objective_steps:
                approved = "\n".join(f"{idx}. {step}" for idx, step in enumerate(task.objective_steps, start=1))
                session.append_user_message(
                    f"Finalized desktop objective: {task.description}\n\nApproved objectives:\n{approved}"
                )
            else:
                session.append_user_message(task.description)
            if task.expected_outcome:
                session.append_user_message(f"Definition of done: {task.expected_outcome}")

            execution_log: list[dict[str, Any]] = []
            artifacts: list[str] = []
            final_text = ""
            for step in range(self.max_iterations):
                messages = [{"role": "system", "content": self._build_system_prompt(task)}] + session.messages
                response = await self.llm.call(messages=messages, tools=tools)
                if response.tool_calls:
                    session.append_assistant_tool_calls(response.tool_calls, response.text or "")
                    for call in response.tool_calls:
                        tool = tools.get(call.name)
                        if tool is None:
                            session.append_assistant_message(f"Unknown tool requested: {call.name}")
                            execution_log.append(
                                {
                                    "step": step + 1,
                                    "action": call.name,
                                    "result": "failure",
                                    "details": "Unknown tool requested by model.",
                                    "timestamp": datetime.now().isoformat(),
                                    "metadata": {},
                                }
                            )
                            continue
                        tool_result = await tool.execute(**call.arguments)
                        session.append_tool_result(call.id, call.name, tool_result)
                        tool_artifacts = tool_result.metadata.get("artifacts", [])
                        if isinstance(tool_artifacts, list):
                            artifacts.extend(str(item) for item in tool_artifacts if item)
                        artifact_path = tool_result.metadata.get("artifact_path")
                        if artifact_path:
                            artifacts.append(str(artifact_path))
                        execution_log.append(
                            {
                                "step": step + 1,
                                "action": call.name,
                                "result": "success" if tool_result.status == "success" else "failure",
                                "details": tool_result.output or tool_result.error,
                                "timestamp": datetime.now().isoformat(),
                                "metadata": dict(tool_result.metadata),
                                "exit_code": tool_result.metadata.get("exit_code"),
                            }
                        )
                    continue
                final_text = response.text or ""
                session.append_assistant_message(final_text)
                break

            duration_ms = (time.monotonic() - t0) * 1000
            if not final_text.strip():
                verification = build_failure_verification(
                    module=self._verification_module(task),
                    error="Execution ended without a final answer.",
                    evidence={
                        "strategy_id": self.strategy.strategy_id,
                        "visible_tools": [descriptor.name for descriptor in self._cached_descriptors],
                        "visible_tool_metadata": {descriptor.name: dict(descriptor.metadata) for descriptor in self._cached_descriptors},
                        "successful_actions": sum(1 for entry in execution_log if entry.get("result") == "success"),
                        "total_actions": len(execution_log),
                    },
                )
                return TaskResult(
                    task_id=task.task_id,
                    status="failure",
                    category="backend_error",
                    code=failure_code("backend_error"),
                    retriable=is_retriable("backend_error"),
                    error="Execution ended without a final answer.",
                    execution_log=execution_log,
                    artifacts=artifacts,
                    verification=verification,
                    metadata={
                        "strategy_id": self.strategy.strategy_id,
                        "visible_tools": [descriptor.name for descriptor in self._cached_descriptors],
                        "visible_tool_metadata": {descriptor.name: dict(descriptor.metadata) for descriptor in self._cached_descriptors},
                        "verification_status": verification.status,
                        "verification_summary": verification.summary,
                        "duration_ms": duration_ms,
                    },
                )

            backend_result = self._build_backend_result(
                execution_log=execution_log,
                artifacts=artifacts,
                final_text=final_text,
            )
            task_status = "failure" if any(entry.get("result") == "failure" for entry in execution_log) else "success"
            verification = build_verification(
                task=verification_task,
                module=self._verification_module(task),
                backend_result=backend_result,
                task_status=task_status,
                execution_log=execution_log,
                output_text=final_text,
            )
            return self._result_from_verification(
                task=task,
                execution_log=execution_log,
                artifacts=artifacts,
                final_text=final_text,
                verification=verification,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            verification = build_failure_verification(
                module=self._verification_module(task),
                error=str(exc),
                evidence={"strategy_id": self.strategy.strategy_id},
            )
            return TaskResult(
                task_id=task.task_id,
                status="failure",
                category="backend_error",
                code=failure_code("backend_error"),
                retriable=is_retriable("backend_error"),
                error=str(exc),
                execution_log=[],
                artifacts=[],
                verification=verification,
                metadata={
                    "strategy_id": self.strategy.strategy_id,
                    "verification_status": verification.status,
                    "verification_summary": verification.summary,
                },
            )
