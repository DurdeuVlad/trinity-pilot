"""Integration tests: agentic worker handoff and escalation paths.

Four critical paths:
  1. Blocker -> auto_steer -> success
  2. Blocker -> ask_user -> StuckSignal emitted
  3. Multi-step loop -> WorkerStepSignals emitted per domain tool
  4. Worker definitive failure -> reviewer skipped, no retry
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trinity_pilot.config import Settings
from trinity_pilot.core.types import (
    DomainType,
    ObjectiveSpec,
    ReviewResult,
    RiskClass,
)
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.orchestrator.analyser import SteerDecision
from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator
from trinity_pilot.orchestrator.signals import StuckSignal, WorkerStepSignal
from trinity_pilot.workers.terminal_worker import TerminalWorker


_SETTINGS = Settings(gemini_api_key="fake-key-for-tests", db_path=":memory:")


def _spec(objective_id: str = "obj", max_attempts: int = 3) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id=objective_id,
        goal="echo hello",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["stdout contains hello"],
        evidence_bundle=["stdout"],
        max_attempts=max_attempts,
        rollback_or_abort_rule="abort",
        metadata={},
    )


class _SeqLLM(LLMProvider):
    """Returns LLMResponse objects in sequence."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._iter = iter(responses)

    async def complete(self, messages: list[LLMMessage], system: str = "", **kwargs) -> LLMResponse:
        return LLMResponse(content="")

    async def complete_with_tools(self, messages, tools, system="", **kwargs) -> LLMResponse:
        return next(self._iter)


def _tool_call(name: str, **args: object) -> LLMResponse:
    return LLMResponse(content="", tool_calls=[{"name": name, "args": args}])


def _finish(status: str = "success") -> LLMResponse:
    return _tool_call("finish", status=status, summary="done")


def _blocker(reason: str = "need external help") -> LLMResponse:
    return _tool_call("report_blocking", reason=reason)


def _run_cmd(cmd: str = "echo hello") -> LLMResponse:
    return _tool_call("run_command", command=cmd)


def _mock_reviewer(passed: bool = True) -> MagicMock:
    r = MagicMock()
    r.review = AsyncMock(
        return_value=ReviewResult(passed=passed, failure_reason=None, notes="ok", recovery_hint="")
    )
    return r


def _drain(q) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


class TestAgenticHandoff:

    @pytest.mark.asyncio
    async def test_blocker_auto_steer_then_success(self):
        """Attempt 1 raises WorkerBlocker; analyser returns auto_steer; attempt 2 succeeds."""
        llm = _SeqLLM([_blocker(), _run_cmd(), _finish()])
        worker = TerminalWorker(llm=llm)

        mock_analyser = MagicMock()
        mock_analyser.analyse = AsyncMock(
            return_value=SteerDecision(action="auto_steer", guidance="retry with echo hello")
        )

        orch = AsyncTaskOrchestrator(_SETTINGS, db_path=":memory:")
        orch._router.route = MagicMock(return_value=worker)

        with patch("trinity_pilot.orchestrator.engine.GeminiProvider"):
            with patch("trinity_pilot.orchestrator.engine.ObjectiveReviewer", return_value=_mock_reviewer()):
                with patch("trinity_pilot.orchestrator.engine.OrchestratorAnalyser", return_value=mock_analyser):
                    result = await orch.run("echo hello", objectives=[_spec()])

        assert result["status"] == "completed"
        assert result["results"]["obj"]["status"] == "passed"
        mock_analyser.analyse.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocker_ask_user_emits_stuck_signal(self):
        """WorkerBlocker + ask_user -> StuckSignal in queue, failure_reason=blocker_needs_user_input."""
        llm = _SeqLLM([_blocker("missing credentials")])
        worker = TerminalWorker(llm=llm)

        mock_analyser = MagicMock()
        mock_analyser.analyse = AsyncMock(
            return_value=SteerDecision(
                action="ask_user",
                question="What credentials should I use to connect?",
            )
        )

        orch = AsyncTaskOrchestrator(_SETTINGS, db_path=":memory:")
        orch._router.route = MagicMock(return_value=worker)

        with patch("trinity_pilot.orchestrator.engine.GeminiProvider"):
            with patch("trinity_pilot.orchestrator.engine.ObjectiveReviewer"):
                with patch("trinity_pilot.orchestrator.engine.OrchestratorAnalyser", return_value=mock_analyser):
                    result = await orch.run("echo hello", objectives=[_spec(max_attempts=1)])

        assert result["results"]["obj"]["failure_reason"] == "blocker_needs_user_input"

        signals = _drain(orch.signals)
        stuck = [s for s in signals if isinstance(s, StuckSignal)]
        assert len(stuck) == 1
        assert stuck[0].reason == "worker_blocker"
        assert "credentials" in stuck[0].user_question

    @pytest.mark.asyncio
    async def test_multi_step_loop_emits_worker_step_signals(self):
        """Two run_command calls emit two WorkerStepSignals before finish."""
        llm = _SeqLLM([_run_cmd("echo step1"), _run_cmd("echo step2"), _finish()])
        worker = TerminalWorker(llm=llm)

        orch = AsyncTaskOrchestrator(_SETTINGS, db_path=":memory:")
        orch._router.route = MagicMock(return_value=worker)

        with patch("trinity_pilot.orchestrator.engine.GeminiProvider"):
            with patch("trinity_pilot.orchestrator.engine.ObjectiveReviewer", return_value=_mock_reviewer()):
                with patch("trinity_pilot.orchestrator.engine.OrchestratorAnalyser"):
                    result = await orch.run("echo hello", objectives=[_spec()])

        assert result["status"] == "completed"

        signals = _drain(orch.signals)
        step_sigs = [s for s in signals if isinstance(s, WorkerStepSignal)]
        assert len(step_sigs) == 2
        assert all(s.tool_name == "run_command" for s in step_sigs)

    @pytest.mark.asyncio
    async def test_worker_definitive_failure_skips_reviewer(self):
        """finish(status=failure) -> engine skips reviewer, no retry, worker_declared_failure."""
        llm = _SeqLLM([_finish("failure")])
        worker = TerminalWorker(llm=llm)

        mock_reviewer = _mock_reviewer()

        orch = AsyncTaskOrchestrator(_SETTINGS, db_path=":memory:")
        orch._router.route = MagicMock(return_value=worker)

        with patch("trinity_pilot.orchestrator.engine.GeminiProvider"):
            with patch("trinity_pilot.orchestrator.engine.ObjectiveReviewer", return_value=mock_reviewer):
                with patch("trinity_pilot.orchestrator.engine.OrchestratorAnalyser"):
                    result = await orch.run("echo hello", objectives=[_spec(max_attempts=3)])

        assert result["results"]["obj"]["failure_reason"] == "worker_declared_failure"
        mock_reviewer.review.assert_not_called()
