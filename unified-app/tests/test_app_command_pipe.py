from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_server.app_command_pipe import AppCommandPipeServer, CommandSurfaceUnavailable, ensure_desktop_app_started


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
        can_reset=lambda: None,
        resume_run=lambda: None,
        cancel_run=lambda: None,
        reset_session=lambda: None,
        shutdown_app=lambda: None,
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


def test_reset_session_requires_idle_app() -> None:
    server = AppCommandPipeServer(
        event_bus=SimpleNamespace(pipe_task_registered=_FakeSignal()),
        history_manager=_FakeHistory(),
        run_monitor=SimpleNamespace(get_events=lambda *args, **kwargs: []),
        can_submit=lambda: "Run still active",
        can_reset=lambda: "Run still active",
        resume_run=lambda: None,
        cancel_run=lambda: None,
        reset_session=lambda: None,
        shutdown_app=lambda: None,
    )

    response = server._handle_payload({"command": "reset-session", "args": {}})

    assert response["ok"] is False
    assert response["error_code"] == "reset_blocked"


def test_reset_session_calls_callback_when_idle() -> None:
    calls: list[str] = []
    server = AppCommandPipeServer(
        event_bus=SimpleNamespace(pipe_task_registered=_FakeSignal()),
        history_manager=_FakeHistory(),
        run_monitor=SimpleNamespace(get_events=lambda *args, **kwargs: []),
        can_submit=lambda: None,
        can_reset=lambda: None,
        resume_run=lambda: None,
        cancel_run=lambda: None,
        reset_session=lambda: calls.append("reset"),
        shutdown_app=lambda: None,
    )

    response = server._handle_payload({"command": "reset-session", "args": {}})

    assert response["ok"] is True
    assert calls == ["reset"]


def test_shutdown_ui_calls_callback_when_idle() -> None:
    calls: list[str] = []
    server = AppCommandPipeServer(
        event_bus=SimpleNamespace(pipe_task_registered=_FakeSignal()),
        history_manager=_FakeHistory(),
        run_monitor=SimpleNamespace(get_events=lambda *args, **kwargs: []),
        can_submit=lambda: None,
        can_reset=lambda: None,
        resume_run=lambda: None,
        cancel_run=lambda: None,
        reset_session=lambda: None,
        shutdown_app=lambda: calls.append("shutdown"),
    )

    response = server._handle_payload({"command": "shutdown-ui", "args": {}})

    assert response["ok"] is True
    assert calls == ["shutdown"]


def test_ensure_desktop_app_started_returns_ready_when_command_surface_exists(monkeypatch) -> None:
    monkeypatch.setattr(
        "mcp_server.app_command_pipe.send_command_via_pipe",
        lambda command, timeout_seconds=1.0: {
            "ok": True,
            "status": "ok",
            "message": "desktop app command surface ready",
            "payload": {"message": "desktop app command surface ready"},
        },
    )

    response = ensure_desktop_app_started()

    assert response["launched"] is False
    assert response["status"] == "ok"


def test_shutdown_ui_ignores_submission_block_when_app_is_idle() -> None:
    calls: list[str] = []
    server = AppCommandPipeServer(
        event_bus=SimpleNamespace(pipe_task_registered=_FakeSignal()),
        history_manager=_FakeHistory(),
        run_monitor=SimpleNamespace(get_events=lambda *args, **kwargs: []),
        can_submit=lambda: "Startup blocked",
        can_reset=lambda: None,
        resume_run=lambda: None,
        cancel_run=lambda: None,
        reset_session=lambda: None,
        shutdown_app=lambda: calls.append("shutdown"),
    )

    response = server._handle_payload({"command": "shutdown-ui", "args": {}})

    assert response["ok"] is True
    assert calls == ["shutdown"]


def test_ensure_desktop_app_started_terminates_spawned_process_on_timeout(monkeypatch) -> None:
    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 4242
            self.returncode = None
            self.kill_calls = 0

        def poll(self):
            return None

        def kill(self):
            self.kill_calls += 1

    process = _FakeProcess()
    calls = {"count": 0}

    def fake_send_command_via_pipe(command, timeout_seconds=0.5):
        calls["count"] += 1
        raise CommandSurfaceUnavailable("not ready")

    monkeypatch.setattr("mcp_server.app_command_pipe.send_command_via_pipe", fake_send_command_via_pipe)
    monkeypatch.setattr("mcp_server.app_command_pipe.subprocess.Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        "mcp_server.app_command_pipe.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    with pytest.raises(CommandSurfaceUnavailable):
        ensure_desktop_app_started(startup_timeout_seconds=0.1)

    assert calls["count"] >= 1
