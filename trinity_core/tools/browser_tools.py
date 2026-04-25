"""Browser MCP tools wired directly to browser automation primitives."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BROWSER_MODULE_ROOT = PROJECT_ROOT / "browser-gui-automation"
_PLAYWRIGHT_TOOLS = None


def _load_playwright_tools():
    global _PLAYWRIGHT_TOOLS
    if _PLAYWRIGHT_TOOLS is None:
        spec = importlib.util.spec_from_file_location(
            "trinity_browser_playwright_tools",
            BROWSER_MODULE_ROOT / "tools" / "playwright_tools.py",
        )
        if spec is None or spec.loader is None:
            raise ImportError("Unable to load browser Playwright tools module.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PLAYWRIGHT_TOOLS = module
    return _PLAYWRIGHT_TOOLS


async def _ensure_session():
    return await _load_playwright_tools()._ensure_session()


async def navigate(url: str) -> str:
    return await _load_playwright_tools().navigate(url)


async def click_element(selector_or_desc: str) -> str:
    return await _load_playwright_tools().click_element(selector_or_desc)


async def type_text(selector: str, text: str) -> str:
    return await _load_playwright_tools().type_text(selector, text)


async def screenshot(selector: str | None = None, file_path: str | None = None, full_page: bool = False) -> str:
    return await _load_playwright_tools().screenshot(selector=selector, file_path=file_path, full_page=full_page)


async def wait_for_element(selector: str, timeout: float = 10.0, state: str = "visible") -> str:
    return await _load_playwright_tools().wait_for_element(selector=selector, timeout=timeout, state=state)


async def get_current_url() -> str:
    return await _load_playwright_tools().get_current_url()


async def get_page_title() -> str:
    return await _load_playwright_tools().get_page_title()

from .base import Tool, ToolResult


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


def _result_from_browser_output(
    raw: str,
    *,
    code: str = "BROWSER_TOOL_FAILED",
    retryable: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    if raw.startswith("ERROR:"):
        return _error_payload(raw[7:].strip(), code=code, retryable=retryable)
    return ToolResult(
        status="success",
        output=json.dumps({"success": True, "result": raw, **(metadata or {})}),
        metadata={"result": raw, **(metadata or {})},
    )


class BrowserNavigateTool(Tool):
    def name(self) -> str:
        return "navigate"

    def description(self) -> str:
        return "Navigate the active browser session to a URL."

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}

    def annotations(self) -> dict:
        return {"title": "Navigate to URL", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return _result_from_browser_output(await navigate(str(kwargs["url"])))


class BrowserClickTool(Tool):
    def name(self) -> str:
        return "click"

    def description(self) -> str:
        return "Click a browser element by CSS selector or visible text description."

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}

    def annotations(self) -> dict:
        return {"title": "Click Element", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return _result_from_browser_output(await click_element(str(kwargs["selector"])))


class BrowserTypeTool(Tool):
    def name(self) -> str:
        return "type"

    def description(self) -> str:
        return "Type text into a browser input element."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"selector": {"type": "string"}, "text": {"type": "string"}},
            "required": ["selector", "text"],
        }

    def annotations(self) -> dict:
        return {"title": "Type Text", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return _result_from_browser_output(await type_text(str(kwargs["selector"]), str(kwargs["text"])))


class BrowserExtractTool(Tool):
    def name(self) -> str:
        return "extract"

    def description(self) -> str:
        return "Extract text from browser elements matching a selector."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"selector": {"type": "string"}, "limit": {"type": "number"}},
            "required": ["selector"],
        }

    def annotations(self) -> dict:
        return {"title": "Extract Text", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            page = await _ensure_session()
            locator = page.locator(str(kwargs["selector"]))
            texts = [item.strip() for item in await locator.all_inner_texts() if item.strip()]
            limit = kwargs.get("limit")
            if limit is not None:
                texts = texts[: int(limit)]
            return _success_payload(items=texts, count=len(texts))
        except Exception as exc:
            return _error_payload(str(exc), code="BROWSER_EXTRACT_FAILED", retryable=True)


class BrowserScreenshotTool(Tool):
    def name(self) -> str:
        return "screenshot"

    def description(self) -> str:
        return "Capture a screenshot of the current page."

    def annotations(self) -> dict:
        return {"title": "Take Screenshot", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "selector": {"type": "string"},
                "full_page": {"type": "boolean"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        file_path = kwargs.get("path")
        raw = await screenshot(
            selector=str(kwargs["selector"]) if kwargs.get("selector") else None,
            file_path=str(file_path) if file_path else None,
            full_page=bool(kwargs.get("full_page", False)),
        )
        metadata = {"artifact_path": str(file_path), "artifacts": [str(file_path)]} if file_path else {}
        return _result_from_browser_output(raw, code="BROWSER_SCREENSHOT_FAILED", metadata=metadata)


class BrowserWaitForElementTool(Tool):
    def name(self) -> str:
        return "wait_for_element"

    def description(self) -> str:
        return "Wait for an element to reach the requested state."

    def annotations(self) -> dict:
        return {"title": "Wait for Element", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

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
        raw = await wait_for_element(
            selector=str(kwargs["selector"]),
            timeout=float(kwargs.get("timeout", 10)),
            state=str(kwargs.get("state", "visible")),
        )
        return _result_from_browser_output(raw, code="BROWSER_WAIT_FAILED")


class BrowserWaitForNavigationTool(Tool):
    def name(self) -> str:
        return "wait_for_navigation"

    def description(self) -> str:
        return "Wait for browser navigation to settle."

    def annotations(self) -> dict:
        return {"title": "Wait for Navigation", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

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
        try:
            page = await _ensure_session()
            await page.wait_for_load_state(
                state=str(kwargs.get("wait_until", "load")),
                timeout=float(kwargs.get("timeout", 30)) * 1000,
            )
            return _success_payload(url=await get_current_url(), title=await get_page_title())
        except Exception as exc:
            return _error_payload(str(exc), code="BROWSER_NAVIGATION_TIMEOUT", retryable=True)


class BrowserWaitForTextTool(Tool):
    def name(self) -> str:
        return "wait_for_text"

    def description(self) -> str:
        return "Wait until specific text appears on the page."

    def annotations(self) -> dict:
        return {"title": "Wait for Text", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}, "timeout": {"type": "number", "default": 10}},
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = str(kwargs["text"])
        deadline = time.time() + float(kwargs.get("timeout", 10))
        while time.time() < deadline:
            page = await _ensure_session()
            body_text = await page.inner_text("body")
            if text in body_text:
                return _success_payload(text=text)
            await asyncio.sleep(0.5)
        return _error_payload(
            f"Timed out waiting for text '{text}' to appear.",
            code="BROWSER_TEXT_TIMEOUT",
            retryable=True,
        )


def build_browser_tools() -> dict[str, Tool]:
    tools: list[Tool] = [
        BrowserNavigateTool(),
        BrowserClickTool(),
        BrowserTypeTool(),
        BrowserExtractTool(),
        BrowserScreenshotTool(),
        BrowserWaitForElementTool(),
        BrowserWaitForNavigationTool(),
        BrowserWaitForTextTool(),
    ]
    return {tool.name(): tool for tool in tools}
