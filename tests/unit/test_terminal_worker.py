"""Terminal worker unit tests — uses real subprocess in isolated temp dirs."""
from __future__ import annotations

import sys

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.terminal_worker import TerminalWorker


def _spec(goal: str) -> ObjectiveSpec:
    return ObjectiveSpec(
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


class TestTerminalWorker:
    async def test_echo_command_captured_in_stdout(self):
        if sys.platform == "win32":
            goal = "run `echo hello world`"
        else:
            goal = "run `echo hello world`"
        worker = TerminalWorker()
        evidence = await worker.execute(_spec(goal))
        assert "hello world" in evidence["stdout"]
        assert evidence["exit_code"] == 0

    async def test_exit_code_nonzero_raises_worker_error(self):
        if sys.platform == "win32":
            goal = "run `exit 1`"
        else:
            goal = "run `exit 1`"
        worker = TerminalWorker()
        with pytest.raises(WorkerError):
            await worker.execute(_spec(goal))

    async def test_no_command_in_goal_raises_worker_error(self):
        worker = TerminalWorker()
        with pytest.raises(WorkerError, match="No runnable command"):
            await worker.execute(_spec("just do something vague"))

    async def test_workspace_cleaned_up_after_execution(self):
        import os
        worker = TerminalWorker()
        captured_workspace: list[str] = []

        original_execute = worker._run_objective

        async def capture(workspace, spec, evidence):
            captured_workspace.append(workspace)
            await original_execute(workspace, spec, evidence)

        worker._run_objective = capture  # type: ignore

        goal = "run `echo test`"
        await worker.execute(_spec(goal))

        if captured_workspace:
            assert not os.path.exists(captured_workspace[0]), "workspace not cleaned up"

    def test_extract_command_backtick(self):
        cmd = TerminalWorker._extract_command("run `ls -la` in the workspace")
        assert cmd == "ls -la"

    def test_extract_command_run_prefix(self):
        cmd = TerminalWorker._extract_command("execute python script.py")
        assert cmd == "python script.py"

    def test_extract_command_none_on_no_match(self):
        cmd = TerminalWorker._extract_command("vague goal with no command")
        assert cmd is None

    def test_extract_command_backtick_wins_over_run_prefix(self):
        # Goal has both "run X" and backtick — backtick is matched first (re.search finds first)
        cmd = TerminalWorker._extract_command("run echo hello and also run `ls -la`")
        # backtick pattern appears in goal, so backtick wins
        assert cmd == "ls -la"

    def test_extract_command_backtick_only_whitespace_returns_none(self):
        # Backtick with only whitespace — strip returns empty string → falsy → None
        cmd = TerminalWorker._extract_command("run `   ` in workspace")
        # Stripped content is empty string, which is falsy
        assert not cmd  # either None or empty string is acceptable
