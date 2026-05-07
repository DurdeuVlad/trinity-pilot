from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass
class LLMResponse:
    content: str
    raw: Any = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class LLMProvider(ABC):
    """Strategy interface for LLM backends. Swap Gemini → any other provider here."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
    ) -> LLMResponse: ...

    @abstractmethod
    async def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        system: str = "",
    ) -> LLMResponse: ...
