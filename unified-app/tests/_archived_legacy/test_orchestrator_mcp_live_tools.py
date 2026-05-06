from __future__ import annotations

import json
import sys
import types

import pytest

_mcp_module = types.ModuleType("mcp")
_mcp_server_module = types.ModuleType("mcp.server")
_mcp_stdio_module = types.ModuleType("mcp.server.stdio")
_mcp_types_module = types.ModuleType("mcp.types")


class _DummyServer:
    def __init__(self, *_args, **_kwargs):
        pass

    def list_tools(self):
        def decorator(fn):
            return fn
        return decorator

    def call_tool(self):
        def decorator(fn):
            return fn
        return decorator


class _DummyTextContent:
    def __init__(self, *, type: str, text: str):
        self.type = type
        self.text = text


class _DummyTool:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


_mcp_server_module.Server = _DummyServer
_mcp_stdio_module.stdio_server = object
_mcp_types_module.TextContent = _DummyTextContent
_mcp_types_module.Tool = _DummyTool
sys.modules["mcp"] = _mcp_module
sys.modules["mcp.server"] = _mcp_server_module
sys.modules["mcp.server.stdio"] = _mcp_stdio_module
sys.modules["mcp.types"] = _mcp_types_module

from mcp_server.orchestrator_mcp import OrchestratorMCPServer


@pytest.mark.asyncio
async def test_start_ui_uses_startup_helper(monkeypatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(
        "mcp_server.orchestrator_mcp.ensure_desktop_app_started",
        lambda: {
            "launched": True,
            "status": "started",
            "pid": 4242,
            "message": "desktop app started",
        },
    )

    result = await server._start_ui({})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["data"]["launched"] is True
    assert payload["data"]["pid"] == 4242


@pytest.mark.asyncio
async def test_submit_case_uses_command_surface(monkeypatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(
        "mcp_server.orchestrator_mcp.send_command_via_pipe",
        lambda command, args=None: {
            "ok": True,
            "payload": {"task_id": "run_123", "case": {"id": "TC-BROWSER-01"}},
            "error_code": None,
            "message": "Case submitted",
        },
    )

    result = await server._submit_case({"case_id": "TC-BROWSER-01"})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["data"]["task_id"] == "run_123"
    assert payload["data"]["case"]["id"] == "TC-BROWSER-01"


@pytest.mark.asyncio
async def test_get_artifact_bundle_uses_command_surface(monkeypatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(
        "mcp_server.orchestrator_mcp.send_command_via_pipe",
        lambda command, args=None: {
            "ok": True,
            "payload": {
                "task": {"task_id": "run_123"},
                "terminal_session_references": [{"session_id": "session_1"}],
            },
            "error_code": None,
            "message": "Artifact bundle retrieved successfully",
        },
    )

    result = await server._get_artifact_bundle({"task_id": "run_123"})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["data"]["terminal_session_references"][0]["session_id"] == "session_1"


@pytest.mark.asyncio
async def test_reset_session_uses_command_surface(monkeypatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(
        "mcp_server.orchestrator_mcp.send_command_via_pipe",
        lambda command, args=None: {
            "ok": True,
            "payload": {"message": "desktop app session reset for the next run"},
            "error_code": None,
            "message": "desktop app session reset for the next run",
        },
    )

    result = await server._reset_session({})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["data"]["message"] == "desktop app session reset for the next run"


@pytest.mark.asyncio
async def test_shutdown_ui_uses_command_surface(monkeypatch) -> None:
    server = OrchestratorMCPServer()

    monkeypatch.setattr(
        "mcp_server.orchestrator_mcp.send_command_via_pipe",
        lambda command, args=None: {
            "ok": True,
            "payload": {"message": "desktop app shutdown scheduled"},
            "error_code": None,
            "message": "desktop app shutdown scheduled",
        },
    )

    result = await server._shutdown_ui({})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["data"]["message"] == "desktop app shutdown scheduled"
