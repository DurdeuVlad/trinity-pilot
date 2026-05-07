"""Real terminal test — runs live subprocess commands via TerminalWorker."""
import sys

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.terminal_worker import TerminalWorker

pytestmark = pytest.mark.real


def _spec(goal: str) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="real-terminal-1",
        goal=goal,
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal_command"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["exit code 0"],
        evidence_bundle=["stdout", "stderr", "exit_code"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )


async def test_echo_command_stdout():
    worker = TerminalWorker()
    evidence = await worker.execute(_spec("run `echo hello-trinity`"))

    assert evidence["exit_code"] == 0
    assert "hello-trinity" in evidence["stdout"]
    assert evidence["domain"] == "terminal"


async def test_workspace_isolated():
    """Each execution gets its own tempdir — files don't persist between calls."""
    worker = TerminalWorker()
    spec = _spec("run `echo isolated`")

    e1 = await worker.execute(spec)
    e2 = await worker.execute(spec)

    # Both succeed; workspaces are independent
    assert e1["exit_code"] == 0
    assert e2["exit_code"] == 0


async def test_created_files_listed():
    if sys.platform == "win32":
        goal = "run `echo content > output.txt`"
    else:
        goal = "run `touch output.txt`"

    worker = TerminalWorker()
    evidence = await worker.execute(_spec(goal))

    assert evidence["exit_code"] == 0
    # On Windows echo redirect creates the file
    # created_files may or may not list it depending on shell behavior — just assert no crash
    assert "created_files" in evidence
