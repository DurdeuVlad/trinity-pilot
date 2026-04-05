"""Phase-level tests for execute() decomposition (UA-S6).

Covers cancel and failure edge cases for each extracted phase method.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.execution_runner import TaskExecutionRunner
from orchestrator.execution_context import ExecutionContext
from orchestrator.macro_planner import ExecutionPlan


# ── Minimal fakes ──────────────────────────────────────────────────────────────

def _make_bridge(ok: bool = True) -> MagicMock:
    bridge = MagicMock()
    bridge.initialize = AsyncMock()
    bridge.shutdown = AsyncMock()
    bridge.get_capabilities = AsyncMock(return_value={})
    return bridge


def _make_history() -> MagicMock:
    h = MagicMock()
    h.create_task = MagicMock()
    h.start_task = MagicMock()
    h.update_task_plan = MagicMock()
    h.add_step = MagicMock()
    h.update_step_status = MagicMock()
    h.complete_task = MagicMock()
    h.close = MagicMock()
    return h


def _make_planner(steps: list[str] | None = None) -> MagicMock:
    planner = MagicMock()
    if steps is not None:
        plan = ExecutionPlan(
            description="test",
            domain="cli",
            steps=steps,
            estimated_duration=60,
            confidence=0.8,
        )
        planner.generate_plan = AsyncMock(return_value=plan)
    else:
        planner.generate_plan = AsyncMock(side_effect=RuntimeError("planner exploded"))
    return planner


def _make_runner(
    steps: list[str] | None = None,
    cancel: bool = False,
    approved_plan: list[str] | None = None,
    planner: MagicMock | None = None,
) -> TaskExecutionRunner:
    bus = MagicMock()
    bus.emit_status = MagicMock()

    event_bus_obj = MagicMock()
    event_bus_obj.execution_started = MagicMock()
    event_bus_obj.execution_started.emit = MagicMock()
    event_bus_obj.plan_generated = MagicMock()
    event_bus_obj.plan_generated.emit = MagicMock()
    event_bus_obj.step_started = MagicMock()
    event_bus_obj.step_started.emit = MagicMock()
    event_bus_obj.step_completed = MagicMock()
    event_bus_obj.step_completed.emit = MagicMock()
    event_bus_obj.step_failed = MagicMock()
    event_bus_obj.step_failed.emit = MagicMock()
    event_bus_obj.execution_complete = MagicMock()
    event_bus_obj.execution_complete.emit = MagicMock()
    event_bus_obj.execution_ended = MagicMock()
    event_bus_obj.execution_ended.emit = MagicMock()
    event_bus_obj.task_result_ready = MagicMock()
    event_bus_obj.task_result_ready.emit = MagicMock()
    event_bus_obj.status_updated = MagicMock()
    event_bus_obj.status_updated.emit = MagicMock()

    watcher = MagicMock()
    watcher.start_watching = MagicMock()
    watcher.stop_watching = MagicMock()

    error_handler = MagicMock()
    error_handler.build_user_message = MagicMock(return_value="error message")
    error_handler.map_backend_unavailable_reason = MagicMock(return_value=None)

    provider = MagicMock()
    provider.close = AsyncMock()

    runner = TaskExecutionRunner(
        run_id="test-run",
        task_description="do something",
        domain="cli",
        event_bus=event_bus_obj,
        history_manager=_make_history(),
        error_handler=error_handler,
        planner=planner or _make_planner(steps),
        provider=provider,
        bridge=_make_bridge(),
        screenshot_watcher=watcher,
        cancel_requested=lambda: cancel,
        cancel_event=None,
        approved_plan=approved_plan,
    )
    return runner


# ── _plan_phase ────────────────────────────────────────────────────────────────

async def test_plan_phase_returns_none_on_exception() -> None:
    """_plan_phase must return None (not raise) when plan generation fails."""
    runner = _make_runner(steps=None)  # planner raises RuntimeError
    result = await runner._plan_phase()
    assert result is None


async def test_plan_phase_returns_plan_on_success() -> None:
    runner = _make_runner(steps=["step 1", "step 2"])
    result = await runner._plan_phase()
    assert result is not None
    assert len(result.steps) == 2


async def test_plan_phase_uses_approved_plan_when_set() -> None:
    runner = _make_runner(approved_plan=["obj 1", "obj 2", "obj 3"])
    result = await runner._plan_phase()
    assert result is not None
    assert result.steps == ["obj 1", "obj 2", "obj 3"]
    assert result.confidence == 0.95


async def test_plan_phase_approved_plan_does_not_call_planner() -> None:
    planner = _make_planner(steps=["this should not be used"])
    runner = _make_runner(approved_plan=["manual objective"], planner=planner)
    await runner._plan_phase()
    planner.generate_plan.assert_not_called()


# ── _build_attempt_context ────────────────────────────────────────────────────

def test_build_attempt_context_fresh_when_no_checkpoint() -> None:
    runner = _make_runner(steps=["step1"])
    plan = ExecutionPlan(
        description="test", domain="cli", steps=["step1"],
        estimated_duration=60, confidence=0.9,
    )
    runner.checkpoint_manager.get_latest_checkpoint = MagicMock(return_value=None)
    context, start_index, agent_loop = runner._build_attempt_context(plan)
    assert start_index == 0
    assert isinstance(context, ExecutionContext)
    assert context.objective == "do something"


def test_build_attempt_context_loads_checkpoint_when_available() -> None:
    runner = _make_runner(steps=["step1"])
    plan = ExecutionPlan(
        description="test", domain="cli", steps=["step1"],
        estimated_duration=60, confidence=0.9,
    )
    stored_ctx = ExecutionContext(objective="original")
    runner.checkpoint_manager.get_latest_checkpoint = MagicMock(return_value="cp-001")
    runner.checkpoint_manager.load_checkpoint = MagicMock(return_value=(stored_ctx, 2))
    context, start_index, agent_loop = runner._build_attempt_context(plan)
    assert start_index == 2
    assert context is stored_ctx
    # task description must be refreshed onto loaded context
    assert context.objective == "do something"


# ── _attempt_phase – cancel edge case ─────────────────────────────────────────

async def test_attempt_phase_returns_none_when_immediately_cancelled() -> None:
    """If cancel_requested fires at loop entry, _attempt_phase returns None."""
    runner = _make_runner(steps=["step1"], cancel=True)
    plan = ExecutionPlan(
        description="t", domain="cli", steps=["step1"],
        estimated_duration=60, confidence=0.9,
    )
    ctx = ExecutionContext(objective="t")
    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = {}

    result = await runner._attempt_phase(plan.steps, ctx, 0, agent_loop)
    assert result is None


async def test_attempt_phase_returns_tuple_when_not_cancelled() -> None:
    """With 0 objectives, _attempt_phase completes normally returning empty lists."""
    runner = _make_runner(steps=[])
    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = {}
    ctx = ExecutionContext(objective="t")

    result = await runner._attempt_phase([], ctx, 0, agent_loop)
    assert result is not None
    completed, failed = result
    assert completed == []
    assert failed == []


# ── _finalize_phase – outcome categorisation ──────────────────────────────────

async def test_finalize_phase_success_when_no_failures() -> None:
    runner = _make_runner(steps=["s1", "s2"])
    signals: list[dict] = []
    runner.event_bus.execution_complete.emit = lambda payload: signals.append(payload)

    await runner._finalize_phase(
        plan_steps=["s1", "s2"],
        completed=[(1, "s1"), (2, "s2")],
        failed=[],
    )
    assert signals[-1]["status"] == "success"


async def test_finalize_phase_failure_when_all_objectives_failed() -> None:
    runner = _make_runner(steps=["s1"])
    signals: list[dict] = []
    runner.event_bus.execution_complete.emit = lambda payload: signals.append(payload)

    await runner._finalize_phase(
        plan_steps=["s1"],
        completed=[],
        failed=[(1, "s1", "error msg")],
    )
    assert signals[-1]["status"] == "failure"


async def test_finalize_phase_partial_when_some_failed() -> None:
    runner = _make_runner(steps=["s1", "s2"])
    signals: list[dict] = []
    runner.event_bus.execution_complete.emit = lambda payload: signals.append(payload)

    await runner._finalize_phase(
        plan_steps=["s1", "s2"],
        completed=[(1, "s1")],
        failed=[(2, "s2", "error")],
    )
    assert signals[-1]["status"] == "partial"


# ── execute() line count guard ────────────────────────────────────────────────

def test_execute_method_is_under_30_lines() -> None:
    """The orchestration-only execute() must stay under 30 lines."""
    import inspect
    lines = inspect.getsource(TaskExecutionRunner.execute).splitlines()
    # Strip blank lines and comment-only lines for a fair count
    non_trivial = [
        ln for ln in lines
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(non_trivial) <= 30, (
        f"execute() has {len(non_trivial)} non-trivial lines — keep it under 30. "
        "Extract more logic into phase methods."
    )
