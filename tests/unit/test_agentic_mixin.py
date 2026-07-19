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
    def __init__(
        self,
        responses: list[LLMResponse],
        reflection_responses: list[LLMResponse] | None = None,
    ) -> None:
        self._responses = iter(responses)
        self._reflection_responses = iter(reflection_responses or [])
        self.reflection_calls: list[list[LLMMessage]] = []
        self.tool_messages: list[list[LLMMessage]] = []

    async def complete(self, messages, system="") -> LLMResponse:
        self.reflection_calls.append(messages)
        return next(self._reflection_responses)

    async def complete_with_tools(self, messages, tools, system="") -> LLMResponse:
        self.tool_messages.append(list(messages))
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


def _domain_tool_response(
    tool_name="run_command",
    token_count=0,
    args: dict | None = None,
) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[{"name": tool_name, "args": args or {"command": "ls"}}],
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
    """AC-03: loop returns failure after max_steps domain tool calls."""
    # Provide more responses than max_steps
    responses = [_domain_tool_response("run_command")] * 10
    llm = MockLLMProvider(responses)
    worker = _ConcreteWorker(llm)
    result = await worker.run_loop(_spec(), {}, max_steps=3)
    assert result.status == "failure"
    assert "step budget exhausted" in result.summary


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
async def test_loop_recovers_from_empty_response_at_step_zero():
    """A fully empty first response (e.g. Gemini MALFORMED_FUNCTION_CALL) gets a
    bounded nudge and retries instead of hard-failing immediately."""
    llm = MockLLMProvider([
        LLMResponse(content="", tool_calls=[]),
        _finish_response("success", "done after empty first turn"),
    ])
    worker = _ConcreteWorker(llm)
    result = await worker.run_loop(_spec(), {}, max_steps=5)
    assert result.status == "success"
    assert result.summary == "done after empty first turn"


@pytest.mark.asyncio
async def test_loop_exhausts_budget_on_all_empty_responses():
    """If every turn is empty, the loop returns a failure result once max_steps
    is exhausted rather than looping forever or raising."""
    llm = MockLLMProvider([LLMResponse(content="", tool_calls=[]) for _ in range(5)])
    worker = _ConcreteWorker(llm)
    result = await worker.run_loop(_spec(), {}, max_steps=3)
    assert result.status == "failure"
    assert "step budget exhausted" in result.summary


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


@pytest.mark.asyncio
async def test_mid_episode_reflection_default_off_on_repeated_call():
    llm = MockLLMProvider([
        _domain_tool_response("run_command"),
        _domain_tool_response("run_command"),
        _finish_response("success", "done"),
    ])
    worker = _ConcreteWorker(llm)

    result = await worker.run_loop(_spec(), {}, max_steps=5)

    assert result.status == "success"
    assert llm.reflection_calls == []
    third_call_messages = llm.tool_messages[2]
    tool_result = third_call_messages[-1]
    assert "REPEATED CALL" in tool_result.content
    assert "LIVE REFLECTION" not in tool_result.content


@pytest.mark.asyncio
async def test_mid_episode_reflection_opt_in_fires_once_on_second_identical_call():
    llm = MockLLMProvider(
        [
            _domain_tool_response("run_command"),
            _domain_tool_response("run_command"),
            _finish_response("success", "done"),
        ],
        reflection_responses=[
            LLMResponse(content="Try inspecting the directory before running ls again.")
        ],
    )
    worker = _ConcreteWorker(llm)
    evidence: dict = {}

    result = await worker.run_loop(
        _spec(metadata={"mid_episode_reflection": True}),
        evidence,
        max_steps=5,
    )

    assert result.status == "success"
    assert len(llm.reflection_calls) == 1
    third_call_messages = llm.tool_messages[2]
    tool_result = third_call_messages[-1]
    assert "REPEATED CALL" in tool_result.content
    assert "LIVE REFLECTION: Try inspecting the directory" in tool_result.content
    assert evidence["llm_transcript"][1]["mid_episode_reflection"] is True


@pytest.mark.asyncio
async def test_mid_episode_reflection_ignores_first_call_before_warning():
    llm = MockLLMProvider([
        _domain_tool_response("run_command"),
        _finish_response("success", "done"),
    ])
    worker = _ConcreteWorker(llm)

    result = await worker.run_loop(
        _spec(metadata={"mid_episode_reflection": True}),
        {},
        max_steps=5,
    )

    assert result.status == "success"
    assert llm.reflection_calls == []


@pytest.mark.asyncio
async def test_mid_episode_reflection_truncates_injected_text():
    long_suggestion = "x" * 5000
    llm = MockLLMProvider(
        [
            _domain_tool_response("run_command"),
            _domain_tool_response("run_command"),
            _finish_response("success", "done"),
        ],
        reflection_responses=[LLMResponse(content=long_suggestion)],
    )
    worker = _ConcreteWorker(llm)

    result = await worker.run_loop(
        _spec(metadata={"mid_episode_reflection": True}),
        {},
        max_steps=5,
    )

    assert result.status == "success"
    tool_result = llm.tool_messages[2][-1].content
    assert f"LIVE REFLECTION: {'x' * 3000}" in tool_result
    assert "x" * 3001 not in tool_result


@pytest.mark.asyncio
async def test_third_identical_call_still_hard_blocks_with_reflection_enabled():
    llm = MockLLMProvider(
        [
            _domain_tool_response("run_command"),
            _domain_tool_response("run_command"),
            _domain_tool_response("run_command"),
            _finish_response("success", "done"),
        ],
        reflection_responses=[
            LLMResponse(content="Try a different command before repeating.")
        ],
    )
    worker = _ConcreteWorker(llm)

    result = await worker.run_loop(
        _spec(metadata={"mid_episode_reflection": True}),
        {},
        max_steps=5,
    )

    assert result.status == "success"
    assert len(llm.reflection_calls) == 1
    finish_call_messages = llm.tool_messages[3]
    blocked_result = finish_call_messages[-1]
    assert "BLOCKED" in blocked_result.content
    assert "called with identical arguments 3 times" in blocked_result.content


@pytest.mark.asyncio
async def test_worker_result_records_sanitized_tool_log():
    worker = _ConcreteWorker(MockLLMProvider([
        _domain_tool_response("run_command", args={"command": "echo hello"}),
        _finish_response("success", "done"),
    ]))
    evidence: dict = {}
    result = await worker.run_loop(_spec(), evidence, max_steps=3)

    assert [record.tool for record in result.tool_call_log] == ["run_command", "finish"]
    assert result.tool_call_log[0].args == {"command": "echo hello"}
    assert "llm_text" not in result.tool_call_log[0].result
    assert evidence["tool_call_log"][0]["tool"] == "run_command"
