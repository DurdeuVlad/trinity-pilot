"""CLI domain tools built on top of CLIAdapter."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any

from ..adapters.cli import CLIAdapter
from ..models import TaskInput
from .base import Tool, ToolResult


class _CLITool(Tool):
    def __init__(self, adapter: CLIAdapter) -> None:
        self.adapter = adapter
        self._last_output = ""

    async def _run_adapter(self, description: str, context: dict[str, Any] | None = None) -> ToolResult:
        try:
            task = TaskInput(
                task_id=f"tool-cli-{uuid.uuid4().hex[:12]}",
                description=description,
                domain="cli",
                context=context or {},
            )
            result = await self.adapter.execute(task)
            if result.status == "success":
                self._last_output = (result.error or "") if result.error else str(result.metadata)
                output_data = {"success": True, **result.metadata}
                return ToolResult(status="success", output=json.dumps(output_data), metadata=result.metadata)
            error_msg = result.error or "cli task failed"
            output_data = {"success": False, "error_code": "CLI_TASK_FAILED", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="CLI_TASK_FAILED",
                retryable=True,
            )
        except Exception as exc:
            output_data = {"success": False, "error_code": "EXCEPTION", "message": str(exc)}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=str(exc),
                error_code="EXCEPTION",
                retryable=False,
            )


class CLIRunCommandTool(_CLITool):
    def name(self) -> str:
        return "run_command"

    def description(self) -> str:
        return "Run a shell command"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "async_mode": {"type": "boolean", "default": False},
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "command" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: command"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: command",
                error_code="INVALID_ARG",
                retryable=False,
            )
        command = str(kwargs["command"])
        async_mode = bool(kwargs.get("async_mode", False))
        if async_mode:
            process_id = f"async-process:{uuid.uuid4().hex[:8]}"
            output_data = {"success": True, "process_id": process_id}
            return ToolResult(status="success", output=json.dumps(output_data))
        return await self._run_adapter(f"Run this command and return output: {command}")


class CLIReadOutputTool(_CLITool):
    def name(self) -> str:
        return "read_output"

    def description(self) -> str:
        return "Read output from the last CLI command"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._last_output:
            output_data = {"success": False, "error_code": "NO_OUTPUT", "message": "No output is available"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="No output is available",
                error_code="NO_OUTPUT",
                retryable=False,
            )
        output_data = {"success": True, "output": self._last_output}
        return ToolResult(status="success", output=json.dumps(output_data))


class CLIWaitForOutputTool(_CLITool):
    def name(self) -> str:
        return "wait_for_output"

    def description(self) -> str:
        return "Wait until command output contains specific text"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "timeout": {"type": "number", "default": 30},
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "text" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: text"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: text",
                error_code="INVALID_ARG",
                retryable=False,
            )
        text = str(kwargs["text"])
        timeout = float(kwargs.get("timeout", 30))
        try:
            await self.adapter.wait_for_output_contains(text=text, timeout=timeout)
            output_data = {"success": True, "text": text}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for output '{text}': {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


class CLIWaitForProcessTool(_CLITool):
    def name(self) -> str:
        return "wait_for_process"

    def description(self) -> str:
        return "Wait for a process to exit"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "process_id": {"type": "string"},
                "timeout": {"type": "number", "default": 60},
            },
            "required": ["process_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "process_id" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: process_id"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: process_id",
                error_code="INVALID_ARG",
                retryable=False,
            )
        process_id = str(kwargs["process_id"])
        timeout = float(kwargs.get("timeout", 60))
        try:
            await self.adapter.wait_for_process_exit(process_id=process_id, timeout=timeout)
            output_data = {"success": True, "process_id": process_id}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for process {process_id}: {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


class CLIWaitForFileTool(_CLITool):
    def name(self) -> str:
        return "wait_for_file"

    def description(self) -> str:
        return "Wait for a file condition"

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

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "file_path" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: file_path"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: file_path",
                error_code="INVALID_ARG",
                retryable=False,
            )
        file_path = str(kwargs["file_path"])
        condition = str(kwargs.get("condition", "exists"))
        timeout = float(kwargs.get("timeout", 30))
        try:
            await self.adapter.wait_for_file_condition(
                file_path=file_path,
                condition=condition,
                timeout=timeout,
            )
            output_data = {"success": True, "file_path": file_path, "condition": condition}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for file condition: {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


def build_cli_tools(adapter: CLIAdapter) -> dict[str, Tool]:
    tools: list[Tool] = [
        CLIRunCommandTool(adapter),
        CLIReadOutputTool(adapter),
        CLIWaitForOutputTool(adapter),
        CLIWaitForProcessTool(adapter),
        CLIWaitForFileTool(adapter),
    ]
    return {tool.name(): tool for tool in tools}
