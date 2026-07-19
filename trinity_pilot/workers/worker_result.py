from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


@dataclass(frozen=True)
class ToolCallRecord:
    """Sanitized worker tool event; intentionally excludes model reasoning."""

    tool: str
    args: dict[str, Any]
    result: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class WorkerResult:
    status: Literal["success", "partial_blocker", "failure"]
    summary: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    steps_taken: int = 0
    tokens_used: int = 0
    tool_call_log: list[ToolCallRecord] = field(default_factory=list)
