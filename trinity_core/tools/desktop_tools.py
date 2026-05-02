"""Desktop MCP tools wired directly to desktop automation primitives."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
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


def get_focused_window() -> str:
    return _load_uia_tools().get_focused_window()


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
        windows_before = await asyncio.to_thread(list_open_windows)
        raw = await asyncio.to_thread(launch_app, str(kwargs.get("app_exe_path") or app_name))
        if not raw.startswith("ERROR:"):
            title = await asyncio.to_thread(_wait_for_matching_window, app_name, 8.0)
            focus_result = await asyncio.to_thread(focus_window, title or raw)
            active_window = title or raw
            was_existing = any(active_window.lower() in w.lower() for w in windows_before)
            self.state.active_app = title or app_name
            return _success_payload(
                result=raw,
                app_name=app_name,
                active_window=active_window,
                was_existing=was_existing,
                focus_result=focus_result,
                open_windows=await asyncio.to_thread(list_open_windows),
            )

        recovered = await asyncio.to_thread(_launch_wait_attach, app_name, str(kwargs.get("app_exe_path") or ""))
        if recovered["success"]:
            active_window = recovered.get("active_window") or app_name
            was_existing = any(active_window.lower() in w.lower() for w in windows_before)
            self.state.active_app = active_window
            return _success_payload(app_name=app_name, was_existing=was_existing, **recovered)
        return ToolResult(
            status="error",
            output=json.dumps({"success": False, "error_code": "DESKTOP_OPEN_FAILED", **recovered}),
            error=recovered["message"],
            error_code="DESKTOP_OPEN_FAILED",
            retryable=True,
            metadata=recovered,
        )


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


class DesktopListWindowsTool(Tool):
    def name(self) -> str:
        return "list_windows"

    def description(self) -> str:
        return "List all currently visible desktop window titles."

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def annotations(self) -> dict:
        return {"title": "List Windows", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        titles = await asyncio.to_thread(list_open_windows)
        visible = [t for t in titles if t and t.strip()][:20]
        return _success_payload(windows=visible)


class DesktopGetFocusedWindowTool(Tool):
    def name(self) -> str:
        return "get_focused_window"

    def description(self) -> str:
        return "Return the title of the currently focused (foreground) window."

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def annotations(self) -> dict:
        return {"title": "Get Focused Window", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

    async def execute(self, **kwargs: Any) -> ToolResult:
        raw = await asyncio.to_thread(get_focused_window)
        if raw.startswith("ERROR:"):
            return _error_payload(raw[7:].strip(), code="DESKTOP_FOCUS_READ_FAILED", retryable=False)
        return _success_payload(title=raw)


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
        DesktopListWindowsTool(),
        DesktopGetFocusedWindowTool(),
    ]
    return {tool.name(): tool for tool in tools}


def _launch_wait_attach(app_name: str, app_exe_path: str = "") -> dict[str, Any]:
    exe = app_exe_path.strip() or _known_desktop_exe(app_name)
    launch_error = ""
    if exe:
        try:
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            launch_error = str(exc)

    title = _wait_for_matching_window(app_name, timeout=12.0)
    if title:
        focus_result = focus_window(title)
        return {
            "success": True,
            "result": f"Opened {app_name}",
            "active_window": title,
            "focus_result": focus_result,
            "open_windows": list_open_windows(),
        }

    windows = list_open_windows()
    return {
        "success": False,
        "message": (
            f"Launched {app_name} but no matching window was attachable."
            + (f" Launch error: {launch_error}" if launch_error else "")
        ),
        "active_window": "",
        "open_windows": windows,
        "process_running": check_app_running(app_name) or bool(exe and check_app_running(Path(exe).stem)),
    }


def _known_desktop_exe(app_name: str) -> str:
    key = app_name.lower().replace(".exe", "").strip()
    known = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "paint": "mspaint.exe",
    }
    return known.get(key, app_name)


def _wait_for_matching_window(app_name: str, timeout: float) -> str:
    aliases = _window_aliases(app_name)
    deadline = time.time() + timeout
    while time.time() < deadline:
        windows = list_open_windows()
        for window in windows:
            lowered = window.lower()
            if any(alias in lowered for alias in aliases):
                return window
        time.sleep(0.5)
    return ""


def _window_aliases(app_name: str) -> list[str]:
    key = app_name.lower().replace(".exe", "").strip()
    aliases = {
        "notepad": ["notepad", "untitled"],
        "calculator": ["calculator", "calc"],
        "calc": ["calculator", "calc"],
    }
    return aliases.get(key, [key])
