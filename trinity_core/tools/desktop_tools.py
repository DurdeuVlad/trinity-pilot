"""Desktop MCP tools wired directly to desktop automation primitives."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_MODULE_ROOT = PROJECT_ROOT / "api-accessibility-poc"
_UIA_TOOLS = None


def _load_uia_tools():
    global _UIA_TOOLS
    if _UIA_TOOLS is None:
        spec = importlib.util.spec_from_file_location(
            "trinity_desktop_uia_tools",
            DESKTOP_MODULE_ROOT / "tools" / "uia_tools.py",
        )
        if spec is None or spec.loader is None:
            raise ImportError("Unable to load desktop UIA tools module.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _UIA_TOOLS = module
    return _UIA_TOOLS


def check_app_running(name: str) -> bool:
    return _load_uia_tools().check_app_running(name)


def click_element(app: str, description: str) -> str:
    return _load_uia_tools().click_element(app, description)


def find_element_exists(app: str, element_description: str) -> str:
    return _load_uia_tools().find_element_exists(app, element_description)


def focus_window(title: str) -> str:
    return _load_uia_tools().focus_window(title)


def launch_app(name: str) -> str:
    return _load_uia_tools().launch_app(name)


def list_open_windows() -> list[str]:
    return _load_uia_tools().list_open_windows()


def read_window_content(app: str) -> str:
    return _load_uia_tools().read_window_content(app)


def type_text(text: str) -> str:
    return _load_uia_tools().type_text(text)

from .base import Tool, ToolResult


class _DesktopState:
    def __init__(self) -> None:
        self.active_app = ""


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


def _result_from_desktop_output(raw: str, *, code: str = "DESKTOP_TOOL_FAILED") -> ToolResult:
    if raw.startswith("ERROR:"):
        return _error_payload(raw[7:].strip(), code=code, retryable=True)
    return _success_payload(result=raw)


class DesktopOpenAppTool(Tool):
    def __init__(self, state: _DesktopState) -> None:
        self.state = state

    def name(self) -> str:
        return "open_app"

    def description(self) -> str:
        return "Open a desktop application by name or executable path."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {"type": "string"},
                "app_exe_path": {"type": "string"},
            },
            "required": ["app_name"],
        }

    def annotations(self) -> dict:
        return {"title": "Open Application", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        app_name = str(kwargs["app_name"])
        raw = await asyncio.to_thread(launch_app, str(kwargs.get("app_exe_path") or app_name))
        if not raw.startswith("ERROR:"):
            self.state.active_app = app_name
            return _success_payload(result=raw, app_name=app_name)
        return _result_from_desktop_output(raw, code="DESKTOP_OPEN_FAILED")


class DesktopClickTool(Tool):
    def __init__(self, state: _DesktopState) -> None:
        self.state = state

    def name(self) -> str:
        return "click"

    def description(self) -> str:
        return "Click a desktop UI element in the active or specified app."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "element_name": {"type": "string"},
                "app": {"type": "string"},
            },
            "required": ["element_name"],
        }

    def annotations(self) -> dict:
        return {"title": "Click Element", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        app = str(kwargs.get("app") or self.state.active_app)
        if not app:
            return _error_payload("No active desktop app is selected.", code="NO_ACTIVE_APP", retryable=False)
        raw = await asyncio.to_thread(click_element, app, str(kwargs["element_name"]))
        if not raw.startswith("ERROR:"):
            return _success_payload(result=raw, app=app, element=str(kwargs["element_name"]))
        return _result_from_desktop_output(raw, code="DESKTOP_CLICK_FAILED")


class DesktopTypeTool(Tool):
    def name(self) -> str:
        return "type"

    def description(self) -> str:
        return "Type text into the currently focused desktop control."

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    def annotations(self) -> dict:
        return {"title": "Type Text", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = str(kwargs["text"])
        raw = await asyncio.to_thread(type_text, text)
        if not raw.startswith("ERROR:"):
            return _success_payload(result=raw, text=text)
        return _result_from_desktop_output(raw, code="DESKTOP_TYPE_FAILED")


class DesktopFocusTool(Tool):
    def __init__(self, state: _DesktopState) -> None:
        self.state = state

    def name(self) -> str:
        return "focus"

    def description(self) -> str:
        return "Bring a desktop window to the foreground."

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"window_title": {"type": "string"}}, "required": ["window_title"]}

    def annotations(self) -> dict:
        return {"title": "Focus Window", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        title = str(kwargs["window_title"])
        raw = await asyncio.to_thread(focus_window, title)
        if not raw.startswith("ERROR:"):
            self.state.active_app = title
            return _success_payload(result=raw, title=title)
        return _result_from_desktop_output(raw, code="DESKTOP_FOCUS_FAILED")


class DesktopWaitForAppTool(Tool):
    def name(self) -> str:
        return "wait_for_app"

    def description(self) -> str:
        return "Wait for a desktop app process to start."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"app_name": {"type": "string"}, "timeout": {"type": "number", "default": 15}},
            "required": ["app_name"],
        }

    def annotations(self) -> dict:
        return {"title": "Wait for App", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        app_name = str(kwargs["app_name"])
        deadline = time.time() + float(kwargs.get("timeout", 15))
        while time.time() < deadline:
            if await asyncio.to_thread(check_app_running, app_name):
                return _success_payload(app_name=app_name)
            await asyncio.sleep(0.5)
        return _error_payload(f"Timed out waiting for app '{app_name}'.", code="DESKTOP_APP_TIMEOUT", retryable=True)


class DesktopWaitForWindowTool(Tool):
    def name(self) -> str:
        return "wait_for_window"

    def description(self) -> str:
        return "Wait for a desktop window title to appear."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"title": {"type": "string"}, "timeout": {"type": "number", "default": 10}},
            "required": ["title"],
        }

    def annotations(self) -> dict:
        return {"title": "Wait for Window", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        title = str(kwargs["title"])
        deadline = time.time() + float(kwargs.get("timeout", 10))
        while time.time() < deadline:
            windows = await asyncio.to_thread(list_open_windows)
            if any(title.lower() in window.lower() for window in windows):
                return _success_payload(title=title)
            await asyncio.sleep(0.5)
        return _error_payload(f"Timed out waiting for window '{title}'.", code="DESKTOP_WINDOW_TIMEOUT", retryable=True)


class DesktopWaitForElementTool(Tool):
    def __init__(self, state: _DesktopState) -> None:
        self.state = state

    def name(self) -> str:
        return "wait_for_element"

    def description(self) -> str:
        return "Wait for a desktop UI element to appear."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "element_name": {"type": "string"},
                "app": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
            "required": ["element_name"],
        }

    def annotations(self) -> dict:
        return {"title": "Wait for Element", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        app = str(kwargs.get("app") or self.state.active_app)
        if not app:
            return _error_payload("No active desktop app is selected.", code="NO_ACTIVE_APP", retryable=False)
        element_name = str(kwargs["element_name"])
        deadline = time.time() + float(kwargs.get("timeout", 10))
        while time.time() < deadline:
            if await asyncio.to_thread(find_element_exists, app, element_name) == "true":
                return _success_payload(app=app, element_name=element_name)
            await asyncio.sleep(0.5)
        return _error_payload(
            f"Timed out waiting for element '{element_name}'.",
            code="DESKTOP_ELEMENT_TIMEOUT",
            retryable=True,
        )


class DesktopWaitForTextTool(Tool):
    def __init__(self, state: _DesktopState) -> None:
        self.state = state

    def name(self) -> str:
        return "wait_for_text"

    def description(self) -> str:
        return "Wait for text to appear in the active or specified app window."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "app": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
            "required": ["text"],
        }

    def annotations(self) -> dict:
        return {"title": "Wait for Text", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        app = str(kwargs.get("app") or self.state.active_app)
        if not app:
            return _error_payload("No active desktop app is selected.", code="NO_ACTIVE_APP", retryable=False)
        text = str(kwargs["text"])
        deadline = time.time() + float(kwargs.get("timeout", 10))
        while time.time() < deadline:
            content = await asyncio.to_thread(read_window_content, app)
            if not content.startswith("ERROR:") and text in content:
                return _success_payload(app=app, text=text)
            await asyncio.sleep(0.5)
        return _error_payload(f"Timed out waiting for text '{text}'.", code="DESKTOP_TEXT_TIMEOUT", retryable=True)


def build_desktop_tools() -> dict[str, Tool]:
    state = _DesktopState()
    tools: list[Tool] = [
        DesktopOpenAppTool(state),
        DesktopClickTool(state),
        DesktopTypeTool(),
        DesktopFocusTool(state),
        DesktopWaitForAppTool(),
        DesktopWaitForWindowTool(),
        DesktopWaitForElementTool(state),
        DesktopWaitForTextTool(state),
    ]
    return {tool.name(): tool for tool in tools}
