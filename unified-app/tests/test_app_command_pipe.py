from __future__ import annotations

from types import SimpleNamespace

from mcp_server.app_command_pipe import AppCommandPipeServer


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
            "run_new": {
                "task_id": "run_new",
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


def test_dispatch_task_uses_request_to_run_mapping(monkeypatch) -> None:
    pipe_task_registered = _FakeSignal()
    pipe_task_submitted = _FakeSignal()
    event_bus = SimpleNamespace(
        pipe_task_registered=pipe_task_registered,
        pipe_task_submitted=pipe_task_submitted,
    )
    history = _FakeHistory()
    run_monitor = SimpleNamespace(get_events=lambda *args, **kwargs: [])

    server = AppCommandPipeServer(
        event_bus=event_bus,
        history_manager=history,
        run_monitor=run_monitor,
        can_submit=lambda: None,
        resume_run=lambda: None,
        cancel_run=lambda: None,
    )

    def fake_invoke_method(*_args, **_kwargs):
        pipe_task_registered.emit("cmd-fixed1234567890a", "run_new")
        return True

    monkeypatch.setattr("mcp_server.app_command_pipe.uuid.uuid4", lambda: SimpleNamespace(hex="fixed1234567890abcdef"))
    monkeypatch.setattr("mcp_server.app_command_pipe.QMetaObject.invokeMethod", fake_invoke_method)

    response = server._dispatch_task("repeat case", "web")

    assert response["ok"] is True
    assert response["task_id"] == "run_new"
    assert response["payload"]["task_id"] == "run_new"
