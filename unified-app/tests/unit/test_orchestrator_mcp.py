from __future__ import annotations

import json

import pytest

from mcp_server.orchestrator_mcp import OrchestratorMCPServer


@pytest.mark.asyncio
async def test_submit_task_returns_explicit_error_when_task_not_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    server = OrchestratorMCPServer()

    class _Signal:
        def emit(self, _description: str, _domain: str) -> None:
            return None

    server.event_bus.task_submitted = _Signal()

    async def _never_observed(_description: str, _domain: str, _timeout_seconds: float = 3.0):
        return None

    monkeypatch.setattr(server, "_submit_task_via_pipe", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_wait_for_submitted_task", _never_observed)

    result = await server._submit_task({"description": "Open Notepad", "domain": "desktop"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert payload["error_code"] == "task_not_observed"
    assert payload["task_id"] is None


@pytest.mark.asyncio
async def test_submit_task_uses_pipe_response_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(
        server,
        "_submit_task_via_pipe",
        lambda **_kwargs: {
            "ok": True,
            "task_id": "run_pipe_123",
            "description": "Open Notepad",
            "domain": "desktop",
            "status": "pending",
        },
    )

    result = await server._submit_task({"description": "Open Notepad", "domain": "desktop"})
    payload = json.loads(result[0].text)

    assert payload["task_id"] == "run_pipe_123"
    assert payload["status"] == "pending"
    assert payload["domain"] == "desktop"


@pytest.mark.asyncio
async def test_submit_task_surfaces_pipe_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(
        server,
        "_submit_task_via_pipe",
        lambda **_kwargs: {
            "ok": False,
            "error_code": "transport_unavailable",
            "message": "pipe endpoint unavailable",
        },
    )

    result = await server._submit_task({"description": "Open Notepad", "domain": "desktop"})
    payload = json.loads(result[0].text)

    assert payload["task_id"] is None
    assert payload["status"] == "error"
    assert payload["error_code"] == "transport_unavailable"


@pytest.mark.asyncio
async def test_get_task_status_returns_json_not_found_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(server, "_resolve_task_id", lambda _task_id: "missing-task")
    monkeypatch.setattr(server.history_manager, "get_task", lambda _task_id: None)

    result = await server._get_task_status({"task_id": "missing-task"})
    payload = json.loads(result[0].text)

    assert payload["found"] is False
    assert payload["status"] == "not_found"
    assert payload["task_id"] == "missing-task"


@pytest.mark.asyncio
async def test_get_task_status_latest_returns_no_tasks_message(monkeypatch: pytest.MonkeyPatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(server, "_resolve_task_id", lambda _task_id: None)

    result = await server._get_task_status({"task_id": "latest"})
    payload = json.loads(result[0].text)

    assert payload["found"] is False
    assert payload["status"] == "not_found"
    assert payload["task_id"] == "latest"
