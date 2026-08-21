"""FastMCP server exposing TerminalWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.terminal_server

Product path is MCP-only: the orchestrator always dispatches via MCPClientPool
(there is no hot-path that skips this server).

MCP tools exposed
-----------------
High-level task tools:
  terminal_run       — run a full agentic terminal objective

Domain sensor tools (read-only, terminal-specific — require active session):
  read_stdout        — last N lines of PTY stdout buffer
  current_directory  — cwd of the active terminal session
  env_vars           — environment variables (keys required / allowlisted; secrets redacted)
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

import os
import re
import shutil
import tempfile
from pathlib import Path

from fastmcp import FastMCP

from trinity_pilot import __version__
from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.mcp.base_server import ControlState
from trinity_pilot.mcp.tool_registry import ToolManifest, ToolMetadata
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.terminal_worker import TerminalWorker

mcp = FastMCP(
    name="trinity-pilot-terminal",
    version=__version__,
)

SERVER_NAME = "trinity-pilot-terminal"
_control = ControlState()

# Safe non-secret env keys callers may request without an explicit list.
_ENV_ALLOWLIST = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
    "USERNAME", "USERPROFILE", "HOME", "COMPUTERNAME", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "COMSPEC", "PUBLIC", "LOCALAPPDATA", "APPDATA",
})
_SECRET_KEY_RE = re.compile(r"(KEY|TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY)", re.IGNORECASE)

TOOL_MANIFEST: ToolManifest = (
    ToolMetadata("terminal_run", SERVER_NAME, "task", "Run a full terminal objective."),
    ToolMetadata("current_directory", SERVER_NAME, "sensor", "Read the terminal working directory."),
    ToolMetadata("env_vars", SERVER_NAME, "sensor", "Read process environment variables."),
    ToolMetadata("list_created_files", SERVER_NAME, "sensor", "Read workspace file listing."),
    ToolMetadata("list_files", SERVER_NAME, "sensor", "List files in a directory."),
    ToolMetadata("read_file", SERVER_NAME, "sensor", "Read a text file."),
    ToolMetadata("run_command", SERVER_NAME, "action", "Execute a shell command."),
    ToolMetadata("write_file", SERVER_NAME, "action", "Write text to a file."),
    ToolMetadata("delete_file", SERVER_NAME, "action", "Delete a file."),
    ToolMetadata("create_dir", SERVER_NAME, "action", "Create a directory."),
    ToolMetadata("todo_write", SERVER_NAME, "control", "Replace the current todo list."),
    ToolMetadata("todo_read", SERVER_NAME, "control", "Read the current todo list."),
    ToolMetadata("todo_check", SERVER_NAME, "control", "Complete a todo item."),
    ToolMetadata("todo_add", SERVER_NAME, "control", "Append a todo item."),
    ToolMetadata("finish", SERVER_NAME, "control", "Signal objective completion."),
    ToolMetadata("report_blocking", SERVER_NAME, "control", "Signal an unresolvable blocker."),
)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("health://terminal")
def health() -> str:
    return "ok"


@mcp.resource("version://terminal")
def version() -> str:
    return __version__


# ---------------------------------------------------------------------------
# High-level task tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def terminal_run(spec_dict: dict) -> dict:
    """Execute a full terminal objective and return a tagged result envelope.

    spec_dict is ObjectiveSpec.to_dict() — the complete objective spec,
    including metadata (retry_context, steering_context, dependency_evidence,
    timeout_seconds), dependencies, max_attempts, risk_class, etc. This is the
    real dispatch boundary: a fresh TerminalWorker is constructed per call.

    Returns one of three tagged shapes (WorkerBlocker/WorkerError cannot cross
    the MCP JSON-RPC boundary as raised exceptions, so they are translated):
      {"mcp_status": "ok", "evidence": {...}}
      {"mcp_status": "blocker", "reason": str, "result": {status, summary,
                                            evidence, steps_taken, tokens_used}}
      {"mcp_status": "error", "message": str}
    """
    spec = ObjectiveSpec.from_dict(spec_dict)
    worker = TerminalWorker()
    try:
        evidence = await worker.execute(spec)
        return {"mcp_status": "ok", "evidence": evidence}
    except WorkerBlocker as exc:
        result = exc.result
        return {
            "mcp_status": "blocker",
            "reason": str(exc),
            "result": {
                "status": result.status,
                "summary": result.summary,
                "evidence": result.evidence,
                "steps_taken": result.steps_taken,
                "tokens_used": result.tokens_used,
            },
        }
    except WorkerError as exc:
        return {"mcp_status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Domain sensor tools (terminal-specific, require active session context)
# These return data about the current terminal session state.
# ---------------------------------------------------------------------------

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
    """Return environment variables (never dumps the full secret-bearing environ).

    Args:
        keys: Specific variable names to return. If omitted, returns only a
              small allowlist of non-secret system vars. Keys matching
              *_KEY / *_TOKEN / PASSWORD / SECRET are redacted.

    Returns:
        dict mapping variable names to values (or \"<redacted>\").
    """
    if keys:
        selected = list(keys)
    else:
        selected = sorted(k for k in _ENV_ALLOWLIST if k in os.environ)

    vars_out: dict[str, str | None] = {}
    for k in selected:
        if _SECRET_KEY_RE.search(k):
            vars_out[k] = "<redacted>" if k in os.environ else None
        else:
            vars_out[k] = os.environ.get(k)
    return {"vars": vars_out}


@mcp.tool()
async def list_created_files(workspace: str) -> dict:
    """List files in the workspace directory (files created during a terminal session).

    Args:
        workspace: Absolute path to the workspace directory.

    Returns:
        dict with files: list of relative file paths.
    """
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


@mcp.tool()
async def list_files(path: str = ".", recursive: bool = False) -> dict:
    root = Path(path)
    try:
        iterator = root.rglob("*") if recursive else root.iterdir()
        return {"path": str(root), "files": sorted(str(item) for item in iterator)}
    except Exception as exc:
        return {"path": str(root), "files": [], "error": str(exc)}


@mcp.tool()
async def read_file(path: str, encoding: str = "utf-8") -> dict:
    try:
        return {"path": path, "content": Path(path).read_text(encoding=encoding)}
    except Exception as exc:
        return {"path": path, "error": str(exc)}


# ---------------------------------------------------------------------------
# Domain action tools (mirror the inner ReAct loop tools)
# ---------------------------------------------------------------------------

@mcp.tool()
async def run_command(
    command: str,
    allow_failure: bool = False,
    cwd: str | None = None,
    shell_raw: bool = False,
    required_capabilities: list[str] | None = None,
) -> dict:
    """Execute a PowerShell command and return stdout, stderr, and exit_code.

    If cwd is omitted a temporary directory is used as the working directory
    and cleaned up afterwards. shell_raw requires \"shell_raw\" in
    required_capabilities (same gate as TerminalWorker).
    """
    caps = required_capabilities or []
    if shell_raw and "shell_raw" not in caps:
        return {
            "success": False,
            "action": "run_command",
            "result": "shell_raw denied",
            "observation": {},
            "error": (
                "shell_raw=True requires 'shell_raw' in required_capabilities "
                "(same gate as TerminalWorker)."
            ),
        }

    created_temp = cwd is None
    work_dir = cwd or tempfile.mkdtemp(prefix="trinity-mcp-term-")
    try:
        stdout, stderr, exit_code = await TerminalWorker._run_command(
            command, cwd=work_dir, shell_raw=shell_raw
        )
        success = exit_code == 0 or allow_failure
        return {
            "success": success,
            "action": "run_command",
            "result": f"command exited {exit_code}",
            "observation": {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "cwd": work_dir if not created_temp else None,
            },
            "error": None if success else f"Command exited {exit_code}",
        }
    finally:
        if created_temp:
            shutil.rmtree(work_dir, ignore_errors=True)


@mcp.tool()
async def write_file(path: str, content: str) -> dict:
    """Write text content directly to a file at an absolute path.

    Parent directories are created automatically.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "success": True,
        "action": "write_file",
        "result": f"wrote {len(content.encode())} bytes to {target}",
        "observation": {"path": str(target), "cwd": str(target.parent)},
        "error": None,
    }


@mcp.tool()
async def delete_file(path: str) -> dict:
    target = Path(path)
    try:
        target.unlink()
        return {"success": True, "action": "delete_file", "result": f"deleted {target}", "observation": {}, "error": None}
    except Exception as exc:
        return {"success": False, "action": "delete_file", "result": "delete failed", "observation": {}, "error": str(exc)}


@mcp.tool()
async def create_dir(path: str) -> dict:
    target = Path(path)
    try:
        target.mkdir(parents=True, exist_ok=True)
        return {"success": True, "action": "create_dir", "result": f"created {target}", "observation": {}, "error": None}
    except Exception as exc:
        return {"success": False, "action": "create_dir", "result": "create failed", "observation": {}, "error": str(exc)}


# ---------------------------------------------------------------------------
# Control tools (finish / report_blocking)
# ---------------------------------------------------------------------------

@mcp.tool()
def todo_write(items: list[str], session_id: str = "default") -> dict:
    return _control.write(items, session_id)

@mcp.tool()
def todo_read(session_id: str = "default") -> dict:
    return _control.read(session_id)

@mcp.tool()
def todo_check(index: int, session_id: str = "default") -> dict:
    return _control.check(index, session_id)

@mcp.tool()
def todo_add(item: str, session_id: str = "default") -> dict:
    return _control.add(item, session_id)

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
