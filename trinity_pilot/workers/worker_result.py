from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class WorkerResult:
    status: Literal["success", "partial_blocker", "failure"]
    summary: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    steps_taken: int = 0
    tokens_used: int = 0
