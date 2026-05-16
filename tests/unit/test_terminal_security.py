"""Terminal worker security tests — verifies shlex is used by default."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMProvider, LLMResponse
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


def _run_command_resp(command):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "run_command", "args": {"command": command}}],
    )


def _finish(status="success", summary="done"):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "finish", "args": {"status": status, "summary": summary}}],
    )


def _spec(goal: str, capabilities: list[str] | None = None) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-sec",
        goal=goal,
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=capabilities or ["terminal_command"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["exit 0"],
        evidence_bundle=["stdout"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )


class TestTerminalSecurity:
    async def test_default_uses_subprocess_exec_not_shell(self):
        """Without shell_raw: create_subprocess_exec called, not create_subprocess_shell."""
        exec_calls = []
        shell_calls = []

        async def fake_exec(*args, **kwargs):
            exec_calls.append(args)
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            return mock_proc

        async def fake_shell(*args, **kwargs):
            shell_calls.append(args)
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            return mock_proc

        llm = _MockLLM([
            _run_command_resp("echo hello"),
            _finish("success", "done"),
        ])
        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
             patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            worker = TerminalWorker(llm=llm)
            await worker.execute(_spec("run `echo hello`"))

        assert len(exec_calls) == 1, "exec should be called"
        assert len(shell_calls) == 0, "shell must NOT be called by default"

    async def test_windows_builtin_uses_powershell_via_exec_not_shell(self, monkeypatch):
        exec_calls = []

        async def fake_exec(*args, **kwargs):
            exec_calls.append(args)
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"hello\r\n", b""))
            mock_proc.returncode = 0
            return mock_proc

        monkeypatch.setattr(
            "trinity_pilot.workers.terminal_worker.sys.platform",
            "win32",
        )

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec), \
             patch("asyncio.create_subprocess_shell", side_effect=AssertionError("shell should not be called")):
            stdout, stderr, exit_code = await TerminalWorker._run_command(
                "echo hello",
                cwd=".",
            )

        # Windows now uses PowerShell (not cmd.exe) to match the system prompt
        assert exec_calls == [("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "echo hello")]
        assert "hello" in stdout
        assert stderr == ""
        assert exit_code == 0

    async def test_shell_raw_capability_uses_subprocess_shell(self):
        """With shell_raw capability: create_subprocess_shell is used for command execution."""
        shell_calls = []

        async def fake_shell(*args, **kwargs):
            shell_calls.append(args)
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            return mock_proc

        async def fake_exec(*args, **kwargs):
            # exec may still be called by asyncio internals; only track shell calls
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            return mock_proc

        llm = _MockLLM([
            _run_command_resp("echo hello"),
            _finish("success", "done"),
        ])
        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            worker = TerminalWorker(llm=llm)
            await worker.execute(_spec("run `echo hello`", capabilities=["terminal_command", "shell_raw"]))

        assert len(shell_calls) == 1

    async def test_shell_raw_evidence_flag_set(self):
        async def fake_shell(*args, **kwargs):
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"out", b""))
            mock_proc.returncode = 0
            return mock_proc

        llm = _MockLLM([
            _run_command_resp("echo ok"),
            _finish("success", "done"),
        ])
        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            worker = TerminalWorker(llm=llm)
            evidence = await worker.execute(_spec("run `echo ok`", capabilities=["terminal_command", "shell_raw"]))

        assert evidence.get("shell_raw_used") is True
