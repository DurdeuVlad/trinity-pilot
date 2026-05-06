from __future__ import annotations

from types import SimpleNamespace

from mcp_server.task_submission_pipe import TaskSubmissionPipeServer


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class _FakeHistory:
    def __init__(self) -> None:
        self.tasks = {
            "run_pipe": {
                "task_id": "run_pipe",
                "description": "repeat case",
                "domain": "web",
                "status": "running",
            }
        }

    def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    def get_task_with_steps(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            return None
        return {"task": dict(task), "steps": []}


def test_task_submission_pipe_resolves_request_to_exact_run(monkeypatch) -> None:
    pipe_task_registered = _FakeSignal()
    pipe_task_submitted = _FakeSignal()
    event_bus = SimpleNamespace(
        pipe_task_registered=pipe_task_registered,
        pipe_task_submitted=pipe_task_submitted,
    )
    history = _FakeHistory()
    server = TaskSubmissionPipeServer(
        event_bus=event_bus,
        history_manager=history,
        can_submit=lambda: None,
        observe_timeout_seconds=0.5,
    )

    def fake_invoke_method(_obj, _method, _connection_type, _arg1, _arg2, _arg3):
        pipe_task_registered.emit("req-1", "run_pipe")
        return True

    monkeypatch.setattr("mcp_server.task_submission_pipe.QMetaObject.invokeMethod", fake_invoke_method)

    response = server._handle_payload(
        {
            "request_id": "req-1",
            "description": "repeat case",
            "domain": "web",
            "observe_timeout_seconds": 0.3,
        }
    )

    assert response["ok"] is True
    assert response["task_id"] == "run_pipe"
