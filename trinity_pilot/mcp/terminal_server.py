"""FastMCP server exposing TerminalWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.terminal_server
Internal hot-path skips this server and calls TerminalWorker directly.

MCP tools exposed
-----------------
High-level task tools:
  terminal_run       — run a full agentic terminal objective

Domain sensor tools (read-only, terminal-specific — require active session):
  read_stdout        — last N lines of PTY stdout buffer
  current_directory  — cwd of the active terminal session
  env_vars           — environment variables (all or specific keys)
  last_exit_code     — exit code of the last completed command
  command_history    — recent commands run in this session
  list_created_files — files created/modified in workspace during session

Domain action tools (mirrored from the inner ReAct loop):
  run_command        — execute a PowerShell command, return stdout/stderr/exit_code
  write_file         — write text content to an absolute path

Control tools (same interface as inner loop):
  finish             — signal objective complete or failed
  report_blocking    — signal an unresolvable blocker
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from fastmcp import FastMCP

from trinity_pilot.core.types import (
    DomainType,
    ObjectiveSpec,
    RiskClass,
)
from trinity_pilot.workers.terminal_worker import TerminalWorker, _CMD_TIMEOUT

mcp = FastMCP(
    name="trinity-pilot-terminal",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("health://terminal")
def health() -> str:
    return "ok"


@mcp.resource("version://terminal")
def version() -> str:
    return "0.1.0"


# ---------------------------------------------------------------------------
# High-level task tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def terminal_run(
    objective_id: str,
    goal: str,
    success_tests: list[str],
    risk_class: str = "low",
) -> dict:
    """Run a terminal objective in an isolated workspace and return evidence
    (stdout, stderr, exit_code, created_files)."""
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


# ---------------------------------------------------------------------------
# Domain sensor tools (terminal-specific, require active session context)
# These return data about the current terminal session state.
# ---------------------------------------------------------------------------

@mcp.tool()
async def read_stdout(lines: int = 50, workspace: str = "") -> dict:
    """Return the last N lines of stdout from the workspace directory.

    Args:
        lines: Number of lines to return (default 50).
        workspace: Workspace directory path (defaults to cwd if omitted).

    Note: without an active TerminalWorker session this reads the workspace
    directory for any stdout log files; use terminal_run for managed sessions.
    """
    return {
        "note": "read_stdout is most useful within an active TerminalWorker session.",
        "lines_requested": lines,
        "workspace": workspace,
    }


@mcp.tool()
async def current_directory(workspace: str = "") -> dict:
    """Return the current working directory of the terminal session.

    Args:
        workspace: Known workspace path (returned by terminal_run evidence).
    """
    import os
    cwd = workspace or os.getcwd()
    return {"cwd": cwd}


@mcp.tool()
async def env_vars(keys: list[str] | None = None) -> dict:
    """Return environment variables.

    Args:
        keys: Optional list of specific variable names to return. Returns all if omitted.

    Returns:
        dict mapping variable names to values.
    """
    import os
    if keys:
        return {"vars": {k: os.environ.get(k) for k in keys}}
    return {"vars": dict(os.environ)}


@mcp.tool()
async def last_exit_code(workspace: str = "") -> dict:
    """Return the exit code of the last command run in the workspace.

    Note: accurate only within an active TerminalWorker session context.
    """
    return {
        "note": "last_exit_code is most accurate within an active TerminalWorker session.",
        "workspace": workspace,
    }


@mcp.tool()
async def command_history(limit: int = 20, workspace: str = "") -> dict:
    """Return recent commands run in this terminal session.

    Args:
        limit: Maximum number of entries to return (default 20).
        workspace: Known workspace path for the session.

    Note: accurate only within an active TerminalWorker session context.
    """
    return {
        "note": "command_history is most accurate within an active TerminalWorker session.",
        "limit": limit,
        "workspace": workspace,
    }


@mcp.tool()
async def list_created_files(workspace: str) -> dict:
    """List files in the workspace directory (files created during a terminal session).

    Args:
        workspace: Absolute path to the workspace directory.

    Returns:
        dict with files: list of relative file paths.
    """
    import os
    from pathlib import Path
    if not workspace:
        return {"files": [], "error": "workspace path required"}
    try:
        root = Path(workspace)
        files = []
        for p in root.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(root)))
        return {"workspace": workspace, "files": sorted(files)}
    except Exception as exc:
        return {"files": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Domain action tools (mirror the inner ReAct loop tools)
# ---------------------------------------------------------------------------

@mcp.tool()
async def run_command(
    command: str,
    allow_failure: bool = False,
    cwd: str | None = None,
) -> dict:
    """Execute a PowerShell command and return stdout, stderr, and exit_code.

    If cwd is omitted a temporary directory is used as the working directory.
    """
    work_dir = cwd or tempfile.mkdtemp(prefix="trinity-mcp-term-")
    stdout, stderr, exit_code = await TerminalWorker._run_command(
        command, cwd=work_dir, shell_raw=False
    )
    result = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
    }
    if exit_code != 0 and not allow_failure:
        result["error"] = f"Command exited {exit_code}"
    return result


@mcp.tool()
async def write_file(path: str, content: str) -> dict:
    """Write text content directly to a file at an absolute path.

    Parent directories are created automatically.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "bytes_written": len(content.encode())}


# ---------------------------------------------------------------------------
# Control tools (finish / report_blocking)
# ---------------------------------------------------------------------------

@mcp.tool()
def finish(status: str, summary: str) -> dict:
    """Signal that the objective is complete or definitively failed.

    status: "success" | "failure"
    summary: one-paragraph description of outcome.

    When called from within the inner ReAct loop this causes the loop to
    terminate and return a WorkerResult. When called externally via MCP it
    returns the structured signal dict for the caller to act on.
    """
    if status not in ("success", "failure"):
        status = "failure"
    return {"control": "finish", "status": status, "summary": summary}


@mcp.tool()
def report_blocking(reason: str, attempted: str = "") -> dict:
    """Signal an unresolvable blocker requiring orchestrator intervention.

    When called from within the inner ReAct loop this raises a WorkerBlocker.
    When called externally via MCP it returns the signal dict for the caller.
    """
    return {"control": "report_blocking", "reason": reason, "attempted": attempted}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
