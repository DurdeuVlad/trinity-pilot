"""Unit tests for _worker_state_snapshot continuous state injection (AC-01 to AC-07)."""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.workers.agentic_mixin import AgenticWorkerMixin
from trinity_pilot.workers.base import DomainWorker
from trinity_pilot.workers.browser_worker import BrowserWorker
from trinity_pilot.workers.desktop_worker import DesktopWorker
from trinity_pilot.workers.terminal_worker import TerminalWorker


def _spec(goal: str = "test") -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="snap-test",
        goal=goal,
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=[],
        evidence_bundle=[],
        max_attempts=1,
        rollback_or_abort_rule="abort",
        metadata={},
    )


class _FinishLLM(LLMProvider):
    """Returns finish(success) immediately."""
    async def complete(self, messages, system="", **kw) -> LLMResponse:
        return LLMResponse(content="")
    async def complete_with_tools(self, messages, tools, system="", **kw) -> LLMResponse:
        return LLMResponse(content="", tool_calls=[{"name": "finish", "args": {"status": "success", "summary": "done"}}])


class _RunThenFinishLLM(LLMProvider):
    """Returns run_command on step 1, finish on step 2. Captures sent messages."""
    def __init__(self):
        self.sent_messages: list[list[LLMMessage]] = []
    async def complete(self, messages, system="", **kw) -> LLMResponse:
        return LLMResponse(content="")
    async def complete_with_tools(self, messages, tools, system="", **kw) -> LLMResponse:
        self.sent_messages.append(list(messages))
        if len(self.sent_messages) == 1:
            return LLMResponse(content="", tool_calls=[{"name": "run_command", "args": {"command": "echo hi"}}])
        return LLMResponse(content="", tool_calls=[{"name": "finish", "args": {"status": "success", "summary": "done"}}])


# AC-01: base class _worker_state_snapshot returns ""
def test_base_state_snapshot_returns_empty():
    class _ConcreteWorker(AgenticWorkerMixin, DomainWorker):
        async def execute(self, spec): ...
        async def _dispatch_tool(self, tool_name, args, evidence): return "obs"
    w = _ConcreteWorker(llm=_FinishLLM())
    assert w._worker_state_snapshot({}) == ""


# AC-02: non-empty snapshot appears as [STATE] block in next user message
@pytest.mark.asyncio
async def test_state_appended_to_observation_when_non_empty():
    llm = _RunThenFinishLLM()
    worker = TerminalWorker(llm=llm)
    spec = _spec("run `echo hi`")
    await worker.execute(spec)
    # Second call to complete_with_tools receives messages including the observation
    assert len(llm.sent_messages) >= 2
    second_call_messages = llm.sent_messages[1]
    obs_messages = [m for m in second_call_messages if m.role == "user" and "[observation]" in m.content]
    assert obs_messages, "No observation message found"
    assert "[STATE]" in obs_messages[-1].content


# AC-03: empty snapshot does not inject [STATE]
@pytest.mark.asyncio
async def test_no_state_injected_when_snapshot_empty():
    llm = _RunThenFinishLLM()
    worker = TerminalWorker(llm=llm)
    # Patch _worker_state_snapshot to return ""
    with patch.object(worker, "_worker_state_snapshot", return_value=""):
        spec = _spec("run `echo hi`")
        await worker.execute(spec)
    second_call_messages = llm.sent_messages[1]
    obs_messages = [m for m in second_call_messages if m.role == "user" and "[observation]" in m.content]
    assert obs_messages
    assert "[STATE]" not in obs_messages[-1].content


# AC-04: TerminalWorker snapshot has required fields
def test_terminal_snapshot_fields():
    w = TerminalWorker(llm=_FinishLLM())
    evidence = {
        "workspace": "C:/tmp/ws",
        "exit_code": 0,
        "action_log": ["run_command: exit=0 cmd=echo hi"],
        "stdout": "hi",
    }
    snap = w._worker_state_snapshot(evidence)
    assert "workspace=C:/tmp/ws" in snap
    assert "exit_code=0" in snap
    assert "files_in_workspace=" in snap
    assert "last_action=" in snap


# AC-05: BrowserWorker snapshot has URL and title
def test_browser_snapshot_fields():
    w = BrowserWorker(llm=_FinishLLM())
    evidence = {"page_url": "https://example.com", "page_title": "Example Domain"}
    snap = w._worker_state_snapshot(evidence)
    assert "current_url=https://example.com" in snap
    assert "page_title=Example Domain" in snap


# AC-05b: BrowserWorker snapshot defaults to about:blank when no URL
def test_browser_snapshot_defaults():
    w = BrowserWorker(llm=_FinishLLM())
    snap = w._worker_state_snapshot({})
    assert "about:blank" in snap
    assert "unknown" in snap


# AC-06: DesktopWorker snapshot has active_window and last_action
def test_desktop_snapshot_fields():
    w = DesktopWorker(llm=_FinishLLM())
    evidence = {"action_log": ["Launched: notepad.exe"]}
    with patch.object(DesktopWorker, "_get_active_window_title", return_value="Notepad"):
        snap = w._worker_state_snapshot(evidence)
    assert "active_window=" in snap
    assert "Notepad" in snap
    assert "last_action=Launched: notepad.exe" in snap


# AC-07: finish tool exits loop before snapshot is called
@pytest.mark.asyncio
async def test_finish_exits_before_snapshot():
    llm = _FinishLLM()
    worker = TerminalWorker(llm=llm)
    snapshot_called = []
    original = worker._worker_state_snapshot
    def tracking_snapshot(evidence):
        snapshot_called.append(True)
        return original(evidence)
    with patch.object(worker, "_worker_state_snapshot", side_effect=tracking_snapshot):
        await worker.execute(_spec())
    assert not snapshot_called, "snapshot should not be called on finish"
