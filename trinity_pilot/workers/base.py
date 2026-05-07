from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from trinity_pilot.core.types import ObjectiveSpec


class WorkerError(Exception):
    pass


class DomainWorker(ABC):
    """Strategy interface for domain workers. One instance per objective attempt."""

    @abstractmethod
    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        """Execute the objective. Return evidence dict. Raise WorkerError on failure."""
        ...
