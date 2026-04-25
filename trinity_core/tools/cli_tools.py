"""CLI MCP tools wired directly to CLI execution primitives."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI_MODULE_ROOT = PROJECT_ROOT / "cli-automation-poc"
if str(CLI_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(CLI_MODULE_ROOT))

from cli_executor import CLIExecutor  # type: ignore[import-not-found]

from .base import Tool, ToolResult


class _CLISession:
    def __init__(self) -> None:
        self.executor = CLIExecutor(timeout=120)
        self.last_output = ""


def _success_payload(**payload: Any) -> ToolResult:
    return ToolResult(status="success", output=json.dumps({"success": True, **payload}), metadata=payload)


def _error_payload(message: str, *, code: str, retryable: bool) -> ToolResult:
    return ToolResult(
        status="error",
        output=json.dumps({"success": False, "error_code": code, "message": message}),
        error=message,
        error_code=code,
        retryable=retryable,
    )


class CLIRunCommandTool(Tool):
    def __init__(self, session: _CLISession) -> None:
        self.session = session

    def name(self) -> str:
        return "run_command"

    def description(self) -> str:
        return "Run a PowerShell command directly."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "async_mode": {"type": "boolean", "default": False},
            },
            "required": ["command"],
        }

    def annotations(self) -> dict:
        return {"title": "Run Command", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = str(kwargs["command"])
        if bool(kwargs.get("async_mode", False)):
            return _error_payload(
                "async_mode is disabled until objective-scoped process cleanup is implemented.",
                code="ASYNC_MODE_UNSUPPORTED",
                retryable=False,
            )

        result = await asyncio.to_thread(self.session.executor.execute_command, command)
        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        self.session.last_output = combined_output
        if result.exit_code != 0:
            return _error_payload(
                combined_output or f"Command exited with code {result.exit_code}",
                code="CLI_COMMAND_FAILED",
                retryable=True,
            )
        return _success_payload(
            command=command,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )


class CLIReadOutputTool(Tool):
    def __init__(self, session: _CLISession) -> None:
        self.session = session

    def name(self) -> str:
        return "read_output"

    def description(self) -> str:
        return "Read output from the most recent CLI command."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def annotations(self) -> dict:
        return {"title": "Read Output", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self.session.last_output:
            return _error_payload("No output is available.", code="NO_OUTPUT", retryable=False)
        return _success_payload(output=self.session.last_output)


class CLIWaitForOutputTool(Tool):
    def __init__(self, session: _CLISession) -> None:
        self.session = session

    def name(self) -> str:
        return "wait_for_output"

    def description(self) -> str:
        return "Wait until output contains specific text."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "timeout": {"type": "number", "default": 30},
            },
            "required": ["text"],
        }

    def annotations(self) -> dict:
        return {"title": "Wait for Output", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = str(kwargs["text"])
        timeout = float(kwargs.get("timeout", 30))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if text in self.session.last_output:
                return _success_payload(text=text)
            await asyncio.sleep(0.5)
        return _error_payload(
            f"Timed out waiting for output '{text}'.",
            code="CLI_OUTPUT_TIMEOUT",
            retryable=True,
        )


class CLIWaitForFileTool(Tool):
    def name(self) -> str:
        return "wait_for_file"

    def description(self) -> str:
        return "Wait for a file condition."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "condition": {"type": "string", "default": "exists"},
                "timeout": {"type": "number", "default": 30},
            },
            "required": ["file_path"],
        }

    def annotations(self) -> dict:
        return {"title": "Wait for File", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        file_path = str(kwargs["file_path"])
        condition = str(kwargs.get("condition", "exists")).lower()
        timeout = float(kwargs.get("timeout", 30))
        deadline = time.time() + timeout
        initial_mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else None
        while time.time() < deadline:
            exists = os.path.exists(file_path)
            if condition == "exists" and exists:
                return _success_payload(file_path=file_path, condition=condition)
            if condition == "modified" and exists and initial_mtime is not None and os.path.getmtime(file_path) > initial_mtime:
                return _success_payload(file_path=file_path, condition=condition)
            if condition == "size" and exists and os.path.getsize(file_path) > 0:
                return _success_payload(file_path=file_path, condition=condition)
            await asyncio.sleep(0.5)
        return _error_payload(
            f"Timed out waiting for file condition '{condition}' on '{file_path}'.",
            code="CLI_FILE_TIMEOUT",
            retryable=True,
        )


def build_cli_tools() -> dict[str, Tool]:
    session = _CLISession()
    tools: list[Tool] = [
        CLIRunCommandTool(session),
        CLIReadOutputTool(session),
        CLIWaitForOutputTool(session),
        CLIWaitForFileTool(),
    ]
    return {tool.name(): tool for tool in tools}
