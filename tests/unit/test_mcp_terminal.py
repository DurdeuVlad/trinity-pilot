"""Unit tests for MCP terminal server tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.mcp.terminal_server import terminal_run
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.worker_result import WorkerResult


def _spec_dict(objective_id: str = "obj-1", goal: str = "echo hi",
                success_tests: list[str] | None = None,
                risk_class: RiskClass = RiskClass.LOW) -> dict:
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal_command"],
        risk_class=risk_class,
        preconditions=[],
        success_tests=success_tests or ["stdout contains hi"],
        evidence_bundle=["stdout", "stderr", "exit_code"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    return spec.to_dict()


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


class TestMcpTerminalRun:
    async def test_terminal_run_returns_evidence_dict(self):
        fake_evidence = {
            "domain": "terminal",
            "objective_id": "obj-1",
            "stdout": "hi\n",
            "stderr": "",
            "exit_code": 0,
            "created_files": [],
            "workspace": "/tmp/test",
            "error": None,
        }
        with patch(
            "trinity_pilot.mcp.terminal_server.TerminalWorker.execute",
            new_callable=AsyncMock,
            return_value=fake_evidence,
        ):
            result = await terminal_run(_spec_dict())
        assert result["mcp_status"] == "ok"
        assert result["evidence"]["exit_code"] == 0
        assert result["evidence"]["stdout"] == "hi\n"

    async def test_terminal_run_passes_objective_id(self):
        fake_evidence = {
            "domain": "terminal",
            "objective_id": "obj-smoke",
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "created_files": [],
            "workspace": "/tmp",
            "error": None,
        }
        captured: list = []

        async def _capture(spec):
            captured.append(spec)
            return fake_evidence

        with patch(
            "trinity_pilot.mcp.terminal_server.TerminalWorker.execute",
            side_effect=_capture,
        ):
            await terminal_run(_spec_dict(objective_id="obj-smoke", goal="true",
                                           success_tests=["exit_code is 0"]))

        assert captured[0].objective_id == "obj-smoke"

    def test_terminal_run_invalid_risk_class_raises(self):
        with pytest.raises(ValueError):
            import asyncio
            spec_dict = _spec_dict()
            spec_dict["risk_class"] = "not-a-valid-class"
            asyncio.run(terminal_run(spec_dict))

    async def test_terminal_run_translates_worker_error(self):
        with patch(
            "trinity_pilot.mcp.terminal_server.TerminalWorker.execute",
            side_effect=WorkerError("boom"),
        ):
            result = await terminal_run(_spec_dict())
        assert result["mcp_status"] == "error"
        assert result["message"] == "boom"
