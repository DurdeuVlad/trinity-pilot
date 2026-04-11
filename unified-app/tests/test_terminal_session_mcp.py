from __future__ import annotations

import json
import sys
import types
from pathlib import Path

_mcp_module = types.ModuleType("mcp")
_mcp_server_module = types.ModuleType("mcp.server")
_mcp_stdio_module = types.ModuleType("mcp.server.stdio")
_mcp_types_module = types.ModuleType("mcp.types")
_mcp_server_module.Server = object
_mcp_stdio_module.stdio_server = object
_mcp_types_module.TextContent = object
_mcp_types_module.Tool = object
sys.modules["mcp"] = _mcp_module
sys.modules["mcp.server"] = _mcp_server_module
sys.modules["mcp.server.stdio"] = _mcp_stdio_module
sys.modules["mcp.types"] = _mcp_types_module

from mcp_server.terminal_session_mcp import TerminalSessionManager


def test_terminal_session_manager_persists_metadata(tmp_path: Path) -> None:
    manager = TerminalSessionManager(metadata_dir=tmp_path / "terminal_sessions")

    session = manager.create_session(cwd=str(tmp_path), purpose="case-runner")
    manager.run_command(session.id, "python -c \"print('hello')\"")

    metadata_path = tmp_path / "terminal_sessions" / f"{session.id}.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert payload["id"] == session.id
    assert payload["purpose"] == "case-runner"
    assert any(event["text"] == "hello" for event in payload["events"])
