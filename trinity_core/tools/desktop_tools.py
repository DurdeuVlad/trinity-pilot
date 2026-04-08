"""Desktop domain tools built on top of DesktopAdapter."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from ..adapters.desktop import DesktopAdapter
from ..models import TaskInput
from .base import Tool, ToolResult


class _DesktopTool(Tool):
    def __init__(self, adapter: DesktopAdapter) -> None:
        self.adapter = adapter

    async def _run_adapter(self, description: str, context: dict[str, Any] | None = None) -> ToolResult:
        try:
            task = TaskInput(
                task_id=f"tool-desktop-{uuid.uuid4().hex[:12]}",
                description=description,
                domain="desktop",
                context=context or {},
            )
            result = await self.adapter.execute(task)
            if result.status == "success":
                output_data = {"success": True, **result.metadata}
                return ToolResult(status="success", output=json.dumps(output_data))
            error_msg = result.error or "desktop task failed"
            output_data = {"success": False, "error_code": "DESKTOP_TASK_FAILED", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="DESKTOP_TASK_FAILED",
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


class DesktopOpenAppTool(_DesktopTool):
    def name(self) -> str:
        return "open_app"

    def description(self) -> str:
        return "Open a desktop application"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "app_name" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: app_name"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: app_name",
                error_code="INVALID_ARG",
                retryable=False,
            )
        app_name = str(kwargs["app_name"])
        app_exe_path = kwargs.get("app_exe_path")
        context = {"app_name": app_name}
        if app_exe_path:
            context["app_exe_path"] = str(app_exe_path)
        return await self._run_adapter(f"Open {app_name}", context=context)


class DesktopClickTool(_DesktopTool):
    def name(self) -> str:
        return "click"

    def description(self) -> str:
        return "Click a desktop UI element"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "element_name": {"type": "string"},
                "element_type": {"type": "string"},
            },
            "required": ["element_name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "element_name" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: element_name"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: element_name",
                error_code="INVALID_ARG",
                retryable=False,
            )
        element_name = str(kwargs["element_name"])
        element_type = kwargs.get("element_type")
        extra = f" of type '{element_type}'" if element_type else ""
        return await self._run_adapter(f"Click desktop element '{element_name}'{extra}")


class DesktopTypeTool(_DesktopTool):
    def name(self) -> str:
        return "type"

    def description(self) -> str:
        return "Type text in the active desktop window"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
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
        return await self._run_adapter(f"Type '{text}' in the active window")


class DesktopFocusTool(_DesktopTool):
    def name(self) -> str:
        return "focus"

    def description(self) -> str:
        return "Bring a desktop window to the foreground"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"window_title": {"type": "string"}},
            "required": ["window_title"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "window_title" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: window_title"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: window_title",
                error_code="INVALID_ARG",
                retryable=False,
            )
        title = str(kwargs["window_title"])
        return await self._run_adapter(f"Focus window with title containing '{title}'", context={"focus_only": True})


async def _poll(condition: Any, timeout: float, failure_message: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await condition():
            return
        await asyncio.sleep(0.5)
    raise TimeoutError(failure_message)


class DesktopWaitForAppTool(_DesktopTool):
    def name(self) -> str:
        return "wait_for_app"

    def description(self) -> str:
        return "Wait for a desktop app process to start"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"},
                "timeout": {"type": "number", "default": 15},
            },
            "required": ["app_name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "app_name" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: app_name"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: app_name",
                error_code="INVALID_ARG",
                retryable=False,
            )
        app_name = str(kwargs["app_name"])
        timeout = float(kwargs.get("timeout", 15))
        try:
            await self.adapter.wait_for_process(app_name=app_name, timeout=timeout)
            output_data = {"success": True, "app_name": app_name}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for app '{app_name}': {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


class DesktopWaitForWindowTool(_DesktopTool):
    def name(self) -> str:
        return "wait_for_window"

    def description(self) -> str:
        return "Wait for a desktop window title"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
            "required": ["title"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "title" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: title"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: title",
                error_code="INVALID_ARG",
                retryable=False,
            )
        title = str(kwargs["title"])
        timeout = float(kwargs.get("timeout", 10))
        try:
            await self.adapter.wait_for_window_title(title=title, timeout=timeout)
            output_data = {"success": True, "title": title}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for window '{title}': {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


class DesktopWaitForElementTool(_DesktopTool):
    def name(self) -> str:
        return "wait_for_element"

    def description(self) -> str:
        return "Wait for a desktop UI element to appear"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "element_name": {"type": "string"},
                "element_type": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
            "required": ["element_name"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "element_name" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: element_name"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: element_name",
                error_code="INVALID_ARG",
                retryable=False,
            )
        element_name = str(kwargs["element_name"])
        element_type = kwargs.get("element_type")
        timeout = float(kwargs.get("timeout", 10))
        try:
            await self.adapter.wait_for_ui_element(
                element_name=element_name,
                element_type=str(element_type) if element_type is not None else None,
                timeout=timeout,
            )
            output_data = {"success": True, "element_name": element_name}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for element '{element_name}': {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


class DesktopWaitForTextTool(_DesktopTool):
    def name(self) -> str:
        return "wait_for_text"

    def description(self) -> str:
        return "Wait for text to appear in the active window"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
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
        timeout = float(kwargs.get("timeout", 10))
        try:
            await self.adapter.wait_for_text_in_window(text=text, timeout=timeout)
            output_data = {"success": True, "text": text}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for text '{text}': {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


def build_desktop_tools(adapter: DesktopAdapter) -> dict[str, Tool]:
    tools: list[Tool] = [
        DesktopOpenAppTool(adapter),
        DesktopClickTool(adapter),
        DesktopTypeTool(adapter),
        DesktopFocusTool(adapter),
        DesktopWaitForAppTool(adapter),
        DesktopWaitForWindowTool(adapter),
        DesktopWaitForElementTool(adapter),
        DesktopWaitForTextTool(adapter),
    ]
    return {tool.name(): tool for tool in tools}
