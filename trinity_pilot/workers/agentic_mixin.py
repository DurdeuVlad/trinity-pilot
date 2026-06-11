"""AgenticWorkerMixin: ReAct loop shared by all domain workers (Stories 2 & 3)."""
from __future__ import annotations

import asyncio
import base64
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


_take_screenshot_decl = genai_types.FunctionDeclaration(
    name="screenshot",
    description=(
        "Capture a screenshot and return it as a visual observation. "
        "mode='screen' captures one monitor (screen_index=0 is the primary monitor). "
        "mode='all_screens' captures every monitor combined into one image. "
        "mode='app' captures a specific window — supply its title as app_title (regex supported)."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "mode": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Capture mode: 'screen', 'all_screens', or 'app'.",
                enum=["screen", "all_screens", "app"],
            ),
            "screen_index": genai_types.Schema(
                type=genai_types.Type.INTEGER,
                description="Monitor index to capture (0 = primary). Only used when mode='screen'.",
            ),
            "app_title": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Window title regex to capture. Only used when mode='app'.",
            ),
        },
        required=[],
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
        return [_make_tool([_finish_decl, _report_blocking_decl, _take_screenshot_decl])]

    def _worker_system_prompt(self) -> str:
        """Return the system prompt for this worker. Subclasses override."""
        return ""

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str | tuple[str, bytes] | _FinishSignal | _BlockerSignal:
        """Dispatch a tool call. Returns observation string or a control-flow signal.

        Base handles "finish" and "report_blocking". Subclasses handle domain tools
        and delegate unknown names to super().
        """
        if tool_name == "screenshot":
            from trinity_pilot.tools.screenshot import capture_screenshot
            mode = args.get("mode", "screen")
            screen_index = int(args.get("screen_index", 0))
            app_title = args.get("app_title", "")
            try:
                img_bytes, desc = capture_screenshot(
                    mode=mode, screen_index=screen_index, app_title=app_title
                )
                evidence["screenshot"] = base64.b64encode(img_bytes).decode()
                evidence.setdefault("action_log", []).append(
                    f"Screenshot captured: mode={mode} desc={desc!r}"
                )
                return (
                    f"Screenshot captured ({desc}). Image attached — read the screen carefully "
                    "to determine the current state and what is visible.",
                    img_bytes,
                )
            except Exception as exc:
                evidence.setdefault("action_log", []).append(f"screenshot failed: {exc}")
                return f"Screenshot failed: {exc}"

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

    def _shared_sensor_context(self) -> str:
        """Best-effort cross-cutting sensor snapshot injected at worker startup. Never raises."""
        import datetime as _dt
        lines = ["[SHARED SENSOR CONTEXT]"]
        lines.append(f"  timestamp: {_dt.datetime.now().isoformat(timespec='seconds')}")
        try:
            import pyautogui as _pg
            w, h = _pg.size()
            lines.append(f"  screen_dimensions: {w}x{h}")
        except Exception:
            pass
        try:
            import ctypes as _ct
            hwnd = _ct.windll.user32.GetForegroundWindow()
            length = _ct.windll.user32.GetWindowTextLengthW(hwnd)
            buf = _ct.create_unicode_buffer(length + 1)
            _ct.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if title:
                lines.append(f"  active_window: {title!r}")
        except Exception:
            pass
        return "\n".join(lines)

    def _worker_initial_message(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> str:
        """Build the first user message for the ReAct loop."""
        steering = spec.metadata.get("steering_context", "")
        if isinstance(steering, dict):
            steering = steering.get("latest_recovery_hint", "")
        parts: list[str] = []
        shared_ctx = self._shared_sensor_context()
        if shared_ctx:
            parts.append(shared_ctx)
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
            max_steps = int(spec.metadata.get("max_agent_steps", 30))

        effective_signals = signals if signals is not None else self._signals_queue
        task_id = self._task_id or spec.objective_id

        messages: list[LLMMessage] = [
            LLMMessage(role="user", content=self._worker_initial_message(spec, evidence))
        ]

        steps_taken = 0
        tokens_used = 0
        recent_calls: dict[tuple[str, str], int] = {}

        while steps_taken < max_steps:
            response: LLMResponse = await self._llm.complete_with_tools(
                messages,
                cast(list[Any], self._worker_tools()),
                system=self._worker_system_prompt(),
            )
            tokens_used += response.token_count

            # Build transcript entry for this step (written to evidence after dispatch)
            _tx_entry: dict[str, Any] = {
                "step": steps_taken + 1,
                "llm_text": response.content or "",
            }

            # Case: empty response
            if not response.tool_calls and not response.content:
                _tx_entry["tool_name"] = "(empty)"
                evidence.setdefault("llm_transcript", []).append(_tx_entry)
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
                _tx_entry["tool_name"] = "(text-only)"
                evidence.setdefault("llm_transcript", []).append(_tx_entry)
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
            _tx_entry["tool_name"] = tool_name
            _tx_entry["tool_args"] = {k: v for k, v in args.items() if k != "image_data"}

            # Emit proper FunctionCall part (model turn) — NOT "[tool_call]:" text.
            # Attach raw_provider_content so GeminiProvider can replay the original
            # Content object verbatim (preserving thought_signature for 2.5+ models).
            messages.append(
                LLMMessage(
                    role="tool_call",
                    content=json.dumps({"name": tool_name, "args": args}),
                    raw_provider_content=getattr(response, "raw_model_content", None),
                )
            )

            # Dedup guard — warn on 2nd identical call, block on 3rd+
            _CONTROL_TOOLS = {"finish", "report_blocking"}
            _dedup_prefix = ""
            if tool_name not in _CONTROL_TOOLS:
                _args_key = json.dumps(args, sort_keys=True)
                _call_key = (tool_name, _args_key)
                _prior = recent_calls.get(_call_key, 0)
                recent_calls[_call_key] = _prior + 1
                if _prior == 1:
                    _dedup_prefix = (
                        f"⚠️ REPEATED CALL: You already called {tool_name!r} with these exact "
                        "arguments. Try a fundamentally different approach."
                    )
                elif _prior >= 2:
                    _blocked_obs = (
                        f"🛑 BLOCKED: {tool_name!r} called with identical arguments {_prior + 1} "
                        "times. You are stuck in a loop. Call finish('failure') with a clear "
                        "explanation of what you tried and why you could not complete the goal."
                    )
                    _snap = self._worker_state_snapshot(evidence)
                    if _snap:
                        _blocked_obs = f"{_blocked_obs}\n\n[STATE]\n{_snap}"
                    messages.append(LLMMessage(
                        role="tool_result",
                        content=json.dumps({"name": tool_name, "result": _blocked_obs}),
                    ))
                    steps_taken += 1
                    if effective_signals is not None:
                        await effective_signals.put(WorkerStepSignal(
                            task_id=task_id, objective_id=spec.objective_id,
                            step_num=steps_taken, tool_name=tool_name,
                            tokens_this_step=response.token_count,
                        ))
                    continue

            # Dispatch through unified tool routing (finish/blocking handled at base)
            dispatch_result = await self._dispatch_tool(tool_name, args, evidence)

            # Control-flow signals
            if isinstance(dispatch_result, _FinishSignal):
                _tx_entry["tool_result"] = f"finish(status={dispatch_result.status}): {dispatch_result.summary}"
                evidence.setdefault("llm_transcript", []).append(_tx_entry)
                return WorkerResult(
                    status=dispatch_result.status,
                    summary=dispatch_result.summary,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                )

            if isinstance(dispatch_result, _BlockerSignal):
                _tx_entry["tool_result"] = f"report_blocking: {dispatch_result.reason}"
                evidence.setdefault("llm_transcript", []).append(_tx_entry)
                wr = WorkerResult(
                    status="partial_blocker",
                    summary=dispatch_result.reason,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                )
                raise WorkerBlocker(dispatch_result.reason, wr)

            # Domain tool: observation string or (string, image_bytes) tuple
            img_bytes: bytes | None = None
            if isinstance(dispatch_result, tuple):
                observation, img_bytes = dispatch_result
            else:
                observation = dispatch_result  # type: ignore[assignment]
            if _dedup_prefix:
                observation = f"{_dedup_prefix}\n\n{observation}"
            snapshot = self._worker_state_snapshot(evidence)
            if snapshot:
                observation = f"{observation}\n\n[STATE]\n{snapshot}"
            _tx_entry["tool_result"] = observation[:2000] if isinstance(observation, str) else str(observation)[:2000]
            evidence.setdefault("llm_transcript", []).append(_tx_entry)

            # Emit proper FunctionResponse part (user turn).
            # When image bytes are attached (e.g. screenshot), include them
            # so the LLM receives a multimodal tool result and can read the screen.
            messages.append(
                LLMMessage(
                    role="tool_result",
                    content=json.dumps({"name": tool_name, "result": observation}),
                    image_data=img_bytes,
                    image_mime="image/jpeg",
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

        # Return failure result so evidence (action_log, transcript) is preserved for review.
        return WorkerResult(
            status="failure",
            summary=f"Worker step budget exhausted after {max_steps} steps for '{spec.objective_id}'",
        )
