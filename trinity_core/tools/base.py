"""Base tool contract for tool-first orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class ToolResult:
    """Result payload returned by every tool execution.

    Attributes:
        status: Tool execution status, expected values are "success" or "error".
        output: Human-readable or JSON-serialized output payload.
        error: Optional error details when status is "error".
        metadata: Additional structured fields for downstream reasoning or logging.
        error_code: Optional machine-readable error classification.
        retryable: Whether the operation can be retried (default True).
    """

    status: str
    output: str
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    retryable: bool = True


class Tool(ABC):
    """Abstract base class for all executable tools."""

    @abstractmethod
    def name(self) -> str:
        """Return the stable tool name exposed to the LLM."""

    @abstractmethod
    def description(self) -> str:
        """Return a concise tool description used in tool selection."""

    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """Return a JSON schema describing accepted tool input."""

    def annotations(self) -> dict[str, Any]:
        """Return optional tool capability metadata exposed to the orchestrator."""
        return {}

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with keyword arguments validated by parameters()."""
