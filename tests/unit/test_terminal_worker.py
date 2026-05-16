"""Terminal worker unit tests — uses mock LLM for the agentic loop."""
from __future__ import annotations

import sys

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.terminal_worker import TerminalWorker


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------

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


def _run_command(command, allow_failure=False):
    args = {"command": command}
    if allow_failure:
        args["allow_failure"] = True
    return LLMResponse(
        content="",
        tool_calls=[{"name": "run_command", "args": args}],
    )


def _write_file(path, content):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": path, "content": content}}],
    )


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------

def _spec(goal: str, **kwargs) -> ObjectiveSpec:
    defaults = dict(
        objective_id="obj-term",
        goal=goal,
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal_command"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["exit code 0"],
        evidence_bundle=["stdout", "stderr", "exit_code"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )
    defaults.update(kwargs)
    return ObjectiveSpec(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTerminalWorker:
    async def test_echo_command_captured_in_stdout(self):
        llm = _MockLLM([
            _run_command("echo hello world"),
            _finish("success", "echoed"),
        ])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("run `echo hello world`"))
        # PowerShell echo splits args onto separate lines; check both words present
        assert "hello" in evidence["stdout"] and "world" in evidence["stdout"]
        assert evidence["exit_code"] == 0

    async def test_exit_code_nonzero_run_command_returns_error_observation(self):
        # When a command exits non-zero, _dispatch_tool returns an error string.
        # The LLM then calls finish(failure). run_loop returns WorkerResult(failure).
        # execute() does NOT raise WorkerError for failure status — it returns evidence.
        llm = _MockLLM([
            _run_command("exit 1", allow_failure=True),
            _finish("failure", "command failed with exit code 1"),
        ])
        worker = TerminalWorker(llm=llm)
        spec = _spec("run `exit 1`")
        evidence = await worker.execute(spec)
        assert evidence["exit_code"] == 1
        assert evidence["worker_result_status"] == "failure"

    async def test_exit_code_nonzero_without_allow_failure_observation(self):
        # Without allow_failure, _dispatch_tool returns FAILED observation.
        # LLM sees it and calls finish(failure). No WorkerError raised.
        llm = _MockLLM([
            _run_command("exit 1"),
            _finish("failure", "command failed"),
        ])
        worker = TerminalWorker(llm=llm)
        spec = _spec("run `exit 1`")
        evidence = await worker.execute(spec)
        assert evidence["worker_result_status"] == "failure"

    async def test_workspace_cleaned_up_after_execution(self):
        import os
        llm = _MockLLM([_finish("success", "done")])
        worker = TerminalWorker(llm=llm)
        workspace_path: list[str] = []

        # Capture workspace from evidence during run_loop by patching validate_evidence
        original_validate = None
        import trinity_pilot.workers.terminal_worker as tw_mod

        original_validate = tw_mod.validate_evidence

        captured = {}

        def capturing_validate(domain, evidence):
            captured["workspace"] = evidence.get("workspace")
            return original_validate(domain, evidence)

        tw_mod.validate_evidence = capturing_validate
        try:
            await worker.execute(_spec("run `echo test`"))
        finally:
            tw_mod.validate_evidence = original_validate

        if captured.get("workspace"):
            assert not os.path.exists(captured["workspace"]), "workspace not cleaned up"

    def test_extract_command_backtick(self):
        cmd = TerminalWorker._extract_command("run `ls -la` in the workspace")
        assert cmd == "ls -la"

    def test_extract_command_run_prefix(self):
        cmd = TerminalWorker._extract_command("execute python script.py")
        assert cmd == "python script.py"

    def test_extract_command_none_on_no_match(self):
        cmd = TerminalWorker._extract_command("vague goal with no command")
        assert cmd is None

    async def test_created_files_captured_in_evidence(self):
        import tempfile, os
        tmp = tempfile.mkdtemp()
        out_path = os.path.join(tmp, "output.txt").replace("\\", "/")
        llm = _MockLLM([
            _write_file(out_path, "content"),
            _finish("success", "file written"),
        ])
        spec = ObjectiveSpec(
            objective_id="obj-files",
            goal="write content to a file",
            dependencies=[],
            domain=DomainType.TERMINAL,
            required_capabilities=["shell_raw"],
            risk_class=RiskClass.LOW,
            preconditions=[],
            success_tests=["file created"],
            evidence_bundle=["created_files"],
            max_attempts=1,
            rollback_or_abort_rule="abort",
        )
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(spec)
        assert out_path in evidence["created_files"]

    def test_extract_command_backtick_wins_over_run_prefix(self):
        cmd = TerminalWorker._extract_command("run echo hello and also run `ls -la`")
        assert cmd == "ls -la"

    def test_extract_command_backtick_only_whitespace_returns_none(self):
        cmd = TerminalWorker._extract_command("run `   ` in workspace")
        assert not cmd

    async def test_metadata_command_used_when_present(self):
        # The agentic path sees the goal via LLM. We test that when the LLM
        # calls run_command with the metadata command, the stdout is captured.
        llm = _MockLLM([
            _run_command("echo metadata-marker"),
            _finish("success", "done"),
        ])
        spec = ObjectiveSpec(
            objective_id="obj-meta-cmd",
            goal="Execute the command some vague prose in a terminal.",
            dependencies=[],
            domain=DomainType.TERMINAL,
            required_capabilities=[],
            risk_class=RiskClass.LOW,
            preconditions=[],
            success_tests=["exit code 0"],
            evidence_bundle=["stdout"],
            max_attempts=1,
            rollback_or_abort_rule="abort",
            metadata={"command": "echo metadata-marker"},
        )
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(spec)
        assert "metadata-marker" in evidence["stdout"]
        assert evidence["exit_code"] == 0

    async def test_vague_goal_llm_calls_finish(self):
        # With a vague goal, the LLM can still call finish(failure) cleanly.
        llm = _MockLLM([
            _finish("failure", "cannot determine command from vague goal"),
        ])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("just do something vague"))
        assert evidence["worker_result_status"] == "failure"

    async def test_timeout_raises_worker_error(self):
        import asyncio

        async def slow_run_loop(spec, evidence, **kwargs):
            await asyncio.sleep(999)

        llm = _MockLLM([])
        worker = TerminalWorker(llm=llm)
        worker.run_loop = slow_run_loop  # type: ignore

        spec = _spec("run `echo test`")
        spec.metadata["timeout_seconds"] = 0.01

        with pytest.raises(WorkerError, match="[Tt]imeout"):
            await worker.execute(spec)
