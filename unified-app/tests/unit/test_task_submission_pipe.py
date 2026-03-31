from __future__ import annotations

from mcp_server.task_submission_pipe import TaskSubmissionPipeServer


class _Signal:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def emit(self, description: str, domain: str) -> None:
        self.calls.append((description, domain))


class _EventBus:
    def __init__(self) -> None:
        self.task_submitted = _Signal()


class _HistoryManager:
    def list_tasks(self, limit: int = 20) -> list[dict]:
        return []


def test_pipe_server_retries_transient_duplicate_submit_block(monkeypatch) -> None:
    event_bus = _EventBus()
    history = _HistoryManager()
    responses = iter(
        [
            "Task is already running.",
            "Task is already running.",
            None,
        ]
    )

    server = TaskSubmissionPipeServer(
        event_bus=event_bus,
        history_manager=history,
        can_submit=lambda: next(responses),
    )
    monkeypatch.setattr(
        server,
        "_wait_for_task",
        lambda **_kwargs: {
            "task_id": "run_retry_ok",
            "description": "Open Notepad",
            "domain": "desktop",
            "status": "submitted",
        },
    )

    response = server._handle_payload(
        {
            "request_id": "req-1",
            "description": "Open Notepad",
            "domain": "desktop",
            "observe_timeout_seconds": 1.0,
        }
    )

    assert response["ok"] is True
    assert response["task_id"] == "run_retry_ok"
    assert event_bus.task_submitted.calls == [("Open Notepad", "desktop")]


def test_pipe_server_does_not_retry_non_transient_submission_blocks() -> None:
    event_bus = _EventBus()
    history = _HistoryManager()
    server = TaskSubmissionPipeServer(
        event_bus=event_bus,
        history_manager=history,
        can_submit=lambda: "Live Gemini blocked: invalid API key.",
    )

    response = server._handle_payload(
        {
            "request_id": "req-2",
            "description": "Open Notepad",
            "domain": "desktop",
        }
    )

    assert response["ok"] is False
    assert response["error_code"] == "submission_blocked"
    assert "invalid API key" in response["message"]
    assert event_bus.task_submitted.calls == []


def test_pipe_server_bounds_request_cache_size() -> None:
    event_bus = _EventBus()
    history = _HistoryManager()
    server = TaskSubmissionPipeServer(
        event_bus=event_bus,
        history_manager=history,
    )

    for index in range(300):
        server._cache_response(f"req-{index}", {"ok": True, "task_id": f"task-{index}"})  # noqa: SLF001

    assert len(server._request_cache) == 256  # noqa: SLF001
    assert "req-0" not in server._request_cache  # noqa: SLF001
    assert "req-43" not in server._request_cache  # noqa: SLF001
    assert "req-44" in server._request_cache  # noqa: SLF001
    assert "req-299" in server._request_cache  # noqa: SLF001
