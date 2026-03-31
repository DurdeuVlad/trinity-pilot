"""Regression tests for MCP task details serialization."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from types import SimpleNamespace

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.database.models import TaskStatus
from mcp_server.orchestrator_mcp import OrchestratorMCPServer


def test_get_task_details_serializes_task_object(monkeypatch):
    server = OrchestratorMCPServer()
    fake_task = SimpleNamespace(
        task_id="run_live_demo",
        description="List all Python files in the current directory and count them",
        domain="cli",
        status=TaskStatus.COMPLETED,
        created_at=datetime(2026, 3, 23, 17, 0, 35, 852162, tzinfo=timezone.utc),
        started_at=datetime(2026, 3, 23, 17, 0, 36, tzinfo=timezone.utc),
        completed_at=datetime(2026, 3, 23, 17, 0, 58, 770454, tzinfo=timezone.utc),
        confidence=0.9,
        estimated_duration=120,
        error_message=None,
        result_data='{"status":"partial","category":"partial","output":"Completed 1 of 2 steps"}',
    )
    fake_steps = [{"step_number": 1, "description": "List files", "status": "completed"}]

    server.history_manager = SimpleNamespace(
        get_task=lambda task_id: fake_task,
        get_task_steps=lambda task_id: fake_steps,
    )

    result = asyncio.run(server._get_task_details({"task_id": "run_live_demo"}))
    payload = json.loads(result[0].text)

    assert payload["task"]["task_id"] == "run_live_demo"
    assert payload["task"]["status"] == "completed"
    assert payload["task"]["final_status"] == "partial"
    assert payload["task"]["result_data"]["output"] == "Completed 1 of 2 steps"
    assert payload["steps"] == fake_steps
