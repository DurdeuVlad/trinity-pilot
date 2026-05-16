from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from trinity_pilot.core.types import ObjectiveSpec

if TYPE_CHECKING:
    from trinity_pilot.workers.worker_result import WorkerResult


class WorkerError(Exception):
    pass


class WorkerBlocker(WorkerError):
    """Raised when the worker encounters an unresolvable blocker requiring orchestrator intervention.

    Carries the partial WorkerResult accumulated before the blocker was hit.
    The engine catches this before WorkerError and routes to OrchestratorAnalyser.
    """

    def __init__(self, reason: str, result: "WorkerResult") -> None:
        super().__init__(reason)
        self.result = result


class DomainWorker(ABC):
    """Strategy interface for domain workers. One instance per objective attempt."""

    @abstractmethod
    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        """Execute the objective. Return evidence dict. Raise WorkerError on failure."""
        ...
