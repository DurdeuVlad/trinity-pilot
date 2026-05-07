from __future__ import annotations

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError
from trinity_pilot.workers.browser_worker import BrowserWorker
from trinity_pilot.workers.desktop_worker import DesktopWorker
from trinity_pilot.workers.terminal_worker import TerminalWorker

_WORKER_MAP: dict[DomainType, type[DomainWorker]] = {
    DomainType.BROWSER: BrowserWorker,
    DomainType.TERMINAL: TerminalWorker,
    DomainType.DESKTOP: DesktopWorker,
}


class WorkerRouter:
    def route(self, spec: ObjectiveSpec) -> DomainWorker:
        worker_cls = _WORKER_MAP.get(spec.domain)
        if worker_cls is None:
            raise WorkerError(
                f"No worker for domain '{spec.domain.value}'. "
                "MIXED domain requires explicit domain decomposition before routing."
            )
        return worker_cls()
