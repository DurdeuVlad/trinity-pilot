from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_server.app_command_pipe import AppCommandPipeServer
from mcp_server.run_monitor import RunEventRecorder
from orchestrator.agent_loop import AgentLoop
from orchestrator.database import HistoryManager, TaskStatus
from orchestrator.execution_context import ExecutionContext
from orchestrator.prompt_registry import PromptRegistry


class _DummyProvider:
    def __init__(self, response: str) -> None:
        self._response = response

    async def call(self, messages, *, json_mode=True, purpose="execution"):
        return self._response


class _NeverCalledBridge:
    async def execute_task(self, **kwargs):
        raise AssertionError("Bridge should not execute a blocked cross-domain action")


@pytest.mark.asyncio
async def test_agent_loop_policy_stops_cli_domain_escape() -> None:
    loop = AgentLoop(
        provider=_DummyProvider(
            json.dumps(
                    {
                        "done": False,
                        "action_type": "desktop",
                        "module": "desktop_app",
                        "rationale": "Try opening Explorer.",
                        "parameters": {"action": "open", "app": "explorer"},
                    }
                )
        ),
        bridge=_NeverCalledBridge(),
        emit_status=lambda *_args, **_kwargs: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        run_domain="cli",
        context=ExecutionContext(objective="List files with the CLI"),
    )

    result = await loop.act(
        objective="List files with the CLI",
        obj_index=1,
        context=ExecutionContext(objective="List files with the CLI"),
        adapt_hint="",
    )

    assert result.startswith("[policy_stop:")
    assert loop.last_step_payload["metadata"]["policy_category"] == "domain_escape"
    assert loop.last_step_payload["metadata"]["canonical_status"] == "policy_terminated"


def test_run_monitor_prefers_canonical_policy_terminated_status(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "_runtime"
    runtime_dir.mkdir(parents=True)
    history = HistoryManager(runtime_dir / "orchestrator_history.db")
    history.create_task("run_stop", "example", "cli", plan_steps=["step"])
    history.start_task("run_stop")
    history.add_step("run_stop", 1, "first step")
    history.update_step_status(
        "run_stop",
        1,
        TaskStatus.CANCELLED,
        result_data={"status": "policy_terminated", "category": "policy_stop"},
        error_message="Policy stop: domain escape",
    )
    history.complete_task(
        "run_stop",
        result_data={"status": "policy_terminated", "category": "policy_stop"},
        error_message="Policy stop: domain escape",
        status=TaskStatus.CANCELLED,
    )

    recorder = RunEventRecorder(history, runtime_dir)
    bundle = recorder.build_artifact_bundle("run_stop")

    assert bundle["final_disposition"]["task_status"] == "policy_terminated"
    assert bundle["final_disposition"]["persisted_task_status"] == "cancelled"


def test_command_pipe_terminate_waits_for_terminal_state() -> None:
    class _FakeSignal:
        def connect(self, callback):
            self._callback = callback

    class _FakeHistory:
        def __init__(self) -> None:
            self.calls = 0

        def get_task_with_steps(self, task_id: str):
            self.calls += 1
            status = "running"
            result_data = {}
            if self.calls >= 2:
                status = "cancelled"
                result_data = {"status": "policy_terminated", "category": "policy_stop"}
            return {
                "task": {
                    "task_id": task_id,
                    "description": "example",
                    "domain": "cli",
                    "status": status,
                    "result_data": result_data,
                    "error_message": "Policy stop",
                },
                "steps": [],
            }

        def list_tasks(self, limit=20):
            return [{"task_id": "run_stop"}]

    run_monitor = SimpleNamespace(
        record_event=lambda *args, **kwargs: None,
        get_events=lambda *args, **kwargs: [],
        latest_task_id=lambda: "run_stop",
    )
    server = AppCommandPipeServer(
        event_bus=SimpleNamespace(pipe_task_registered=_FakeSignal()),
        history_manager=_FakeHistory(),
        run_monitor=run_monitor,
        can_submit=lambda: None,
        resume_run=lambda: None,
        cancel_run=lambda reason: None,
        observe_timeout_seconds=0.3,
    )

    response = server._terminate_run("terminate-run", {"task_id": "run_stop", "reason": "policy stop"})

    assert response["status"] == "policy_terminated"
    assert response["payload"]["task"]["status"] == "cancelled"


def test_agent_loop_web_prompt_is_domain_scoped() -> None:
    loop = AgentLoop(
        provider=_DummyProvider("{}"),
        bridge=_NeverCalledBridge(),
        emit_status=lambda *_args, **_kwargs: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        run_domain="web",
        context=ExecutionContext(objective="Open GitHub in the browser"),
    )

    messages = loop._build_messages(
        SimpleNamespace(
            objective="Open GitHub in the browser",
            history=[],
            iteration=0,
            adapt_hint="",
            steer_hint="",
            consecutive_failures=0,
            last_action_failed=False,
        )
    )

    system_prompt = messages[0]["content"]
    assert '<browse | done>' in system_prompt
    assert "cli_runner" not in system_prompt
    assert "desktop_app" not in system_prompt


def test_agent_loop_mixed_run_with_active_browser_adds_session_continuity_note() -> None:
    context = ExecutionContext(objective="Continue browser work, then save the result")
    context.world_state.active_app = "browser"
    context.world_state.last_opened_url = "https://github.com"

    loop = AgentLoop(
        provider=_DummyProvider("{}"),
        bridge=_NeverCalledBridge(),
        emit_status=lambda *_args, **_kwargs: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        run_domain="mixed",
        context=context,
    )

    messages = loop._build_messages(
        SimpleNamespace(
            objective="Read the current GitHub page and then save notes elsewhere",
            history=[],
            iteration=0,
            adapt_hint="",
            steer_hint="",
            consecutive_failures=0,
            last_action_failed=False,
        )
    )

    continuity_notes = [
        message["content"]
        for message in messages
        if message["role"] == "user" and "BROWSER SESSION CONTINUITY:" in message["content"]
    ]
    assert continuity_notes
    assert "Do NOT use cli_runner or desktop_app to open URLs" in continuity_notes[0]


def test_agent_loop_mixed_run_without_active_browser_skips_session_continuity_note() -> None:
    context = ExecutionContext(objective="Use CLI then browser")

    loop = AgentLoop(
        provider=_DummyProvider("{}"),
        bridge=_NeverCalledBridge(),
        emit_status=lambda *_args, **_kwargs: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        run_domain="mixed",
        context=context,
    )

    messages = loop._build_messages(
        SimpleNamespace(
            objective="Start with CLI work",
            history=[],
            iteration=0,
            adapt_hint="",
            steer_hint="",
            consecutive_failures=0,
            last_action_failed=False,
        )
    )

    assert not any(
        message["role"] == "user" and "BROWSER SESSION CONTINUITY:" in message["content"]
        for message in messages
    )
