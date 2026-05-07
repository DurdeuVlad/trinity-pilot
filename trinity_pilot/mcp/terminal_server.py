"""FastMCP server exposing TerminalWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.terminal_server
Internal hot-path skips this server and calls TerminalWorker directly.
"""
from __future__ import annotations

from fastmcp import FastMCP
from trinity_pilot.core.types import (
    DomainType,
    ObjectiveSpec,
    RiskClass,
)
from trinity_pilot.workers.terminal_worker import TerminalWorker

mcp = FastMCP(
    name="trinity-pilot-terminal",
    version="0.1.0",
)


@mcp.resource("health://terminal")
def health() -> str:
    return "ok"


@mcp.resource("version://terminal")
def version() -> str:
    return "0.1.0"


@mcp.tool()
async def terminal_run(
    objective_id: str,
    goal: str,
    success_tests: list[str],
    risk_class: str = "low",
) -> dict:
    """Run a terminal command in an isolated workspace and return evidence (stdout, stderr, exit_code, created_files)."""
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal_command"],
        risk_class=RiskClass(risk_class),
        preconditions=[],
        success_tests=success_tests,
        evidence_bundle=["stdout", "stderr", "exit_code"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    worker = TerminalWorker()
    return await worker.execute(spec)


if __name__ == "__main__":
    mcp.run()
