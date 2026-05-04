from __future__ import annotations

import sys
from pathlib import Path

import pytest

from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.sub_objective_executor import SubObjectiveExecutor
from trinity_core.models import TaskInput
from trinity_core.strategy_registry import MCPStrategy, PromptContribution
from trinity_core.tools.base import ToolResult
from trinity_core.tools.base import Tool


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    async def call(self, messages, tools):
        self.calls += 1
        self.messages.append(messages)
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="inspect_state", arguments={})])
        return LLMResponse(text="done")


class _FakeMutatingTool(Tool):
    def name(self) -> str:
        return "hotkey"

    def description(self) -> str:
        return "Fake mutating hotkey."

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def annotations(self) -> dict:
        return {"readOnlyHint": False}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", output="ok")


@pytest.mark.asyncio
async def test_sub_objective_executor_exposes_full_visible_tool_catalog():
    strategy = MCPStrategy(
        strategy_id="fake",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="web",
        display_name="Fake",
        description="Fake strategy",
        prompt_contribution=PromptContribution(
            tool_guidance=["Every visible tool is available to the orchestrator."],
            forbidden_patterns=["Do not assume hidden tools."],
        ),
    )
    llm = _FakeLLM()
    runtime = SubObjectiveExecutor(strategy, llm_provider=llm)
    try:
        result = await runtime.execute(TaskInput(task_id="rt1", description="inspect state", domain="web"))
    finally:
        await runtime.close()

    assert result.status == "success"
    assert result.verification is not None
    assert result.verification.status == "success"
    assert {"echo", "inspect_state"}.issubset(set(result.metadata["visible_tools"]))
    assert result.execution_log
    assert result.metadata["verification_status"] == "success"
    assert result.metadata["visible_tool_metadata"]["echo"]["readOnlyHint"] is True
    system_prompt = llm.messages[0][0]["content"]
    assert "Every visible tool is available to the orchestrator." in system_prompt
    assert "echo" in system_prompt
    assert "inspect_state" in system_prompt
    assert "annotations: idempotentHint=True" in system_prompt
    assistant_tool_call_message = llm.messages[1][-2]
    tool_result_message = llm.messages[1][-1]
    assert assistant_tool_call_message["role"] == "assistant"
    assert assistant_tool_call_message["tool_calls"][0]["function"]["name"] == "inspect_state"
    assert tool_result_message["role"] == "tool"
    assert tool_result_message["tool_call_id"] == "1"


class _NoToolLLM:
    async def call(self, messages, tools):
        return LLMResponse(text="done without tools")


@pytest.mark.asyncio
async def test_sub_objective_executor_fails_without_visible_tool_execution():
    strategy = MCPStrategy(
        strategy_id="fake",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="web",
        display_name="Fake",
        description="Fake strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_NoToolLLM())
    try:
        result = await runtime.execute(TaskInput(task_id="rt2", description="inspect state", domain="web"))
    finally:
        await runtime.close()

    assert result.status == "failure"
    assert result.verification is not None
    assert result.verification.status == "failure"
    assert "No successful visible MCP tool calls" in (result.error or "")


class _SilentToolLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def call(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="silent_success", arguments={})])
        return LLMResponse(text="done")


@pytest.mark.asyncio
async def test_sub_objective_executor_fails_when_tool_output_is_not_verifiable_for_cli():
    strategy = MCPStrategy(
        strategy_id="fake-cli",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="cli",
        display_name="Fake CLI",
        description="Fake CLI strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_SilentToolLLM())
    try:
        result = await runtime.execute(TaskInput(task_id="rt3", description="run command", domain="cli"))
    finally:
        await runtime.close()

    assert result.status == "failure"
    assert result.verification is not None
    assert result.verification.status == "unknown"
    assert "deterministic evidence is incomplete" in result.verification.summary


class _ExplicitCheckLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def call(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "verified"})])
        return LLMResponse(text="done")


@pytest.mark.asyncio
async def test_sub_objective_executor_uses_explicit_verification_checks():
    target = Path(__file__).with_name("runtime-proof.txt")
    target.write_text("ok", encoding="utf-8")
    strategy = MCPStrategy(
        strategy_id="fake-cli",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="cli",
        display_name="Fake CLI",
        description="Fake CLI strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_ExplicitCheckLLM())
    try:
        result = await runtime.execute(
            TaskInput(
                task_id="rt4",
                description="confirm file exists",
                domain="cli",
                verification_checks=[{"kind": "file_exists", "target": str(target), "expected": True}],
            )
        )
    finally:
        await runtime.close()
        target.unlink(missing_ok=True)

    assert result.status == "success"
    assert result.verification is not None
    assert result.verification.status == "success"
    assert any(check.kind == "file_exists" and check.status == "success" for check in result.verification.checks)


def test_sub_objective_executor_guides_recovery_after_rejected_powershell_variables():
    strategy = MCPStrategy(
        strategy_id="fake-cli",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="cli",
        display_name="Fake CLI",
        description="Fake CLI strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_ExplicitCheckLLM())

    guidance = runtime._recovery_guidance(
        "run_command",
        {"command": '$logPath = "logs"; Get-ChildItem -Path $logPath'},
        ToolResult(
            status="error",
            output='{"success": false, "message": "Command validation failed: Unknown or disallowed command: $logPath"}',
            error_code="CLI_COMMAND_FAILED",
        ),
    )

    assert "variable-assignment style" in guidance
    assert "literal paths" in guidance
    assert "Do not start the command" in guidance


class _EchoThenDoneLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def call(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "hello"})])
        return LLMResponse(text="done")


class _RepeatHotkeyLLM:
    async def call(self, messages, tools):
        return LLMResponse(tool_calls=[ToolCall(id="1", name="hotkey", arguments={"app": "Notepad", "keys": "^s"})])


@pytest.mark.asyncio
async def test_sub_objective_executor_web_requires_browser_side_evidence_not_model_text():
    strategy = MCPStrategy(
        strategy_id="fake-web",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="web",
        display_name="Fake Web",
        description="Fake web strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_EchoThenDoneLLM())
    try:
        result = await runtime.execute(TaskInput(task_id="rt-web-proof", description="open page", domain="web"))
    finally:
        await runtime.close()

    assert result.status == "failure"
    assert result.verification is not None
    assert result.verification.status == "unknown"


@pytest.mark.asyncio
async def test_sub_objective_executor_desktop_requires_postcondition_evidence_not_generic_tool_success():
    strategy = MCPStrategy(
        strategy_id="fake-desktop",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="desktop",
        display_name="Fake Desktop",
        description="Fake desktop strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_EchoThenDoneLLM())
    try:
        result = await runtime.execute(TaskInput(task_id="rt-desktop-proof", description="open window", domain="desktop"))
    finally:
        await runtime.close()

    assert result.status == "failure"
    assert result.verification is not None
    assert result.verification.status == "unknown"


class _TransientFailureLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def call(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="transient_fail", arguments={})])
        return LLMResponse(text="done")


@pytest.mark.asyncio
async def test_sub_objective_executor_marks_transient_failure_as_unknown_verification():
    strategy = MCPStrategy(
        strategy_id="fake-desktop",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="desktop",
        display_name="Fake Desktop",
        description="Fake desktop strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_TransientFailureLLM())
    try:
        result = await runtime.execute(TaskInput(task_id="rt5", description="open window", domain="desktop"))
    finally:
        await runtime.close()

    assert result.status == "failure"
    assert result.verification is not None
    assert result.verification.status == "unknown"
    assert result.verification.review_required is True


@pytest.mark.asyncio
async def test_sub_objective_executor_records_tool_success_as_failure_when_objective_verification_fails(monkeypatch):
    strategy = MCPStrategy(
        strategy_id="fake-desktop",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="desktop",
        display_name="Fake Desktop",
        description="Fake desktop strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_EchoThenDoneLLM())
    writes = []

    async def _capture_write(**kwargs):
        writes.append(kwargs)

    monkeypatch.setattr(runtime, "_write_action_memory", _capture_write)
    try:
        result = await runtime.execute(TaskInput(task_id="rt-memory-fail", description="open window", domain="desktop"))
    finally:
        await runtime.close()

    assert result.status == "failure"
    assert writes
    assert writes[0]["action_name"] == "echo"
    assert writes[0]["outcome"] == "failure"
    assert writes[0]["error_code"] == "OBJECTIVE_UNKNOWN"


def test_sub_objective_executor_blocks_repeated_mutating_action_after_two_successes():
    strategy = MCPStrategy(
        strategy_id="fake-desktop",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="desktop",
        display_name="Fake Desktop",
        description="Fake desktop strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_EchoThenDoneLLM())
    execution_log = [
        {"action": "hotkey", "arguments": {"app": "Notepad", "keys": "^s"}, "result": "success"},
        {"action": "hotkey", "arguments": {"app": "Notepad", "keys": "^s"}, "result": "success"},
    ]

    guidance = runtime._repeated_action_guidance(
        tool=_FakeMutatingTool(),
        action_name="hotkey",
        action_args={"app": "Notepad", "keys": "^s"},
        execution_log=execution_log,
    )

    assert "Repeated action blocked" in guidance
    assert "materially different next step" in guidance


def test_sub_objective_executor_blocks_repeated_mutating_action_after_failure():
    strategy = MCPStrategy(
        strategy_id="fake-desktop",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="desktop",
        display_name="Fake Desktop",
        description="Fake desktop strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_EchoThenDoneLLM())
    execution_log = [
        {
            "action": "hotkey",
            "arguments": {"app": "Notepad", "keys": "^s"},
            "result": "failure",
            "error_code": "WINDOW_NOT_FOUND",
        },
    ]

    guidance = runtime._repeated_action_guidance(
        tool=_FakeMutatingTool(),
        action_name="hotkey",
        action_args={"app": "Notepad", "keys": "^s"},
        execution_log=execution_log,
    )

    assert "already failed" in guidance
    assert "materially different next step" in guidance


@pytest.mark.asyncio
async def test_sub_objective_executor_stops_after_repeated_blocked_mutating_action(monkeypatch):
    strategy = MCPStrategy(
        strategy_id="fake-desktop",
        server_command=sys.executable,
        server_args=[str(Path(__file__).with_name("fake_strategy_server.py"))],
        domain="desktop",
        display_name="Fake Desktop",
        description="Fake desktop strategy",
    )
    runtime = SubObjectiveExecutor(strategy, llm_provider=_RepeatHotkeyLLM(), max_turns=8)

    async def _discover_tools():
        return {"hotkey": _FakeMutatingTool()}

    monkeypatch.setattr(runtime, "_discover_tools", _discover_tools)

    result = await runtime.execute(TaskInput(task_id="rt-repeat-stop", description="save the file", domain="desktop"))

    assert result.status == "failure"
    assert len(result.execution_log) == 4
    assert result.execution_log[-1].result == "failure"
    assert "Repeated action blocked" in (result.execution_log[-1].details or "")
    assert "Repeated action blocked" in (result.error or "")
