from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.agent_loop import AgentLoop
from orchestrator.execution_context import ExecutionContext
from orchestrator.prompt_registry import PromptRegistry
from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.models import TaskInput


@pytest.mark.asyncio
async def test_browser_adapter_always_uses_browser_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_run_browser_task(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            result="success",
            error_details=None,
            extracted_text="YouTube search results visible",
            screenshot_path="shot.png",
            attempt_log=SimpleNamespace(
                actions=["open browser", "search youtube"],
                observations=["browser launched", "results loaded"],
            ),
            model_dump=lambda: {
                "result": "success",
                "error_details": None,
                "extracted_text": "YouTube search results visible",
            },
        )

    monkeypatch.setattr("trinity_core.adapters.browser.run_browser_task", fake_run_browser_task)
    monkeypatch.setattr("trinity_core.adapters.browser.close_browser_session", lambda *_args, **_kwargs: None)

    adapter = BrowserAdapter()
    task = TaskInput(
        task_id="test_youtube",
        description="Search Lady Gaga on YouTube",
        expected_outcome="YouTube search results visible",
        domain="web",
        context={
            "_browser_session_id": "objective-browser-session",
            "_reuse_browser_session": True,
        },
        max_retries=1,
        timeout=30,
    )

    result = await adapter.execute(task)

    assert len(calls) == 1
    assert calls[0]["objective"] == "Search Lady Gaga on YouTube"
    assert calls[0]["session_id"] == "objective-browser-session"
    assert calls[0]["reuse_session"] is True
    assert result.status == "success"
    assert result.metadata["text_output"] == "YouTube search results visible"
    assert result.artifacts == ["shot.png"]
    assert [entry.action for entry in result.execution_log] == ["open browser", "search youtube"]


class _DummyProvider:
    async def call(self, messages, *, json_mode=True):
        raise AssertionError("Provider should not be called in this test")


@pytest.mark.asyncio
async def test_agent_loop_reuses_and_cleans_up_browser_session_across_objectives() -> None:
    class _Bridge:
        def __init__(self) -> None:
            self.execute_calls: list[dict[str, object]] = []
            self.closed_sessions: list[str] = []

        async def execute_task(self, **kwargs):
            self.execute_calls.append(kwargs)
            return SimpleNamespace(
                status="success",
                category="success",
                error=None,
                artifacts=[],
                execution_log=[],
                metadata={},
            )

        async def close_browser_session(self, session_id: str) -> None:
            self.closed_sessions.append(session_id)

    bridge = _Bridge()
    context = ExecutionContext(objective="Search for Lady Gaga on YouTube")
    loop = AgentLoop(
        provider=_DummyProvider(),
        bridge=bridge,
        emit_status=lambda *_args, **_kwargs: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=context,
    )

    action = {
        "action_type": "browse",
        "parameters": {"action": "click", "selector": "Search"},
    }

    await loop._execute(action, obj_index=1, turn=1)
    await loop._execute(action, obj_index=2, turn=1)

    assert len(bridge.execute_calls) == 2
    session_ids = [call["context"]["_browser_session_id"] for call in bridge.execute_calls]
    assert session_ids[0] == session_ids[1]
    assert bridge.execute_calls[0]["context"]["_reuse_browser_session"] is True

    await loop.cleanup_browser_session(2, context)

    assert bridge.closed_sessions == [session_ids[0]]
    assert "task_browser_session_id" not in context.accumulated_state
