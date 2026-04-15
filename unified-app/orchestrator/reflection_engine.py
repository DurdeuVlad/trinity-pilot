"""Reflexion-pattern reflection engine for post-objective evaluation.

Implements the Reflexion architecture (Shinn et al., NeurIPS 2023):
After each agent attempt on an objective, the LLM produces a natural-language
critique of what went wrong. That critique is injected into the next attempt,
conditioning the agent to try a fundamentally different approach rather than
repeating the same failure.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from .prompt_registry import PromptRegistry

if TYPE_CHECKING:
    from .providers.base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class Reflection:
    """Result of evaluating one objective attempt."""

    achieved: bool
    confidence: float           # 0.0–1.0
    critique: Optional[str]     # None when achieved=True; actionable hint otherwise


class ReflectionEngine:
    """Evaluates whether an objective was achieved and produces a verbal critique.

    Usage (per objective, per attempt):
        reflection = await engine.reflect(objective, result, attempt)
        if reflection.achieved:
            break   # move to next objective
        else:
            inject reflection.critique into next agent_loop.act() call
    """

    def __init__(self, provider: "LLMProvider", registry: PromptRegistry) -> None:
        self._provider = provider
        self._registry = registry

    async def reflect(
        self,
        objective: str,
        result: str,
        attempt: int,
        execution_log: list[dict[str, Any]] | None = None,
        verification: dict[str, Any] | None = None,
    ) -> Reflection:
        """Evaluate whether *result* satisfies *objective*.

        Returns:
            Reflection with achieved=True if objective is done, or
            achieved=False with an actionable critique for the next attempt.
        """
        # Fast-path: explicit failure signals from the act loop — no need to call LLM
        if any(
            result.startswith(prefix)
            for prefix in (
                "ERROR:", "[AI error:", "[stuck:", "[schema error:", "[cancelled]",
                "[timeout after", "[max iterations",
            )
        ):
            critique = (
                f"The previous attempt terminated with: {result[:120]}. "
                "Try a completely different approach — different module, different action sequence, "
                "or simplify the objective into a smaller first step."
            )
            logger.info("[Reflection] Fast-path failure for obj='%s...' attempt=%d", objective[:40], attempt)
            return Reflection(achieved=False, confidence=0.9, critique=critique)

        failure_summary = _summarize_execution_failures(execution_log or [])
        if failure_summary and not _has_successful_execution_entries(execution_log or []):
            critique = (
                f"The execution evidence still shows only failed backend actions: {failure_summary}. "
                "Use a different selector, command, or interaction path before claiming success."
            )
            logger.info("[Reflection] Fast-path execution-log failure for obj='%s...' attempt=%d", objective[:40], attempt)
            return Reflection(achieved=False, confidence=0.9, critique=critique)

        if _is_successful_text_capture(objective, result):
            logger.info("[Reflection] Fast-path text capture success for obj='%s...' attempt=%d", objective[:40], attempt)
            return Reflection(achieved=True, confidence=0.95, critique=None)

        if _is_successful_title_capture(objective, result):
            logger.info("[Reflection] Fast-path title capture success for obj='%s...' attempt=%d", objective[:40], attempt)
            return Reflection(achieved=True, confidence=0.95, critique=None)

        if _is_successful_file_listing(objective, result):
            logger.info("[Reflection] Fast-path file listing success for obj='%s...' attempt=%d", objective[:40], attempt)
            return Reflection(achieved=True, confidence=0.95, critique=None)

        if _is_successful_python_version(objective, result):
            logger.info("[Reflection] Fast-path python version success for obj='%s...' attempt=%d", objective[:40], attempt)
            return Reflection(achieved=True, confidence=0.95, critique=None)

        if _is_successful_current_directory_inspection(objective, result):
            logger.info("[Reflection] Fast-path directory inspection success for obj='%s...' attempt=%d", objective[:40], attempt)
            return Reflection(achieved=True, confidence=0.95, critique=None)

        messages = [
            {"role": "system", "content": self._registry.reflection_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"OBJECTIVE: {objective}\n\n"
                    f"RESULT: {result}\n\n"
                    f"EXECUTION FAILURES: {failure_summary or 'none'}\n\n"
                    f"DETERMINISTIC VERIFICATION: {json.dumps(verification or {}, ensure_ascii=True)}\n\n"
                    f"This was attempt {attempt + 1}."
                ),
            },
        ]

        try:
            raw = await self._provider.call(messages, json_mode=True, purpose="reflection")
            data = _parse_json(raw)
            reflection = Reflection(
                achieved=bool(data.get("achieved", False)),
                confidence=float(data.get("confidence", 0.5)),
                critique=data.get("critique") or None,
            )
            if failure_summary and reflection.critique is None:
                reflection.critique = f"Execution failures observed: {failure_summary}."
            logger.info(
                "[Reflection] obj='%s...' attempt=%d achieved=%s confidence=%.2f",
                objective[:40],
                attempt,
                reflection.achieved,
                reflection.confidence,
            )
            return reflection

        except Exception as exc:
            # If reflection itself errors, conservatively treat as achieved to avoid
            # blocking execution on a reflection infrastructure failure.
            logger.warning("[Reflection] LLM call failed (%s) — treating as achieved", exc)
            return Reflection(achieved=True, confidence=0.4, critique=None)


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Cannot parse reflection JSON: {raw[:200]}")


def _is_successful_text_capture(objective: str, result: str) -> bool:
    lower_objective = (objective or "").lower()
    text = (result or "").strip()
    if len(text) < 40 or text.startswith("ERROR:") or text.startswith("["):
        return False

    capture_verbs = ("copy", "read", "extract")
    capture_targets = ("paragraph", "text", "content", "summary")
    return any(verb in lower_objective for verb in capture_verbs) and any(
        target in lower_objective for target in capture_targets
    )


def _is_successful_title_capture(objective: str, result: str) -> bool:
    lower_objective = (objective or "").lower()
    text = (result or "").strip()
    if not text or text.startswith("ERROR:") or text.startswith("["):
        return False
    if len(text) > 200:
        return False
    if "\n" in text:
        return False

    title_targets = ("title", "page title", "first result", "search result")
    return any(target in lower_objective for target in title_targets)


def _is_successful_file_listing(objective: str, result: str) -> bool:
    lower_objective = (objective or "").lower()
    text = (result or "").strip()
    if not text or text.startswith("ERROR:") or text.startswith("["):
        return False

    file_targets = ("python file", "python files", ".py file", ".py files")
    file_verbs = ("list", "identify", "show", "find")
    if not any(target in lower_objective for target in file_targets):
        return False
    if not any(verb in lower_objective for verb in file_verbs):
        return False

    lowered_text = text.lower()
    if ".py" in lowered_text or "no python files found" in lowered_text:
        return True

    success_markers = (
        "listed python files",
        "identified python files",
        "found python files",
        "python files in the current working directory",
    )
    return any(marker in lowered_text for marker in success_markers)


def _is_successful_current_directory_inspection(objective: str, result: str) -> bool:
    lower_objective = (objective or "").lower()
    text = (result or "").strip()
    if not text or text.startswith("ERROR:") or text.startswith("["):
        return False

    directory_targets = ("current directory", "working directory")
    directory_verbs = ("path", "location", "contents", "list", "show", "display", "get")
    if not any(target in lower_objective for target in directory_targets):
        return False
    if not any(verb in lower_objective for verb in directory_verbs):
        return False

    return True


def _is_successful_python_version(objective: str, result: str) -> bool:
    lower_objective = (objective or "").lower()
    text = (result or "").strip()
    if not text or text.startswith("ERROR:") or text.startswith("["):
        return False

    if "python" not in lower_objective or "version" not in lower_objective:
        return False

    normalized = text.lower()
    if normalized in {"success", "ok (status=success)"}:
        return True
    if re.fullmatch(r"result \d+: success", normalized, re.IGNORECASE):
        return True

    return bool(re.search(r"\bpython\b|\b\d+(?:\.\d+)+\b", text, re.IGNORECASE))


def _summarize_execution_failures(entries: list[dict[str, Any]]) -> str | None:
    failures: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        result = str(entry.get("result", "")).strip().lower()
        if result != "failure":
            continue
        detail = str(entry.get("details") or entry.get("action") or "execution failure").strip()
        if detail:
            failures.append(detail[:160])
        if len(failures) >= 3:
            break
    if not failures:
        return None
    return " | ".join(failures)


def _has_successful_execution_entries(entries: list[dict[str, Any]]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("result", "")).strip().lower() == "success":
            return True
    return False
