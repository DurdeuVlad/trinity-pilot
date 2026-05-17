"""AgenticWorkerMixin: ReAct loop shared by all domain workers (Stories 2 & 3)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, cast

from google.genai import types as genai_types

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.orchestrator.signals import WorkerStepSignal
from trinity_pilot.workers.base import WorkerError, WorkerBlocker
from trinity_pilot.workers.worker_result import WorkerResult

# ---------------------------------------------------------------------------
# Control-flow signals returned by _dispatch_tool
# ---------------------------------------------------------------------------

@dataclass
class _FinishSignal:
    """Returned by _dispatch_tool when the model calls finish()."""
    status: str   # "success" | "failure"
    summary: str


@dataclass
class _BlockerSignal:
    """Returned by _dispatch_tool when the model calls report_blocking()."""
    reason: str
    attempted: str = ""


# ---------------------------------------------------------------------------
# Shared tool declarations (Gemini FunctionDeclaration — tells the LLM the schema)
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

    Tool dispatch contract
    ----------------------
    _dispatch_tool() handles ALL tool names including "finish" and "report_blocking"
    at the base level. Subclasses handle domain tools and fall through to super()
    for anything they don't own.

    Return types from _dispatch_tool:
      str           → observation string; loop continues
      _FinishSignal → objective complete; run_loop returns WorkerResult
      _BlockerSignal → unresolvable blocker; run_loop raises WorkerBlocker
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
    ) -> str | _FinishSignal | _BlockerSignal:
        """Dispatch a tool call. Returns observation string or a control-flow signal.

        Base handles "finish" and "report_blocking". Subclasses handle domain tools
        and delegate unknown names to super().
        """
        if tool_name == "finish":
            status = args.get("status", "success")
            if status not in ("success", "failure"):
                status = "failure"
            return _FinishSignal(status=status, summary=args.get("summary", ""))

        if tool_name == "report_blocking":
            return _BlockerSignal(
                reason=args.get("reason", "unspecified blocker"),
                attempted=args.get("attempted", ""),
            )

        raise NotImplementedError(f"Unknown tool: {tool_name}")

    def _worker_environment_context(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> str:
        """Return domain-specific environment context injected before GOAL in the initial message."""
        return ""

    def _worker_state_snapshot(self, evidence: dict[str, Any]) -> str:
        """Return a compact snapshot of current domain state after each domain tool dispatch."""
        return ""

    def _worker_initial_message(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> str:
        """Build the first user message for the ReAct loop."""
        steering = spec.metadata.get("steering_context", "")
        if isinstance(steering, dict):
            steering = steering.get("latest_recovery_hint", "")
        parts: list[str] = []
        env_ctx = self._worker_environment_context(spec, evidence)
        if env_ctx:
            parts.append(env_ctx)
        parts.append(f"GOAL: {spec.goal}")
        if steering:
            parts.append(f"STEERING CONTEXT: {steering}")
        parts.append("Begin.")
        return "\n\n".join(parts)

    async def run_loop(
        self,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
        *,
        max_steps: int | None = None,
        signals: asyncio.Queue | None = None,
    ) -> WorkerResult:
        """Execute the ReAct loop until finish/report_blocking or step budget exhausted.

        All tool calls — including finish and report_blocking — are dispatched through
        _dispatch_tool(). Control-flow signals (_FinishSignal, _BlockerSignal) are checked
        after every dispatch. Proper Gemini FunctionCall/FunctionResponse message parts are
        used for tool turns so the model never sees "[tool_call]:" text in its history.
        """
        if max_steps is None:
            max_steps = int(spec.metadata.get("max_agent_steps", 20))

        effective_signals = signals if signals is not None else self._signals_queue
        task_id = self._task_id or spec.objective_id

        messages: list[LLMMessage] = [
            LLMMessage(role="user", content=self._worker_initial_message(spec, evidence))
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

            # Case: empty response
            if not response.tool_calls and not response.content:
                if steps_taken == 0:
                    raise WorkerError(
                        f"LLM returned empty response at step {steps_taken}"
                    )
                messages.append(
                    LLMMessage(
                        role="user",
                        content=(
                            "Empty model response. "
                            "If the objective is complete, call finish. Otherwise call the next tool."
                        ),
                    )
                )
                steps_taken += 1
                if effective_signals is not None:
                    await effective_signals.put(
                        WorkerStepSignal(
                            task_id=task_id,
                            objective_id=spec.objective_id,
                            step_num=steps_taken,
                            tool_name="(empty)",
                            tokens_this_step=response.token_count,
                        )
                    )
                continue

            # Case: text-only response (no tool calls)
            if not response.tool_calls:
                messages.append(LLMMessage(role="model", content=response.content))
                messages.append(
                    LLMMessage(
                        role="user",
                        content="You must call a tool. Call finish, report_blocking, or a domain tool.",
                    )
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

            # Emit proper FunctionCall part (model turn) — NOT "[tool_call]:" text
            messages.append(
                LLMMessage(
                    role="tool_call",
                    content=json.dumps({"name": tool_name, "args": args}),
                )
            )

            # Dispatch through unified tool routing (finish/blocking handled at base)
            dispatch_result = await self._dispatch_tool(tool_name, args, evidence)

            # Control-flow signals
            if isinstance(dispatch_result, _FinishSignal):
                return WorkerResult(
                    status=dispatch_result.status,
                    summary=dispatch_result.summary,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                )

            if isinstance(dispatch_result, _BlockerSignal):
                wr = WorkerResult(
                    status="partial_blocker",
                    summary=dispatch_result.reason,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                )
                raise WorkerBlocker(dispatch_result.reason, wr)

            # Domain tool: observation string
            observation: str = dispatch_result
            snapshot = self._worker_state_snapshot(evidence)
            if snapshot:
                observation = f"{observation}\n\n[STATE]\n{snapshot}"

            # Emit proper FunctionResponse part (user turn)
            messages.append(
                LLMMessage(
                    role="tool_result",
                    content=json.dumps({"name": tool_name, "result": observation}),
                )
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
