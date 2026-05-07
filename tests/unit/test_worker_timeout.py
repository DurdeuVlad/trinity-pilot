"""Worker timeout guard tests — spec.metadata["timeout_seconds"] enforced via asyncio.wait_for."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.base import WorkerError


def _make_spec(domain: DomainType, timeout: int) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-timeout",
        goal="run `sleep 999`",
        dependencies=[],
        domain=domain,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=[],
        evidence_bundle=[],
        max_attempts=1,
        rollback_or_abort_rule="abort",
        metadata={"timeout_seconds": timeout},
    )


class TestBrowserWorkerTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_worker_error(self):
        from trinity_pilot.workers.browser_worker import BrowserWorker

        spec = _make_spec(DomainType.BROWSER, timeout=1)
        worker = BrowserWorker()

        async def slow_inner(*args, **kwargs):
            await asyncio.sleep(10)

        with patch.object(worker, "_execute_inner", side_effect=slow_inner):
            with pytest.raises(WorkerError, match="timeout"):
                await worker.execute(spec)


class TestTerminalWorkerTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_worker_error(self):
        from trinity_pilot.workers.terminal_worker import TerminalWorker

        spec = _make_spec(DomainType.TERMINAL, timeout=1)
        worker = TerminalWorker()

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(10)

        with patch.object(worker, "_run_objective", side_effect=slow_run):
            with pytest.raises(WorkerError, match="timeout"):
                await worker.execute(spec)


class TestDesktopWorkerTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_worker_error(self):
        from trinity_pilot.workers.desktop_worker import DesktopWorker

        spec = _make_spec(DomainType.DESKTOP, timeout=1)
        worker = DesktopWorker()

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(10)

        with patch.object(worker, "_run_objective", side_effect=slow_run):
            with pytest.raises(WorkerError, match="timeout"):
                await worker.execute(spec)
