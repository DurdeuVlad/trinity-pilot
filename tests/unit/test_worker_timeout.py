"""Worker timeout guard and input-cap tests."""
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

        with patch.object(worker, "run_loop", side_effect=slow_run):
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

        with patch.object(worker, "run_loop", side_effect=slow_run):
            with pytest.raises(WorkerError, match="timeout"):
                await worker.execute(spec)


class TestDesktopWorkerTypeTextCap:
    def _make_worker(self):
        from unittest.mock import MagicMock

        from trinity_pilot.workers.desktop_worker import DesktopWorker
        mock_llm = MagicMock()
        return DesktopWorker(llm=mock_llm)

    @pytest.mark.asyncio
    async def test_type_text_blocked_above_500_chars(self):
        worker = self._make_worker()
        evidence: dict = {"action_log": []}
        result = await worker._dispatch_tool(
            "type_text", {"text": "a" * 501}, evidence
        )
        assert "BLOCKED" in result
        assert "501" in result
        assert any("blocked" in entry.lower() for entry in evidence["action_log"])

    @pytest.mark.asyncio
    async def test_type_text_exactly_500_chars_not_blocked(self):
        worker = self._make_worker()
        evidence: dict = {"action_log": [], "typed_text": ""}

        with patch.object(worker, "_ensure_target_focused", new_callable=AsyncMock):
            with patch.object(worker, "_type_text", new_callable=AsyncMock):
                result = await worker._dispatch_tool(
                    "type_text", {"text": "a" * 500}, evidence
                )
        assert "BLOCKED" not in result
        assert "500" in result
