"""Tests for OrchestratorAnalyser (Story 8) and engine integration (Story 9)."""
from __future__ import annotations

import asyncio

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.orchestrator.analyser import OrchestratorAnalyser, SteerDecision


# ---------------------------------------------------------------------------
# Mock LLM for analyser tests
# ---------------------------------------------------------------------------

class MockAnalyserLLM(LLMProvider):
    def __init__(self, response_json: str) -> None:
        self._json = response_json
        self.complete_calls = 0

    async def complete(self, messages, system="", **kwargs) -> LLMResponse:
        self.complete_calls += 1
        return LLMResponse(content=self._json)

    async def complete_with_tools(self, messages, tools, system="", **kwargs) -> LLMResponse:
        raise NotImplementedError


class FailingLLM(LLMProvider):
    async def complete(self, messages, system="", **kwargs) -> LLMResponse:
        raise RuntimeError("LLM unavailable")

    async def complete_with_tools(self, messages, tools, system="", **kwargs) -> LLMResponse:
        raise NotImplementedError


def _spec(risk_class: RiskClass = RiskClass.LOW) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-analyser",
        goal="do something complex",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=risk_class,
        preconditions=[],
        success_tests=[],
        evidence_bundle=[],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )


# ---------------------------------------------------------------------------
# Story 8: OrchestratorAnalyser unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyser_returns_auto_steer():
    """AC-05: analyser returns auto_steer with guidance when LLM says so."""
    llm = MockAnalyserLLM('{"action": "auto_steer", "guidance": "try with sudo", "question": ""}')
    analyser = OrchestratorAnalyser(llm)
    decision = await analyser.analyse(_spec(), [], "permission denied")
    assert decision.action == "auto_steer"
    assert decision.guidance == "try with sudo"


@pytest.mark.asyncio
async def test_analyser_returns_ask_user():
    """Analyser returns ask_user with question when LLM says so."""
    llm = MockAnalyserLLM('{"action": "ask_user", "guidance": "", "question": "What credentials?"}')
    analyser = OrchestratorAnalyser(llm)
    decision = await analyser.analyse(_spec(), [], "missing credentials")
    assert decision.action == "ask_user"
    assert decision.question == "What credentials?"


@pytest.mark.asyncio
async def test_analyser_falls_back_on_llm_failure():
    """When LLM raises, analyser returns auto_steer with blocker reason."""
    analyser = OrchestratorAnalyser(FailingLLM())
    decision = await analyser.analyse(_spec(), [], "some blocker")
    assert decision.action == "auto_steer"
    assert decision.guidance == "some blocker"


@pytest.mark.asyncio
async def test_analyser_falls_back_on_parse_failure():
    """When LLM returns non-JSON, analyser returns auto_steer."""
    llm = MockAnalyserLLM("not json at all")
    analyser = OrchestratorAnalyser(llm)
    decision = await analyser.analyse(_spec(), [], "some blocker")
    assert decision.action == "auto_steer"


@pytest.mark.asyncio
async def test_analyser_high_risk_asks_user_without_llm():
    """HIGH risk is a deterministic human gate, not an LLM judgment."""
    llm = MockAnalyserLLM('{"action": "auto_steer", "guidance": "ignore risk", "question": ""}')
    analyser = OrchestratorAnalyser(llm)

    decision = await analyser.analyse(_spec(RiskClass.HIGH), [], "dangerous blocker")

    assert decision.action == "ask_user"
    assert "dangerous blocker" in decision.question
    assert llm.complete_calls == 0


# ---------------------------------------------------------------------------
# Story 9: Engine integration test for ask_user path
# ---------------------------------------------------------------------------

def _make_settings():
    from trinity_pilot.config import Settings
    return Settings(gemini_api_key="fake-key")


def _engine_spec():
    return ObjectiveSpec(
        objective_id="obj-stuck",
        goal="do something",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=[],
        evidence_bundle=[],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )


class _BlockerWorker:
    async def execute(self, spec):
        from trinity_pilot.workers.base import WorkerBlocker
        from trinity_pilot.workers.worker_result import WorkerResult
        raise WorkerBlocker("stuck here", WorkerResult(status="partial_blocker"))


class _Reviewer:
    def __init__(self, provider):
        pass

    async def review(self, spec, evidence):
        from trinity_pilot.core.types import ReviewResult
        return ReviewResult(passed=True, notes="ok")


@pytest.mark.asyncio
async def test_engine_emits_stuck_signal_on_ask_user(tmp_path, monkeypatch):
    """AC-06: engine emits StuckSignal and returns failure_reason=blocker_needs_user_input."""
    import trinity_pilot.orchestrator.engine as engine_mod
    from trinity_pilot.orchestrator.engine import AsyncTaskOrchestrator
    from trinity_pilot.orchestrator.signals import StuckSignal

    worker = _BlockerWorker()
    ask_user_analyser_json = '{"action": "ask_user", "guidance": "", "question": "What file?"}'

    monkeypatch.setattr(engine_mod, "GeminiProvider", lambda **kwargs: object())
    monkeypatch.setattr(engine_mod, "ObjectiveReviewer", _Reviewer)
    monkeypatch.setattr(engine_mod.WorkerRouter, "route", lambda self, spec: worker)
    monkeypatch.setattr(
        engine_mod, "OrchestratorAnalyser",
        lambda llm: OrchestratorAnalyser(MockAnalyserLLM(ask_user_analyser_json))
    )

    db_path = tmp_path / "state.db"
    orchestrator = AsyncTaskOrchestrator(
        _make_settings(),
        db_path=str(db_path),
    )

    spec = _engine_spec()
    result = await orchestrator.run("do something", task_id="task-ask-user", objectives=[spec])

    assert result["status"] == "failed"
    obj_result = result.get("results", {}).get("obj-stuck", {})
    assert obj_result.get("failure_reason") == "blocker_needs_user_input"

    signals = []
    while not orchestrator.signals.empty():
        signals.append(orchestrator.signals.get_nowait())
    assert any(isinstance(s, StuckSignal) for s in signals)
