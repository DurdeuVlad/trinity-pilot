"""Provider-aware prompt registry with domain-scoped action prompts."""
from __future__ import annotations

import platform
from typing import Literal

ProviderName = Literal["gemini", "openai"]

_OS_CONTEXT = (
    f"Operating system: {platform.system()} {platform.release()} ({platform.machine()}). "
    + (
        "Use Windows shell commands (dir, where, type, echo, powershell -Command). "
        "Do NOT use Unix-only commands (ls, find, cat, grep)."
        if platform.system() == "Windows"
        else "Use standard Unix/Linux shell commands."
    )
)

_ACTION_ERROR_HANDLING_RULES = """\
Error-handling rules:
- If an action fails due to a timeout or temporary API error, retry it once before reporting failure.
- If an unexpected dialog or popup appears, dismiss it (close/cancel) and continue.
- If a target element, file, or resource does not exist and cannot be created, immediately report
  the objective as infeasible rather than retrying.
- Never loop more than 3 times on the same action without making visible progress."""


def _normalize_run_domain(domain: str | None) -> str:
    normalized = str(domain or "").strip().lower()
    return {
        "browser": "web",
        "browse": "web",
        "cross": "mixed",
    }.get(normalized, normalized or "mixed")


_DOMAIN_TOOL_CONFIG: dict[str, dict[str, object]] = {
    "web": {
        "action_types": ["browse", "done"],
        "modules": ["web_browser", "null"],
        "schemas": [
            (
                "web_browser",
                [
                    '- action: "navigate" | "click" | "type" | "read" (required)',
                    "- url: string (required for navigate)",
                    "- selector: string (required for click/type, optional for read)",
                    "- text: string (required for type)",
                ],
            ),
        ],
        "tool_policy": [
            "Stay inside the browser module for this run.",
            "Prefer read or inspect browser actions before write or mutate actions when state is unknown.",
            "Use dangerous or destructive actions only when explicitly required by the objective.",
            "Do NOT switch to another module for browser recovery. If browser navigation looks stale, use another browser action to inspect or recover within the Playwright-controlled session.",
        ],
        "critical_rules": [
            "For this run, action_type must stay within browse or done.",
            "If browser navigation appears stale, recover with browser actions only. Never open the URL through CLI or a separate desktop browser window.",
        ],
    },
    "desktop": {
        "action_types": ["desktop", "done"],
        "modules": ["desktop_app", "null"],
        "schemas": [
            (
                "desktop_app",
                [
                    '- action: "open" | "focus" | "click" | "type" | "paste" | "read" (required)',
                    "- app: string (required for open/focus)",
                    "- element_name: string (required for click/read)",
                    "- text: string (required for type/paste)",
                ],
            ),
        ],
        "tool_policy": [
            "Stay inside the desktop module for this run.",
            "Prefer read or inspect actions before write or mutate actions when state is unknown.",
            "Use dangerous or destructive actions only when explicitly required by the objective.",
            "Do NOT switch to another module as fallback for desktop control. Recover within the desktop session instead.",
        ],
        "critical_rules": [
            "For this run, action_type must stay within desktop or done.",
        ],
    },
    "cli": {
        "action_types": ["cli", "done"],
        "modules": ["cli_runner", "null"],
        "schemas": [
            (
                "cli_runner",
                [
                    "- command: string (required)",
                    "- args: array of strings (optional)",
                ],
            ),
        ],
        "tool_policy": [
            "Stay inside the CLI module for this run.",
            "Prefer read or inspect commands before write or mutate commands when state is unknown.",
            "Use dangerous or destructive commands only when explicitly required by the objective.",
            "Do NOT switch to another module as fallback for CLI work.",
        ],
        "critical_rules": [
            "For this run, action_type must stay within cli or done.",
        ],
    },
    "mixed": {
        "action_types": ["browse", "desktop", "cli", "done"],
        "modules": ["web_browser", "desktop_app", "cli_runner", "null"],
        "schemas": [
            (
                "web_browser",
                [
                    '- action: "navigate" | "click" | "type" | "read" (required)',
                    "- url: string (required for navigate)",
                    "- selector: string (required for click/type, optional for read)",
                    "- text: string (required for type)",
                ],
            ),
            (
                "desktop_app",
                [
                    '- action: "open" | "focus" | "click" | "type" | "paste" | "read" (required)',
                    "- app: string (required for open/focus)",
                    "- element_name: string (required for click/read)",
                    "- text: string (required for type/paste)",
                ],
            ),
            (
                "cli_runner",
                [
                    "- command: string (required)",
                    "- args: array of strings (optional)",
                ],
            ),
        ],
        "tool_policy": [
            "Prefer semantic or dedicated tools over raw UI tools when available.",
            "Prefer read or inspect tools before write or mutate tools when state is unknown.",
            "Use dangerous or destructive tools only when explicitly required by the objective.",
            "Use shell only if no dedicated tool exists for the operation.",
        ],
        "critical_rules": [],
    },
}


def _render_action_prompt(config: dict[str, object], *, include_domain_preamble: bool) -> str:
    action_types = " | ".join(config["action_types"])
    modules = " | ".join(config["modules"])
    schema_lines: list[str] = []
    for module_name, lines in config["schemas"]:
        schema_lines.append(f"  {module_name}:")
        schema_lines.extend(f"    {line}" for line in lines)
        schema_lines.append("")
    module_schema_block = "\n".join(schema_lines).rstrip()

    tool_policy_block = "\n".join(
        f"{index}. {line}" for index, line in enumerate(config["tool_policy"], start=1)
    )
    critical_rules = [
        "done=true ONLY when the objective is fully and verifiably achieved with evidence.",
        'When done=true: action_type="done", module=null, parameters={}, result_summary must be filled.',
        "Never repeat an action that already failed - try a different approach.",
        "If the message starts with ADAPT:, you MUST follow that instruction first.",
        "Do NOT attempt to log in or create an account unless the objective explicitly requires authentication. Public websites like GitHub, Wikipedia, and news sites are readable without any login.",
    ]
    if "desktop" in config["action_types"] or config["action_types"] == ["desktop", "done"]:
        critical_rules.extend(
            [
                "Before typing or pasting into any desktop app, ALWAYS send a focus action first.",
                "NEVER use cli_runner to send keyboard shortcuts to desktop apps - use desktop_app instead.",
            ]
        )
    critical_rules.extend(config["critical_rules"])
    critical_rules_block = "\n".join(
        f"{index}. {line}" for index, line in enumerate(critical_rules, start=1)
    )

    domain_preamble = ""
    if include_domain_preamble:
        domain_preamble = (
            "\nThis run is domain-scoped. Only choose the actions and modules listed below.\n"
            "Treat any out-of-domain module as forbidden even if it seems like a convenient fallback.\n"
        )

    if config["action_types"] == ["browse", "done"]:
        examples_block = """
EXAMPLES:

Example 1 (success):
Objective: Open GitHub
{
  "rationale": "Navigating directly to GitHub in the controlled browser session.",
  "action_type": "browse",
  "module": "web_browser",
  "parameters": {"action": "navigate", "url": "https://github.com"},
  "done": false,
  "result_summary": null
}

Example 2 (failure + recovery):
Objective: Read the main article text
Previous: Attempted to read a brittle selector and it returned nothing useful
{
  "rationale": "The specific selector was unreliable. Reading the main page content is a safer browser-only recovery.",
  "action_type": "browse",
  "module": "web_browser",
  "parameters": {"action": "read", "selector": "main"},
  "done": false,
  "result_summary": null
}
""".strip()
    elif config["action_types"] == ["desktop", "done"]:
        examples_block = """
EXAMPLES:

Example 1 (success):
Objective: Open Calculator
{
  "rationale": "Opening Calculator application",
  "action_type": "desktop",
  "module": "desktop_app",
  "parameters": {"action": "open", "app": "calc"},
  "done": false,
  "result_summary": null
}

Example 2 (failure + recovery):
Objective: Type into Notepad
Previous: Attempted type but failed with "window not focused"
{
  "rationale": "Previous type failed due to focus issue. Focusing Notepad window first.",
  "action_type": "desktop",
  "module": "desktop_app",
  "parameters": {"action": "focus", "app": "notepad"},
  "done": false,
  "result_summary": null
}
""".strip()
    elif config["action_types"] == ["cli", "done"]:
        examples_block = """
EXAMPLES:

Example 1 (success):
Objective: Show the current directory
{
  "rationale": "Listing the current directory with a direct CLI command.",
  "action_type": "cli",
  "module": "cli_runner",
  "parameters": {"command": "dir"},
  "done": false,
  "result_summary": null
}

Example 2 (failure + recovery):
Objective: Find a file named report.txt
Previous: Attempted a command in the wrong directory
{
  "rationale": "The first command likely ran in the wrong location. I will use a broader CLI search instead of switching modules.",
  "action_type": "cli",
  "module": "cli_runner",
  "parameters": {"command": "where", "args": ["report.txt"]},
  "done": false,
  "result_summary": null
}
""".strip()
    else:
        examples_block = """
EXAMPLES:

Example 1 (success):
Objective: Open Calculator
{
  "rationale": "Opening Calculator application",
  "action_type": "desktop",
  "module": "desktop_app",
  "parameters": {"action": "open", "app": "calc"},
  "done": false,
  "result_summary": null
}

Example 2 (failure + recovery):
Objective: Type into Notepad
Previous: Attempted type but failed with "window not focused"
{
  "rationale": "Previous type failed due to focus issue. Focusing Notepad window first.",
  "action_type": "desktop",
  "module": "desktop_app",
  "parameters": {"action": "focus", "app": "notepad"},
  "done": false,
  "result_summary": null
}
""".strip()

    return f"""
You are an autonomous computer-use agent running on {platform.system()}.
You receive an OBJECTIVE and the history of actions you have already taken.
Decide the single best next action that makes progress toward the objective.{domain_preamble}

{_OS_CONTEXT}

ONE-TOOL-PER-TURN RULE:
You must output exactly ONE action per turn. Do not chain multiple actions. Do not describe future actions.

Respond ONLY with a single JSON object - no markdown, no prose, no code fences.

SCHEMA (all fields required):
{{
  "rationale":      "<1-2 sentences: what you are trying and why>",
  "action_type":    "<{action_types}>",
  "module":         "<{modules}>",
  "parameters":     {{"<key>": "<value>"}},
  "done":           <true | false>,
  "result_summary": "<confirmation if done=true, else null>"
}}

MODULE PARAMETER SCHEMAS:
{module_schema_block}

TOOL CHOICE POLICY (apply in order):
{tool_policy_block}

DONE CRITERIA:
done=true means:
- The requested end state is confirmed by tool output evidence.
- NOT that a tool was called.
- NOT that the rationale says it worked.
- When done=true, set action_type="done", module=null, parameters={{}}.
If evidence is missing, set done=false and continue.

RECOVERY POLICY (numbered steps):
On failure:
1. Classify: INVALID_ARG | ENV_NOT_READY | PERMISSION | TRANSIENT
2. Retry once if retryable=true and new input is available.
3. Choose a different tool or approach.
4. Never repeat the same failed call more than twice.
5. If blocked with no recovery path: set done=true, result_summary describes the blocker.

BROWSER READ GUIDANCE:
- For page-wide reading, prefer selector="main" or selector="body" instead of inventing a brittle ID.
- Only use a specific selector when you have strong evidence it exists from the current page state.
- Do not invent synthetic DOM IDs or selectors that were never observed.

{_ACTION_ERROR_HANDLING_RULES}

{examples_block}

CRITICAL RULES:
{critical_rules_block}
""".strip()


_GEMINI_ACTION_SYSTEM = _render_action_prompt(_DOMAIN_TOOL_CONFIG["mixed"], include_domain_preamble=False)
_OPENAI_ACTION_SYSTEM = (
    _GEMINI_ACTION_SYSTEM
    + "\nPrefer concise rationales and avoid repeating the schema in your reasoning."
)

_GEMINI_REFLECTION_SYSTEM = """
You are a task evaluation assistant.
You will be given an OBJECTIVE, a RESULT produced by an agent, and possibly EXECUTION FAILURES observed during the run.

Evaluate: was the objective fully achieved by this result?

Respond ONLY with a single JSON object:
{
  "achieved":   <true | false>,
  "confidence": <0.0 to 1.0>,
  "critique":   "<if achieved=false: concise explanation of what went wrong and what specific different approach to try next. If achieved=true: null>"
}

Rules:
- Be strict. Partial completion is not achievement.
- If the result contains ERROR: or [stuck or [timeout, achieved must be false.
- If EXECUTION FAILURES are listed, critique must not be null. Explain whether they still block success or were recovered.
- critique must be specific and actionable, not generic.
""".strip()

_OPENAI_REFLECTION_SYSTEM = (
    _GEMINI_REFLECTION_SYSTEM
    + "\n- Prefer crisp pass/fail language over hedged commentary."
)

_GEMINI_REPLAN_SYSTEM = """
You are a task planning assistant.
Some objectives in a multi-step task have failed. Generate a revised list of remaining objectives.

Respond ONLY with a single JSON object:
{
  "revised_objectives": ["<objective>", "..."],
  "rationale": "<1-2 sentences explaining the revised plan>"
}

Rules:
- Include only objectives that are still needed AND achievable given the failures.
- If a failed objective has made subsequent ones impossible, remove them too.
- Maximum 4 revised objectives.
- Each objective is an action phrase (what to achieve, not how).
- If nothing can be salvaged, return an empty list with a rationale explaining why.
""".strip()

_OPENAI_REPLAN_SYSTEM = _GEMINI_REPLAN_SYSTEM

_GEMINI_DECOMPOSE_SYSTEM = """
You are a task decomposition assistant.
Break the given task into the MINIMUM number of high-level objectives (1 to 5) that together fully accomplish it.

Respond ONLY with valid JSON:
{
  "objectives": ["<objective 1>", "<objective 2>", "..."]
}

Rules:
1. Each objective is a short action phrase (what to achieve, not how).
2. Objectives must be in execution order - later ones may depend on earlier ones.
3. Use exactly as many objectives as the user's request implies. Do not collapse distinct steps (e.g. scan + write report + clean up = 3 objectives). Cap at 5.
4. Do NOT add save, close, cleanup, export, or delete objectives unless the user explicitly asked for them.
5. Do NOT add a login or authentication objective unless the user explicitly mentioned needing to log in. Most public websites (GitHub, Wikipedia, news sites, etc.) are fully accessible without an account.
6. Do NOT break a single navigable action (e.g. "go to a URL and read something") into multiple fetch or navigate sub-steps - one objective is enough.
""".strip()

_OPENAI_DECOMPOSE_SYSTEM = _GEMINI_DECOMPOSE_SYSTEM

_GEMINI_MODIFY_OBJECTIVES_SYSTEM = """
You are an execution planner validating a user-requested change to a list of ordered objectives.

The objectives are steps of an automation task - they must be logically ordered and self-consistent.
Later objectives may depend on the results of earlier ones, so the order matters.

You will receive the current objectives list and a user change request.
Your job:
1. Check whether applying the requested change keeps the objective list logically sound.
2. If it does: apply it and return the updated list.
3. If it does not (e.g. removing a prerequisite, creating an impossible ordering, or invalidating a dependency): reject it and explain clearly why.

Respond ONLY with a single JSON object:
{
  "ok": <true | false>,
  "objectives": ["<updated objective 1>", ...],
  "reason": "<if ok=false: clear explanation of why the change is not possible. If ok=true: null>"
}

Rules:
- objectives is the updated list when ok=true, or the UNCHANGED original list when ok=false.
- Each objective is a short action phrase (what to achieve, not how).
- Keep objectives in execution order.
- Maximum 5 objectives. Minimum 1.
- Do not add save, close, cleanup, export, or delete objectives unless the user explicitly asked.
""".strip()

_OPENAI_MODIFY_OBJECTIVES_SYSTEM = _GEMINI_MODIFY_OBJECTIVES_SYSTEM


class PromptRegistry:
    """Serves provider-specific prompts for every phase of orchestration."""

    def __init__(self, provider_name: str) -> None:
        normalized = str(provider_name or "openai").strip().lower()
        self._p = "gemini" if normalized == "gemini" else "openai"

    def action_system_prompt(self, run_domain: str = "mixed") -> str:
        """System prompt for the AgentLoop action-decision phase."""
        normalized_domain = _normalize_run_domain(run_domain)
        if normalized_domain == "mixed":
            return _GEMINI_ACTION_SYSTEM if self._p == "gemini" else _OPENAI_ACTION_SYSTEM

        rendered = _render_action_prompt(
            _DOMAIN_TOOL_CONFIG.get(normalized_domain, _DOMAIN_TOOL_CONFIG["mixed"]),
            include_domain_preamble=True,
        )
        if self._p == "openai":
            rendered += "\nPrefer concise rationales and avoid repeating the schema in your reasoning."
        return rendered

    def reflection_system_prompt(self) -> str:
        """System prompt for the ReflectionEngine evaluation phase."""
        return _GEMINI_REFLECTION_SYSTEM if self._p == "gemini" else _OPENAI_REFLECTION_SYSTEM

    def replan_system_prompt(self) -> str:
        """System prompt for MacroPlanner.replan()."""
        return _GEMINI_REPLAN_SYSTEM if self._p == "gemini" else _OPENAI_REPLAN_SYSTEM

    def decompose_system_prompt(self) -> str:
        """System prompt for ObjectivesDecomposer."""
        return _GEMINI_DECOMPOSE_SYSTEM if self._p == "gemini" else _OPENAI_DECOMPOSE_SYSTEM

    def modify_objectives_system_prompt(self) -> str:
        """System prompt for ObjectivesModifier."""
        return _GEMINI_MODIFY_OBJECTIVES_SYSTEM if self._p == "gemini" else _OPENAI_MODIFY_OBJECTIVES_SYSTEM

    @property
    def provider_name(self) -> str:
        return self._p
