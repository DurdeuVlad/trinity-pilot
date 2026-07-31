"""app_control_cli.py — Trinity Pilot live-test control surface CLI.

Usage:
    python app_control_cli.py start-ui
    python app_control_cli.py shutdown-ui
    python app_control_cli.py submit-case <tc_file> [--task-id UUID]
    python app_control_cli.py stream-events <task_id> [--cursor ISO] [--poll-interval N] [--until-terminal]
    python app_control_cli.py get-artifact-bundle <task_id> [--output PATH]
    python app_control_cli.py reset-session [--confirm]

All commands print JSON to stdout.  Errors print {"error": "...", "error_code": "..."} and exit 1.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# MCP client helper — spawn orchestrator_server as subprocess and call a tool
# ---------------------------------------------------------------------------

_SERVER_MODULE = "trinity_pilot.mcp.orchestrator_server"


async def _call_tool_async(tool_name: str, args: dict) -> dict | list:
    """Spawn orchestrator_server via stdio MCP, call one tool, return parsed result."""
    try:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", _SERVER_MODULE],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                # result.content is a list of TextContent/ImageContent items
                if result.content:
                    raw = result.content[0].text
                    try:
                        return json.loads(raw)
                    except (json.JSONDecodeError, AttributeError):
                        return {"raw": str(raw)}
                return {}
    except ImportError:
        # Fallback: raw JSON-RPC over subprocess stdin/stdout
        return await _call_tool_jsonrpc(tool_name, args)


async def _call_tool_jsonrpc(tool_name: str, args: dict) -> dict | list:
    """Fallback: communicate with orchestrator_server via raw JSON-RPC framing."""
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-m", _SERVER_MODULE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    def _send(obj: dict) -> None:
        msg = json.dumps(obj)
        line = f"Content-Length: {len(msg)}\r\n\r\n{msg}"
        proc.stdin.write(line.encode())
        proc.stdin.flush()

    def _recv() -> dict:
        # Read Content-Length header
        headers: dict[str, str] = {}
        while True:
            raw_line = proc.stdout.readline()
            if not raw_line:
                break
            text = raw_line.decode().strip()
            if not text:
                break
            if ":" in text:
                k, v = text.split(":", 1)
                headers[k.strip()] = v.strip()
        length = int(headers.get("Content-Length", "0"))
        body = proc.stdout.read(length)
        return json.loads(body)

    # Initialize
    _send({"jsonrpc": "2.0", "id": 0, "method": "initialize",
           "params": {"protocolVersion": "2024-11-05",
                      "capabilities": {},
                      "clientInfo": {"name": "app_control_cli", "version": "0.1.0"}}})
    _recv()  # discard init response

    _send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    # Call tool
    _send({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": tool_name, "arguments": args}})
    response = _recv()

    proc.stdin.close()
    proc.wait(timeout=600)  # tasks can take minutes

    if "error" in response:
        return {"error": response["error"].get("message", "unknown"), "error_code": "RPC_ERROR"}

    content = response.get("result", {}).get("content", [])
    if content:
        raw = content[0].get("text", "{}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return {}


def call_tool(tool_name: str, args: dict) -> dict | list:
    """Synchronous wrapper around _call_tool_async."""
    return asyncio.run(_call_tool_async(tool_name, args))


def print_json(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


def die(error: str, error_code: str = "ERROR") -> None:
    print_json({"error": error, "error_code": error_code})
    sys.exit(1)


# ---------------------------------------------------------------------------
# TC-*.md parser
# ---------------------------------------------------------------------------

def _parse_tc_file(path: Path) -> dict:
    """Parse a TC-*.md file and return frontmatter dict + user_request string."""
    try:
        import yaml
    except ImportError:
        die("pyyaml is required: pip install pyyaml", "MISSING_DEPENDENCY")

    content = path.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) < 3:
        die(f"TC file has no valid frontmatter: {path}", "INVALID_TC_FILE")

    try:
        frontmatter = yaml.safe_load(parts[1])
    except Exception as exc:
        die(f"TC file frontmatter parse failed: {exc}", "INVALID_TC_FILE")

    body = parts[2]

    # Extract user_request section
    match = re.search(r"##\s+user_request\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
    if not match:
        die("TC file missing '## user_request' section", "INVALID_TC_FILE")
    user_request = match.group(1).strip()
    if not user_request:
        die("TC file 'user_request' section is empty", "INVALID_TC_FILE")

    # Validate tc_id matches filename
    expected_prefix = path.stem.split("-")[0] + "-" + path.stem.split("-")[1]  # e.g. TC-001
    tc_id = str(frontmatter.get("tc_id", ""))
    if not tc_id.upper().startswith(expected_prefix.upper()):
        die(
            f"tc_id '{tc_id}' does not match filename '{path.name}'",
            "INVALID_TC_FILE",
        )

    # Validate domain
    valid_domains = {"browser", "terminal", "desktop", "mixed"}
    domain = str(frontmatter.get("domain", ""))
    if domain not in valid_domains:
        die(f"Invalid domain '{domain}'. Valid: {valid_domains}", "INVALID_TC_FILE")

    # Validate risk_class
    valid_risk = {"low", "medium", "high"}
    risk_class = str(frontmatter.get("risk_class", ""))
    if risk_class not in valid_risk:
        die(f"Invalid risk_class '{risk_class}'. Valid: {valid_risk}", "INVALID_TC_FILE")

    # Validate difficulty
    valid_difficulty = {"easy", "medium", "hard"}
    difficulty = str(frontmatter.get("difficulty", ""))
    if difficulty not in valid_difficulty:
        die(f"Invalid difficulty '{difficulty}'. Valid: {valid_difficulty}", "INVALID_TC_FILE")

    return {"frontmatter": frontmatter, "user_request": user_request}


# ---------------------------------------------------------------------------
# Command: start-ui
# ---------------------------------------------------------------------------

def cmd_start_ui(args: argparse.Namespace) -> None:
    import subprocess

    pid_file = Path(args.pid_file)
    app_module = args.app_module

    # Check if already running
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text().strip())
            # Check if process is alive

            try:
                if sys.platform == "win32":
                    import ctypes
                    handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, existing_pid)
                    if handle:
                        ctypes.windll.kernel32.CloseHandle(handle)
                        print_json({"status": "already_running", "pid": existing_pid})
                        return
                else:
                    os.kill(existing_pid, 0)
                    print_json({"status": "already_running", "pid": existing_pid})
                    return
            except (OSError, ProcessLookupError):
                # Process is dead — stale PID file, continue to spawn
                pid_file.unlink(missing_ok=True)
        except (ValueError, OSError):
            pid_file.unlink(missing_ok=True)

    # Spawn the UI process
    try:
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

        proc = subprocess.Popen(
            [sys.executable, "-m", app_module],
            **kwargs,
        )
        pid_file.write_text(str(proc.pid))
        print_json({"status": "started", "pid": proc.pid, "pid_file": str(pid_file)})
    except Exception as exc:
        die(f"Failed to spawn UI process: {exc}", "SPAWN_FAILED")


# ---------------------------------------------------------------------------
# Command: shutdown-ui
# ---------------------------------------------------------------------------

def cmd_shutdown_ui(args: argparse.Namespace) -> None:
    import subprocess

    pid_file = Path(args.pid_file)
    if not pid_file.exists():
        die("No UI running (PID file not found)", "NOT_RUNNING")

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError) as exc:
        die(f"Cannot read PID file: {exc}", "NOT_RUNNING")

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True, capture_output=True)
        else:
            import signal as _signal
            os.kill(pid, _signal.SIGTERM)
    except Exception as exc:
        die(f"Failed to stop process {pid}: {exc}", "KILL_FAILED")

    pid_file.unlink(missing_ok=True)
    print_json({"status": "stopped", "pid": pid})


# ---------------------------------------------------------------------------
# Command: submit-case
# ---------------------------------------------------------------------------

def cmd_submit_case(args: argparse.Namespace) -> None:
    tc_path = Path(args.tc_file)
    if not tc_path.exists():
        die(f"TC file not found: {tc_path}", "FILE_NOT_FOUND")

    parsed = _parse_tc_file(tc_path)
    user_request = parsed["user_request"]

    tool_args: dict = {"user_request": user_request}
    if args.task_id:
        tool_args["task_id"] = args.task_id

    result = call_tool("submit_task", tool_args)
    print_json(result)


# ---------------------------------------------------------------------------
# Command: stream-events
# ---------------------------------------------------------------------------

def cmd_stream_events(args: argparse.Namespace) -> None:
    task_id: str = args.task_id
    cursor: str | None = args.cursor
    poll_interval: int = args.poll_interval
    until_terminal: bool = args.until_terminal

    tool_args: dict = {"task_id": task_id}
    if cursor:
        tool_args["since_cursor"] = cursor

    result = call_tool("get_task_events", tool_args)
    print_json(result)

    if not until_terminal:
        return

    # Polling loop
    current_cursor: str | None = result.get("next_cursor") if isinstance(result, dict) else None
    is_terminal: bool = result.get("is_terminal", False) if isinstance(result, dict) else False

    while not is_terminal:
        time.sleep(poll_interval)
        poll_args: dict = {"task_id": task_id}
        if current_cursor:
            poll_args["since_cursor"] = current_cursor
        result = call_tool("get_task_events", poll_args)
        print_json(result)
        if isinstance(result, dict):
            current_cursor = result.get("next_cursor", current_cursor)
            is_terminal = result.get("is_terminal", False)

    print_json({"done": True, "task_status": result.get("task_status") if isinstance(result, dict) else "unknown"})


# ---------------------------------------------------------------------------
# Command: get-artifact-bundle
# ---------------------------------------------------------------------------

def cmd_get_artifact_bundle(args: argparse.Namespace) -> None:
    result = call_tool("get_artifact_bundle", {"task_id": args.task_id})
    output_text = json.dumps(result, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print_json({"status": "written", "output_file": args.output})
    else:
        print(output_text)


# ---------------------------------------------------------------------------
# Command: reset-session
# ---------------------------------------------------------------------------

def cmd_reset_session(args: argparse.Namespace) -> None:
    result = call_tool("reset_session", {"confirm": bool(args.confirm)})
    print_json(result)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app_control_cli.py",
        description="Trinity Pilot live-test control surface CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start-ui
    p_start = sub.add_parser("start-ui", help="Launch the Trinity Pilot UI application")
    p_start.add_argument(
        "--app-module",
        default="trinity_pilot",
        help="Python module to run as the UI (default: trinity_pilot)",
    )
    p_start.add_argument(
        "--pid-file",
        default=".trinity_pilot_ui.pid",
        help="Path to PID lock file (default: .trinity_pilot_ui.pid)",
    )

    # shutdown-ui
    p_stop = sub.add_parser("shutdown-ui", help="Shut down the running Trinity Pilot UI")
    p_stop.add_argument(
        "--pid-file",
        default=".trinity_pilot_ui.pid",
        help="Path to PID lock file (default: .trinity_pilot_ui.pid)",
    )

    # submit-case
    p_submit = sub.add_parser("submit-case", help="Submit a TC-*.md test case file as a task")
    p_submit.add_argument("tc_file", help="Path to the TC-*.md test case file")
    p_submit.add_argument("--task-id", default=None, help="Optional caller-supplied task UUID")

    # stream-events
    p_stream = sub.add_parser("stream-events", help="Poll attempt_logs events for a task")
    p_stream.add_argument("task_id", help="Task UUID to poll")
    p_stream.add_argument(
        "--cursor",
        default=None,
        help="ISO-8601 datetime of last seen event (default: all events)",
    )
    p_stream.add_argument(
        "--poll-interval",
        type=int,
        default=3,
        help="Seconds between polls when --until-terminal is set (default: 3)",
    )
    p_stream.add_argument(
        "--until-terminal",
        action="store_true",
        help="Poll in a loop until the task reaches a terminal state",
    )

    # get-artifact-bundle
    p_bundle = sub.add_parser("get-artifact-bundle", help="Retrieve full artifact bundle for a task")
    p_bundle.add_argument("task_id", help="Task UUID")
    p_bundle.add_argument(
        "--output",
        default=None,
        help="Write bundle JSON to this file path (default: stdout)",
    )

    # reset-session
    p_reset = sub.add_parser("reset-session", help="Delete all tasks, attempts, and reflections")
    p_reset.add_argument(
        "--confirm",
        action="store_true",
        help="Actually perform deletion (omit for dry-run)",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMAND_HANDLERS = {
    "start-ui": cmd_start_ui,
    "shutdown-ui": cmd_shutdown_ui,
    "submit-case": cmd_submit_case,
    "stream-events": cmd_stream_events,
    "get-artifact-bundle": cmd_get_artifact_bundle,
    "reset-session": cmd_reset_session,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    handler = _COMMAND_HANDLERS.get(args.command)
    if handler is None:
        die(f"Unknown command: {args.command}", "UNKNOWN_COMMAND")
    handler(args)


if __name__ == "__main__":
    main()
