"""Minimal LLM provider abstraction with tool-calling response format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    """Structured tool invocation returned by an LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    """Unified model output that can be text or tool calls."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    def is_text(self) -> bool:
        return bool(self.text) and not self.tool_calls


class LLMProvider:
    """Provider interface used by runtimes for iterative tool selection."""

    async def call(self, messages: list[dict], tools: dict[str, Any]) -> LLMResponse:
        """Return a text response by default, intended to be replaced in production."""
        if not messages:
            return LLMResponse(text="No objective provided.")
        return LLMResponse(text="Execution complete.")
