"""FastMCP server exposing DesktopWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.desktop_server
Internal hot-path skips this server and calls DesktopWorker directly.
"""
from __future__ import annotations

from fastmcp import FastMCP

from trinity_pilot.core.types import (
    DomainType,
    ObjectiveSpec,
    RiskClass,
)
from trinity_pilot.workers.desktop_worker import DesktopWorker

mcp = FastMCP(
    name="trinity-pilot-desktop",
    version="0.1.0",
)


@mcp.resource("health://desktop")
def health() -> str:
    return "ok"


@mcp.resource("version://desktop")
def version() -> str:
    return "0.1.0"


@mcp.tool()
async def desktop_screenshot(objective_id: str, goal: str) -> dict:
    """Take a screenshot of the current desktop and return evidence."""
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_screenshot"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["screenshot captured"],
        evidence_bundle=["screenshot"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    worker = DesktopWorker()
    return await worker.execute(spec)


@mcp.tool()
async def desktop_find_window(objective_id: str, goal: str) -> dict:
    """Find a window and return its element tree snapshot."""
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_uia"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["window found"],
        evidence_bundle=["element_tree_snapshot", "screenshot"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    worker = DesktopWorker()
    return await worker.execute(spec)


if __name__ == "__main__":
    mcp.run()
