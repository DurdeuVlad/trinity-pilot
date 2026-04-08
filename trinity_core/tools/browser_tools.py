"""Browser domain tools built on top of BrowserAdapter."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..adapters.browser import BrowserAdapter
from ..models import TaskInput
from .base import Tool, ToolResult


class _BrowserTool(Tool):
    def __init__(self, adapter: BrowserAdapter) -> None:
        self.adapter = adapter

    async def _run_adapter(self, description: str, context: dict[str, Any] | None = None) -> ToolResult:
        try:
            task = TaskInput(
                task_id=f"tool-browser-{uuid.uuid4().hex[:12]}",
                description=description,
                domain="web",
                context=context or {},
            )
            result = await self.adapter.execute(task)
            if result.status == "success":
                output_data = {"success": True, **result.metadata}
                return ToolResult(status="success", output=json.dumps(output_data))
            error_msg = result.error or "browser task failed"
            output_data = {"success": False, "error_code": "BROWSER_TASK_FAILED", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="BROWSER_TASK_FAILED",
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


class BrowserNavigateTool(_BrowserTool):
    def name(self) -> str:
        return "navigate"

    def description(self) -> str:
        return "Navigate to a URL in the browser"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "url" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: url"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: url",
                error_code="INVALID_ARG",
                retryable=False,
            )
        url = str(kwargs["url"])
        return await self._run_adapter(f"Navigate to {url}")


class BrowserClickTool(_BrowserTool):
    def name(self) -> str:
        return "click"

    def description(self) -> str:
        return "Click an element in the browser"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "selector" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: selector"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: selector",
                error_code="INVALID_ARG",
                retryable=False,
            )
        selector = str(kwargs["selector"])
        return await self._run_adapter(f"Click the element matching selector '{selector}'")


class BrowserTypeTool(_BrowserTool):
    def name(self) -> str:
        return "type"

    def description(self) -> str:
        return "Type text into an input element"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["selector", "text"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "selector" not in kwargs or "text" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameters: selector and text"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameters: selector and text",
                error_code="INVALID_ARG",
                retryable=False,
            )
        selector = str(kwargs["selector"])
        text = str(kwargs["text"])
        return await self._run_adapter(f"Type '{text}' into selector '{selector}'")


class BrowserExtractTool(_BrowserTool):
    def name(self) -> str:
        return "extract"

    def description(self) -> str:
        return "Extract text from elements matching a selector"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "limit": {"type": "number"},
            },
            "required": ["selector"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "selector" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: selector"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: selector",
                error_code="INVALID_ARG",
                retryable=False,
            )
        selector = str(kwargs["selector"])
        limit = kwargs.get("limit")
        limit_text = f" (up to {int(limit)} items)" if limit is not None else ""
        return await self._run_adapter(f"Extract data from selector '{selector}'{limit_text}")


class BrowserScreenshotTool(_BrowserTool):
    def name(self) -> str:
        return "screenshot"

    def description(self) -> str:
        return "Take a screenshot of the current page"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path")
        suffix = f" at path '{path}'" if path else ""
        return await self._run_adapter(f"Take a screenshot{suffix}")


class BrowserWaitForElementTool(_BrowserTool):
    def name(self) -> str:
        return "wait_for_element"

    def description(self) -> str:
        return "Wait until an element reaches the requested visibility state"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
                "state": {"type": "string", "default": "visible"},
            },
            "required": ["selector"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if "selector" not in kwargs:
            output_data = {"success": False, "error_code": "INVALID_ARG", "message": "Missing required parameter: selector"}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error="Missing required parameter: selector",
                error_code="INVALID_ARG",
                retryable=False,
            )
        selector = str(kwargs["selector"])
        timeout = float(kwargs.get("timeout", 10))
        state = str(kwargs.get("state", "visible"))
        try:
            await self.adapter.wait_for_selector(selector=selector, timeout=timeout, state=state)
            output_data = {"success": True, "selector": selector, "state": state}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for element '{selector}' with state '{state}': {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


class BrowserWaitForNavigationTool(_BrowserTool):
    def name(self) -> str:
        return "wait_for_navigation"

    def description(self) -> str:
        return "Wait for browser navigation to complete"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timeout": {"type": "number", "default": 30},
                "wait_until": {"type": "string", "default": "load"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        timeout = float(kwargs.get("timeout", 30))
        wait_until = str(kwargs.get("wait_until", "load"))
        try:
            await self.adapter.wait_for_load_state(wait_until=wait_until, timeout=timeout)
            output_data = {"success": True, "state": wait_until}
            return ToolResult(status="success", output=json.dumps(output_data))
        except Exception as exc:
            error_msg = f"Timed out waiting for navigation: {exc}"
            output_data = {"success": False, "error_code": "TIMEOUT", "message": error_msg}
            return ToolResult(
                status="error",
                output=json.dumps(output_data),
                error=error_msg,
                error_code="TIMEOUT",
                retryable=True,
            )


class BrowserWaitForTextTool(_BrowserTool):
    def name(self) -> str:
        return "wait_for_text"

    def description(self) -> str:
        return "Wait for specific text to appear on the page"

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
        return await self._run_adapter(
            f"Wait up to {timeout}s until text '{text}' appears on the current page"
        )


def build_browser_tools(adapter: BrowserAdapter) -> dict[str, Tool]:
    tools: list[Tool] = [
        BrowserNavigateTool(adapter),
        BrowserClickTool(adapter),
        BrowserTypeTool(adapter),
        BrowserExtractTool(adapter),
        BrowserScreenshotTool(adapter),
        BrowserWaitForElementTool(adapter),
        BrowserWaitForNavigationTool(adapter),
        BrowserWaitForTextTool(adapter),
    ]
    return {tool.name(): tool for tool in tools}
