"""AgenticWorkerMixin: ReAct loop shared by all domain workers (Stories 2 & 3)."""
from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from google.genai import types as genai_types

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.orchestrator.signals import WorkerStepSignal
from trinity_pilot.workers.action_verification import verify_action
from trinity_pilot.workers.base import WorkerError, WorkerBlocker
from trinity_pilot.workers.worker_result import ToolCallRecord, WorkerResult

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

_todo_write_decl = genai_types.FunctionDeclaration(
    name="todo_write",
    description="Replace the objective todo list. Call this first to plan the work.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={"items": genai_types.Schema(type=genai_types.Type.ARRAY, items=genai_types.Schema(type=genai_types.Type.STRING))},
        required=["items"],
    ),
)
_todo_read_decl = genai_types.FunctionDeclaration(
    name="todo_read", description="Read the current objective todo list.",
    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
)
_todo_check_decl = genai_types.FunctionDeclaration(
    name="todo_check", description="Mark a zero-based todo item complete.",
    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={"index": genai_types.Schema(type=genai_types.Type.INTEGER)}, required=["index"]),
)
_todo_add_decl = genai_types.FunctionDeclaration(
    name="todo_add", description="Append one todo item.",
    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={"item": genai_types.Schema(type=genai_types.Type.STRING)}, required=["item"]),
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
        self._todo_items: list[dict[str, Any]] = []

    def _worker_tools(self) -> list[genai_types.Tool]:
        """Return the tool list for this worker. Subclasses override to add domain tools."""
        return [_make_tool([
            _todo_write_decl, _todo_read_decl, _todo_check_decl, _todo_add_decl,
            _finish_decl, _report_blocking_decl, _take_screenshot_decl,
        ])]

    def _todo_context(self) -> str:
        if not self._todo_items:
            return "[TODO]\n(no plan written yet)"
        return "[TODO]\n" + "\n".join(
            f"{'[x]' if item['done'] else '[ ]'} {index}: {item['text']}"
            for index, item in enumerate(self._todo_items)
        )

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
                    f"Screenshot captured ({desc}). Image attached — read the window carefully: "
                    "identify every visible number, label, and display field. "
                    "Use what you see in the image for your finish summary."
                    ,
                    img_bytes,
                )
            except Exception as exc:
                evidence.setdefault("action_log", []).append(f"screenshot failed: {exc}")
                return f"Screenshot failed: {exc}"

        if tool_name == "todo_write":
            self._todo_items = [{"text": str(item), "done": False} for item in args.get("items", [])]
            return self._todo_context()
        if tool_name == "todo_read":
            return self._todo_context()
        if tool_name == "todo_check":
            index = int(args.get("index", -1))
            if not 0 <= index < len(self._todo_items):
                return f"Invalid todo index {index}.\n{self._todo_context()}"
            self._todo_items[index]["done"] = True
            return self._todo_context()
        if tool_name == "todo_add":
            self._todo_items.append({"text": str(args.get("item", "")), "done": False})
            return self._todo_context()

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

    def _action_sensor_check(self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]):
        """Return an eventually-consistent-tier sensor check for `tool_name`, or None.

        Only relevant for actions registered as ActionTier.EVENTUALLY_CONSISTENT
        in action_verification.TIER_REGISTRY (e.g. launch_app, navigate). Workers
        override this to supply a real poll predicate; the default is a no-op so
        unregistered/unsupported actions get no tiered verification, unchanged
        from today's behavior.
        """
        return None

    def _action_sensor_read(self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]):
        """Return an LLM-grounded-tier sensor read for `tool_name`, or None.

        Only relevant for actions registered as ActionTier.LLM_GROUNDED (e.g.
        click_button, type_text). The returned text is folded into the *same*
        next-turn observation the acting LLM already reads — no extra LLM call
        is made here; judgment is left to that next turn.
        """
        return None

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
        dep_evidence = spec.metadata.get("dependency_evidence")
        if dep_evidence:
            import json as _json
            parts.append(
                "DEPENDENCY EVIDENCE (real facts/output from completed prior objectives "
                "this one depends on — use these actual values, don't guess or invent them):\n"
                + _json.dumps(dep_evidence, indent=2, default=str)[:3000]
            )
        parts.append(f"GOAL: {spec.goal}")
        if steering:
            parts.append(f"STEERING CONTEXT: {steering}")
        parts.append(self._todo_context())
        parts.append("Begin by calling todo_write with a concise plan. Call exactly one tool per turn.")
        return "\n\n".join(parts)

    async def _mid_episode_reflection(
        self,
        *,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
        tool_name: str,
        args: dict[str, Any],
    ) -> str:
        """Ask for a short live recovery hint when the dedup guard warns."""
        transcript = json.dumps(
            evidence.get("llm_transcript", []),
            indent=2,
            default=str,
        )[:3000]
        prompt = (
            "The worker is about to repeat a tool call it already tried with identical "
            "arguments during the same attempt.\n\n"
            f"Objective: {spec.goal}\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {json.dumps(args, sort_keys=True, default=str)[:3000]}\n\n"
            f"Recent transcript:\n{transcript}\n\n"
            "Give one concise sentence suggesting a fundamentally different next approach. "
            "Do not restate the repeated call."
        )
        response = await self._llm.complete(
            [LLMMessage(role="user", content=prompt)],
            system="You are a live reflection helper for a ReAct worker.",
        )
        return (response.content or "").strip()[:3000]

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
        loop_started = time.monotonic()
        wall_limit = float(spec.metadata.get("timeout_seconds", 120))

        while steps_taken < max_steps:
            elapsed = time.monotonic() - loop_started
            if elapsed >= wall_limit:
                from trinity_pilot.telemetry.trace import emit

                emit(
                    "agentic_mixin.py:run_loop",
                    "wall_clock_timeout",
                    {
                        "objective_id": spec.objective_id,
                        "steps_taken": steps_taken,
                        "wall_limit": wall_limit,
                        "elapsed": round(elapsed, 1),
                    },
                    span="worker",
                )
                return WorkerResult(
                    status="failure",
                    summary=(
                        f"Worker wall-clock timeout after {wall_limit:.0f}s "
                        f"({steps_taken} steps) for '{spec.objective_id}'"
                    ),
                )

            _llm_call_started = time.monotonic()
            response: LLMResponse = await self._llm.complete_with_tools(
                messages,
                cast(list[Any], self._worker_tools()),
                system=self._worker_system_prompt(),
            )
            tokens_used += response.token_count
            from trinity_pilot.telemetry.trace import emit as _trace_llm_call

            _trace_llm_call(
                "agentic_mixin.py:run_loop",
                "llm_call",
                {
                    "objective_id": spec.objective_id,
                    "step": steps_taken + 1,
                    "elapsed_ms": round((time.monotonic() - _llm_call_started) * 1000),
                    "token_count": response.token_count,
                },
                span="llm_call",
            )

            # Build transcript entry for this step (written to evidence after dispatch)
            _tx_entry: dict[str, Any] = {
                "step": steps_taken + 1,
                "llm_text": response.content or "",
            }

            # Case: empty response
            if not response.tool_calls and not response.content:
                _tx_entry["tool_name"] = "(empty)"
                evidence.setdefault("llm_transcript", []).append(_tx_entry)
                # Was a hard fail at step 0. Gemini can return a genuinely empty
                # response (finish_reason MALFORMED_FUNCTION_CALL — model emitted
                # an invalid tool call structure) on the very first step; nudging
                # and retrying recovers cleanly, same as the later-step path below,
                # and is bounded by max_steps so it can't loop forever. (HH06)
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
                    if spec.metadata.get("mid_episode_reflection", False):
                        suggestion = await self._mid_episode_reflection(
                            spec=spec,
                            evidence=evidence,
                            tool_name=tool_name,
                            args=args,
                        )
                        if suggestion:
                            _dedup_prefix = f"{_dedup_prefix}\n\nLIVE REFLECTION: {suggestion}"
                        _tx_entry["mid_episode_reflection"] = True
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
            from trinity_pilot.telemetry.trace import emit as trace_emit

            trace_emit(
                "agentic_mixin.py:run_loop",
                "tool_dispatch",
                {
                    "objective_id": spec.objective_id,
                    "step": steps_taken + 1,
                    "tool": tool_name,
                    "args_preview": {k: str(v)[:80] for k, v in args.items()},
                },
                span="worker",
            )
            dispatch_result = await self._dispatch_tool(tool_name, args, evidence)
            if isinstance(dispatch_result, _FinishSignal):
                log_result = {"control": tool_name, "status": dispatch_result.status, "summary": dispatch_result.summary}
            elif isinstance(dispatch_result, _BlockerSignal):
                log_result = {"control": tool_name, "reason": dispatch_result.reason}
            else:
                log_result = {"observation": str(dispatch_result[0] if isinstance(dispatch_result, tuple) else dispatch_result)[:2000]}
            evidence.setdefault("tool_call_log", []).append(
                ToolCallRecord(tool=tool_name, args=dict(args), result=log_result).__dict__
            )

            # Control-flow signals
            if isinstance(dispatch_result, _FinishSignal):
                trace_emit(
                    "agentic_mixin.py:run_loop",
                    "tool_result",
                    {
                        "objective_id": spec.objective_id,
                        "step": steps_taken + 1,
                        "tool": tool_name,
                        "success": dispatch_result.status == "success",
                        "result_preview": dispatch_result.summary[:200],
                    },
                    span="worker",
                )
                _tx_entry["tool_result"] = f"finish(status={dispatch_result.status}): {dispatch_result.summary}"
                evidence.setdefault("llm_transcript", []).append(_tx_entry)
                return WorkerResult(
                    status=dispatch_result.status,
                    summary=dispatch_result.summary,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                    tool_call_log=[ToolCallRecord(**record) for record in evidence.get("tool_call_log", [])],
                )

            if isinstance(dispatch_result, _BlockerSignal):
                trace_emit(
                    "agentic_mixin.py:run_loop",
                    "tool_result",
                    {
                        "objective_id": spec.objective_id,
                        "step": steps_taken + 1,
                        "tool": tool_name,
                        "success": False,
                        "result_preview": dispatch_result.reason[:200],
                    },
                    span="worker",
                )
                _tx_entry["tool_result"] = f"report_blocking: {dispatch_result.reason}"
                evidence.setdefault("llm_transcript", []).append(_tx_entry)
                wr = WorkerResult(
                    status="partial_blocker",
                    summary=dispatch_result.reason,
                    evidence=evidence,
                    steps_taken=steps_taken + 1,
                    tokens_used=tokens_used,
                    tool_call_log=[ToolCallRecord(**record) for record in evidence.get("tool_call_log", [])],
                )
                raise WorkerBlocker(dispatch_result.reason, wr)

            # Domain tool: observation string or (string, image_bytes) tuple
            img_bytes: bytes | None = None
            if isinstance(dispatch_result, tuple):
                observation, img_bytes = dispatch_result
            else:
                observation = str(dispatch_result)
            _obs_str = observation if isinstance(observation, str) else str(observation)
            trace_emit(
                "agentic_mixin.py:run_loop",
                "tool_result",
                {
                    "objective_id": spec.objective_id,
                    "step": steps_taken + 1,
                    "tool": tool_name,
                    "success": not (
                        _obs_str.startswith("🛑")
                        or _obs_str.lower().startswith("failed")
                        or " failed" in _obs_str.lower()[:120]
                    ),
                    "result_preview": _obs_str[:200],
                },
                span="worker",
            )
            verify_result = await verify_action(
                tool_name,
                evidence,
                sensor_check=self._action_sensor_check(tool_name, args, evidence),
                sensor_read=self._action_sensor_read(tool_name, args, evidence),
            )
            if verify_result is not None:
                observation = f"{observation}\n\n[VERIFY:{verify_result.tier.value}] {verify_result.detail}"
            if _dedup_prefix:
                observation = f"{_dedup_prefix}\n\n{observation}"
            snapshot = self._worker_state_snapshot(evidence)
            todo_context = self._todo_context()
            if snapshot:
                observation = f"{observation}\n\n{todo_context}\n\n[STATE]\n{snapshot}"
            else:
                observation = f"{observation}\n\n{todo_context}"
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
