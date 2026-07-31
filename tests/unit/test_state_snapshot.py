"""Unit tests for _worker_state_snapshot continuous state injection (AC-01 to AC-07)."""
from __future__ import annotations

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
    # Second call receives messages including the tool_result with STATE
    assert len(llm.sent_messages) >= 2
    second_call_messages = llm.sent_messages[1]
    # tool_result role carries the observation JSON
    import json as _json
    tool_results = [m for m in second_call_messages if m.role == "tool_result"]
    assert tool_results, "No tool_result message found"
    result_content = _json.loads(tool_results[-1].content).get("result", "")
    assert "[STATE]" in result_content


# AC-03: empty snapshot does not inject [STATE]
@pytest.mark.asyncio
async def test_no_state_injected_when_snapshot_empty():
    llm = _RunThenFinishLLM()
    worker = TerminalWorker(llm=llm)
    with patch.object(worker, "_worker_state_snapshot", return_value=""):
        spec = _spec("run `echo hi`")
        await worker.execute(spec)
    import json as _json
    second_call_messages = llm.sent_messages[1]
    tool_results = [m for m in second_call_messages if m.role == "tool_result"]
    assert tool_results
    result_content = _json.loads(tool_results[-1].content).get("result", "")
    assert "[STATE]" not in result_content


# AC-04: TerminalWorker snapshot has required fields including file names
def test_terminal_snapshot_fields():
    w = TerminalWorker(llm=_FinishLLM())
    evidence = {
        "workspace": "C:/tmp/ws",
        "exit_code": 0,
        "action_log": ["run_command: exit=0 cmd=echo hi"],
        "stdout": "hi",
        "stderr": "",
    }
    snap = w._worker_state_snapshot(evidence)
    assert "workspace=C:/tmp/ws" in snap
    assert "exit_code=0" in snap
    assert "files=[" in snap          # names list, not count
    assert "last_action=" in snap


# AC-08: Terminal snapshot includes last_stdout when stdout non-empty
def test_terminal_snapshot_includes_stdout():
    w = TerminalWorker(llm=_FinishLLM())
    evidence = {
        "workspace": "",
        "exit_code": 0,
        "action_log": [],
        "stdout": "hello world",
        "stderr": "",
    }
    snap = w._worker_state_snapshot(evidence)
    assert "last_stdout=" in snap
    assert "hello world" in snap


# AC-09: Terminal snapshot omits last_stdout when stdout empty
def test_terminal_snapshot_omits_empty_stdout():
    w = TerminalWorker(llm=_FinishLLM())
    evidence = {
        "workspace": "",
        "exit_code": None,
        "action_log": [],
        "stdout": "",
        "stderr": "",
    }
    snap = w._worker_state_snapshot(evidence)
    assert "last_stdout" not in snap
    assert "last_stderr" not in snap


# AC-10: Terminal snapshot caps file list at 20 with overflow indicator
def test_terminal_snapshot_file_cap():
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(25):
            open(os.path.join(tmp, f"file{i:02d}.txt"), "w").close()
        w = TerminalWorker(llm=_FinishLLM())
        evidence = {"workspace": tmp, "exit_code": None, "action_log": [], "stdout": "", "stderr": ""}
        snap = w._worker_state_snapshot(evidence)
    assert "...+5 more]" in snap


# AC-05: BrowserWorker snapshot has URL, title, and HTTP status
def test_browser_snapshot_fields():
    w = BrowserWorker(llm=_FinishLLM())
    evidence = {
        "page_url": "https://example.com",
        "page_title": "Example Domain",
        "page_http_status": 200,
    }
    snap = w._worker_state_snapshot(evidence)
    assert "current_url=https://example.com" in snap
    assert "page_title=Example Domain" in snap
    assert "page_status=200" in snap


# AC-05b: BrowserWorker snapshot defaults to about:blank / unknown / unknown status
def test_browser_snapshot_defaults():
    w = BrowserWorker(llm=_FinishLLM())
    snap = w._worker_state_snapshot({})
    assert "about:blank" in snap
    assert "unknown" in snap
    assert "page_status=unknown" in snap


# AC-06: DesktopWorker snapshot has active_window, open_windows, and last_action
def test_desktop_snapshot_fields():
    w = DesktopWorker(llm=_FinishLLM())
    evidence = {"action_log": ["Launched: notepad.exe"]}
    with patch.object(DesktopWorker, "_get_active_window_title", return_value="Notepad"), \
         patch.object(DesktopWorker, "_get_open_windows", return_value=["Notepad", "Task Manager"]):
        snap = w._worker_state_snapshot(evidence)
    assert "active_window=" in snap
    assert "Notepad" in snap
    assert "open_windows=" in snap
    assert "Task Manager" in snap
    assert "last_action=Launched: notepad.exe" in snap


# AC-11: DesktopWorker _get_open_windows returns empty list on non-Windows (no ctypes.windll)
def test_desktop_get_open_windows_safe_on_non_windows():
    with patch("ctypes.windll", side_effect=AttributeError("no windll")):
        result = DesktopWorker._get_open_windows()
    assert result == []


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
