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
from orchestrator.agent_loop import _build_verification_checks


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit_status = MagicMock()
    for name in (
        "execution_started",
        "plan_generated",
        "step_started",
        "step_completed",
        "step_failed",
        "step_detail",
        "plan_state_updated",
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
    agent_loop.last_attempt_payload = agent_loop.last_step_payload
    agent_loop.act = AsyncMock(side_effect=["first result", "second result"])

    with patch("orchestrator.execution_runner.classify", return_value=FailureKind.TRANSIENT):
        achieved, final_result, attempt_count = await runner._run_attempts(
            "run a command",
            1,
            ExecutionContext(objective="run a command"),
            agent_loop,
        )

    assert achieved is True
    assert final_result == "second result"
    assert attempt_count == 2
    messages = [call.kwargs["message"] for call in runner.audit_recorder.event.call_args_list]
    assert "Objective reflection complete" in messages
    assert "Retry triggered" in messages


async def test_run_attempts_downgrades_failed_review_when_plan_is_unfinished() -> None:
    runner = _make_runner()
    runner.reflection_engine.reflect = AsyncMock(
        side_effect=[
            SimpleNamespace(achieved=False, critique="page still settling"),
            SimpleNamespace(achieved=True, critique=None),
        ]
    )
    runner.active_reviewer.review_progress = AsyncMock(
        return_value=ReviewResult(
            status=ReviewStatus.FAILED,
            assessment="The task failed",
            missing=["dashboard"],
            next_steps=[],
            hints=[],
            alternative_strategies=[],
            confidence=0.2,
        )
    )

    first_payload = {
        "status": "failure",
        "execution_log": [{"action": "click"}],
        "metadata": {
            "plan_state": {
                "revision": 1,
                "steps": [
                    {"title": "Wait for dashboard", "status": "in_progress"},
                    {"title": "Read result", "status": "pending"},
                ],
            }
        },
    }
    second_payload = {
        "status": "success",
        "execution_log": [{"action": "extract_text"}],
        "metadata": {
            "plan_state": {
                "revision": 2,
                "steps": [
                    {"title": "Wait for dashboard", "status": "done"},
                    {"title": "Read result", "status": "done"},
                ],
            }
        },
    }

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = first_payload
    agent_loop.last_attempt_payload = first_payload
    results = iter(["first result", "second result"])
    payloads = iter([first_payload, second_payload])

    async def _act(**_kwargs):
        payload = next(payloads)
        agent_loop.last_step_payload = payload
        agent_loop.last_attempt_payload = payload
        return next(results)

    agent_loop.act = AsyncMock(side_effect=_act)

    with patch("orchestrator.execution_runner.classify", return_value=FailureKind.PERMANENT):
        achieved, final_result, attempt_count = await runner._run_attempts(
            "wait for the dashboard",
            1,
            ExecutionContext(objective="wait for the dashboard"),
            agent_loop,
        )

    assert achieved is True
    assert final_result == "second result"
    assert attempt_count == 2


async def test_run_attempts_accepts_verified_cli_backend_success_before_review() -> None:
    runner = _make_runner()
    runner.reflection_engine.reflect = AsyncMock(
        return_value=SimpleNamespace(achieved=False, critique="summary looked incomplete")
    )
    runner.active_reviewer.review_progress = AsyncMock()

    verified_payload = {
        "status": "success",
        "execution_log": [{"action": "run", "result": "success"}],
        "metadata": {
            "raw_result": {
                "status": "success",
                "metadata": {
                    "module": "cli",
                    "raw_result": {
                        "status": "success",
                        "plan_state": {
                            "steps": [
                                {"status": "success", "verification": "passed"},
                            ]
                        },
                    },
                },
            }
        },
    }

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = verified_payload
    agent_loop.last_attempt_payload = verified_payload
    agent_loop.act = AsyncMock(return_value="command completed")

    achieved, final_result, attempt_count = await runner._run_attempts(
        "run the command and verify the output",
        1,
        ExecutionContext(objective="run the command and verify the output"),
        agent_loop,
    )

    assert achieved is True
    assert final_result == "command completed"
    assert attempt_count == 1
    runner.active_reviewer.review_progress.assert_not_awaited()


async def test_run_attempts_skips_reviewer_when_deterministic_verification_fails() -> None:
    runner = _make_runner()
    runner.reflection_engine.reflect = AsyncMock(
        return_value=SimpleNamespace(achieved=False, critique="retry with a different command")
    )
    runner.active_reviewer.review_progress = AsyncMock()

    failed_payload = {
        "status": "failure",
        "execution_log": [{"action": "run", "result": "failure"}],
        "metadata": {
            "verification": {
                "status": "failure",
                "summary": "command_exit_code expected 0 but observed 1.",
                "checks": [
                    {"kind": "command_exit_code", "status": "failure", "message": "command_exit_code expected 0 but observed 1."},
                ],
                "review_required": False,
            }
        },
    }

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = failed_payload
    agent_loop.last_attempt_payload = failed_payload
    agent_loop.act = AsyncMock(return_value="ERROR: command failed")

    with patch("orchestrator.execution_runner.classify", return_value=FailureKind.PERMANENT):
        achieved, final_result, attempt_count = await runner._run_attempts(
            "run the command",
            1,
            ExecutionContext(objective="run the command"),
            agent_loop,
        )

    assert achieved is False
    assert final_result == "ERROR: command failed"
    assert attempt_count == 1
    runner.active_reviewer.review_progress.assert_not_awaited()


async def test_run_attempts_calls_reviewer_when_deterministic_verification_is_unknown() -> None:
    runner = _make_runner()
    runner.reflection_engine.reflect = AsyncMock(
        return_value=SimpleNamespace(achieved=False, critique="wait for the UI to settle")
    )
    runner.active_reviewer.review_progress = AsyncMock(
        return_value=ReviewResult(
            status=ReviewStatus.CONTINUE,
            assessment="The app may still be loading",
            missing=["stable UI"],
            next_steps=["wait and re-check"],
            hints=[],
            alternative_strategies=[],
            confidence=0.6,
        )
    )

    unknown_payload = {
        "status": "success",
        "execution_log": [{"action": "open", "result": "success"}],
        "metadata": {
            "verification": {
                "status": "unknown",
                "summary": "Desktop execution may still be settling.",
                "checks": [],
                "review_required": True,
            }
        },
    }

    second_payload = {
        "status": "success",
        "execution_log": [{"action": "open", "result": "success"}],
        "metadata": {
            "verification": {
                "status": "success",
                "summary": "window_exists passed for Notepad.",
                "checks": [],
                "review_required": False,
            }
        },
    }

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    payloads = iter([unknown_payload, second_payload])
    results = iter(["first attempt", "second attempt"])

    async def _act(**_kwargs):
        payload = next(payloads)
        agent_loop.last_step_payload = payload
        agent_loop.last_attempt_payload = payload
        return next(results)

    agent_loop.act = AsyncMock(side_effect=_act)

    achieved, final_result, attempt_count = await runner._run_attempts(
        "open notepad",
        1,
        ExecutionContext(objective="open notepad"),
        agent_loop,
    )

    assert achieved is True
    assert final_result == "second attempt"
    assert attempt_count == 2
    runner.active_reviewer.review_progress.assert_awaited()


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


def test_get_completed_tasks_for_review_includes_backend_plan_context() -> None:
    runner = _make_runner()
    context = ExecutionContext(objective="read the page")
    context.backend_plan_state["objective_1"] = {
        "browser": {
            "revision": 3,
            "steps": [
                {"title": "Open site", "status": "done"},
                {"title": "Wait for page", "status": "in_progress"},
            ],
        }
    }

    completed = runner._get_completed_tasks_for_review(context, 1)

    assert any(task["description"] == "browser live plan" for task in completed)
    browser_plan = next(task for task in completed if task["description"] == "browser live plan")
    assert browser_plan["status"] == "running"
    assert "Wait for page" in browser_plan["result"]


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


def test_build_verification_checks_avoids_unverifiable_desktop_type_checks() -> None:
    checks = _build_verification_checks(
        {
            "action_type": "desktop",
            "parameters": {"action": "type", "app": "Notepad", "text": "hello"},
        },
        "Type hello in Notepad",
    )

    assert checks == []


async def test_attempt_phase_persists_backend_flight_report_path() -> None:
    runner = _make_runner()
    runner.checkpoint_manager.save_checkpoint = MagicMock(return_value="cp-1")
    runner._run_attempts = AsyncMock(return_value=(True, "done", 1))
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
    agent_loop.last_attempt_payload = agent_loop.last_step_payload

    result = await runner._attempt_phase(["step 1"], context, 0, agent_loop)

    assert result == ([(1, "step 1")], [])
    assert runner.history_manager.update_step_status.call_args.kwargs["flight_report_path"] == "C:/tmp/backend-report.json"


async def test_attempt_phase_updates_prompt_logging_objective_context() -> None:
    runner = _make_runner()
    runner.checkpoint_manager.save_checkpoint = MagicMock(return_value="cp-1")
    runner._run_attempts = AsyncMock(return_value=(True, "done", 1))
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


# ── TC-CLI-01 verifier-loop drift regression tests ──────────────────────


def test_stabilize_review_result_respects_completed_plan_state() -> None:
    """When all plan steps are done, _stabilize_review_result must NOT
    override a FAILED/PIVOT verdict to CONTINUE.  This was the root cause
    of the TC-CLI-01 verifier-loop drift."""
    from orchestrator.execution_runner import _stabilize_review_result

    failed_review = ReviewResult(
        status=ReviewStatus.FAILED,
        assessment="Objective not achieved",
        missing=["report file"],
        next_steps=[],
        hints=[],
        alternative_strategies=[],
        confidence=0.4,
    )

    completed_payload = {
        "metadata": {
            "plan_state": {
                "status": "complete",
                "steps": [
                    {"status": "success", "command": "dir"},
                    {"status": "success", "command": "echo report"},
                ],
            }
        }
    }

    result = _stabilize_review_result(
        review=failed_review,
        final_result="all done",
        step_payload=completed_payload,
        attempt=0,
        max_attempts=3,
    )

    assert result.status == ReviewStatus.FAILED, (
        "stabilizer must not override FAILED when plan_state steps are all completed"
    )


def test_stabilize_review_result_still_overrides_when_plan_unfinished() -> None:
    """When plan steps are still pending, the stabilizer SHOULD override
    FAILED to CONTINUE (existing behaviour for loading/unfinished plans)."""
    from orchestrator.execution_runner import _stabilize_review_result

    failed_review = ReviewResult(
        status=ReviewStatus.FAILED,
        assessment="window not found",
        missing=["Notepad window"],
        next_steps=[],
        hints=[],
        alternative_strategies=[],
        confidence=0.4,
    )

    unfinished_payload = {
        "metadata": {
            "plan_state": {
                "status": "in_progress",
                "steps": [
                    {"status": "success", "command": "open notepad"},
                    {"status": "pending", "command": "type text"},
                ],
            }
        }
    }

    result = _stabilize_review_result(
        review=failed_review,
        final_result="window_not_found",
        step_payload=unfinished_payload,
        attempt=0,
        max_attempts=3,
    )

    assert result.status == ReviewStatus.CONTINUE, (
        "stabilizer should override FAILED to CONTINUE when plan has unfinished steps"
    )


def test_cli_backend_success_is_verified_recognises_complete_plan_state() -> None:
    """_cli_backend_success_is_verified should return True when
    plan_state.status == 'complete', even if individual step statuses
    are not in the canonical completed set."""
    from orchestrator.execution_runner import _cli_backend_success_is_verified

    task_result = {"status": "success", "execution_log": []}
    backend_result = {
        "status": "success",
        "plan_state": {
            "status": "complete",
            "steps": [
                {"status": "success", "command": "dir", "verification": "passed"},
            ],
        },
    }

    assert _cli_backend_success_is_verified(task_result, backend_result) is True


async def test_active_reviewer_returns_failed_on_final_attempt_error() -> None:
    """When the LLM call raises on the final attempt, the reviewer must
    return FAILED instead of CONTINUE to prevent infinite drift."""
    from orchestrator.active_reviewer import ActiveReviewer

    broken_llm = MagicMock()
    broken_llm.call = AsyncMock(side_effect=RuntimeError("JSON parse error"))
    reviewer = ActiveReviewer(llm_provider=broken_llm)

    result = await reviewer.review_progress(
        objective="scan log files and write report",
        completed_tasks=[],
        world_state={},
        attempt=2,
        max_attempts=3,
    )

    assert result.status == ReviewStatus.FAILED, (
        "reviewer must return FAILED on final attempt when LLM call fails"
    )


async def test_active_reviewer_returns_continue_on_early_attempt_error() -> None:
    """When the LLM call raises on a non-final attempt, CONTINUE is still
    acceptable to allow retries."""
    from orchestrator.active_reviewer import ActiveReviewer

    broken_llm = MagicMock()
    broken_llm.call = AsyncMock(side_effect=RuntimeError("JSON parse error"))
    reviewer = ActiveReviewer(llm_provider=broken_llm)

    result = await reviewer.review_progress(
        objective="scan log files and write report",
        completed_tasks=[],
        world_state={},
        attempt=0,
        max_attempts=3,
    )

    assert result.status == ReviewStatus.CONTINUE, (
        "reviewer should return CONTINUE on early attempt errors to allow retry"
    )


async def test_run_attempts_exits_on_cli_backend_complete_plan_state() -> None:
    """TC-CLI-01 regression: when CLI backend returns success with
    plan_state.status='complete', the attempt loop must exit on the first
    attempt without calling the reviewer."""
    runner = _make_runner()
    runner.reflection_engine.reflect = AsyncMock(
        return_value=SimpleNamespace(achieved=False, critique="looks incomplete")
    )
    runner.active_reviewer.review_progress = AsyncMock()

    cli_complete_payload = {
        "status": "success",
        "execution_log": [{"action": "run", "result": "success"}],
        "metadata": {
            "raw_result": {
                "status": "success",
                "metadata": {
                    "module": "cli",
                    "raw_result": {
                        "status": "success",
                        "plan_state": {
                            "status": "complete",
                            "steps": [
                                {"status": "success", "verification": "passed"},
                                {"status": "success", "verification": "passed"},
                            ],
                        },
                    },
                },
            }
        },
    }

    agent_loop = MagicMock()
    agent_loop.cleanup_browser_session = AsyncMock()
    agent_loop.last_step_payload = cli_complete_payload
    agent_loop.last_attempt_payload = cli_complete_payload
    agent_loop.act = AsyncMock(return_value="report written successfully")

    achieved, final_result, attempt_count = await runner._run_attempts(
        "scan logs and write error report",
        1,
        ExecutionContext(objective="scan logs and write error report"),
        agent_loop,
    )

    assert achieved is True, "objective should be achieved on first attempt"
    assert attempt_count == 1, "should exit after one attempt"
    runner.active_reviewer.review_progress.assert_not_awaited()
