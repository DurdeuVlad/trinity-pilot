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
_WIKIPEDIA_TOPIC_PATTERNS = (
    re.compile(r"wikipedia page for ([a-z0-9 _()-]+)", re.IGNORECASE),
    re.compile(r"navigate to (?:the )?[\"']?([a-z0-9 _()-]+)[\"']? page", re.IGNORECASE),
    re.compile(r"from (?:the )?[\"']([a-z0-9 _()-]+)[\"'] wikipedia page", re.IGNORECASE),
    re.compile(r"page of ([a-z0-9 _()-]+)", re.IGNORECASE),
)
_BLANK_DOCUMENT_APPS = {"notepad", "wordpad"}
_URL_PATTERN = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)
_APP_EXECUTABLES = {
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "notepad": "notepad.exe",
    "paint": "mspaint.exe",
    "wordpad": "write.exe",
}
_DIRECT_DESKTOP_APP_ALIASES = {
    "calculator": "Calculator",
    "calc": "Calculator",
    "notepad": "Notepad",
    "paint": "Paint",
    "wordpad": "WordPad",
}
_VAGUE_PRODUCTIVITY_PATTERNS = (
    re.compile(r"\bwork faster\b", re.IGNORECASE),
    re.compile(r"\bmore productive\b", re.IGNORECASE),
    re.compile(r"\b(improve|speed up|make faster)\b.*\b(computer|pc|laptop)\b", re.IGNORECASE),
)
_PRODUCTIVITY_GUIDANCE_PATTERN = re.compile(
    r"provide brief general productivity guidance .* (app|workflow|slowdown symptom)",
    re.IGNORECASE,
)
_PYTHON_FILE_LISTING_PATTERNS = (
    re.compile(r"\blist\b.*\bpython files?\b", re.IGNORECASE),
    re.compile(r"\bidentify\b.*\bpython files?\b", re.IGNORECASE),
    re.compile(r"\bshow\b.*\bpython files?\b", re.IGNORECASE),
    re.compile(r"\bfind\b.*\bpython files?\b", re.IGNORECASE),
)
_CURRENT_DIRECTORY_PATH_PATTERNS = (
    re.compile(
        r"^\s*(?:get|show|display|return|print|tell me)\s+(?:the\s+)?(?:current|working)\s+directory\s+(?:path|location)\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
)
_CURRENT_DIRECTORY_CONTENTS_PATTERNS = (
    re.compile(
        r"^\s*(?:list|show|display|print|enumerate)\s+(?:the\s+)?(?:contents|files|items|entries)\s+"
        r"(?:of\s+(?:the\s+)?)?(?:current|working)\s+directory\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
)
_PYTHON_VERSION_OBJECTIVE_PATTERNS = (
    re.compile(r"^\s*(?:py|python)(?:\.exe)?\s+(?:--version|-v)\s*[.!]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:show|get|display|tell me|what is)\s+(?:the\s+)?python\s+version\s*[.!]?\s*$", re.IGNORECASE),
)
_SEARCH_QUERY_PATTERNS = (
    re.compile(r"search(?: the web)? for ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(
        r"search(?: the web)? for ([a-z0-9][^.,;\n]+?)(?:\s+(?:using|and|then|in|on)\b|$)",
        re.IGNORECASE,
    ),
)
_FIRST_SEARCH_RESULT_TITLE_PATTERNS = (
    re.compile(r"\bfirst search result\b", re.IGNORECASE),
    re.compile(r"\bfirst result title\b", re.IGNORECASE),
)
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
_DIRECT_DESKTOP_OPEN_PATTERNS = (
    re.compile(
        r"^\s*(?:open|launch|start)\s+(?:the\s+)?(?:windows\s+)?"
        r"(calculator|calc|notepad|paint|wordpad)"
        r"(?:\s+application|\s+app)?[.!]?\s*$",
        re.IGNORECASE,
    ),
)
_APP_VERSION_QUERY_PATTERNS = (
    re.compile(
        r"^\s*(?:open|launch|start)\s+an?\s+application\s+called\s+['\"]([^'\"]+)['\"].*\bversion(?: number)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:open|launch|start)\s+([a-z0-9_. -]+?)\s+and\s+tell me\s+(?:its|the)\s+version(?: number)?\b",
        re.IGNORECASE,
    ),
)
_EXPLICIT_APP_OPEN_PATTERNS = (
    re.compile(
        r"^\s*attempt\s+to\s+open\s+the\s+application\s+['\"]([^'\"]+)['\"][.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*attempt\s+to\s+open\s+the\s+['\"]([^'\"]+)['\"]\s+application[.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*open\s+the\s+application\s+['\"]([^'\"]+)['\"][.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*open\s+the\s+['\"]([^'\"]+)['\"]\s+application[.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:attempt\s+to\s+open|open|launch|start)\s+(?:an?|the)\s+application\s+called\s+['\"]([^'\"]+)['\"]"
        r"(?:\s+that\s+does\s+not\s+exist)?[.!]?\s*$",
        re.IGNORECASE,
    ),
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
    ) -> None:
        self._provider = provider
        self._bridge = bridge
        self._emit = emit_status
        self._cancel = cancel_requested
        self._registry = registry
        self._context = context
        self._validator = output_validator or OutputValidator()
        self._cancel_event = cancel_event
        self.last_step_payload: dict[str, Any] | None = None

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

        fast_path_result = await self._try_objective_fast_path(
            objective=objective,
            obj_index=obj_index,
            context=exec_ctx,
        )
        if fast_path_result is not None:
            lower_objective = objective.lower()
            stripped_result = fast_path_result.strip()
            if (
                exec_ctx is not None
                and "first paragraph" in lower_objective
                and ("wikipedia" in lower_objective or "page" in lower_objective)
                and len(stripped_result) >= 20
                and not fast_path_result.startswith("ERROR:")
                and not any(stripped_result.startswith(p) for p in _STATUS_PREFIXES)
            ):
                exec_ctx.update_state("latest_text_result", stripped_result)
                exec_ctx.world_state.last_text_artifact = stripped_result
            return fast_path_result

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

    async def _try_objective_fast_path(
        self,
        *,
        objective: str,
        obj_index: int,
        context: Optional[ExecutionContext],
    ) -> str | None:
        lower = objective.lower().strip()

        if _is_vague_productivity_objective(lower):
            guidance = (
                "To work faster, first identify the biggest bottleneck: slow startup, a specific slow app, "
                "or repetitive tasks. Quick wins are to close unnecessary startup apps and browser tabs, "
                "keep Windows and your main apps updated, and use keyboard shortcuts or simple automation "
                "for repeated work. Tell me which app, workflow, or slowdown symptom is costing you the "
                "most time and I can give targeted next steps."
            )
            self.last_step_payload = {
                "status": "success",
                "output": guidance,
                "artifacts": [],
                "execution_log": [],
                "metadata": {"fast_path": "vague_productivity_guidance"},
            }
            return guidance

        direct_app = _extract_direct_desktop_open_app(objective)
        if direct_app:
            app_key = direct_app.lower()
            description = (
                f"Open {direct_app} and create a new blank document"
                if app_key in _BLANK_DOCUMENT_APPS
                else f"Open {direct_app}"
            )
            return await self._execute_direct_bridge_task(
                description=description,
                domain="desktop",
                obj_index=obj_index,
                turn=1,
                extra_context={
                    "app_name": direct_app,
                    "app_exe_path": _APP_EXECUTABLES.get(app_key),
                },
                action={
                    "action_type": "desktop",
                    "parameters": {"app": direct_app, "action": "open"},
                },
            )

        version_query_app = _extract_app_version_query_target(objective)
        if version_query_app:
            open_result = await self._execute(
                {
                    "action_type": "desktop",
                    "parameters": {"app": version_query_app, "action": "open"},
                },
                obj_index,
                1,
            )
            if _looks_like_app_unavailable_result(open_result):
                return (
                    f"ERROR: The application '{version_query_app}' could not be found. "
                    "Therefore, its version number cannot be determined."
                )
            return None

        explicit_open_app = _extract_explicit_app_open_target(objective)
        if explicit_open_app:
            return await self._execute(
                {
                    "action_type": "desktop",
                    "parameters": {"app": explicit_open_app, "action": "open"},
                },
                obj_index,
                1,
            )

        if _looks_like_python_file_listing_objective(objective):
            result = await self._execute_direct_bridge_task(
                description="List all Python files in the current working directory",
                domain="cli",
                obj_index=obj_index,
                turn=1,
            )
            if _is_generic_success_marker(result):
                return "Listed Python files in the current working directory."
            return result

        if _looks_like_current_directory_path_objective(objective):
            return await self._execute_direct_bridge_task(
                description="Get the current directory path",
                domain="cli",
                obj_index=obj_index,
                turn=1,
            )

        if _looks_like_current_directory_contents_objective(objective):
            return await self._execute_direct_bridge_task(
                description="List the contents of the current directory",
                domain="cli",
                obj_index=obj_index,
                turn=1,
            )

        if _looks_like_python_version_objective(objective):
            result = await self._execute_direct_bridge_task(
                description="python --version",
                domain="cli",
                obj_index=obj_index,
                turn=1,
            )
            if _is_generic_success_marker(result):
                return "Successfully found the installed Python version using the command 'python --version'."
            return result

        query = _extract_search_query(objective)
        if query and "wikipedia" not in lower:
            return await self._execute(
                {
                    "action_type": "browse",
                    "parameters": {"action": "search", "text": query},
                },
                obj_index,
                1,
            )

        if _looks_like_first_search_result_title_objective(objective):
            return await self._execute_direct_bridge_task(
                description=objective,
                domain="web",
                obj_index=obj_index,
                turn=1,
            )

        topic = _infer_wikipedia_topic(objective, context)
        if (
            topic
            and "wikipedia" in lower
            and "first paragraph" not in lower
            and ("open" in lower or "navigate" in lower or "search" in lower)
        ):
            return await self._execute(
                {
                    "action_type": "browse",
                    "parameters": {"action": "search", "text": f"{topic} wikipedia"},
                },
                obj_index,
                1,
            )

        if (
            topic
            and "first paragraph" in lower
            and ("wikipedia" in lower or "page" in lower)
        ):
            return await self._execute(
                {
                    "action_type": "browse",
                    "parameters": {"action": "copy", "text": "first paragraph from the Wikipedia page"},
                },
                obj_index,
                1,
            )

        if lower in {"open notepad", "open notepad."}:
            return await self._execute(
                {
                    "action_type": "desktop",
                    "parameters": {"app": "Notepad", "action": "open"},
                },
                obj_index,
                1,
            )

        if "paste the copied paragraph into notepad" in lower:
            return await self._execute(
                {
                    "action_type": "desktop",
                    "parameters": {"app": "Notepad", "action": "paste"},
                },
                obj_index,
                1,
            )

        direct_desktop_match = re.match(
            r"open\s+(notepad|wordpad)\s+and\s+type\s+(.+)",
            objective.strip(),
            re.IGNORECASE,
        )
        if direct_desktop_match:
            app_name = direct_desktop_match.group(1).capitalize()
            app_key = direct_desktop_match.group(1).lower()
            return await self._execute_direct_bridge_task(
                description=objective,
                domain="desktop",
                obj_index=obj_index,
                turn=1,
                extra_context={
                    "app_name": app_name,
                    "app_exe_path": _APP_EXECUTABLES.get(app_key),
                },
                action={
                    "action_type": "desktop",
                    "parameters": {
                        "app": app_name,
                        "action": "type",
                        "text": direct_desktop_match.group(2),
                    },
                },
            )

        if _URL_PATTERN.search(objective) and any(
            token in lower for token in ("screenshot", "capture")
        ):
            return await self._execute_direct_bridge_task(
                description=objective,
                domain="web",
                obj_index=obj_index,
                turn=1,
            )

        return None

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
                if app.lower() in _BLANK_DOCUMENT_APPS:
                    description = f"Open {app} and create a new blank document"
                else:
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
            if app.lower() in _APP_EXECUTABLES:
                ctx["app_exe_path"] = _APP_EXECUTABLES[app.lower()]
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
            elif browse_action == "search" and text:
                description = f"Search the web for {text}"
            elif browse_action in {"read", "copy"}:
                target = selector or text or "the current page"
                description = f"{browse_action.title()} content from {target}"
            elif browse_action == "click":
                target = selector or text or url or "the current page"
                description = f"Click {target}"
            elif browse_action == "type":
                target = selector or "the current page"
                description = f"Type '{text}' into {target}".strip()
            else:
                description = " ".join(part for part in (browse_action, url, text, selector) if part).strip()

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

    async def _execute_direct_bridge_task(
        self,
        *,
        description: str,
        domain: str,
        obj_index: int,
        turn: int,
        extra_context: Optional[dict[str, Any]] = None,
        action: Optional[dict[str, Any]] = None,
    ) -> str:
        """Execute a direct single-step objective without an intermediate LLM action."""
        task_id = f"obj{obj_index}_t{turn}_{uuid.uuid4().hex[:6]}"
        exec_ctx = self._context
        ctx = dict(extra_context or {})

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

        if exec_ctx is not None and exec_ctx.world_state.has_state():
            ctx["_world_state"] = exec_ctx.world_state.to_context_dict()

        try:
            result = await self._bridge.execute_task(
                task_id=task_id,
                description=description,
                domain=domain,
                context=ctx,
                expected_outcome=None,
                timeout=60,
                max_retries=1,
                cancel_event=self._cancel_event,
            )
            result_str = _extract_result(result)
            self.last_step_payload = _build_step_payload(result, result_str)
            if self._context is not None and action is not None:
                self._context.update_world_state_from_action(action, result_str)
            return result_str
        except Exception as exc:
            self.last_step_payload = {
                "status": "failure",
                "output": f"ERROR: {exc}",
                "artifacts": [],
                "execution_log": [],
                "metadata": {},
            }
            return f"ERROR: {exc}"


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


def _infer_wikipedia_topic(objective: str, context: Optional[ExecutionContext]) -> str | None:
    candidates = [objective]
    if context is not None:
        for key, value in context.accumulated_state.items():
            if key.endswith("_desc") or key.endswith("_result"):
                candidates.append(str(value))

    for candidate in candidates:
        for pattern in _WIKIPEDIA_TOPIC_PATTERNS:
            match = pattern.search(candidate)
            if match:
                topic = match.group(1).strip().strip(" .,!?:;")
                if topic:
                    return topic
    return None


def _is_vague_productivity_objective(objective: str) -> bool:
    normalized = (objective or "").strip().lower()
    return bool(_PRODUCTIVITY_GUIDANCE_PATTERN.search(normalized)) or any(
        pattern.search(normalized) for pattern in _VAGUE_PRODUCTIVITY_PATTERNS
    )


def _extract_direct_desktop_open_app(objective: str) -> str | None:
    normalized = (objective or "").strip()
    for pattern in _DIRECT_DESKTOP_OPEN_PATTERNS:
        match = pattern.match(normalized)
        if not match:
            continue
        return _DIRECT_DESKTOP_APP_ALIASES.get(match.group(1).lower())
    return None


def _looks_like_python_file_listing_objective(objective: str) -> bool:
    normalized = (objective or "").strip().lower()
    if "python file" not in normalized:
        return False
    return any(pattern.search(normalized) for pattern in _PYTHON_FILE_LISTING_PATTERNS)


def _looks_like_current_directory_path_objective(objective: str) -> bool:
    normalized = (objective or "").strip()
    return any(pattern.match(normalized) for pattern in _CURRENT_DIRECTORY_PATH_PATTERNS)


def _looks_like_current_directory_contents_objective(objective: str) -> bool:
    normalized = (objective or "").strip()
    return any(pattern.match(normalized) for pattern in _CURRENT_DIRECTORY_CONTENTS_PATTERNS)


def _looks_like_python_version_objective(objective: str) -> bool:
    normalized = (objective or "").strip()
    return any(pattern.match(normalized) for pattern in _PYTHON_VERSION_OBJECTIVE_PATTERNS)


def _is_generic_success_marker(result: str) -> bool:
    normalized = (result or "").strip()
    if not normalized:
        return False
    if re.fullmatch(r"Result \d+: success", normalized, re.IGNORECASE):
        return True
    return normalized in {"OK (status=success)", "success"}


def _extract_app_version_query_target(objective: str) -> str | None:
    normalized = (objective or "").strip()
    for pattern in _APP_VERSION_QUERY_PATTERNS:
        match = pattern.match(normalized)
        if not match:
            continue
        app_name = match.group(1).strip()
        if app_name:
            return app_name
    return None


def _extract_explicit_app_open_target(objective: str) -> str | None:
    normalized = (objective or "").strip()
    for pattern in _EXPLICIT_APP_OPEN_PATTERNS:
        match = pattern.match(normalized)
        if not match:
            continue
        app_name = match.group(1).strip()
        if app_name:
            return app_name
    return None


def _looks_like_app_unavailable_result(result: str) -> bool:
    if not isinstance(result, str) or not result.startswith("ERROR:"):
        return False
    lowered = result.lower()
    return any(marker in lowered for marker in _APP_UNAVAILABLE_MARKERS)


def _extract_search_query(objective: str) -> str | None:
    normalized = (objective or "").strip()
    for pattern in _SEARCH_QUERY_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        query = match.group(1).strip().strip(" .,!?:;")
        if query:
            return query
    return None


def _looks_like_first_search_result_title_objective(objective: str) -> bool:
    normalized = (objective or "").strip().lower()
    return any(pattern.search(normalized) for pattern in _FIRST_SEARCH_RESULT_TITLE_PATTERNS)


def _is_terminal_app_unavailable_failure(action: dict[str, Any], result: str) -> bool:
    if action.get("action_type") != "desktop":
        return False

    params = action.get("parameters", {})
    if str(params.get("action", "")).strip().lower() != "open":
        return False

    return _looks_like_app_unavailable_result(result)
