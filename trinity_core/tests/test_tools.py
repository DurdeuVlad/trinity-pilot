from __future__ import annotations

import pytest

from trinity_core.tools.base import ToolResult
from trinity_core.tools.browser_tools import build_browser_tools
from trinity_core.tools.cli_tools import build_cli_tools
from trinity_core.tools.desktop_tools import build_desktop_tools


@pytest.mark.asyncio
async def test_browser_toolset_has_expected_tools_and_executes(monkeypatch):
    async def _navigate(url: str) -> str:
        return f"title:{url}"

    monkeypatch.setattr("trinity_core.tools.browser_tools.navigate", _navigate)
    tools = build_browser_tools()
    assert set(tools.keys()) == {
        "navigate",
        "click",
        "type",
        "extract",
        "screenshot",
        "wait_for_element",
        "wait_for_navigation",
        "wait_for_text",
    }
    result = await tools["navigate"].execute(url="https://example.com")
    assert isinstance(result, ToolResult)
    assert result.status == "success"


@pytest.mark.asyncio
async def test_desktop_toolset_has_expected_tools_and_executes(monkeypatch):
    monkeypatch.setattr("trinity_core.tools.desktop_tools.launch_app", lambda name: f"Launched {name}")
    tools = build_desktop_tools()
    assert "open_app" in tools
    assert "wait_for_text" in tools
    result = await tools["open_app"].execute(app_name="notepad")
    assert result.status == "success"


@pytest.mark.asyncio
async def test_cli_toolset_has_expected_tools_and_executes(monkeypatch):
    class _Result:
        stdout = "hi"
        stderr = ""
        exit_code = 0
        duration_ms = 1

    monkeypatch.setattr(
        "trinity_core.tools.cli_tools.CLIExecutor.execute_command",
        lambda self, command: _Result(),
    )
    tools = build_cli_tools()
    assert set(tools.keys()) == {
        "run_command",
        "read_output",
        "wait_for_output",
        "wait_for_file",
    }
    result = await tools["run_command"].execute(command="echo hi", async_mode=False)
    assert result.status == "success"


@pytest.mark.asyncio
async def test_cli_async_mode_is_rejected_until_cleanup_exists():
    tools = build_cli_tools()
    result = await tools["run_command"].execute(command="echo hi", async_mode=True)
    assert result.status == "error"
    assert result.error_code == "ASYNC_MODE_UNSUPPORTED"


@pytest.mark.asyncio
async def test_browser_wait_element_timeout_returns_error(monkeypatch):
    async def _wait_for_element(selector: str, timeout: float = 10.0, state: str = "visible") -> str:
        return f"ERROR: Timeout waiting for '{selector}' to be {state}"

    monkeypatch.setattr("trinity_core.tools.browser_tools.wait_for_element", _wait_for_element)
    tools = build_browser_tools()
    result = await tools["wait_for_element"].execute(selector="#missing", timeout=1)
    assert result.status == "error"
    assert "#missing" in (result.error or "")


@pytest.mark.asyncio
async def test_desktop_wait_app_timeout_returns_error(monkeypatch):
    monkeypatch.setattr("trinity_core.tools.desktop_tools.check_app_running", lambda app_name: False)
    tools = build_desktop_tools()
    result = await tools["wait_for_app"].execute(app_name="ghost_app", timeout=1)
    assert result.status == "error"
    assert "ghost_app" in (result.error or "")


@pytest.mark.asyncio
async def test_cli_wait_output_timeout_returns_error():
    tools = build_cli_tools()
    result = await tools["wait_for_output"].execute(text="expected", timeout=1)
    assert result.status == "error"
    assert "expected" in (result.error or "")
