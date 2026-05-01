"""Sub-objective executor backed by one visible MCP tool catalog."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

from .action_store import ActionStore
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


class SubObjectiveExecutor:
    """Execute one domain-scoped sub-objective through one MCP strategy.

    This is deliberately not the whole-objective orchestrator. It owns the
    LLM/tool loop for a single selected MCP server and returns evidence for
    the caller to coordinate.
    """

    def __init__(
        self,
        strategy: MCPStrategy,
        llm_provider: LLMProvider | None = None,
        max_turns: int = 50,
        audit_config=None,
    ) -> None:
        self.strategy = strategy
        self.client = MCPStrategyClient(
            command=strategy.server_command,
            args=strategy.server_args,
            env=strategy.env,
        )
        if llm_provider is None:
            raise ValueError("SubObjectiveExecutor requires a real tool-calling LLM provider.")
        self.llm = llm_provider
        self.max_turns = max_turns
        self._audit_config = audit_config  # AuditConfig or None
        self._cached_descriptors: list[MCPToolDescriptor] = []
        self._server_context_cache: str = ""  # populated once at first connect
        self._action_store: ActionStore | None = None

    async def close(self) -> None:
        await self.client.disconnect()

    def _get_action_store(self) -> ActionStore:
        if self._action_store is None:
            self._action_store = ActionStore()
        return self._action_store

    async def _write_action_memory(
        self,
        *,
        task: TaskInput,
        action_name: str,
        action_args: dict[str, Any],
        outcome: str,
        error_code: str | None,
    ) -> None:
        try:
            store = self._get_action_store()
            await asyncio.to_thread(
                store.write,
                task.domain,
                task.description,
                action_name,
                action_args,
                outcome,
                error_code,
            )
        except Exception:
            logger.warning("Action memory write failed for %s", action_name, exc_info=True)

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
            "You are Trinity Core's sub-objective executor.",
            f"The objective orchestrator selected MCP server '{self.strategy.strategy_id}' for this sub-objective.",
            "Use only tools visible below. Do not assume hidden tools exist.",
            f"Objective domain: {task.domain}",
            f"Strategy description: {self.strategy.description}",
            (
                "STOPPING RULE: Once you have obtained tool output that satisfies the objective, "
                "return a plain-text summary of what was done and the result. "
                "Do NOT call any more tools after the objective is met. "
                "One successful action is enough — do not repeat or verify unless the first attempt failed."
            ),
            (
                "ORIENTATION RULE: Before executing any sub-objective, use available tools to read the "
                "current environment state (list files, check paths, ping services, take a screenshot, etc.). "
                "Do not assume the environment matches the task description. "
                "If something is missing but fixable (directory does not exist, file not yet created), "
                "create it and continue. Only stop if the situation is fundamentally unworkable "
                "(service unreachable, permission denied, wrong OS, unavailable dependency)."
            ),
        ]

        prior_results = task.context.get("prior_results") if task.context else None
        if prior_results:
            prior_lines = []
            for entry in prior_results:
                prior_lines.append(
                    f"  [{entry.get('sub_objective_id', '?')}] ({entry.get('domain', '?')}) "
                    f"{entry.get('objective', '')}\n  Output: {entry.get('output', '').strip()}"
                )
            sections.append(
                "[PRIOR RESULTS — outputs from earlier objectives in this run]\n"
                + "\n\n".join(prior_lines)
                + "\n\nUse these results as inputs where needed. Do not re-execute work already completed."
            )

        if task.sub_objectives:
            objectives_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(task.sub_objectives))
            sections.append(
                "SUB-OBJECTIVES (targets to reach, not a script to follow):\n"
                + objectives_text
                + "\n\nThese are goals, not ordered commands. "
                "Achieve them by whatever sequence makes sense given the current environment. "
                "If something is missing but you can fix it (directory does not exist, file not created yet, "
                "package not installed), FIX IT and continue. "
                "Only stop and report if something is fundamentally unworkable: "
                "service unreachable, permission denied, wrong OS, required dependency unavailable."
            )

        if self._server_context_cache:
            # Server is self-documenting via FastMCP -- use its own briefing
            sections.append(self._server_context_cache)
        else:
            # Fallback: registry-based guidance (pre-FastMCP or legacy servers)
            fallback = self.strategy.prompt_contribution.render()
            if fallback:
                sections.append(fallback)

        try:
            memory_section = self._get_action_store().format_prompt_section(task.domain, task.description)
            if memory_section:
                sections.append(memory_section)
        except Exception:
            logger.warning("Action memory prompt injection failed", exc_info=True)

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
        last_exc: BaseException | None = None
        last_stderr = ""
        for attempt in range(3):
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
            except BaseException as exc:
                if exc.__class__.__name__ != "CancelledError" and not isinstance(exc, Exception):
                    raise
                last_exc = exc
                last_stderr = getattr(self.client, "_last_stderr", "") or last_stderr
                await self.client.disconnect()
                self.client = MCPStrategyClient(
                    command=self.strategy.server_command,
                    args=self.strategy.server_args,
                    env=self.strategy.env,
                )
                # Some stdio transports leave a cancelled anyio scope behind after
                # "Connection closed"; awaiting here can promote that cleanup state
                # into asyncio.CancelledError and kill the caller. Retry immediately.

        assert last_exc is not None
        error = create_structured_error(
            last_exc,
            layer="mcp_runtime",
            phase="health_check",
            context={
                "strategy_id": self.strategy.strategy_id,
                "command": self.strategy.server_command,
                "args": self.strategy.server_args,
                "subprocess_stderr": last_stderr,
            }
        )
        logger.error(f"Health check failed for {self.strategy.strategy_id}: {last_exc}", exc_info=True)
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
        if (
            self.strategy.domain == "web"
            and merged_metadata.get("result")
            and not backend_result.get("page_title")
        ):
            backend_result["page_title"] = str(merged_metadata["result"])
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
        recorder = None
        _output_dir: str | None = None
        if self._audit_config is not None:
            try:
                from audit_debugger import FlightRecorder
                session_id = task.task_id
                objective_id = f"{task.domain}-obj-{task.task_id[:8]}"
                recorder = FlightRecorder.start(
                    module=self.strategy.strategy_id,
                    objective={
                        "task_id": task.task_id,
                        "description": task.description,
                        "domain": task.domain,
                    },
                    session_id=session_id,
                    objective_id=objective_id,
                    config=self._audit_config,
                )
                recorder.__enter__()
                _output_dir = os.path.join(
                    self._audit_config.output_dir, session_id, objective_id
                )
            except Exception as _e:
                logger.warning("FlightRecorder setup failed (non-fatal): %s", _e)
                recorder = None

        if recorder is not None and _output_dir is not None:
            try:
                from audit_debugger.prompt_logger import set_active_recorder
                set_active_recorder(recorder, _output_dir)
            except Exception:
                pass

        result: TaskResult | None = None
        _exc: BaseException | None = None
        try:
            result = await self._execute_inner(task, recorder)
            return result
        except BaseException as exc:
            _exc = exc
            raise
        finally:
            if recorder is not None:
                try:
                    from audit_debugger.prompt_logger import clear_active_recorder
                    clear_active_recorder()
                except Exception:
                    pass
                try:
                    if _exc is not None:
                        recorder.report.status = "failure"
                    elif result is not None:
                        recorder.report.status = "success" if result.status == "success" else "failure"
                    recorder.__exit__(None, None, None)
                except Exception as _e2:
                    logger.warning("FlightRecorder teardown failed (non-fatal): %s", _e2)

    async def _execute_inner(self, task: TaskInput, recorder=None) -> TaskResult:
        t0 = time.monotonic()
        try:
            tools = await self._discover_tools()
            if recorder is not None:
                try:
                    recorder.event(
                        phase="planning",
                        message="MCP execution started",
                        level="info",
                        data={
                            "strategy_id": self.strategy.strategy_id,
                            "tools": [d.name for d in self._cached_descriptors],
                            "task_id": task.task_id,
                        },
                        importance=2,
                    )
                except Exception:
                    pass

            verification_task = self._task_with_runtime_verification(task)
            session = Session(session_id=task.task_id)
            if task.sub_objectives:
                sub_obj = "\n".join(f"  - {s}" for s in task.sub_objectives)
                session.append_user_message(
                    f"Task: {task.description}\n\n"
                    f"Sub-objectives to achieve (adapt as needed based on what you find):\n{sub_obj}\n\n"
                    f"Start by orienting: read current environment state first. "
                    f"If something is missing but you can create it (directory, file, config), do so and continue."
                )
            else:
                session.append_user_message(task.description)
            if task.expected_outcome:
                session.append_user_message(f"Definition of done: {task.expected_outcome}")

            execution_log: list[dict[str, Any]] = []
            artifacts: list[str] = []
            final_text = ""
            for turn in range(self.max_turns):
                if recorder is not None:
                    try:
                        recorder.event(
                            phase="execution",
                            message=f"LLM call turn {turn + 1}",
                            level="info",
                            data={"turn": turn + 1},
                            importance=3,
                        )
                    except Exception:
                        pass

                messages = [{"role": "system", "content": self._build_system_prompt(task)}] + session.messages
                try:
                    response = await asyncio.wait_for(
                        self.llm.call(messages=messages, tools=tools),
                        timeout=90.0,
                    )
                except asyncio.TimeoutError:
                    logger.error("LLM call timed out after 90s for task %s", task.task_id)
                    if recorder is not None:
                        try:
                            recorder.event(
                                phase="execution",
                                message="LLM call timed out",
                                level="warning",
                                data={"turn": turn + 1},
                                importance=5,
                            )
                        except Exception:
                            pass
                    break

                if response.tool_calls:
                    session.append_assistant_tool_calls(response.tool_calls, response.text or "")
                    for call in response.tool_calls:
                        tool = tools.get(call.name)
                        if tool is None:
                            session.append_assistant_message(f"Unknown tool requested: {call.name}")
                            execution_log.append(
                                {
                                    "turn": turn + 1,
                                    "action": call.name,
                                    "result": "failure",
                                    "details": "Unknown tool requested by model.",
                                    "timestamp": datetime.now().isoformat(),
                                    "metadata": {},
                                }
                            )
                            continue

                        if recorder is not None:
                            try:
                                recorder.event(
                                    phase="execution",
                                    message=f"Tool call: {call.name}",
                                    level="info",
                                    data={"tool": call.name, "args": call.arguments, "turn": turn + 1},
                                    importance=4,
                                )
                            except Exception:
                                pass

                        tool_result = await tool.execute(**call.arguments)
                        asyncio.create_task(
                            self._write_action_memory(
                                task=task,
                                action_name=call.name,
                                action_args=call.arguments,
                                outcome="success" if tool_result.status == "success" else "failure",
                                error_code=tool_result.error_code,
                            )
                        )

                        if recorder is not None:
                            try:
                                recorder.event(
                                    phase="execution",
                                    message=f"Tool result: {call.name}",
                                    level="info" if tool_result.status == "success" else "warning",
                                    data={
                                        "tool": call.name,
                                        "status": tool_result.status,
                                        "output_preview": str(tool_result.output or "")[:200],
                                        "turn": turn + 1,
                                    },
                                    importance=4,
                                )
                            except Exception:
                                pass

                        session.append_tool_result(call.id, call.name, tool_result)
                        meta = tool_result.metadata if isinstance(tool_result.metadata, dict) else {}
                        tool_artifacts = meta.get("artifacts", [])
                        if isinstance(tool_artifacts, list):
                            artifacts.extend(str(item) for item in tool_artifacts if item)
                        artifact_path = meta.get("artifact_path")
                        if artifact_path:
                            artifacts.append(str(artifact_path))
                        execution_log.append(
                            {
                                "turn": turn + 1,
                                "action": call.name,
                                "result": "success" if tool_result.status == "success" else "failure",
                                "details": tool_result.output or tool_result.error,
                                "timestamp": datetime.now().isoformat(),
                                "metadata": meta,
                                "exit_code": meta.get("exit_code"),
                            }
                        )
                    # Early-stop heuristic: only fires for free-form tasks (no sub_objectives).
                    # For structured tasks the LLM must explicitly return a text answer —
                    # tool-call successes alone do not prove objectives were met.
                    if not task.sub_objectives:
                        successful_entries = [
                            entry for entry in execution_log
                            if entry.get("result") == "success"
                        ]
                        if len(successful_entries) >= 10 and not any(
                            entry.get("result") == "failure" for entry in execution_log[-5:]
                        ):
                            final_text = self._synthesize_final_text(successful_entries[-1])
                            session.append_assistant_message(final_text)
                            if recorder is not None:
                                try:
                                    recorder.event(
                                        phase="execution",
                                        message="Synthesized final text from tool evidence",
                                        level="info",
                                        data={"turn": turn + 1},
                                        importance=3,
                                    )
                                except Exception:
                                    pass
                            break
                    continue

                final_text = response.text or ""
                if recorder is not None:
                    try:
                        recorder.event(
                            phase="execution",
                            message="Final text response received",
                            level="info",
                            data={"turn": turn + 1, "response_preview": final_text[:200]},
                            importance=4,
                        )
                    except Exception:
                        pass
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
                if recorder is not None:
                    try:
                        recorder.event(
                            phase="verification",
                            message=f"Verification: {verification.status}",
                            level="warning",
                            data={"verification_status": verification.status, "summary": verification.summary},
                            importance=4,
                        )
                        from audit_debugger.models import AttemptLog
                        recorder.report.metrics["execution"] = {
                            "total_actions": len(execution_log),
                            "successful_actions": sum(1 for e in execution_log if e.get("result") == "success"),
                            "duration_ms": duration_ms,
                        }
                        recorder.report.attempts.append(AttemptLog(
                            attempt_number=1,
                            actions=[e["action"] for e in execution_log],
                            observations=[str(e.get("details", ""))[:200] for e in execution_log],
                            outcome=f"{verification.status} -- {(verification.summary or '')[:80]}",
                        ))
                    except Exception:
                        pass
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

            if recorder is not None:
                try:
                    recorder.event(
                        phase="verification",
                        message=f"Verification: {verification.status}",
                        level="info" if verification.status == "success" else "warning",
                        data={"verification_status": verification.status, "summary": verification.summary},
                        importance=4,
                    )
                    from audit_debugger.models import AttemptLog
                    recorder.report.metrics["execution"] = {
                        "total_actions": len(execution_log),
                        "successful_actions": sum(1 for e in execution_log if e.get("result") == "success"),
                        "duration_ms": duration_ms,
                    }
                    recorder.report.attempts.append(AttemptLog(
                        attempt_number=1,
                        actions=[e["action"] for e in execution_log],
                        observations=[str(e.get("details", ""))[:200] for e in execution_log],
                        outcome=f"{verification.status} -- {(verification.summary or '')[:80]}",
                    ))
                    for artifact_path in artifacts:
                        recorder.report.artifacts.append({"path": artifact_path, "type": "execution_artifact"})
                except Exception:
                    pass

            return self._result_from_verification(
                task=task,
                execution_log=execution_log,
                artifacts=artifacts,
                final_text=final_text,
                verification=verification,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            if recorder is not None:
                try:
                    recorder.event(
                        phase="system",
                        message=f"Unhandled exception: {exc}",
                        level="error",
                        data={"error": str(exc), "error_type": type(exc).__name__},
                        importance=5,
                    )
                except Exception:
                    pass
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

    def _synthesize_final_text(self, last_success: dict[str, Any]) -> str:
        """Stop runaway tool loops once visible successful evidence exists."""
        metadata = last_success.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        for key in ("stdout", "extracted_text", "text", "title", "url"):
            value = metadata.get(key)
            if value:
                return str(value)
        details = str(last_success.get("details") or "").strip()
        if details:
            return details[:4000]
        return "Execution completed with visible tool evidence."
