import pytest

from trinity_core.tools.base import ToolResult
from trinity_core.tools.browser_tools import build_browser_tools
from trinity_core.tools.desktop_tools import build_desktop_tools
from trinity_core.tools.cli_tools import build_cli_tools


class _BrowserAdapter:
    async def execute(self, task):
        class R:
            status = "success"
            error = None
            metadata = {"ok": True}

        return R()

    async def wait_for_selector(self, selector, timeout, state):
        return None

    async def wait_for_load_state(self, wait_until, timeout):
        return None


class _DesktopAdapter:
    async def execute(self, task):
        class R:
            status = "success"
            error = None
            metadata = {"ok": True}

        return R()

    async def wait_for_process(self, app_name, timeout):
        return None

    async def wait_for_window_title(self, title, timeout):
        return None

    async def wait_for_ui_element(self, element_name, element_type, timeout):
        return None

    async def wait_for_text_in_window(self, text, timeout):
        return None


class _CLIAdapter:
    async def execute(self, task):
        class R:
            status = "success"
            error = None
            metadata = {"ok": True}

        return R()

    async def wait_for_output_contains(self, text, timeout):
        return None

    async def wait_for_process_exit(self, process_id, timeout):
        return None

    async def wait_for_file_condition(self, file_path, condition, timeout):
        return None


@pytest.mark.asyncio
async def test_browser_toolset_has_expected_tools_and_executes():
    tools = build_browser_tools(_BrowserAdapter())
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


@pytest.mark.asyncio
async def test_desktop_toolset_has_expected_tools_and_executes():
    tools = build_desktop_tools(_DesktopAdapter())
    assert "open_app" in tools
    assert "wait_for_text" in tools
    result = await tools["open_app"].execute(app_name="notepad")
    assert result.status == "success"


@pytest.mark.asyncio
async def test_cli_toolset_has_expected_tools_and_executes():
    tools = build_cli_tools(_CLIAdapter())
    assert set(tools.keys()) == {
        "run_command",
        "read_output",
        "wait_for_output",
        "wait_for_process",
        "wait_for_file",
    }
    result = await tools["run_command"].execute(command="echo hi", async_mode=False)
    assert result.status == "success"


# --- Wait tool timeout tests ---

class _TimeoutBrowserAdapter(_BrowserAdapter):
    async def wait_for_selector(self, selector, timeout, state):
        raise TimeoutError(f"element not found within {timeout}s")


class _TimeoutDesktopAdapter(_DesktopAdapter):
    async def wait_for_process(self, app_name, timeout):
        raise TimeoutError(f"process not ready within {timeout}s")


class _TimeoutCLIAdapter(_CLIAdapter):
    async def wait_for_output_contains(self, text, timeout):
        raise TimeoutError(f"output not found within {timeout}s")


@pytest.mark.asyncio
async def test_browser_wait_element_timeout_returns_error():
    tools = build_browser_tools(_TimeoutBrowserAdapter())
    result = await tools["wait_for_element"].execute(selector="#missing", timeout=1)
    assert result.status == "error"
    assert "#missing" in result.error or "element" in result.error.lower()


@pytest.mark.asyncio
async def test_desktop_wait_app_timeout_returns_error():
    tools = build_desktop_tools(_TimeoutDesktopAdapter())
    result = await tools["wait_for_app"].execute(app_name="ghost_app", timeout=1)
    assert result.status == "error"
    assert "ghost_app" in result.error


@pytest.mark.asyncio
async def test_cli_wait_output_timeout_returns_error():
    tools = build_cli_tools(_TimeoutCLIAdapter())
    result = await tools["wait_for_output"].execute(text="expected", timeout=1)
    assert result.status == "error"
    assert "expected" in result.error
