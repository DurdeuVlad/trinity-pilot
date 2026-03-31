"""Unit tests for AgentLoop cross-objective context injection (Layers 1 & 2)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_UNIFIED = REPO_ROOT / "unified-app"
for _p in (str(REPO_ROOT), str(_UNIFIED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from orchestrator.execution_context import ExecutionContext  # noqa: E402
from trinity_core.models import TaskResult  # noqa: E402


def _make_bridge_mock() -> MagicMock:
    """Return a TrinityBridge mock that records calls and returns a success result."""
    task_result = MagicMock()
    task_result.status = "success"
    task_result.category = "success"
    task_result.error = None
    task_result.execution_log = []
    task_result.artifacts = []
    task_result.metadata = {}
    task_result.output = None
    mock = MagicMock()
    mock.execute_task = AsyncMock(return_value=task_result)
    return mock


def _make_loop(bridge: Any, exec_ctx: ExecutionContext | None = None):
    """Instantiate AgentLoop with a mock bridge, bypassing __init__."""
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    loop = AgentLoop.__new__(AgentLoop)
    loop._bridge = bridge
    loop._context = exec_ctx
    loop._cancel_event = None
    loop._provider = MagicMock()
    loop._provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for a fast-path objective"))
    loop._emit = lambda *_args, **_kwargs: None
    loop._cancel = lambda: False
    loop._registry = MagicMock()
    loop.last_step_payload = None
    return loop


def _get_ctx_from_call(mock_bridge: MagicMock) -> dict:
    """Extract the `context` kwarg passed to execute_task."""
    call_kwargs = mock_bridge.execute_task.call_args[1]
    return call_kwargs["context"]


# ---------------------------------------------------------------------------
# Layer 2: _prior_results injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prior_results_injected_when_prior_objectives_exist() -> None:
    exec_ctx = ExecutionContext(objective="multi-step task")
    exec_ctx.accumulated_state["objective_1_desc"] = "browse wikipedia cats"
    exec_ctx.accumulated_state["objective_1_result"] = "Cats are mammals."

    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    action = {"action_type": "cli", "parameters": {"command": "echo hi"}}
    await loop._execute(action, obj_index=2, turn=1)

    ctx = _get_ctx_from_call(bridge)
    assert "_prior_results" in ctx
    assert "obj1" in ctx["_prior_results"]
    assert ctx["_prior_results"]["obj1"]["result"] == "Cats are mammals."


@pytest.mark.asyncio
async def test_prior_results_not_injected_on_first_objective() -> None:
    exec_ctx = ExecutionContext(objective="first task only")
    # No objective_N_desc keys present — nothing to inject

    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    action = {"action_type": "cli", "parameters": {"command": "dir"}}
    await loop._execute(action, obj_index=1, turn=1)

    ctx = _get_ctx_from_call(bridge)
    assert "_prior_results" not in ctx


@pytest.mark.asyncio
async def test_prior_results_truncated_to_200_and_400_chars() -> None:
    exec_ctx = ExecutionContext(objective="truncation test")
    exec_ctx.accumulated_state["objective_1_desc"] = "x" * 500    # over 200
    exec_ctx.accumulated_state["objective_1_result"] = "y" * 600   # over 400

    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    action = {"action_type": "browse", "parameters": {"url": "https://example.com"}}
    await loop._execute(action, obj_index=2, turn=1)

    ctx = _get_ctx_from_call(bridge)
    prior = ctx["_prior_results"]
    assert len(prior["obj1"]["desc"]) <= 200
    assert len(prior["obj1"]["result"]) <= 400


# ---------------------------------------------------------------------------
# Layer 1: clipboard handoff for paste verb
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clipboard_content_added_for_paste_when_prior_text_exists() -> None:
    exec_ctx = ExecutionContext(objective="paste test")
    exec_ctx.accumulated_state["objective_1_desc"] = "browse page"
    exec_ctx.accumulated_state["objective_1_result"] = "Wikipedia paragraph text"

    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    action = {
        "action_type": "desktop",
        "parameters": {"app": "Notepad", "action": "paste"},
    }
    await loop._execute(action, obj_index=2, turn=1)

    ctx = _get_ctx_from_call(bridge)
    assert ctx.get("clipboard_content") == "Wikipedia paragraph text"


@pytest.mark.asyncio
async def test_clipboard_content_absent_when_no_prior_text() -> None:
    exec_ctx = ExecutionContext(objective="empty paste test")
    # No prior objectives — get_latest_text_result() returns None

    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    action = {
        "action_type": "desktop",
        "parameters": {"app": "Notepad", "action": "paste"},
    }
    await loop._execute(action, obj_index=1, turn=1)

    ctx = _get_ctx_from_call(bridge)
    assert "clipboard_content" not in ctx


@pytest.mark.asyncio
async def test_browse_search_action_uses_rich_description() -> None:
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, ExecutionContext(objective="search task"))

    action = {
        "action_type": "browse",
        "parameters": {"action": "search", "text": "cats wikipedia"},
    }
    await loop._execute(action, obj_index=1, turn=1)

    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["description"] == "Search the web for cats wikipedia"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_wikipedia_open_without_provider() -> None:
    exec_ctx = ExecutionContext(objective="teacher flow")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(loop, "Open the Wikipedia page for cats.", obj_index=1, context=exec_ctx)

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["description"] == "Search the web for cats wikipedia"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_wikipedia_navigate_wording() -> None:
    exec_ctx = ExecutionContext(objective="teacher flow")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(loop, "Open Wikipedia and navigate to the 'Cats' page.", obj_index=1, context=exec_ctx)

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["description"] == "Search the web for Cats wikipedia"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_notepad_paste_with_clipboard() -> None:
    exec_ctx = ExecutionContext(objective="teacher flow")
    exec_ctx.accumulated_state["latest_text_result"] = "Cats are small, carnivorous mammals."
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(loop, "Paste the copied paragraph into Notepad.", obj_index=4, context=exec_ctx)

    assert result
    ctx = _get_ctx_from_call(bridge)
    assert ctx["clipboard_content"] == "Cats are small, carnivorous mammals."


@pytest.mark.asyncio
async def test_desktop_open_notepad_requests_blank_document() -> None:
    exec_ctx = ExecutionContext(objective="teacher flow")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(loop, "Open Notepad.", obj_index=3, context=exec_ctx)

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["description"] == "Open Notepad and create a new blank document"
    assert exec_ctx.world_state.active_app == "Notepad"
    assert exec_ctx.world_state.document_state == "fresh"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_simple_calculator_launch_directly_to_desktop_bridge() -> None:
    exec_ctx = ExecutionContext(objective="desktop task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "Open the Windows Calculator application",
        obj_index=1,
        context=exec_ctx,
    )

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "desktop"
    assert call_kwargs["description"] == "Open Calculator"
    assert call_kwargs["context"]["app_name"] == "Calculator"
    assert call_kwargs["context"]["app_exe_path"] == "calc.exe"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_copy_from_named_page_with_prior_context() -> None:
    exec_ctx = ExecutionContext(objective="teacher flow")
    exec_ctx.accumulated_state["objective_1_desc"] = "Open Wikipedia and navigate to the 'Cats' page."
    exec_ctx.accumulated_state["objective_1_result"] = "Opened https://en.wikipedia.org/wiki/Cats"
    bridge = _make_bridge_mock()
    bridge.execute_task.return_value.metadata = {
        "text_output": "The cat is a domestic species of small carnivorous mammal."
    }
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(loop, "Copy the first paragraph from the 'Cats' page.", obj_index=2, context=exec_ctx)

    assert result.startswith("The cat is a domestic species")
    assert exec_ctx.accumulated_state["latest_text_result"].startswith("The cat is a domestic species")


@pytest.mark.asyncio
async def test_objective_fast_path_routes_open_and_type_directly_to_desktop_bridge() -> None:
    exec_ctx = ExecutionContext(objective="desktop task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(loop, "Open Notepad and type PROD_DESKTOP_OK", obj_index=1, context=exec_ctx)

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "desktop"
    assert call_kwargs["description"] == "Open Notepad and type PROD_DESKTOP_OK"
    assert call_kwargs["context"]["app_name"] == "Notepad"
    assert call_kwargs["context"]["app_exe_path"] == "notepad.exe"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_screenshot_request_directly_to_browser_bridge() -> None:
    exec_ctx = ExecutionContext(objective="browser task")
    bridge = MagicMock()
    bridge.execute_task = AsyncMock(
        return_value=TaskResult(
            task_id="web-1",
            status="success",
            execution_log=[],
            artifacts=["_runtime/output/page.png"],
            metadata={"raw_result": {"result": "success"}},
        )
    )
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "Open https://example.com and capture a screenshot",
        obj_index=1,
        context=exec_ctx,
    )

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "web"
    assert call_kwargs["description"] == "Open https://example.com and capture a screenshot"
    assert loop.last_step_payload["artifacts"] == ["_runtime/output/page.png"]
    assert loop.last_step_payload["metadata"]["raw_result"]["result"] == "success"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_search_queries_directly_to_browser_bridge() -> None:
    exec_ctx = ExecutionContext(objective="browser search task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "Search for 'Python programming language' using a web browser",
        obj_index=1,
        context=exec_ctx,
    )

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "web"
    assert call_kwargs["description"] == "Search the web for Python programming language"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_python_file_listing_to_cli_bridge() -> None:
    exec_ctx = ExecutionContext(objective="python files task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "Identify Python files in the project",
        obj_index=1,
        context=exec_ctx,
    )

    assert result == "Listed Python files in the current working directory."
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "cli"
    assert call_kwargs["description"] == "List all Python files in the current working directory"


@pytest.mark.asyncio
async def test_objective_fast_path_routes_current_directory_path_to_cli_bridge() -> None:
    exec_ctx = ExecutionContext(objective="directory task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "Get the current directory path",
        obj_index=1,
        context=exec_ctx,
    )

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "cli"
    assert call_kwargs["description"] == "Get the current directory path"
    loop._provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_objective_fast_path_routes_current_directory_contents_to_cli_bridge() -> None:
    exec_ctx = ExecutionContext(objective="directory task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "List the contents of the current directory",
        obj_index=1,
        context=exec_ctx,
    )

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "cli"
    assert call_kwargs["description"] == "List the contents of the current directory"
    loop._provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_objective_fast_path_routes_python_version_to_cli_bridge() -> None:
    exec_ctx = ExecutionContext(objective="version task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "python --version",
        obj_index=1,
        context=exec_ctx,
    )

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "cli"
    assert call_kwargs["description"] == "python --version"
    loop._provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_objective_fast_path_normalizes_generic_python_version_success_marker() -> None:
    exec_ctx = ExecutionContext(objective="version task")
    bridge = _make_bridge_mock()
    task_result = bridge.execute_task.return_value
    task_result.execution_log = [MagicMock(details="Result 1: success")]
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "python --version",
        obj_index=1,
        context=exec_ctx,
    )

    assert result == "Successfully found the installed Python version using the command 'python --version'."
    loop._provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_objective_fast_path_routes_first_result_title_to_browser_adapter() -> None:
    exec_ctx = ExecutionContext(objective="browser search task")
    exec_ctx.accumulated_state["objective_1_desc"] = "Search for 'Python programming language' using a web browser"
    exec_ctx.accumulated_state["objective_1_result"] = (
        "Searched the web for 'Python programming language'. "
        "First result: Python (programming language) - Wikipedia"
    )
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(
        loop,
        "Display the title of the first search result",
        obj_index=2,
        context=exec_ctx,
    )

    assert result
    call_kwargs = bridge.execute_task.call_args[1]
    assert call_kwargs["domain"] == "web"
    assert call_kwargs["description"] == "Display the title of the first search result"
    assert call_kwargs["context"]["_prior_results"]["obj1"]["desc"] == (
        "Search for 'Python programming language' using a web browser"
    )


@pytest.mark.asyncio
async def test_act_stops_after_desktop_open_reports_app_unavailable() -> None:
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415
    from orchestrator.prompt_registry import PromptRegistry  # noqa: PLC0415

    exec_ctx = ExecutionContext(objective="desktop failure task")
    provider = MagicMock()
    provider.call = AsyncMock(
        side_effect=[
            (
                '{"rationale":"Open the requested application.",'
                '"action_type":"desktop","module":"desktop_app",'
                '"parameters":{"action":"open","app":"InvalidSoftware_ABCDEF"},'
                '"done":false}'
            ),
            (
                '{"rationale":"Fallback with CLI lookup.",'
                '"action_type":"cli","module":"terminal",'
                '"parameters":{"command":"where","args":["InvalidSoftware_ABCDEF"]},'
                '"done":false}'
            ),
        ]
    )
    bridge = MagicMock()
    bridge.execute_task = AsyncMock(
        return_value=TaskResult(
            task_id="desktop-failure-1",
            status="failure",
            category="failure",
            error="The application 'InvalidSoftware_ABCDEF' does not exist and cannot be opened.",
            execution_log=[],
            artifacts=[],
            metadata={},
        )
    )

    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        emit_status=lambda *_args: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=exec_ctx,
        cancel_event=None,
    )

    result = await loop.act(
        "Attempt to open the application 'InvalidSoftware_ABCDEF'",
        obj_index=1,
        context=exec_ctx,
    )

    assert result.startswith("ERROR:")
    assert "does not exist and cannot be opened" in result
    provider.call.assert_not_awaited()
    assert bridge.execute_task.await_count == 1


@pytest.mark.asyncio
async def test_act_fails_fast_for_app_version_query_when_app_is_unavailable() -> None:
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415
    from orchestrator.prompt_registry import PromptRegistry  # noqa: PLC0415

    exec_ctx = ExecutionContext(objective="desktop version failure task")
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called before fast-path app check"))
    bridge = MagicMock()
    bridge.execute_task = AsyncMock(
        return_value=TaskResult(
            task_id="desktop-failure-version-1",
            status="failure",
            category="failure",
            error="Could not find the NonExistentApp_XYZ123456 window. Please make sure the application is installed. (Technical details: .*NonExistentApp_XYZ123456.*, window_not_found)",
            execution_log=[],
            artifacts=[],
            metadata={},
        )
    )

    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        emit_status=lambda *_args: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=exec_ctx,
        cancel_event=None,
    )

    result = await loop.act(
        "Open an application called 'NonExistentApp_XYZ123456' and tell me its version number",
        obj_index=1,
        context=exec_ctx,
    )

    assert result.startswith("ERROR:")
    assert "version number cannot be determined" in result
    bridge.execute_task.assert_awaited_once()
    provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_act_routes_explicit_attempt_to_open_objective_directly_to_desktop_bridge() -> None:
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415
    from orchestrator.prompt_registry import PromptRegistry  # noqa: PLC0415

    exec_ctx = ExecutionContext(objective="desktop open task")
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for explicit app open objective"))
    bridge = MagicMock()
    bridge.execute_task = AsyncMock(
        return_value=TaskResult(
            task_id="desktop-open-1",
            status="failure",
            category="failure",
            error="The application 'InvalidSoftware_ABCDEF' does not exist and cannot be opened.",
            execution_log=[],
            artifacts=[],
            metadata={},
        )
    )

    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        emit_status=lambda *_args: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=exec_ctx,
        cancel_event=None,
    )

    result = await loop.act(
        "Attempt to open the 'InvalidSoftware_ABCDEF' application",
        obj_index=2,
        context=exec_ctx,
    )

    assert result.startswith("ERROR:")
    assert "cannot be opened" in result
    bridge.execute_task.assert_awaited_once()
    provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_act_routes_open_application_called_objective_directly_to_desktop_bridge() -> None:
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415
    from orchestrator.prompt_registry import PromptRegistry  # noqa: PLC0415

    exec_ctx = ExecutionContext(objective="desktop open task")
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for application-called open objective"))
    bridge = MagicMock()
    bridge.execute_task = AsyncMock(
        return_value=TaskResult(
            task_id="desktop-open-2",
            status="failure",
            category="failure",
            error="The application 'InvalidSoftware_ABCDEF' could not be found. Please make sure the application is installed.",
            execution_log=[],
            artifacts=[],
            metadata={},
        )
    )

    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        emit_status=lambda *_args: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=exec_ctx,
        cancel_event=None,
    )

    result = await loop.act(
        "Open an application called 'InvalidSoftware_ABCDEF' that does not exist",
        obj_index=2,
        context=exec_ctx,
    )

    assert result.startswith("ERROR:")
    assert "could not be found" in result
    bridge.execute_task.assert_awaited_once()
    provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_act_updates_latest_text_result_for_browse_copy_actions() -> None:
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415
    from orchestrator.prompt_registry import PromptRegistry  # noqa: PLC0415
    from trinity_core.models import TaskResult  # noqa: PLC0415

    exec_ctx = ExecutionContext(objective="copy text")
    provider = MagicMock()
    provider.call = AsyncMock(
        side_effect=[
            (
                '{"rationale":"Copy the paragraph text from the page.",'
                '"action_type":"browse","module":"web_browser",'
                '"parameters":{"action":"copy","text":"first paragraph"},'
                '"done":false}'
            ),
            (
                '{"rationale":"The paragraph is copied.","action_type":"done",'
                '"module":null,"parameters":{},"done":true,'
                '"result_summary":"Copied the paragraph."}'
            ),
        ]
    )
    bridge = MagicMock()
    bridge.execute_task = AsyncMock(
        return_value=TaskResult(
            task_id="copy-1",
            status="success",
            execution_log=[],
            artifacts=[],
            metadata={"text_output": "The cat is a domestic species of small carnivorous mammal."},
        )
    )

    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        emit_status=lambda *_args: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=exec_ctx,
        cancel_event=None,
    )

    result = await loop.act("Copy the first paragraph from the Wikipedia page.", obj_index=1, context=exec_ctx)

    assert result == "Copied the paragraph."
    assert exec_ctx.accumulated_state["latest_text_result"].startswith("The cat is a domestic species")


@pytest.mark.asyncio
async def test_objective_fast_path_returns_guidance_for_vague_productivity_request() -> None:
    exec_ctx = ExecutionContext(objective="productivity task")
    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    result = await AgentLoop.act(loop, "Help me work faster on my computer", obj_index=1, context=exec_ctx)

    assert "biggest bottleneck" in result
    assert "which app, workflow, or slowdown symptom" in result
    bridge.execute_task.assert_not_called()
    assert loop.last_step_payload["metadata"]["fast_path"] == "vague_productivity_guidance"
