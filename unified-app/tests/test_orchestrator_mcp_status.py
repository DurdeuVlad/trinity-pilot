"""Regression tests for MCP task status serialization."""
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


def test_get_task_status_serializes_sqlalchemy_task(monkeypatch):
    """The MCP status tool should support ORM task objects from HistoryManager."""
    server = OrchestratorMCPServer()
    fake_task = SimpleNamespace(
        description="List all Python files in the current directory and count them",
        status=TaskStatus.COMPLETED,
        created_at=datetime(2026, 3, 23, 17, 0, 35, 852162, tzinfo=timezone.utc),
        completed_at=datetime(2026, 3, 23, 17, 0, 58, 770454, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(server, "_resolve_task_id", lambda task_id: "run_live_demo")
    server.active_tasks = {}
    server.history_manager = SimpleNamespace(get_task=lambda task_id: fake_task)

    result = asyncio.run(server._get_task_status({"task_id": "run_live_demo"}))
    payload = json.loads(result[0].text)

    assert payload["found"] is True
    assert payload["task_id"] == "run_live_demo"
    assert payload["status"] == "completed"
    assert payload["created_at"].startswith("2026-03-23T17:00:35")
