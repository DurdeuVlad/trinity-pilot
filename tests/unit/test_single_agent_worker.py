"""SingleAgentWorker unit tests — ablation baseline, mock LLM for the ReAct loop."""
from __future__ import annotations

from pathlib import Path

import pytest

from trinity_pilot.llm.base import LLMProvider, LLMResponse
from trinity_pilot.workers.single_agent_worker import SingleAgentWorker


class _MockLLM(LLMProvider):
    def __init__(self, responses):
        self._responses = iter(responses)

    async def complete(self, messages, system="", **kwargs):
        raise NotImplementedError

    async def complete_with_tools(self, messages, tools, system="", **kwargs):
        return next(self._responses)

    @property
    def model(self):
        return "mock"


def _finish(status="success", summary="done"):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "finish", "args": {"status": status, "summary": summary}}],
    )


def _write_file(path, content):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": path, "content": content}}],
    )


def _run_command(command):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "run_command", "args": {"command": command}}],
    )


@pytest.mark.asyncio
async def test_execute_raw_write_file_then_finish(tmp_path: Path):
    target = tmp_path / "out.txt"
    llm = _MockLLM([
        _write_file(str(target), "hello sa"),
        _finish("success", "wrote the file"),
    ])
    worker = SingleAgentWorker(llm=llm)
    result = await worker.execute_raw("write a file", max_steps=5)

    assert result.status == "success"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello sa"
    assert str(target) in result.evidence.get("created_files", [])
    assert not result.evidence.get("write_file_failures")


@pytest.mark.asyncio
async def test_execute_raw_run_command_then_finish():
    llm = _MockLLM([
        _run_command("echo hello"),
        _finish("success", "ran command"),
    ])
    worker = SingleAgentWorker(llm=llm)
    result = await worker.execute_raw("run a command", max_steps=5)

    assert result.status == "success"
    assert result.evidence.get("exit_code") == 0
    assert "hello" in (result.evidence.get("stdout") or "")


@pytest.mark.asyncio
async def test_execute_raw_failure_returns_failure_result():
    llm = _MockLLM([
        _finish("failure", "could not do it"),
    ])
    worker = SingleAgentWorker(llm=llm)
    result = await worker.execute_raw("do something impossible", max_steps=5)

    assert result.status == "failure"
    assert result.summary == "could not do it"


@pytest.mark.asyncio
async def test_execute_wraps_objective_spec(tmp_path: Path):
    from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass

    target = tmp_path / "spec_out.txt"
    llm = _MockLLM([
        _write_file(str(target), "via spec"),
        _finish("success", "done via spec"),
    ])
    worker = SingleAgentWorker(llm=llm)
    spec = ObjectiveSpec(
        objective_id="obj-1",
        goal="write a file via spec",
        dependencies=[],
        domain=DomainType.MIXED,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=[],
        evidence_bundle=["action_log"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
        metadata={"max_agent_steps": 5},
    )
    evidence = await worker.execute(spec)

    assert evidence["worker_result_status"] == "success"
    assert evidence["objective_id"] == "obj-1"
    assert target.exists()
