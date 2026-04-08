from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.active_reviewer import ReviewResult, ReviewStatus
from orchestrator.execution_context import ExecutionContext
from orchestrator.execution_runner import TaskExecutionRunner
from orchestrator.failure_classifier import FailureKind
from orchestrator.macro_planner import ExecutionPlan


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit_status = MagicMock()
    for name in (
        "execution_started",
        "plan_generated",
        "step_started",
        "step_completed",
        "step_failed",
        "execution_complete",
        "execution_ended",
        "task_result_ready",
    ):
        setattr(bus, name, MagicMock())
        getattr(bus, name).emit = MagicMock()
    return bus


def _make_history() -> MagicMock:
    history = MagicMock()
    history.create_task = MagicMock()
    history.start_task = MagicMock()
    history.update_task_plan = MagicMock()
    history.add_step = MagicMock()
    history.update_step_status = MagicMock()
    history.complete_task = MagicMock()
    history.close = MagicMock()
    history.get_task = MagicMock(return_value=None)
    return history


def _make_runner(
    *,
    planner: MagicMock | None = None,
    approved_plan: list[str] | None = None,
    audit_recorder: MagicMock | None = None,
) -> TaskExecutionRunner:
    bridge = MagicMock()
    bridge.initialize = AsyncMock()
    bridge.shutdown = AsyncMock()
    bridge.get_capabilities = AsyncMock(return_value={"cli": {"run_command": True}})

    provider = MagicMock()
    provider.close = AsyncMock()

    error_handler = MagicMock()
    error_handler.handle = MagicMock(
        return_value={
            "message": "plan failed",
            "user_message": "plan failed",
            "category": "failure",
        }
    )
    error_handler.map_backend_unavailable_reason = MagicMock(return_value=None)
    error_handler.build_user_message = MagicMock(return_value="user-facing error")

    watcher = MagicMock()
    watcher.start_watching = MagicMock()
    watcher.stop_watching = MagicMock()

    planner = planner or MagicMock()
    if "generate_plan" not in planner.__dict__:
        planner.generate_plan = AsyncMock(
            return_value=ExecutionPlan(
                description="do something",
                domain="cli",
                steps=["step 1", "step 2"],
                estimated_duration=120,
                confidence=0.9,
            )
        )
    if "replan" not in planner.__dict__:
        planner.replan = AsyncMock(return_value=["fallback"])

    recorder = audit_recorder or MagicMock()
    recorder.event = MagicMock()
    recorder.report = SimpleNamespace(status="unknown", metrics={}, diagnostics={})

    return TaskExecutionRunner(
        run_id="run-123",
        task_description="do something",
        domain="cli",
        event_bus=_make_event_bus(),
        history_manager=_make_history(),
        error_handler=error_handler,
        planner=planner,
        provider=provider,
        bridge=bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=None,
        approved_plan=approved_plan,
        audit_recorder=recorder,
    )


async def test_plan_phase_emits_planning_events() -> None:
    runner = _make_runner()

    result = await runner._plan_phase()

    assert result is not None
    messages = [call.kwargs["message"] for call in runner.audit_recorder.event.call_args_list]
    assert "MacroPlanner generating plan" in messages
    assert "Capability assessment complete" in messages
    assert "Plan generated successfully" in messages


async def test_plan_phase_uses_approved_plan_and_logs_it() -> None:
    runner = _make_runner(approved_plan=["one", "two"])

    result = await runner._plan_phase()

    assert result is not None
    messages = [call.kwargs["message"] for call in runner.audit_recorder.event.call_args_list]
    assert "Using pre-approved plan" in messages


async def test_plan_phase_is_fail_soft_when_recorder_event_raises() -> None:
    recorder = MagicMock()
    recorder.event = MagicMock(side_effect=RuntimeError("audit broke"))
    recorder.report = SimpleNamespace(status="unknown", metrics={}, diagnostics={})
    runner = _make_runner(audit_recorder=recorder)

    result = await runner._plan_phase()

    assert result is not None


async def test_plan_phase_failure_logs_error_and_marks_status() -> None:
    planner = MagicMock()
    planner.generate_plan = AsyncMock(side_effect=RuntimeError("planner exploded"))
    runner = _make_runner(planner=planner)

    result = await runner._plan_phase()

    assert result is None
    assert runner.audit_recorder.report.status == "failure"
    messages = [call.kwargs["message"] for call in runner.audit_recorder.event.call_args_list]
    assert "Plan generation failed" in messages


async def test_run_attempts_emits_reflection_and_retry_events() -> None:
    runner = _make_runner()
    runner.reflection_engine.reflect = AsyncMock(
        side_effect=[
            SimpleNamespace(achieved=False, critique="try a different command"),
            SimpleNamespace(achieved=True, critique=None),
        ]
    )
    runner.active_reviewer.review_progress = AsyncMock(
        return_value=ReviewResult(
            status=ReviewStatus.FAILED,
            assessment="not done yet",
            missing=[],
            next_steps=[],
            hints=[],
            alternative_strategies=[],
            confidence=0.4,
        )
    )

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = {
        "status": "success",
        "execution_log": [{"action": "run"}],
        "metadata": {},
    }
    agent_loop.act = AsyncMock(side_effect=["first result", "second result"])

    with patch("orchestrator.execution_runner.classify", return_value=FailureKind.TRANSIENT):
        achieved, final_result = await runner._run_attempts(
            "run a command",
            1,
            ExecutionContext(objective="run a command"),
            agent_loop,
        )

    assert achieved is True
    assert final_result == "second result"
    messages = [call.kwargs["message"] for call in runner.audit_recorder.event.call_args_list]
    assert "Objective reflection complete" in messages
    assert "Retry triggered" in messages


async def test_try_replan_logs_completion_event() -> None:
    planner = MagicMock()
    planner.generate_plan = AsyncMock()
    planner.replan = AsyncMock(return_value=["fallback objective"])
    runner = _make_runner(planner=planner)

    revised = await runner._try_replan(
        completed=["first"],
        failed=[("second", "boom")],
        remaining=["third"],
        constraints=["constraint"],
    )

    assert revised == ["fallback objective"]
    messages = [call.kwargs["message"] for call in runner.audit_recorder.event.call_args_list]
    assert "Replanning complete" in messages


def test_derive_backend_report_path_reads_nested_raw_result_metadata() -> None:
    runner = _make_runner()

    path = runner._derive_backend_report_path(
        {
            "metadata": {
                "raw_result": {
                    "metadata": {
                        "flight_report_path": "C:/tmp/report.json",
                    }
                }
            }
        }
    )

    assert path == "C:/tmp/report.json"


async def test_attempt_phase_persists_backend_flight_report_path() -> None:
    runner = _make_runner()
    runner.checkpoint_manager.save_checkpoint = MagicMock(return_value="cp-1")
    runner._run_attempts = AsyncMock(return_value=(True, "done"))
    context = ExecutionContext(objective="do something")

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = {
        "status": "success",
        "output": "done",
        "metadata": {
            "raw_result": {
                "metadata": {
                    "flight_report_path": "C:/tmp/backend-report.json",
                }
            }
        },
    }

    result = await runner._attempt_phase(["step 1"], context, 0, agent_loop)

    assert result == ([(1, "step 1")], [])
    assert runner.history_manager.update_step_status.call_args.kwargs["flight_report_path"] == "C:/tmp/backend-report.json"


async def test_attempt_phase_updates_prompt_logging_objective_context() -> None:
    runner = _make_runner()
    runner.checkpoint_manager.save_checkpoint = MagicMock(return_value="cp-1")
    runner._run_attempts = AsyncMock(return_value=(True, "done"))
    context = ExecutionContext(objective="do something")

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = {
        "status": "success",
        "output": "done",
        "metadata": {},
    }

    with patch("orchestrator.execution_runner.update_prompt_logging_context") as update_context:
        result = await runner._attempt_phase(["step 1"], context, 0, agent_loop)

    assert result == ([(1, "step 1")], [])
    update_context.assert_any_call(
        extra={
            "current_objective_id": "objective_1",
            "current_objective_label": "step 1",
        }
    )
