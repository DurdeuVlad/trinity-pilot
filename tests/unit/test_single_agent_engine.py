"""SingleAgentEngine unit tests — ablation pipeline wrapper, mocked worker."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_pilot.config import Settings
from trinity_pilot.orchestrator.single_agent_engine import SingleAgentEngine
from trinity_pilot.workers.worker_result import WorkerResult


@pytest.mark.asyncio
async def test_run_success_maps_to_completed_status():
    settings = Settings(gemini_api_key="test-key")
    engine = SingleAgentEngine(settings)
    result = WorkerResult(
        status="success",
        summary="did the task",
        evidence={"action_log": ["did stuff"]},
        steps_taken=3,
        tokens_used=120,
    )
    with patch(
        "trinity_pilot.orchestrator.single_agent_engine.SingleAgentWorker"
    ) as mock_worker_cls:
        mock_worker_cls.return_value.execute_raw = AsyncMock(return_value=result)
        out = await engine.run("do the task")

    assert out["status"] == "completed"
    assert out["single_agent_summary"] == "did the task"
    assert out["evidence"] == {"action_log": ["did stuff"]}
    assert out["steps_taken"] == 3
    assert out["tokens_used"] == 120


@pytest.mark.asyncio
async def test_run_failure_maps_to_failed_status():
    settings = Settings(gemini_api_key="test-key")
    engine = SingleAgentEngine(settings)
    result = WorkerResult(status="failure", summary="blew up", evidence={})
    with patch(
        "trinity_pilot.orchestrator.single_agent_engine.SingleAgentWorker"
    ) as mock_worker_cls:
        mock_worker_cls.return_value.execute_raw = AsyncMock(return_value=result)
        out = await engine.run("do the task")

    assert out["status"] == "failed"


@pytest.mark.asyncio
async def test_run_passes_max_steps_through():
    settings = Settings(gemini_api_key="test-key")
    engine = SingleAgentEngine(settings)
    result = WorkerResult(status="success", summary="ok", evidence={})
    with patch(
        "trinity_pilot.orchestrator.single_agent_engine.SingleAgentWorker"
    ) as mock_worker_cls:
        execute_raw = AsyncMock(return_value=result)
        mock_worker_cls.return_value.execute_raw = execute_raw
        await engine.run("do the task", max_steps=7)

    execute_raw.assert_awaited_once_with("do the task", max_steps=7)
