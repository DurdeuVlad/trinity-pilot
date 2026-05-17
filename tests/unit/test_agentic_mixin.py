"""Tests for AgenticWorkerMixin (Stories 2 and 3)."""
from __future__ import annotations

import asyncio

import pytest
from google.genai import types as genai_types

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.workers.agentic_mixin import (
    AgenticWorkerMixin,
    _finish_decl,
    _make_tool,
    _report_blocking_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.worker_result import WorkerResult


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------

class MockLLMProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = iter(responses)

    async def complete(self, messages, system="") -> LLMResponse:
        raise NotImplementedError

    async def complete_with_tools(self, messages, tools, system="") -> LLMResponse:
        return next(self._responses)


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------

class _ConcreteWorker(AgenticWorkerMixin, DomainWorker):
    def __init__(self, llm: LLMProvider) -> None:
        super().__init__(llm=llm)

    async def execute(self, spec: ObjectiveSpec):
        ...  # not used in mixin tests

    async def _dispatch_tool(self, tool_name, args, evidence):
        # finish and report_blocking are handled by base class
        if tool_name in ("finish", "report_blocking"):
            return await super()._dispatch_tool(tool_name, args, evidence)
        return f"ok: {tool_name}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**kwargs) -> ObjectiveSpec:
    defaults = dict(
        objective_id="obj-test",
        goal="test goal",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=[],
        evidence_bundle=[],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    defaults.update(kwargs)
    return ObjectiveSpec(**defaults)


def _finish_response(status="success", summary="done", token_count=0) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[{"name": "finish", "args": {"status": status, "summary": summary}}],
        token_count=token_count,
    )


def _domain_tool_response(tool_name="run_command", token_count=0) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[{"name": tool_name, "args": {"command": "ls"}}],
        token_count=token_count,
    )


def _text_response(content="thinking...", token_count=0) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], token_count=token_count)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_exits_on_finish_success():
    """AC-01: loop returns WorkerResult with status=success when finish tool is called."""
    llm = MockLLMProvider([_finish_response("success", "done")])
    worker = _ConcreteWorker(llm)
    result = await worker.run_loop(_spec(), {})
    assert result.status == "success"
    assert result.summary == "done"


@pytest.mark.asyncio
async def test_loop_raises_blocker_on_report_blocking():
    """AC-02: loop raises WorkerBlocker with partial_blocker status."""
    llm = MockLLMProvider([
        LLMResponse(
            content="",
            tool_calls=[{"name": "report_blocking", "args": {"reason": "file not found"}}],
        )
    ])
    worker = _ConcreteWorker(llm)
    with pytest.raises(WorkerBlocker) as exc_info:
        await worker.run_loop(_spec(), {})
    assert exc_info.value.result.status == "partial_blocker"
    assert "file not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_loop_enforces_max_steps():
    """AC-03: loop raises WorkerError after max_steps domain tool calls."""
    # Provide more responses than max_steps
    responses = [_domain_tool_response("run_command")] * 10
    llm = MockLLMProvider(responses)
    worker = _ConcreteWorker(llm)
    with pytest.raises(WorkerError, match="step budget exhausted"):
        await worker.run_loop(_spec(), {}, max_steps=3)


def test_shared_tool_schemas_are_valid():
    """AC-10: _make_tool constructs a valid genai_types.Tool without error."""
    tool = _make_tool([_finish_decl, _report_blocking_decl])
    assert isinstance(tool, genai_types.Tool)


@pytest.mark.asyncio
async def test_loop_handles_empty_text_response_without_tool():
    """Text-only response (no tool call) causes loop to continue, then finish."""
    llm = MockLLMProvider([
        _text_response("thinking..."),
        _finish_response("success", "done after thinking"),
    ])
    worker = _ConcreteWorker(llm)
    result = await worker.run_loop(_spec(), {}, max_steps=5)
    assert result.status == "success"
    assert result.summary == "done after thinking"


@pytest.mark.asyncio
async def test_loop_raises_on_fully_empty_llm_response():
    """Fully empty first response (no tool calls, no content) raises WorkerError."""
    llm = MockLLMProvider([LLMResponse(content="", tool_calls=[])])
    worker = _ConcreteWorker(llm)
    with pytest.raises(WorkerError):
        await worker.run_loop(_spec(), {})


@pytest.mark.asyncio
async def test_loop_recovers_from_empty_response_after_tool_call():
    """An empty turn after a tool call gets a bounded nudge, then can finish."""
    llm = MockLLMProvider([
        _domain_tool_response("run_command"),
        LLMResponse(content="", tool_calls=[]),
        _finish_response("success", "done after empty turn"),
    ])
    worker = _ConcreteWorker(llm)
    result = await worker.run_loop(_spec(), {}, max_steps=5)
    assert result.status == "success"
    assert result.summary == "done after empty turn"


@pytest.mark.asyncio
async def test_loop_accumulates_token_count():
    """Token counts from each step are accumulated in the result."""
    llm = MockLLMProvider([
        _domain_tool_response("run_command", token_count=10),
        _finish_response("success", "done", token_count=10),
    ])
    worker = _ConcreteWorker(llm)
    result = await worker.run_loop(_spec(), {}, max_steps=5)
    assert result.tokens_used == 20


@pytest.mark.asyncio
async def test_worker_step_signal_emitted_per_step():
    """WorkerStepSignal is emitted once per domain tool call."""
    llm = MockLLMProvider([
        _domain_tool_response("run_command"),
        _finish_response("success", "done"),
    ])
    worker = _ConcreteWorker(llm)
    q: asyncio.Queue = asyncio.Queue()
    result = await worker.run_loop(_spec(), {}, signals=q, max_steps=5)
    assert result.status == "success"
    assert q.qsize() == 1
    sig = q.get_nowait()
    from trinity_pilot.orchestrator.signals import WorkerStepSignal
    assert isinstance(sig, WorkerStepSignal)
    assert sig.tool_name == "run_command"
