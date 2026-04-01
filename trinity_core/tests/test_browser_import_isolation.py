"""Regression tests for browser adapter package isolation."""

from trinity_core.adapters import browser as browser_adapter_module


def test_browser_adapter_imports_unique_browser_agent_package() -> None:
    """The adapter should bind to the browser module via a unique package name."""
    assert browser_adapter_module.run_browser_task.__module__ == "browser_agent.main"
    assert browser_adapter_module.BrowserAgentOutput.__module__ == "browser_agent.core.io_models"
