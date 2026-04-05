"""Level 1 — decomposes a user task description into high-level objectives."""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .providers.base import LLMProvider
    from .prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

_IMPLICIT_OBJECTIVE_PREFIXES = (
    "save ",
    "close ",
    "clean up",
    "cleanup",
    "delete ",
    "remove ",
    "export ",
    "archive ",
)
_EXPLICIT_PERSISTENCE_TOKENS = (
    "save",
    "export",
    "download",
    "archive",
    "delete",
    "remove",
    "close",
    "print",
)
_PRODUCTIVITY_GUIDANCE_OBJECTIVE = (
    "Provide brief general productivity guidance for the user's computer and ask "
    "which app, workflow, or slowdown symptom they want help with"
)
_PROJECT_PYTHON_FILES_OBJECTIVE = "List all Python files in the current working directory"
_CURRENT_DIRECTORY_PATH_OBJECTIVE = "Get the current directory path"
_CURRENT_DIRECTORY_CONTENTS_OBJECTIVE = "List the contents of the current directory"
_VAGUE_PRODUCTIVITY_PATTERNS = (
    re.compile(r"\bwork faster\b", re.IGNORECASE),
    re.compile(r"\bmore productive\b", re.IGNORECASE),
    re.compile(r"\b(improve|speed up|make faster)\b.*\b(computer|pc|laptop)\b", re.IGNORECASE),
    re.compile(r"\bhelp me\b.*\b(computer|pc|laptop)\b", re.IGNORECASE),
)
_AMBIGUOUS_PYTHON_FILES_PATTERNS = (
    re.compile(
        r"\bdo something useful\b.*\bpython files?\b.*\b(project|repo|repository|directory)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bpython files?\b.*\b(project|repo|repository|directory)\b.*\bdo something useful\b",
        re.IGNORECASE,
    ),
)
_DIRECT_PYTHON_FILE_LISTING_PATTERNS = (
    re.compile(
        r"^\s*(?:list|show|display|print|enumerate)\s+(?:all\s+)?python files?\s+"
        r"(?:in|from|under)\s+(?:the\s+)?(?:current\s+working|current|working)\s+directory[.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:list|show|display|print|enumerate)\s+(?:the\s+)?"
        r"(?:current\s+working|current|working)\s+directory(?:'s)?\s+python files?[.!]?\s*$",
        re.IGNORECASE,
    ),
)
_DIRECT_APP_VERSION_QUERY_PATTERNS = (
    re.compile(
        r"^\s*(?:open|launch|start)\b.*\bapplication\b.*\bversion number\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:open|launch|start)\b.*\bapplication\b.*\bversion\b",
        re.IGNORECASE,
    ),
)
_OPEN_APPLICATION_CALLED_PATTERN = re.compile(
    r"\bopen\s+(?:an?|the)\s+application\s+called\s+['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_CONCRETE_CONTEXT_MARKERS = (
    "python",
    "file",
    "folder",
    "directory",
    "browser",
    "website",
    "url",
    "notepad",
    "calculator",
    "search",
    "open ",
    "list ",
    "show ",
    "version",
    "app ",
    "application",
    "command",
)
_DIRECT_DESKTOP_APP_ALIASES = {
    "calculator": "Calculator",
    "calc": "Calculator",
    "notepad": "Notepad",
    "paint": "Paint",
    "wordpad": "WordPad",
}
_DIRECT_DESKTOP_OPEN_PATTERNS = (
    re.compile(
        r"^\s*(?:open|launch|start)\s+(?:the\s+)?(?:windows\s+)?"
        r"(calculator|calc|notepad|paint|wordpad)"
        r"(?:\s+application|\s+app)?[.!]?\s*$",
        re.IGNORECASE,
    ),
)

# Fallback prompt used when no registry is supplied (e.g., unit tests)
_FALLBACK_SYSTEM_PROMPT = """
You are a task decomposition assistant. Break the given task into 2 to 5 high-level objectives.
Respond ONLY with valid JSON: {"objectives": ["<objective 1>", ...]}
Rules: each objective is a short action phrase; objectives are in execution order.
""".strip()


class ObjectivesDecomposer:
    """Calls the AI once to convert a task description into a list of objectives."""

    def __init__(
        self,
        provider: "LLMProvider",
        registry: Optional["PromptRegistry"] = None,
    ) -> None:
        self._provider = provider
        self._registry = registry

    async def decompose(
        self,
        task_description: str,
        capabilities: dict | None = None,
        prompt_suffix: str = "",
    ) -> list[str]:
        """Return a list of high-level objective strings for the given task.

        Falls back to a single-item list containing the raw task if parsing fails.
        """
        deterministic = _deterministic_objectives(task_description)
        if deterministic:
            return deterministic

        system_prompt = (
            self._registry.decompose_system_prompt()
            if self._registry is not None
            else _FALLBACK_SYSTEM_PROMPT
        )
        if prompt_suffix:
            system_prompt = f"{system_prompt}{prompt_suffix}"
        user_content = f"Task: {task_description}"
        if capabilities:
            available = ", ".join(capabilities.keys())
            user_content += f"\n\nAvailable execution adapters: {available}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        try:
            raw = await self._provider.call(messages, json_mode=True)
            objectives = self._parse(raw)
            if objectives:
                objectives = _filter_implied_objectives(task_description, objectives)
                logger.info("Decomposed into %d objectives", len(objectives))
                return objectives
        except Exception as exc:
            logger.warning("Objectives decomposition failed (%s), using raw task", exc)

        return [task_description]

    def _parse(self, raw: str) -> list[str]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise ValueError("No JSON object found in response")
            data = json.loads(match.group(0))

        objectives = data.get("objectives", [])
        if not isinstance(objectives, list) or not objectives:
            raise ValueError("Response missing 'objectives' list")

        return [str(obj).strip() for obj in objectives if str(obj).strip()][:5]


def _filter_implied_objectives(task_description: str, objectives: list[str]) -> list[str]:
    """Drop cleanup/persistence objectives unless the user explicitly requested them."""
    lowered_task = (task_description or "").lower()
    allows_persistence = any(token in lowered_task for token in _EXPLICIT_PERSISTENCE_TOKENS)

    if allows_persistence:
        return objectives

    filtered = [
        objective
        for objective in objectives
        if not (objective or "").strip().lower().startswith(_IMPLICIT_OBJECTIVE_PREFIXES)
    ]
    return filtered or objectives


def _deterministic_objectives(task_description: str) -> list[str] | None:
    """Use a safe non-actuating plan for highly underspecified productivity asks."""
    lowered = (task_description or "").strip().lower()
    if not lowered:
        return None

    if _extract_direct_desktop_open_objective(task_description):
        return [task_description.strip()]

    if _looks_like_python_file_listing_task(task_description):
        return [_PROJECT_PYTHON_FILES_OBJECTIVE]

    if any(pattern.search(lowered) for pattern in _AMBIGUOUS_PYTHON_FILES_PATTERNS):
        return [_PROJECT_PYTHON_FILES_OBJECTIVE]

    if any(pattern.search(task_description or "") for pattern in _DIRECT_APP_VERSION_QUERY_PATTERNS):
        return [task_description.strip()]

    mixed_version_open = _split_python_version_then_app_open(task_description)
    if mixed_version_open is not None:
        return mixed_version_open

    if _looks_like_current_directory_listing_task(lowered):
        return [
            _CURRENT_DIRECTORY_PATH_OBJECTIVE,
            _CURRENT_DIRECTORY_CONTENTS_OBJECTIVE,
        ]

    matches_productivity = any(pattern.search(lowered) for pattern in _VAGUE_PRODUCTIVITY_PATTERNS)
    has_concrete_context = any(marker in lowered for marker in _CONCRETE_CONTEXT_MARKERS)
    if matches_productivity and not has_concrete_context:
        return [_PRODUCTIVITY_GUIDANCE_OBJECTIVE]
    return None


def _looks_like_python_file_listing_task(task_description: str) -> bool:
    """Keep exact/simple Python file listing asks on the deterministic path."""
    normalized = (task_description or "").strip()
    return any(pattern.match(normalized) for pattern in _DIRECT_PYTHON_FILE_LISTING_PATTERNS)


def _looks_like_current_directory_listing_task(lowered_task: str) -> bool:
    """Detect read-only directory inspection requests that should stay deterministic."""
    if "current directory" not in lowered_task and "working directory" not in lowered_task:
        return False

    has_path_request = "path" in lowered_task or "location" in lowered_task or "pwd" in lowered_task
    has_contents_request = any(
        phrase in lowered_task
        for phrase in (
            "list its contents",
            "list the contents",
            "show its contents",
            "show the contents",
            "contents of the current directory",
            "contents of the working directory",
        )
    )
    return has_path_request and has_contents_request


def _extract_direct_desktop_open_objective(task_description: str) -> str | None:
    normalized = (task_description or "").strip()
    for pattern in _DIRECT_DESKTOP_OPEN_PATTERNS:
        match = pattern.match(normalized)
        if not match:
            continue
        return _DIRECT_DESKTOP_APP_ALIASES.get(match.group(1).lower())
    return None


def _split_python_version_then_app_open(task_description: str) -> list[str] | None:
    lowered = (task_description or "").strip().lower()
    if "python" not in lowered or "version" not in lowered:
        return None
    if "open" not in lowered or "application" not in lowered:
        return None

    match = _OPEN_APPLICATION_CALLED_PATTERN.search(task_description or "")
    if not match:
        return None

    app_name = match.group(1).strip()
    if not app_name:
        return None

    return [
        "python --version",
        f"Open an application called '{app_name}'",
    ]
