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
    steer_hint: str = ""  # Consumed once per decision turn; advisory only
    consecutive_failures: int = 0
    last_action_failed: bool = False


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
        run_domain: str = "mixed",
        context: Optional[ExecutionContext] = None,
        output_validator: Optional[OutputValidator] = None,
        cancel_event: Any = None,
        resume_event: Optional[threading.Event] = None,
        pause_event: Optional[threading.Event] = None,
        performance_tracker: Any = None,
        emit_step_detail: Optional[Callable[[int, int, str, str], None]] = None,
        emit_plan_update: Optional[Callable[[int, dict[str, Any]], None]] = None,
        consume_steer: Optional[Callable[[], str]] = None,
        emit_cli_step: Optional[Callable[[int, dict], None]] = None,
    ) -> None:
        self._provider = provider
        self._bridge = bridge
        self._emit = emit_status
        self._cancel = cancel_requested
        self._registry = registry
        self._run_domain = self._normalize_run_domain(run_domain)
        self._context = context
        self._validator = output_validator or OutputValidator()
        self._cancel_event = cancel_event
        self._resume_event = resume_event
        self._pause_event = pause_event
        self._performance_tracker = performance_tracker
        self._emit_step_detail = emit_step_detail
        self._emit_plan_update = emit_plan_update
        self._consume_steer = consume_steer
        self._emit_cli_step = emit_cli_step
        self.last_step_payload: dict[str, Any] | None = None
        self.last_attempt_payload: dict[str, Any] | None = None
        self.last_attempt_trace: list[dict[str, Any]] = []

    @staticmethod
    def _browser_session_state_key(obj_index: int) -> str:
        del obj_index
        return "task_browser_session_id"

    def _handle_cli_step(self, step: dict, obj_index: int) -> None:
        event = step.get("event", "")
        if event == "plan_ready":
            self._emit(f"Planning complete — {step['total']} steps", "thinking")
        elif event == "step_started":
            cmd = step.get("command", "")
            action = step.get("action", "")
            total = step.get("total", "?")
            idx = step.get("step_index", 0) + 1
            label = cmd.strip() if cmd.strip() else action
            if len(label) > 120:
                label = label[:120].rsplit(" ", 1)[0] + "…"
            self._emit(f"[{idx}/{total}] $ {label}", "thinking")
        elif event == "step_done":
            stdout_summary = step.get("stdout_summary", "")
            verification = step.get("verification", "skipped")
            next_action = step.get("next_action")
            if step.get("status") == "success":
                detail = stdout_summary if stdout_summary and stdout_summary != "no output" else "Done."
                self._emit(f"✓ {step['action']}: {detail}", "step")
                if verification == "passed":
                    self._emit("Verified ✓", "step")
                if next_action:
                    self._emit(f"Next: {next_action}", "thinking")
            else:
                self._emit(f"✗ {step['action']} failed", "warning")
        elif event == "replanning":
            msg = step.get("message", "Replanning…")
            self._emit(msg, "warning")
        if self._emit_cli_step is not None:
            self._emit_cli_step(obj_index, step)

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
        self.last_attempt_payload = None
        self.last_attempt_trace = []
        recent_keys: deque[str] = deque(maxlen=3)
        loop_guard_hits = 0
        deadline = asyncio.get_running_loop().time() + MAX_WALL_SECONDS
        exec_ctx = context or self._context

        while state.iteration < MAX_ITERATIONS:
            if self._cancel():
                return "[cancelled]"
            # If the user pressed Pause in the overlay, wait here between turns.
            if self._pause_event is not None and not self._pause_event.is_set():
                self._emit("Paused — waiting for you to resume...", "warning")
                while not self._pause_event.is_set():
                    await asyncio.sleep(0.2)
                    if self._cancel():
                        return "[cancelled]"
                self._emit("Resuming...", "info")
            if asyncio.get_running_loop().time() > deadline:
                return f"[timeout after {MAX_WALL_SECONDS}s]"

            state.iteration += 1
            if state.iteration == MAX_ITERATIONS:
                self._emit(f"Step {state.iteration} — Last attempt…", "thinking")
            elif state.consecutive_failures >= 3:
                self._emit(
                    f"Step {state.iteration} — {state.consecutive_failures} failures in a row…",
                    "warning",
                )
            elif state.last_action_failed:
                self._emit(f"Step {state.iteration} — Retrying after failure…", "thinking")
            else:
                self._emit(f"Step {state.iteration} — Thinking…", "thinking")
            state.steer_hint = self._drain_steer()

            messages = self._build_messages(state)
            state.adapt_hint = ""  # Consumed — clear so it doesn't repeat next turn
            state.steer_hint = ""  # Consumed — clear so it doesn't repeat next turn

            # ── LLM call ──────────────────────────────────────────────────
            try:
                raw = await self._provider.call(messages, json_mode=True, purpose="execution")
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
                if self._run_domain == "mixed":
                    state.adapt_hint = (
                        "You just repeated an action that already ran. That approach is not working. "
                        "Choose a completely different strategy: different module, different parameters, "
                        "or a different interpretation of what the objective needs."
                    )
                else:
                    state.adapt_hint = (
                        "You just repeated an action that already ran. That approach is not working. "
                        f"Stay inside the {self._run_domain} domain and choose a different in-domain strategy: "
                        "different parameters, a different action in the same module family, or a different "
                        "interpretation of what the objective needs."
                    )
                self._emit("That same approach isn't working. Switching strategy…", "warning")
                continue
            recent_keys.append(action_key)

            policy_violation = self._domain_policy_violation(action)
            if policy_violation is not None:
                self.last_step_payload = {
                    "status": "failure",
                    "output": policy_violation,
                    "error": policy_violation,
                    "artifacts": [],
                    "execution_log": [
                        {
                            "step": state.iteration,
                            "action": self._describe_action(action),
                            "result": "failure",
                            "details": policy_violation,
                        }
                    ],
                    "metadata": {
                        "policy_violation": True,
                        "policy_category": "domain_escape",
                        "canonical_status": "policy_terminated",
                        "allowed_domain": self._run_domain,
                    },
                }
                self._emit(policy_violation, "error")
                return f"[policy_stop: {policy_violation}]"

            # ── Execute ────────────────────────────────────────────────────
            rationale = action.get("rationale", "").strip()
            if rationale:
                _r = rationale
                if len(_r) > 280:
                    boundary = max(
                        _r.rfind(". ", 0, 280),
                        _r.rfind("? ", 0, 280),
                        _r.rfind("! ", 0, 280),
                    )
                    _r = _r[: boundary + 1] if boundary >= 40 else _r[:280]
                self._emit(f"→ {_r}", "info")
            else:
                atype = action.get("action_type", "action")
                self._emit(f"→ Running {atype}…", "info")
            result = await self._execute(action, obj_index, state.iteration)
            action_type = action.get("action_type", "")
            params = action.get("parameters", {})

            if action_type == "cli" and result.strip():
                self._emit(result.strip(), "output")
            elif action_type == "desktop" and result.startswith("ERROR:"):
                # Exception path — bridge threw before the result emit inside _execute ran
                _verb = params.get("action", "interact")
                _app = params.get("app", "app")
                self._emit(f"Desktop: {_verb} {_app} — crashed", "error")

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
                and not _result_indicates_failure(None, result)
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
                        status=_task_result_status(None, result),
                        output=result,
                        error=result if _result_indicates_failure(None, result) else None,
                        timestamp=time.time(),
                    ),
                )
                # Note: world state is updated inside _execute() so it also
                # covers fast-path actions that bypass this block.

            if self._emit_step_detail is not None:
                self._emit_step_detail(
                    obj_index,
                    state.iteration,
                    action.get("action_type", "?"),
                    result[:120],
                )

            self._record_attempt_result(state.iteration, action, result)
            state.history.append(_Turn(action=action, result=result))

            _step_status = (self.last_step_payload or {}).get("status", "")
            if _result_indicates_failure(None, result) or _step_status == "failure":
                state.consecutive_failures += 1
                state.last_action_failed = True
            else:
                state.consecutive_failures = 0
                state.last_action_failed = False

        return "[max iterations reached — objective may be incomplete]"

    @staticmethod
    def _normalize_run_domain(domain: str) -> str:
        normalized = str(domain or "").strip().lower()
        return {
            "browser": "web",
            "browse": "web",
            "cross": "mixed",
        }.get(normalized, normalized or "mixed")

    def _domain_policy_violation(self, action: dict[str, Any]) -> str | None:
        allowed_action_types = {
            "web": {"browse"},
            "desktop": {"desktop"},
            "cli": {"cli"},
            "mixed": {"browse", "desktop", "cli"},
        }.get(self._run_domain, {"browse", "desktop", "cli"})

        action_type = str(action.get("action_type", "") or "").strip().lower()
        if action_type in allowed_action_types:
            return None

        label = {
            "browse": "browser",
            "desktop": "desktop",
            "cli": "cli",
        }.get(action_type, action_type or "unknown")
        return (
            f"Domain policy violation: this {self._run_domain} run cannot execute "
            f"{label} actions. Policy stopped the run instead of allowing cross-domain drift."
        )

    # ── Message builder ────────────────────────────────────────────────────

    def _build_messages(self, state: _State) -> list[dict]:
        messages: list[dict] = [
            {"role": "system", "content": self._registry.action_system_prompt(self._run_domain)},
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
                inject_index += 1
            if (
                self._run_domain == "mixed"
                and str(ctx.world_state.active_app or "").strip().lower() == "browser"
            ):
                messages.insert(inject_index, {
                    "role": "user",
                    "content": (
                        "BROWSER SESSION CONTINUITY:\n"
                        "- A Playwright-controlled browser session is already active.\n"
                        "- If this objective involves browsing, navigation, search, login state, or reading web content, stay inside web_browser.\n"
                        "- Do NOT use cli_runner or desktop_app to open URLs, launch another browser window, or manage tabs for this browser objective.\n"
                        "- Only switch away from the browser when the objective explicitly requires a non-browser action on another surface."
                    ),
                })
                inject_index += 1

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
        if state.steer_hint:
            final = (
                "USER STEERING (advisory for the current objective only):\n"
                f"{state.steer_hint}\n\n"
                "Use this to adjust your next action if relevant. "
                "Do not skip the objective, rewrite the plan, or claim completion without execution evidence.\n\n"
                f"{final}"
            )
        messages.append({"role": "user", "content": final})
        return messages

    def _drain_steer(self) -> str:
        if self._consume_steer is None:
            return ""
        try:
            steer_text = str(self._consume_steer() or "")
        except Exception:
            return ""
        lines = [line.strip() for line in steer_text.splitlines() if line.strip()]
        if not lines:
            return ""
        return "\n".join(lines)[:1000]

    # ── Action execution ───────────────────────────────────────────────────

    async def _execute(self, action: dict, obj_index: int, turn: int) -> str:
        """Route action to TrinityBridge and return an observation string."""
        action_type = action.get("action_type", "")
        params = action.get("parameters", {})
        domain = {"browse": "web", "desktop": "desktop", "cli": "cli"}.get(action_type, "web")
        backend = _backend_plan_state_key(action_type)
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
        if exec_ctx is not None and backend is not None:
            plan_state = exec_ctx.get_plan_state(f"objective_{obj_index}", backend)
            if plan_state:
                ctx["_plan_state"] = plan_state

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
            if exec_ctx is not None:
                desktop_session_key = "task_desktop_session_id"
                desktop_session_id = exec_ctx.accumulated_state.get(desktop_session_key)
                if not isinstance(desktop_session_id, str) or not desktop_session_id.strip():
                    desktop_session_id = f"task_desktop_{uuid.uuid4().hex[:8]}"
                    exec_ctx.update_state(desktop_session_key, desktop_session_id)
                ctx["_desktop_session_id"] = desktop_session_id
            logger.info(
                "[AgentLoop] desktop: app=%s verb=%s description=%s", app, verb, description
            )
            self._emit(f"→ Desktop: {verb} {app or 'app'}…", "info")

        elif action_type == "cli":
            cmd = params.get("command", "")
            args = params.get("args", [])
            description = f"{cmd} {' '.join(args)}".strip()
            _cli_label = description if description else "cli"
            if len(_cli_label) > 120:
                _cli_label = _cli_label[:120].rsplit(" ", 1)[0] + "…"
            self._emit(f"$ {_cli_label}", "info")
            if exec_ctx is not None:
                cli_session_key = "task_cli_session_id"
                cli_session_id = exec_ctx.accumulated_state.get(cli_session_key)
                if not isinstance(cli_session_id, str) or not cli_session_id.strip():
                    cli_session_id = f"task_cli_{uuid.uuid4().hex[:8]}"
                    exec_ctx.update_state(cli_session_key, cli_session_id)
                ctx["_cli_session_id"] = cli_session_id
            ctx["_cli_progress_cb"] = lambda step, _oi=obj_index: self._handle_cli_step(step, _oi)

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

        action_timer = (
            self._performance_tracker.start_action(
                action_type=f"{action_type}_action",
                action_description=description,
                module=domain,
                objective=description,
            )
            if self._performance_tracker is not None
            else None
        )
        try:
            result = await self._bridge.execute_task(
                task_id=task_id,
                description=description,
                domain=domain,
                context=ctx,
                expected_outcome=_build_expected_outcome(action, description),
                timeout=60,
                max_retries=1,
                cancel_event=self._cancel_event,
            )
            result_str = _extract_result(result)
            if action_timer is not None and self._performance_tracker is not None:
                self._performance_tracker.finish_action(
                    action_timer,
                    status=_task_result_status(result, result_str),
                    result_summary=result_str,
                    data={"task_id": task_id, "action_type": action_type},
                )
            self.last_step_payload = _build_step_payload(result, result_str)
            if exec_ctx is not None and backend is not None:
                plan_state = _extract_plan_state(self.last_step_payload)
                if plan_state is not None:
                    exec_ctx.update_plan_state(f"objective_{obj_index}", backend, plan_state)
                    if self._emit_plan_update is not None:
                        self._emit_plan_update(obj_index, dict(plan_state))
            if action_type == "browse":
                if result_str and len(result_str) > 4:
                    preview = result_str.strip()[:160].rsplit(" ", 1)[0]
                    self._emit(preview, "success")
                else:
                    self._emit("Browser step complete.", "success")
            elif action_type == "cli":
                _cli_status = (self.last_step_payload or {}).get("status", "")
                if result_str and len(result_str) > 4:
                    _preview = result_str.strip()[:160].rsplit(" ", 1)[0]
                    _level = "success" if _cli_status == "success" else "warning"
                    self._emit(_preview, _level)
                elif _cli_status == "failure":
                    self._emit("Command failed.", "warning")
            elif action_type == "desktop":
                _desktop_verb = params.get("action", "interact")
                _desktop_app = params.get("app", "app")
                _failed = any(
                    kw in result_str.lower()
                    for kw in ("error", "failed", "exception", "unexpected", "traceback")
                )
                if _failed:
                    self._emit(f"Desktop: {_desktop_verb} {_desktop_app} — failed", "error")
                else:
                    self._emit(f"Desktop: {_desktop_verb} {_desktop_app} — done", "success")
        except Exception as exc:
            if self._performance_tracker is not None and action_timer is not None:
                self._performance_tracker.finish_action(
                    action_timer,
                    status="failure",
                    result_summary=str(exc),
                    data={"task_id": task_id, "action_type": action_type},
                )
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
            self._context.update_world_state_from_action(action, result_str, self.last_step_payload)

        return result_str

    def _record_attempt_result(self, step_num: int, action: dict[str, Any], result: str) -> None:
        payload = dict(self.last_step_payload or {})
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        execution_log = payload.get("execution_log", [])
        if not isinstance(execution_log, list):
            execution_log = []

        trace_entry = {
            "step": step_num,
            "action_type": action.get("action_type", ""),
            "module": action.get("module", ""),
            "parameters": dict(action.get("parameters", {}) or {}),
            "rationale": str(action.get("rationale", "") or ""),
            "result": result,
            "status": payload.get("status", _task_result_status(None, result)),
            "execution_log": list(execution_log),
        }
        self.last_attempt_trace.append(trace_entry)

        synthetic_entry = {
            "step": step_num,
            "action": self._describe_action(action),
            "result": "failure" if _result_indicates_failure(None, result) else "success",
            "details": str(result or "")[:240],
        }

        combined_execution_log: list[dict[str, Any]] = []
        if self.last_attempt_payload and isinstance(self.last_attempt_payload.get("execution_log"), list):
            combined_execution_log.extend(self.last_attempt_payload["execution_log"])
        combined_execution_log.extend(entry for entry in execution_log if isinstance(entry, dict))
        combined_execution_log.append(synthetic_entry)

        combined_artifacts: list[Any] = []
        if self.last_attempt_payload and isinstance(self.last_attempt_payload.get("artifacts"), list):
            combined_artifacts.extend(self.last_attempt_payload["artifacts"])
        if isinstance(payload.get("artifacts"), list):
            combined_artifacts.extend(payload["artifacts"])

        combined_metadata = {}
        if self.last_attempt_payload and isinstance(self.last_attempt_payload.get("metadata"), dict):
            combined_metadata.update(self.last_attempt_payload["metadata"])
        combined_metadata.update(metadata)

        if plan_state := _extract_plan_state(payload):
            combined_metadata["plan_state"] = plan_state

        self.last_attempt_payload = {
            "status": payload.get("status", _task_result_status(None, result)),
            "output": result,
            "error": payload.get("error"),
            "artifacts": combined_artifacts,
            "execution_log": combined_execution_log,
            "metadata": combined_metadata,
        }

    @staticmethod
    def _describe_action(action: dict[str, Any]) -> str:
        action_type = str(action.get("action_type", "") or "").strip()
        params = dict(action.get("parameters", {}) or {})
        if action_type == "browse":
            browse_action = str(params.get("action", "")).strip()
            target = str(params.get("selector") or params.get("url") or params.get("text") or "").strip()
            return " ".join(part for part in (browse_action, target) if part).strip() or "browse action"
        if action_type == "desktop":
            desktop_action = str(params.get("action", "")).strip()
            app = str(params.get("app", "")).strip()
            return " ".join(part for part in (desktop_action, app) if part).strip() or "desktop action"
        if action_type == "cli":
            command = str(params.get("command", "")).strip()
            args = params.get("args", [])
            if isinstance(args, list):
                rendered_args = " ".join(str(item) for item in args)
                return " ".join(part for part in (command, rendered_args) if part).strip() or "cli action"
            return command or "cli action"
        return action_type or "action"

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

    async def cleanup_desktop_session(
        self,
        context: Optional[ExecutionContext] = None,
    ) -> None:
        """Close the persistent desktop subprocess session for this run, if one exists."""
        exec_ctx = context or self._context
        if exec_ctx is None:
            return
        session_id = exec_ctx.accumulated_state.pop("task_desktop_session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            return
        close_fn = getattr(self._bridge, "close_desktop_session", None)
        if callable(close_fn):
            await close_fn(session_id)

    async def cleanup_cli_session(
        self,
        context: Optional[ExecutionContext] = None,
    ) -> None:
        """Close the persistent CLI backend session for this run, if one exists."""
        exec_ctx = context or self._context
        if exec_ctx is None:
            return
        session_id = exec_ctx.accumulated_state.pop("task_cli_session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            return
        close_fn = getattr(self._bridge, "close_cli_session", None)
        if callable(close_fn):
            await close_fn(session_id)


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
    execution_log = getattr(result, "execution_log", []) or []
    if _execution_log_has_only_failures(execution_log):
        failure_detail = _execution_log_failure_detail(execution_log)
        if failure_detail:
            return f"ERROR: {failure_detail}"
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        error = metadata.get("error") or metadata.get("error_details")
        if isinstance(error, str) and error.strip() and _looks_like_backend_failure(error):
            return f"ERROR: {error.strip()}"
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
    if plan_state := _extract_plan_state(payload):
        payload["metadata"].setdefault("plan_state", plan_state)
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


def _build_expected_outcome(action: dict[str, Any], description: str) -> str:
    action_type = str(action.get("action_type", "")).strip().lower()
    params = action.get("parameters", {}) if isinstance(action.get("parameters"), dict) else {}

    if action_type == "browse":
        browse_action = str(params.get("action", "")).strip().lower()
        url = str(params.get("url", "")).strip()
        selector = str(params.get("selector", "")).strip()
        text = str(params.get("text", "")).strip()
        if browse_action == "navigate" and url:
            return f"The browser is open on {url}."
        if browse_action == "type" and text:
            target = selector or "the active field"
            return f"The text '{text}' is visible in {target}."
        if browse_action in {"read", "copy"}:
            target = selector or "the current page"
            return f"The requested content from {target} has been extracted."
        if browse_action == "click":
            target = selector or url or "the requested element"
            return f"The click on {target} changed the page into the requested state."

    if action_type == "desktop":
        desktop_action = str(params.get("action", "")).strip().lower()
        app = str(params.get("app", "")).strip() or "the target application"
        text = str(params.get("text", "")).strip()
        if desktop_action == "open":
            return f"{app} is open and ready."
        if desktop_action == "focus":
            return f"{app} is focused."
        if desktop_action in {"type", "paste"} and text:
            return f"The text '{text}' is present in {app}."

    if action_type == "cli":
        command = str(params.get("command", "")).strip()
        if command:
            return f"The command '{command}' completed and produced the requested output."

    return description.rstrip(".") + "."


def _backend_plan_state_key(action_type: str) -> str | None:
    return {
        "browse": "browser",
        "desktop": "desktop",
        "cli": "cli",
    }.get(str(action_type or "").strip().lower())


def _task_result_status(result: Any, result_str: str | None = None) -> str:
    return "failure" if _result_indicates_failure(result, result_str) else "success"


def _result_indicates_failure(result: Any, result_str: str | None = None) -> bool:
    text = str(result_str or "").strip()
    if text.startswith("ERROR:"):
        return True
    if _looks_like_backend_failure(text):
        return True
    if result is None:
        return False

    status = str(getattr(result, "status", "")).strip().lower()
    if status == "failure":
        return True

    execution_log = getattr(result, "execution_log", []) or []
    if _execution_log_has_only_failures(execution_log):
        return True

    error = getattr(result, "error", None)
    if isinstance(error, str) and error.strip() and _looks_like_backend_failure(error):
        return True

    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        raw_result = metadata.get("raw_result", {})
        if isinstance(raw_result, dict):
            raw_error = raw_result.get("error") or raw_result.get("error_details")
            if isinstance(raw_error, str) and raw_error.strip() and _looks_like_backend_failure(raw_error):
                return True

    return False


def _execution_log_has_only_failures(entries: list[Any]) -> bool:
    saw_failure = False
    for entry in entries:
        result = str(getattr(entry, "result", None) if not isinstance(entry, dict) else entry.get("result", "")).strip().lower()
        if result == "success":
            return False
        if result == "failure":
            saw_failure = True
    return saw_failure


def _execution_log_failure_detail(entries: list[Any]) -> str | None:
    for entry in reversed(entries):
        details = getattr(entry, "details", None) if not isinstance(entry, dict) else entry.get("details")
        action = getattr(entry, "action", None) if not isinstance(entry, dict) else entry.get("action")
        for candidate in (details, action):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()[:500]
    return None


def _looks_like_backend_failure(value: str) -> bool:
    stripped = str(value or "").strip()
    return stripped.startswith("[BG-ACT-")


def _extract_plan_state(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        plan_state = metadata.get("plan_state")
        if isinstance(plan_state, dict):
            return dict(plan_state)

        raw_result = metadata.get("raw_result", {})
        if isinstance(raw_result, dict):
            raw_metadata = raw_result.get("metadata", {})
            if isinstance(raw_metadata, dict):
                nested_plan_state = raw_metadata.get("plan_state")
                if isinstance(nested_plan_state, dict):
                    return dict(nested_plan_state)
    return None


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
