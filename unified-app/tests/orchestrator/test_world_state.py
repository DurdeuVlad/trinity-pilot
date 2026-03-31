"""Tests for the first-class WorldState contract.

Covers:
- WorldState.update_from_action() for all action types / verbs
- app_already_open vs must_launch detection via WorldState.is_app_open()
- active document / document_state tracking
- last_text_artifact isolation from generic status strings
- attach-to-existing-window (app_launch_mode = "attached")
- ExecutionContext.get_latest_text_result() priority
- ExecutionContext.update_world_state_from_action() delegation
- AgentLoop._execute() injects _world_state when state is non-empty
- AgentLoop._execute() omits _world_state when state is empty
"""
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

from orchestrator.execution_context import ExecutionContext, WorldState  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws(**kwargs: Any) -> WorldState:
    ws = WorldState()
    for k, v in kwargs.items():
        setattr(ws, k, v)
    return ws


def _make_bridge_mock(text_output: str = "") -> MagicMock:
    task_result = MagicMock()
    task_result.status = "success"
    task_result.category = "success"
    task_result.error = None
    task_result.execution_log = []
    task_result.artifacts = []
    task_result.metadata = {"text_output": text_output} if text_output else {}
    mock = MagicMock()
    mock.execute_task = AsyncMock(return_value=task_result)
    return mock


def _make_loop(bridge: Any, exec_ctx: ExecutionContext | None = None):
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415

    loop = AgentLoop.__new__(AgentLoop)
    loop._bridge = bridge
    loop._context = exec_ctx
    loop._cancel_event = None
    return loop


def _get_ctx_from_call(mock_bridge: MagicMock) -> dict:
    return mock_bridge.execute_task.call_args[1]["context"]


# ---------------------------------------------------------------------------
# WorldState.is_app_open — app already open vs must launch
# ---------------------------------------------------------------------------

def test_is_app_open_matches_exact_name() -> None:
    ws = _ws(active_app="Notepad")
    assert ws.is_app_open("Notepad") is True


def test_is_app_open_case_insensitive() -> None:
    ws = _ws(active_app="Notepad")
    assert ws.is_app_open("notepad") is True
    assert ws.is_app_open("NOTEPAD") is True


def test_is_app_open_strips_exe_suffix() -> None:
    ws = _ws(active_app="Notepad")
    assert ws.is_app_open("notepad.exe") is True


def test_is_app_open_false_for_different_app() -> None:
    ws = _ws(active_app="Notepad")
    assert ws.is_app_open("WordPad") is False


def test_is_app_open_false_when_no_active_app() -> None:
    ws = WorldState()
    assert ws.is_app_open("Notepad") is False


def test_has_state_false_when_empty() -> None:
    assert WorldState().has_state() is False


def test_has_state_true_when_active_app_set() -> None:
    assert _ws(active_app="Notepad").has_state() is True


# ---------------------------------------------------------------------------
# WorldState.update_from_action — desktop open (launched mode)
# ---------------------------------------------------------------------------

def test_desktop_open_sets_active_app_and_launched_mode() -> None:
    ws = WorldState()
    ws.update_from_action("desktop", {"app": "Notepad", "action": "open"}, "Open Notepad")
    assert ws.active_app == "Notepad"
    assert ws.app_launch_mode == "launched"


def test_desktop_open_blank_doc_app_sets_fresh_document_state() -> None:
    ws = WorldState()
    ws.update_from_action("desktop", {"app": "Notepad", "action": "open"}, "Open Notepad")
    assert ws.document_state == "fresh"
    assert ws.active_document == "new document"


def test_desktop_open_non_blank_doc_app_no_document_state() -> None:
    ws = WorldState()
    ws.update_from_action("desktop", {"app": "Calculator", "action": "open"}, "Open Calculator")
    assert ws.document_state is None
    assert ws.active_document is None


# ---------------------------------------------------------------------------
# WorldState.update_from_action — attach-to-existing-window
# ---------------------------------------------------------------------------

def test_desktop_focus_sets_attached_mode() -> None:
    ws = WorldState()
    ws.update_from_action("desktop", {"app": "Notepad", "action": "focus"}, "Focused Notepad")
    assert ws.active_app == "Notepad"
    assert ws.app_launch_mode == "attached"


def test_desktop_focus_does_not_overwrite_existing_launch_mode() -> None:
    """If app was launched by us, a later focus action should not change it to attached."""
    ws = _ws(active_app="Notepad", app_launch_mode="launched")
    ws.update_from_action("desktop", {"app": "Notepad", "action": "focus"}, "Focused Notepad")
    assert ws.app_launch_mode == "launched"


# ---------------------------------------------------------------------------
# WorldState.update_from_action — desktop paste/type (document becomes existing)
# ---------------------------------------------------------------------------

def test_desktop_paste_sets_document_state_existing() -> None:
    ws = _ws(active_app="Notepad", document_state="fresh")
    ws.update_from_action("desktop", {"app": "Notepad", "action": "paste"}, "Pasted content")
    assert ws.document_state == "existing"


def test_desktop_type_sets_document_state_existing() -> None:
    ws = _ws(active_app="Notepad", document_state="fresh")
    ws.update_from_action("desktop", {"app": "Notepad", "action": "type", "text": "hi"}, "Typed")
    assert ws.document_state == "existing"


# ---------------------------------------------------------------------------
# WorldState.update_from_action — browse (last_text_artifact + active_app)
# ---------------------------------------------------------------------------

def test_browse_copy_with_real_text_sets_last_text_artifact() -> None:
    ws = WorldState()
    real_text = "The cat is a domestic species of small carnivorous mammal."
    ws.update_from_action("browse", {"action": "copy"}, real_text)
    assert ws.last_text_artifact == real_text
    assert ws.active_app == "browser"


def test_browse_copy_with_short_result_does_not_set_artifact() -> None:
    """Short strings (< 20 chars) are treated as status, not content."""
    ws = WorldState()
    ws.update_from_action("browse", {"action": "copy"}, "OK")
    assert ws.last_text_artifact is None


def test_browse_copy_with_status_prefix_does_not_contaminate_artifact() -> None:
    """Generic status prefixes must not land in last_text_artifact."""
    ws = WorldState()
    for status_str in (
        "OK (status=success)",
        "Navigated to https://example.com",
        "Opened page successfully.",
        "Focused window",
        "Pasted content into app",
    ):
        ws.update_from_action("browse", {"action": "copy"}, status_str)
    assert ws.last_text_artifact is None


def test_browse_navigate_sets_last_opened_url() -> None:
    ws = WorldState()
    ws.update_from_action("browse", {"action": "navigate", "url": "https://en.wikipedia.org/wiki/Cat"}, "OK")
    assert ws.last_opened_url == "https://en.wikipedia.org/wiki/Cat"


def test_browse_action_sets_browser_as_active_app() -> None:
    ws = WorldState()
    ws.update_from_action("browse", {"action": "search", "text": "cats"}, "Search complete")
    assert ws.active_app == "browser"


# ---------------------------------------------------------------------------
# WorldState.update_from_action — error results never update state
# ---------------------------------------------------------------------------

def test_error_result_does_not_update_active_app() -> None:
    ws = WorldState()
    ws.update_from_action("desktop", {"app": "Notepad", "action": "open"}, "ERROR: window not found")
    assert ws.active_app is None
    assert ws.app_launch_mode is None


def test_error_result_does_not_update_text_artifact() -> None:
    ws = WorldState()
    ws.update_from_action("browse", {"action": "copy"}, "ERROR: page not loaded")
    assert ws.last_text_artifact is None


# ---------------------------------------------------------------------------
# ExecutionContext — get_latest_text_result priority
# ---------------------------------------------------------------------------

def test_get_latest_text_result_prefers_world_state_artifact() -> None:
    """world_state.last_text_artifact wins over accumulated_state["latest_text_result"]."""
    ctx = ExecutionContext(objective="test")
    ctx.world_state.last_text_artifact = "Explicit artifact from world state"
    ctx.accumulated_state["latest_text_result"] = "Legacy override text"
    assert ctx.get_latest_text_result() == "Explicit artifact from world state"


def test_get_latest_text_result_falls_back_to_accumulated_state() -> None:
    ctx = ExecutionContext(objective="test")
    ctx.accumulated_state["latest_text_result"] = "Legacy override text"
    assert ctx.get_latest_text_result() == "Legacy override text"


def test_get_latest_text_result_falls_back_to_objective_results() -> None:
    ctx = ExecutionContext(objective="test")
    ctx.accumulated_state["objective_1_desc"] = "browse cats"
    ctx.accumulated_state["objective_1_result"] = "Paragraph about cats."
    assert ctx.get_latest_text_result() == "Paragraph about cats."


def test_get_latest_text_result_returns_none_when_no_text() -> None:
    ctx = ExecutionContext(objective="test")
    assert ctx.get_latest_text_result() is None


# ---------------------------------------------------------------------------
# ExecutionContext.update_world_state_from_action delegation
# ---------------------------------------------------------------------------

def test_update_world_state_from_action_delegates_correctly() -> None:
    ctx = ExecutionContext(objective="test")
    action = {"action_type": "desktop", "parameters": {"app": "Notepad", "action": "open"}}
    ctx.update_world_state_from_action(action, "Open Notepad")
    assert ctx.world_state.active_app == "Notepad"
    assert ctx.world_state.app_launch_mode == "launched"


def test_update_world_state_from_action_ignores_error_result() -> None:
    ctx = ExecutionContext(objective="test")
    action = {"action_type": "desktop", "parameters": {"app": "Notepad", "action": "open"}}
    ctx.update_world_state_from_action(action, "ERROR: failed")
    assert ctx.world_state.active_app is None


# ---------------------------------------------------------------------------
# WorldState.to_context_dict — serialisation
# ---------------------------------------------------------------------------

def test_to_context_dict_contains_all_fields() -> None:
    ws = _ws(
        active_app="Notepad",
        app_launch_mode="launched",
        document_state="fresh",
        last_text_artifact="Some text",
        last_opened_url="https://example.com",
    )
    d = ws.to_context_dict()
    assert d["active_app"] == "Notepad"
    assert d["app_launch_mode"] == "launched"
    assert d["document_state"] == "fresh"
    assert d["last_text_artifact"] == "Some text"
    assert d["last_opened_url"] == "https://example.com"


def test_to_context_dict_empty_when_no_state() -> None:
    d = WorldState().to_context_dict()
    assert all(v is None for v in d.values())


# ---------------------------------------------------------------------------
# AgentLoop._execute — _world_state injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_world_state_injected_when_state_is_nonempty() -> None:
    exec_ctx = ExecutionContext(objective="paste task")
    exec_ctx.world_state.active_app = "Notepad"
    exec_ctx.world_state.app_launch_mode = "launched"

    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    action = {"action_type": "desktop", "parameters": {"app": "Notepad", "action": "paste"}}
    await loop._execute(action, obj_index=2, turn=1)

    ctx = _get_ctx_from_call(bridge)
    assert "_world_state" in ctx
    assert ctx["_world_state"]["active_app"] == "Notepad"
    assert ctx["_world_state"]["app_launch_mode"] == "launched"


@pytest.mark.asyncio
async def test_world_state_not_injected_when_state_is_empty() -> None:
    exec_ctx = ExecutionContext(objective="fresh task")
    # No world state set — world_state.has_state() == False

    bridge = _make_bridge_mock()
    loop = _make_loop(bridge, exec_ctx)

    action = {"action_type": "cli", "parameters": {"command": "echo hi"}}
    await loop._execute(action, obj_index=1, turn=1)

    ctx = _get_ctx_from_call(bridge)
    assert "_world_state" not in ctx


@pytest.mark.asyncio
async def test_world_state_updated_after_desktop_open_action() -> None:
    """After AgentLoop executes a desktop open action, world_state.active_app is set."""
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415
    from orchestrator.prompt_registry import PromptRegistry  # noqa: PLC0415

    exec_ctx = ExecutionContext(objective="open notepad")
    provider = MagicMock()
    provider.call = AsyncMock(
        side_effect=[
            (
                '{"rationale":"Opening Notepad","action_type":"desktop","module":"desktop",'
                '"parameters":{"app":"Notepad","action":"open"},"done":false}'
            ),
            '{"rationale":"Done","action_type":"done","module":null,"parameters":{},"done":true,'
            '"result_summary":"Notepad opened."}',
        ]
    )
    bridge = _make_bridge_mock()

    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        emit_status=lambda *_: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=exec_ctx,
        cancel_event=None,
    )

    await loop.act("Open Notepad", obj_index=1, context=exec_ctx)

    assert exec_ctx.world_state.active_app == "Notepad"
    assert exec_ctx.world_state.app_launch_mode == "launched"


@pytest.mark.asyncio
async def test_world_state_last_text_artifact_set_after_browse_copy() -> None:
    """After a browse copy action, last_text_artifact is populated."""
    from orchestrator.agent_loop import AgentLoop  # noqa: PLC0415
    from orchestrator.prompt_registry import PromptRegistry  # noqa: PLC0415
    from trinity_core.models import TaskResult  # noqa: PLC0415

    exec_ctx = ExecutionContext(objective="copy text")
    provider = MagicMock()
    provider.call = AsyncMock(
        side_effect=[
            (
                '{"rationale":"Copy paragraph","action_type":"browse","module":"web_browser",'
                '"parameters":{"action":"copy","text":"first paragraph"},"done":false}'
            ),
            '{"rationale":"Done","action_type":"done","module":null,"parameters":{},"done":true,'
            '"result_summary":"Copied."}',
        ]
    )
    bridge = MagicMock()
    bridge.execute_task = AsyncMock(
        return_value=TaskResult(
            task_id="t1",
            status="success",
            execution_log=[],
            artifacts=[],
            metadata={"text_output": "The cat is a domestic species of small carnivorous mammal."},
        )
    )

    loop = AgentLoop(
        provider=provider,
        bridge=bridge,
        emit_status=lambda *_: None,
        cancel_requested=lambda: False,
        registry=PromptRegistry("gemini"),
        context=exec_ctx,
        cancel_event=None,
    )

    await loop.act("Copy the first paragraph from the Wikipedia page.", obj_index=1, context=exec_ctx)

    assert exec_ctx.world_state.last_text_artifact is not None
    assert exec_ctx.world_state.last_text_artifact.startswith("The cat is a domestic species")
    assert exec_ctx.world_state.active_app == "browser"
