"""Level-2 agent loop: pure Act phase for one objective.

Responsibility: execute one objective by iterating action→observation cycles
until the AI declares done, a guard fires, or time runs out.

Deliberately has NO retry logic, NO reflection, NO replanning. Those concerns
belong to the execution runner. This loop just acts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from .execution_context import ExecutionContext, ModuleResult, _STATUS_PREFIXES
from .output_validator import OutputValidator
from .prompt_registry import PromptRegistry

if TYPE_CHECKING:
    from .providers.base import LLMProvider

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12
MAX_WALL_SECONDS = 240
_APP_UNAVAILABLE_MARKERS = (
    "app not found",
    "application not found",
    "could not be found",
    "could not find",
    "cannot be opened",
    "cannot find the file specified",
    "does not exist",
    "not installed",
    "not available",
    "not recognized",
    "window_not_found",
)


@dataclass
class _Turn:
    action: dict
    result: str


@dataclass
class _State:
    objective: str
    history: list[_Turn] = field(default_factory=list)
    iteration: int = 0
    adapt_hint: str = ""  # Consumed once per message build; set by loop guards or caller


class AgentLoop:
    """Executes one objective through a dynamic AI-driven action loop.

    For each iteration:
      1. Build messages (system prompt + objective + prior turns + optional adapt hint).
      2. Call LLM → parse JSON action.
      3. Validate schema; inject correction hint and retry if invalid.
      4. Check done=True → return result summary.
      5. Guard against identical repeated actions → inject rethink hint.
      6. Execute via TrinityBridge.
      7. Record (action, result) in history. Repeat.
    """

    def __init__(
        self,
        provider: "LLMProvider",
        bridge: Any,
        emit_status: Callable[[str, str], None],
        cancel_requested: Callable[[], bool],
        registry: PromptRegistry,
        context: Optional[ExecutionContext] = None,
        output_validator: Optional[OutputValidator] = None,
        cancel_event: Any = None,
        resume_event: Optional[threading.Event] = None,
    ) -> None:
        self._provider = provider
        self._bridge = bridge
        self._emit = emit_status
        self._cancel = cancel_requested
        self._registry = registry
        self._context = context
        self._validator = output_validator or OutputValidator()
        self._cancel_event = cancel_event
        self._resume_event = resume_event
        self.last_step_payload: dict[str, Any] | None = None

    @staticmethod
    def _browser_session_state_key(obj_index: int) -> str:
        del obj_index
        return "task_browser_session_id"

    async def act(
        self,
        objective: str,
        obj_index: int,
        context: Optional[ExecutionContext] = None,
        adapt_hint: str = "",
    ) -> str:
        """Execute one objective. Returns a result summary string.

        Args:
            objective:   The high-level goal for this phase.
            obj_index:   Objective position in the plan (for status messages).
            context:     Shared execution context (accumulated results/errors).
            adapt_hint:  Reflection critique from a previous attempt, injected
                         into the first decision message.
        """
        state = _State(objective=objective, adapt_hint=adapt_hint)
        self.last_step_payload = None
        recent_keys: deque[str] = deque(maxlen=3)
        loop_guard_hits = 0
        deadline = asyncio.get_running_loop().time() + MAX_WALL_SECONDS
        exec_ctx = context or self._context

        while state.iteration < MAX_ITERATIONS:
            if self._cancel():
                return "[cancelled]"
            if asyncio.get_running_loop().time() > deadline:
                return f"[timeout after {MAX_WALL_SECONDS}s]"

            state.iteration += 1
            self._emit("Thinking…", "thinking")

            messages = self._build_messages(state)
            state.adapt_hint = ""  # Consumed — clear so it doesn't repeat next turn

            # ── LLM call ──────────────────────────────────────────────────
            try:
                raw = await self._provider.call(messages, json_mode=True)
                action = _parse_json(raw)
            except Exception as exc:
                logger.warning("AI call failed obj=%d turn=%d: %s", obj_index, state.iteration, exc)
                return f"[AI error: {exc}]"

            # ── Schema validation ──────────────────────────────────────────
            validation = self._validator.validate_action(action)
            if not validation.is_valid:
                errs = "; ".join(validation.errors)
                state.adapt_hint = (
                    f"Schema error in your last response: {errs}. "
                    "Fix the JSON format and choose a valid action."
                )
                if state.iteration < MAX_ITERATIONS - 1:
                    continue
                return f"[schema error: {errs}]"

            # ── Done check ─────────────────────────────────────────────────
            if action.get("done"):
                summary = action.get("result_summary") or "Step complete."
                if _requires_execution_evidence(state.objective) and not _has_successful_execution_history(state.history):
                    state.adapt_hint = (
                        "You cannot mark this objective as done yet. "
                        "This objective requires a real tool action to run successfully first. "
                        "Execute the missing browser, desktop, or CLI action and only mark done after you have concrete evidence."
                    )
                    self._emit(
                        "That completion claim isn't grounded in a successful action yet. Trying again…",
                        "warning",
                    )
                    if state.iteration < MAX_ITERATIONS:
                        continue
                    return "[stuck: objective marked done without execution evidence]"
                self._emit(summary[:160], "success")
                return summary

            # ── Loop guard — identical repeated action ─────────────────────
            action_key = (
                f"{action.get('action_type')}:"
                f"{action.get('module')}:"
                f"{json.dumps(action.get('parameters', {}), sort_keys=True)}"
            )
            if action_key in recent_keys:
                loop_guard_hits += 1
                if loop_guard_hits >= 2:
                    return "[stuck: same action repeated after rethink — objective may be unreachable]"
                # First repeat: warn and clear deque so LLM gets a fresh slate
                recent_keys.clear()
                state.adapt_hint = (
                    "You just repeated an action that already ran. That approach is not working. "
                    "Choose a completely different strategy: different module, different parameters, "
                    "or a different interpretation of what the objective needs."
                )
                self._emit("That same approach isn't working. Switching strategy…", "warning")
                continue
            recent_keys.append(action_key)

            # ── Execute ────────────────────────────────────────────────────
            rationale = action.get("rationale", "").strip()
            if rationale:
                self._emit(f"→ {rationale[:160]}", "info")
            else:
                atype = action.get("action_type", "action")
                self._emit(f"→ Running {atype}…", "info")
            result = await self._execute(action, obj_index, state.iteration)
            action_type = action.get("action_type", "")
            params = action.get("parameters", {})

            if action_type == "cli" and result.strip():
                self._emit(result.strip(), "output")

            if result.startswith("WAITING_FOR_HUMAN:"):
                human_msg = result[len("WAITING_FOR_HUMAN:"):].strip()
                self._emit(f"Waiting for you: {human_msg}", "warning")
                try:
                    from .event_bus import get_event_bus
                    get_event_bus().blocker_detected.emit(human_msg)
                except Exception:
                    pass
                if self._resume_event is not None:
                    self._resume_event.clear()
                    while not self._resume_event.is_set():
                        await asyncio.sleep(0.2)
                        if self._cancel():
                            return "[cancelled]"
                    self._emit("Resuming…", "info")
                    deadline = asyncio.get_running_loop().time() + MAX_WALL_SECONDS
                    state.history.append(_Turn(action=action, result="Human resolved the blocker — reassessing page."))
                    continue
                else:
                    return f"[blocked: {human_msg}]"

            if (
                exec_ctx is not None
                and action_type == "browse"
                and params.get("action") in {"read", "copy"}
                and not result.startswith("ERROR:")
                and not result.startswith("OK (status=")
                and len(result.strip()) >= 20
            ):
                exec_ctx.update_state("latest_text_result", result.strip())

            if _is_terminal_app_unavailable_failure(action, result):
                self._emit("The requested app appears unavailable. Stopping further attempts for this objective.", "warning")
                return result

            # Record in shared context
            if exec_ctx:
                module = action.get("module", "unknown")
                exec_ctx.add_result(
                    module,
                    ModuleResult(
                        module=module,
                        status="failure" if result.startswith("ERROR:") else "success",
                        output=result,
                        error=result if result.startswith("ERROR:") else None,
                        timestamp=time.time(),
                    ),
                )
                # Note: world state is updated inside _execute() so it also
                # covers fast-path actions that bypass this block.

            state.history.append(_Turn(action=action, result=result))

        return "[max iterations reached — objective may be incomplete]"

    # ── Message builder ────────────────────────────────────────────────────

    def _build_messages(self, state: _State) -> list[dict]:
        messages: list[dict] = [
            {"role": "system", "content": self._registry.action_system_prompt()},
            {"role": "user",   "content": f"OBJECTIVE: {state.objective}"},
        ]

        # Inject completed prior-objective results and explicit world state so
        # the AI knows exactly what is open/running before it acts.
        ctx = self._context
        inject_index = 2
        if ctx is not None and ctx.accumulated_state:
            prior_lines: list[str] = []
            i = 1
            while f"objective_{i}_desc" in ctx.accumulated_state:
                desc   = ctx.accumulated_state[f"objective_{i}_desc"]
                result = ctx.accumulated_state.get(f"objective_{i}_result", "completed")
                prior_lines.append(
                    f"  Obj {i}: {desc[:80]} → {str(result)[:120]}"
                )
                i += 1
            if prior_lines:
                messages.insert(inject_index, {
                    "role": "user",
                    "content": (
                        "PRIOR COMPLETED OBJECTIVES (world state before your turn):\n"
                        + "\n".join(prior_lines)
                        + "\n\nBuild on this state — do NOT redo work that is already done."
                    ),
                })
                inject_index += 1

        if ctx is not None and ctx.world_state.has_state():
            ws_lines = ctx.world_state.to_summary_lines()
            if ws_lines:
                messages.insert(inject_index, {
                    "role": "user",
                    "content": (
                        "CURRENT WORLD STATE (explicit facts — trust these over your prior assumptions):\n"
                        + "\n".join(ws_lines)
                        + "\n\nDo NOT reopen apps that are already open. "
                        "Do NOT re-read content that is already in Last text."
                    ),
                })

        history = state.history
        if len(history) > 10:
            old, recent = history[:-8], history[-8:]
            compressed = "\n".join(
                f"- Turn {i + 1}: {t.action.get('action_type')} on "
                f"{t.action.get('module')} → {t.result[:120]}"
                for i, t in enumerate(old)
            )
            messages.append({
                "role": "user",
                "content": f"PRIOR CONTEXT (compressed):\n{compressed}",
            })
            history = recent

        for turn in history:
            messages.append({"role": "assistant", "content": json.dumps(turn.action)})
            messages.append({"role": "user",      "content": f"RESULT: {turn.result}"})

        final = "Choose your next action. Respond with JSON only."
        if state.adapt_hint:
            final = f"ADAPT: {state.adapt_hint}\n\n{final}"
        messages.append({"role": "user", "content": final})
        return messages

    # ── Action execution ───────────────────────────────────────────────────

    async def _execute(self, action: dict, obj_index: int, turn: int) -> str:
        """Route action to TrinityBridge and return an observation string."""
        action_type = action.get("action_type", "")
        params = action.get("parameters", {})
        domain = {"browse": "web", "desktop": "desktop", "cli": "cli"}.get(action_type, "web")
        task_id = f"obj{obj_index}_t{turn}_{uuid.uuid4().hex[:6]}"
        ctx = dict(params)
        exec_ctx = self._context

        # ── Layer 2: inject prior objective results into ctx for all backends ──
        # This makes accumulated state available to every adapter/subprocess so
        # they can make context-aware decisions (e.g. skip reopening an already-
        # open app, know which file was just created, etc.).
        if exec_ctx is not None and exec_ctx.accumulated_state:
            prior: dict[str, dict] = {}
            i = 1
            while f"objective_{i}_desc" in exec_ctx.accumulated_state:
                desc = exec_ctx.accumulated_state[f"objective_{i}_desc"]
                result = exec_ctx.accumulated_state.get(f"objective_{i}_result", "")
                prior[f"obj{i}"] = {
                    "desc": str(desc)[:200],
                    "result": str(result)[:400],
                }
                i += 1
            if prior:
                ctx["_prior_results"] = prior

        # Layer 3: inject explicit world state for structured backend decisions
        # (e.g. skip_relaunch when active_app already matches target)
        if exec_ctx is not None and exec_ctx.world_state.has_state():
            ctx["_world_state"] = exec_ctx.world_state.to_context_dict()

        if action_type == "desktop":
            app = params.get("app", "")
            verb = params.get("action", "")
            text = params.get("text", "")
            if verb == "open":
                description = f"Open {app}"
            elif verb == "focus":
                # Explicit focus/activate — brings the window to the foreground
                # so subsequent type/paste actions land in the right app.
                description = f"Focus and bring to front: {app}"
                ctx["focus_only"] = True
            elif verb == "paste":
                # Paste clipboard content — the executor focuses the window first,
                # then sends Ctrl+V. Never route this through cli_runner.
                description = f"Paste clipboard content into {app}"
                ctx["paste_action"] = True
                # ── Layer 1: clipboard handoff ──────────────────────────────
                # If a prior objective produced text (e.g. browser scraped a page),
                # write it to the OS clipboard NOW, before the desktop subprocess
                # launches. The subprocess will then find it ready for Ctrl+V.
                if exec_ctx is not None:
                    text_content = exec_ctx.get_latest_text_result()
                    if text_content:
                        ctx["clipboard_content"] = text_content
                        logger.info(
                            "[AgentLoop] clipboard handoff: %d chars from prior objective",
                            len(text_content),
                        )
            elif verb == "type" and text:
                description = f"Type '{text}' in {app}"
            else:
                description = f"{verb} {app} {text}".strip()
            ctx["app_name"] = app or "Windows Desktop"
            logger.info(
                "[AgentLoop] desktop: app=%s verb=%s description=%s", app, verb, description
            )

        elif action_type == "cli":
            cmd = params.get("command", "")
            args = params.get("args", [])
            description = f"{cmd} {' '.join(args)}".strip()

        elif action_type == "browse":
            browse_action = str(params.get("action", "")).strip().lower()
            url = str(params.get("url", "")).strip()
            selector = str(params.get("selector", "")).strip()
            text = str(params.get("text", "")).strip()

            if browse_action == "navigate" and url:
                description = f"Open the page at {url}"
            elif browse_action in {"read", "copy"}:
                target = selector or text or "the current page"
                description = f"{browse_action.title()} content from {target}"
            elif browse_action == "search" and text:
                description = f"Find information about {text}"
            elif browse_action == "click":
                target = selector or text or url or "the current page"
                description = f"Click {target}"
            elif browse_action == "type":
                target = selector or "the current page"
                description = f"Type '{text}' into {target}".strip()
            else:
                description = " ".join(part for part in (browse_action, url, text, selector) if part).strip()
            progress_label = "browser action" if browse_action == "search" else (browse_action or "browser action")
            self._emit(f"Launching browser automation for {progress_label}…", "info")
            if exec_ctx is not None:
                session_key = self._browser_session_state_key(obj_index)
                browser_session_id = exec_ctx.accumulated_state.get(session_key)
                if not isinstance(browser_session_id, str) or not browser_session_id.strip():
                    browser_session_id = f"obj{obj_index}_browser_{uuid.uuid4().hex[:8]}"
                    exec_ctx.update_state(session_key, browser_session_id)
                ctx["_browser_session_id"] = browser_session_id
                ctx["_reuse_browser_session"] = True

        else:
            description = json.dumps({"action": action_type, **params})

        try:
            result = await self._bridge.execute_task(
                task_id=task_id,
                description=description,
                domain=domain,
                context=ctx,
                expected_outcome=action.get("rationale"),
                timeout=60,
                max_retries=1,
                cancel_event=self._cancel_event,
            )
            result_str = _extract_result(result)
            self.last_step_payload = _build_step_payload(result, result_str)
            if action_type == "browse":
                self._emit("Browser automation returned a result.", "info")
        except Exception as exc:
            self.last_step_payload = {
                "status": "failure",
                "output": f"ERROR: {exc}",
                "artifacts": [],
                "execution_log": [],
                "metadata": {},
            }
            return f"ERROR: {exc}"

        # Update world state for every action (including fast-path calls)
        if self._context is not None:
            self._context.update_world_state_from_action(action, result_str)

        return result_str

    async def cleanup_browser_session(
        self,
        obj_index: int,
        context: Optional[ExecutionContext] = None,
    ) -> None:
        """Close the reusable browser session for an objective, if one exists."""
        exec_ctx = context or self._context
        if exec_ctx is None:
            return

        session_key = self._browser_session_state_key(obj_index)
        session_id = exec_ctx.accumulated_state.pop(session_key, None)
        if not isinstance(session_id, str) or not session_id.strip():
            return

        close_browser_session = getattr(self._bridge, "close_browser_session", None)
        if callable(close_browser_session):
            await close_browser_session(session_id)


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Cannot parse JSON from: {raw[:200]}")


def _extract_result(result: Any) -> str:
    if result is None:
        return "OK (no output)"
    if hasattr(result, "status") and result.status != "success":
        error = getattr(result, "error", "") or getattr(result, "message", "") or "unknown error"
        if str(error).startswith("WAITING_FOR_HUMAN:"):
            return str(error)
        return f"ERROR: {error}"
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        for candidate in (
            metadata.get("text_output"),
            metadata.get("output"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()[:500]
        raw_result = metadata.get("raw_result")
        if isinstance(raw_result, dict):
            for candidate in (
                raw_result.get("text_output"),
                raw_result.get("output"),
            ):
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()[:500]
    if hasattr(result, "execution_log"):
        execution_log = getattr(result, "execution_log") or []
        if execution_log:
            details = getattr(execution_log[-1], "details", None)
            if isinstance(details, str) and details.strip():
                return details.strip()[:500]
    if hasattr(result, "output") and result.output:
        return str(result.output)[:500]
    if hasattr(result, "status"):
        return f"OK (status={result.status})"
    return str(result)[:500]


def _build_step_payload(result: Any, output: str) -> dict[str, Any]:
    raw_result = _serialize_result(result)
    metadata = getattr(result, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    payload = {
        "status": getattr(result, "status", "success") or "success",
        "output": output,
        "artifacts": list(getattr(result, "artifacts", []) or []),
        "execution_log": _serialize_execution_log(getattr(result, "execution_log", []) or []),
        "metadata": dict(metadata),
    }
    if category := getattr(result, "category", None):
        payload["category"] = category
    if error := getattr(result, "error", None):
        payload["error"] = error
    payload["metadata"].setdefault("raw_result", raw_result)
    return payload


def _serialize_execution_log(entries: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for entry in entries:
        if hasattr(entry, "model_dump"):
            dumped = entry.model_dump()
            if isinstance(dumped, dict):
                serialized.append(dumped)
                continue
        if isinstance(entry, dict):
            serialized.append(dict(entry))
            continue
        serialized.append(
            {
                "step": getattr(entry, "step", None),
                "action": getattr(entry, "action", None),
                "result": getattr(entry, "result", None),
                "details": getattr(entry, "details", None),
                "timestamp": getattr(entry, "timestamp", None),
            }
        )
    return serialized


def _serialize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        dumped = result.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if isinstance(result, dict):
        return dict(result)
    return {
        "task_id": getattr(result, "task_id", None),
        "status": getattr(result, "status", None),
        "category": getattr(result, "category", None),
        "error": getattr(result, "error", None),
        "execution_log": _serialize_execution_log(getattr(result, "execution_log", []) or []),
        "artifacts": list(getattr(result, "artifacts", []) or []),
        "metadata": dict(getattr(result, "metadata", {}) or {}),
    }


def _requires_execution_evidence(objective: str) -> bool:
    normalized = re.sub(r"\s+", " ", (objective or "").strip().lower())
    if not normalized:
        return False

    informational_prefixes = (
        "report ",
        "explain ",
        "inform ",
        "notify ",
        "tell the user",
        "summarize ",
        "answer ",
    )
    if normalized.startswith(informational_prefixes):
        return False

    execution_markers = (
        "open ",
        "launch ",
        "start ",
        "search ",
        "go to ",
        "navigate ",
        "click ",
        "type ",
        "paste ",
        "copy ",
        "read ",
        "extract ",
        "capture ",
        "screenshot ",
        "focus ",
        "list ",
        "show ",
        "display ",
        "find ",
        "run ",
        "execute ",
        "rename ",
        "move ",
        "delete ",
        "close ",
        "use cli",
        "use the cli",
        "use browser",
        "use the browser",
        "use desktop",
        "use the desktop",
    )
    return any(marker in normalized for marker in execution_markers)


def _has_successful_execution_history(history: list[_Turn]) -> bool:
    for turn in history:
        result = str(turn.result or "").strip()
        if result.startswith((
            "ERROR:",
            "[AI error:",
            "[stuck:",
            "[schema error:",
            "[cancelled]",
            "[timeout after",
            "[max iterations",
        )):
            continue
        return True
    return False


def _looks_like_app_unavailable_result(result: str) -> bool:
    if not isinstance(result, str) or not result.startswith("ERROR:"):
        return False
    lowered = result.lower()
    return any(marker in lowered for marker in _APP_UNAVAILABLE_MARKERS)

def _is_terminal_app_unavailable_failure(action: dict[str, Any], result: str) -> bool:
    if action.get("action_type") != "desktop":
        return False

    params = action.get("parameters", {})
    if str(params.get("action", "")).strip().lower() != "open":
        return False

    return _looks_like_app_unavailable_result(result)
