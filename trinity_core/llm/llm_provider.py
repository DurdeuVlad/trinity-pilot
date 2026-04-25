"""Abstract LLM provider interface for Trinity Core tool-calling runtimes."""

from __future__ import annotations

from abc import ABC, abstractmethod
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


class LLMProvider(ABC):
    """Strategy interface for all LLM backends used by Trinity Core runtimes.

    Symmetric to TrinityMCPServer: enforces a contract, delegates
    vendor-specific details to concrete subclasses.
    """

    @abstractmethod
    async def call(self, messages: list[dict], tools: dict[str, Any]) -> LLMResponse:
        """Send messages + available tools; return text or tool-call response."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier, e.g. 'gemini' or 'openai'."""

    @abstractmethod
    async def probe(self) -> None:
        """Cheap liveness check. Raises with a descriptive message on failure."""

    async def close(self) -> None:
        """Release provider resources. Override if the client holds connections."""
        return None
