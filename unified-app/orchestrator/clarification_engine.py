"""Clarification engine — lightweight conversational pre-flight before execution.

Holds a short conversation with the user to confirm intent, then emits
READY with a one-sentence task summary so the UI can offer a Run button.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .providers.base import LLMProvider


_SYSTEM_PROMPT = """\
You are an orchestrator that automates tasks on a user's computer (CLI, browser, desktop, or mixed).

Your job is to understand exactly what the user wants BEFORE running anything.

Rules:
- If the request is clear and actionable, respond with exactly:
  READY: <one-sentence summary of the confirmed task>
- If you need clarification, ask ONE short, focused question. Never ask more than one question at a time.
- Do not repeat back what the user said unless it adds clarity.
- Do not use markdown formatting in your responses.
- Keep all responses concise (2 sentences max, except the READY line).

Examples:
  User: list all python files → READY: List all Python files in the current directory.
  User: open chrome         → READY: Open Google Chrome browser.
  User: search for something → What would you like me to search for, and on which website?
"""


@dataclass
class ClarificationResult:
    ready: bool
    text: str                       # full assistant response (shown in chat)
    confirmed_task: str | None      # set when ready=True


class ClarificationEngine:
    """Holds conversation history and queries the LLM for intent clarification."""

    def __init__(self, provider: "LLMProvider") -> None:
        self._provider = provider
        self._history: list[dict] = []

    def reset(self) -> None:
        """Clear conversation history for a new session."""
        self._history.clear()

    async def process(self, user_message: str) -> ClarificationResult:
        """Add user message, call LLM, return parsed result."""
        self._history.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + self._history

        try:
            raw = await self._provider.call(messages, json_mode=False, purpose="clarification")
        except Exception as exc:
            # On provider error, treat the request as ready to avoid blocking the user
            fallback = f"READY: {user_message}"
            self._history.append({"role": "assistant", "content": fallback})
            return ClarificationResult(ready=True, text=str(exc), confirmed_task=user_message)

        raw = raw.strip()
        self._history.append({"role": "assistant", "content": raw})

        if raw.upper().startswith("READY:"):
            confirmed = raw[6:].strip()
            # Normalise — remove trailing period duplicates
            return ClarificationResult(ready=True, text=raw, confirmed_task=confirmed)

        return ClarificationResult(ready=False, text=raw, confirmed_task=None)
