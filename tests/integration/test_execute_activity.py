"""Integration test: execute_objective activity routes to correct worker.
Imports activities module directly (bypasses workflow/__init__ to avoid temporalio dep).
Mocks temporalio.activity decorator so no Temporal server needed.
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.router import WorkerRouter


def _spec_dict(domain: str = "browser") -> dict:
    return {
        "objective_id": "int-test-1",
        "goal": "navigate to https://example.com",
        "dependencies": [],
        "domain": domain,
        "required_capabilities": ["browser_navigation"],
        "risk_class": "low",
        "preconditions": [],
        "success_tests": ["page loaded"],
        "evidence_bundle": ["screenshot"],
        "max_attempts": 3,
        "rollback_or_abort_rule": "abort",
    }


def _get_execute_objective():
    """Import execute_objective with temporalio stubbed out if not installed."""
    if "temporalio" not in sys.modules:
        fake_temporal = ModuleType("temporalio")
        fake_activity = ModuleType("temporalio.activity")
        fake_activity.defn = lambda f: f
        fake_temporal.activity = fake_activity
        sys.modules["temporalio"] = fake_temporal
        sys.modules["temporalio.activity"] = fake_activity

    if "trinity_pilot.workflow.activities" in sys.modules:
        del sys.modules["trinity_pilot.workflow.activities"]

    import trinity_pilot.workflow.activities as acts
    return acts.execute_objective


class TestExecuteObjectiveActivity:
    async def test_browser_spec_routes_to_browser_worker(self):
        fake_evidence = {"domain": "browser", "screenshot": "base64data"}
        mock_worker = AsyncMock()
        mock_worker.execute = AsyncMock(return_value=fake_evidence)

        execute_objective = _get_execute_objective()

        with patch.object(WorkerRouter, "route", return_value=mock_worker):
            result = await execute_objective(_spec_dict("browser"))

        assert result["domain"] == "browser"
        mock_worker.execute.assert_called_once()

    async def test_terminal_spec_routes_to_terminal_worker(self):
        fake_evidence = {"domain": "terminal", "stdout": "hello", "exit_code": 0}
        mock_worker = AsyncMock()
        mock_worker.execute = AsyncMock(return_value=fake_evidence)

        execute_objective = _get_execute_objective()

        with patch.object(WorkerRouter, "route", return_value=mock_worker):
            result = await execute_objective(_spec_dict("terminal"))

        assert result["domain"] == "terminal"
        mock_worker.execute.assert_called_once()

    async def test_mixed_domain_raises_worker_error(self):
        execute_objective = _get_execute_objective()
        with pytest.raises(WorkerError, match="MIXED"):
            await execute_objective(_spec_dict("mixed"))
