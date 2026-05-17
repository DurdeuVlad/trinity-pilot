from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "user" | "model" | "system"
    content: str
    # Optional provider-specific raw object.  GeminiProvider uses this to store
    # the original Content object for "tool_call" turns so that thought_signature
    # (required by Gemini 2.5+ thinking models) is replayed verbatim without any
    # re-serialisation loss.
    raw_provider_content: Any = None


@dataclass
class LLMResponse:
    content: str
    raw: Any = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    token_count: int = 0
    # Provider-specific raw model Content object (e.g. Gemini Content).
    # Carried through so agentic_mixin can attach it to LLMMessage.raw_provider_content.
    raw_model_content: Any = None


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
