"""AgenticWorkerMixin: ReAct loop shared by all domain workers (Stories 2 & 3)."""
from __future__ import annotations

import asyncio
from typing import Any, cast

from google.genai import types as genai_types

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.orchestrator.signals import WorkerStepSignal
from trinity_pilot.workers.base import WorkerError, WorkerBlocker
from trinity_pilot.workers.worker_result import WorkerResult

# ---------------------------------------------------------------------------
# Shared tool declarations (Story 3)
# ---------------------------------------------------------------------------

_finish_decl = genai_types.FunctionDeclaration(
    name="finish",
    description=(
        "Signal that the objective is complete or definitively failed. "
        "Call this when no further actions are needed."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "status": genai_types.Schema(
                type=genai_types.Type.STRING,
                description='Outcome: "success" if objective achieved, "failure" if definitively impossible.',
                enum=["success", "failure"],
            ),
            "summary": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="One-paragraph summary of what was done or why it failed.",
            ),
        },
        required=["status", "summary"],
    ),
)

_report_blocking_decl = genai_types.FunctionDeclaration(
    name="report_blocking",
    description=(
        "Signal an unresolvable blocker that requires orchestrator or user intervention. "
        "Use when you cannot proceed without external help."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "reason": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Clear description of what is blocking progress and what would be needed to unblock.",
            ),
            "attempted": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Summary of what was tried before concluding blocked.",
            ),
        },
        required=["reason"],
    ),
)


def _make_tool(declarations: list[genai_types.FunctionDeclaration]) -> genai_types.Tool:
    return genai_types.Tool(function_declarations=declarations)


# ---------------------------------------------------------------------------
# AgenticWorkerMixin
# ---------------------------------------------------------------------------

class AgenticWorkerMixin:
    """Mixin that provides the ReAct loop for domain workers.

    MRO: class TerminalWorker(AgenticWorkerMixin, DomainWorker)
    """

    def __init__(self, llm: LLMProvider, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._llm = llm
        self._signals_queue: asyncio.Queue | None = None
        self._task_id: str = ""

    def _worker_tools(self) -> list[genai_types.Tool]:
        """Return the tool list for this worker. Subclasses override to add domain tools."""
        return [_make_tool([_finish_decl, _report_blocking_decl])]

    def _worker_system_prompt(self) -> str:
        """Return the system prompt for this worker. Subclasses override."""
        return ""

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str:
        """Handle domain-specific tool calls. Subclasses implement this. Returns observation string."""
        raise NotImplementedError(f"Unknown tool: {tool_name}")

    async def run_loop(
        self,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
        *,
        max_steps: int | None = None,
        signals: asyncio.Queue | None = None,
    ) -> WorkerResult:
        """Execute the ReAct loop until the LLM calls finish/report_blocking or steps are exhausted."""
        # Resolve max_steps
        if max_steps is None:
            max_steps = int(spec.metadata.get("max_agent_steps", 20))

        # Use injected signals queue if not passed explicitly
        effective_signals = signals if signals is not None else self._signals_queue
        task_id = self._task_id or spec.objective_id

        # Build initial messages
        steering = spec.metadata.get("steering_context", "")
        if isinstance(steering, dict):
            steering = steering.get("latest_recovery_hint", "")
        messages: list[LLMMessage] = [
            LLMMessage(
                role="user",
                content=f"GOAL: {spec.goal}\n\nSTEERING CONTEXT: {steering}\n\nBegin.",
            )
        ]

        steps_taken = 0
        tokens_used = 0

        while steps_taken < max_steps:
            response: LLMResponse = await self._llm.complete_with_tools(
                messages,
                cast(list[Any], self._worker_tools()),
                system=self._worker_system_prompt(),
            )
            tokens_used += response.token_count

            # Case: empty response (no tool calls, no content)
            if not response.tool_calls and not response.content:
                raise WorkerError(
                    f"LLM returned empty response at step {steps_taken}"
                )

            # Case: text-only response (no tool calls)
            if not response.tool_calls:
                messages.append(LLMMessage(role="model", content=response.content))
                messages.append(
                    LLMMessage(role="user", content="[observation]: no tool called, continue.")
                )
                steps_taken += 1
                if effective_signals is not None:
                    await effective_signals.put(
                        WorkerStepSignal(
                            task_id=task_id,
                            objective_id=spec.objective_id,
                            step_num=steps_taken,
                            tool_name="(text)",
                            tokens_this_step=response.token_count,
                        )
                    )
                continue

            # Process first tool call
            tool_call = response.tool_calls[0]
            tool_name: str = tool_call["name"]
            args: dict[str, Any] = tool_call.get("args", {})

            messages.append(
                LLMMessage(role="model", content=f"[tool_call]: {tool_name}({args})")
            )

            if tool_name == "finish":
                status = args.get("status", "success")
                if status not in ("success", "failure"):
                    status = "failure"
                summary = args.get("summary", "")
                return WorkerResult(
                    status=status,
                    summary=summary,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                )

            if tool_name == "report_blocking":
                reason = args.get("reason", "unspecified blocker")
                result = WorkerResult(
                    status="partial_blocker",
                    summary=reason,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                )
                raise WorkerBlocker(reason, result)

            # Domain tool
            observation = await self._dispatch_tool(tool_name, args, evidence)
            messages.append(
                LLMMessage(role="user", content=f"[observation]: {observation}")
            )
            steps_taken += 1
            if effective_signals is not None:
                await effective_signals.put(
                    WorkerStepSignal(
                        task_id=task_id,
                        objective_id=spec.objective_id,
                        step_num=steps_taken,
                        tool_name=tool_name,
                        tokens_this_step=response.token_count,
                    )
                )

        raise WorkerError(
            f"Worker step budget exhausted after {max_steps} steps for '{spec.objective_id}'"
        )
