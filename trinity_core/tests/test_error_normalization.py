"""TC-S2: Tests for canonical error shape normalization across adapter wrappers."""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import patch

from trinity_core.models import TaskInput, TaskResult, failure_code, is_retriable
from trinity_core.adapters.cli import CLIAdapter
from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.adapters.desktop import DesktopAdapter


# ---------------------------------------------------------------------------
# failure_code / is_retriable helpers
# ---------------------------------------------------------------------------

class TestFailureCodeHelper:
    def test_known_categories_return_uppercase_code(self):
        assert failure_code("timeout") == "TIMEOUT"
        assert failure_code("auth_failure") == "AUTH_FAILURE"
        assert failure_code("cancelled") == "CANCELLED"
        assert failure_code("backend_error") == "BACKEND_ERROR"
        assert failure_code("user_error") == "USER_ERROR"
        assert failure_code("health_check_failed") == "HEALTH_CHECK_FAILED"

    def test_unknown_category_returns_unknown_failure(self):
        assert failure_code("mystery_code") == "UNKNOWN_FAILURE"


class TestIsRetriableHelper:
    def test_transient_categories_are_retriable(self):
        assert is_retriable("timeout") is True
        assert is_retriable("backend_error") is True
        assert is_retriable("health_check_failed") is True

    def test_permanent_categories_are_not_retriable(self):
        assert is_retriable("auth_failure") is False
        assert is_retriable("cancelled") is False
        assert is_retriable("user_error") is False


# ---------------------------------------------------------------------------
# CLI adapter error shape
# ---------------------------------------------------------------------------

class TestCLIAdapterErrorShape:
    def test_cancelled_failure_has_code_and_retriable(self):
        import threading
        adapter = CLIAdapter()
        cancel_event = threading.Event()
        cancel_event.set()
        task = TaskInput(
            task_id="cli-cancel",
            description="list files",
            domain="cli",
            cancel_event=cancel_event,
        )

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(adapter.execute(task))

        assert result.status == "failure"
        assert result.code == "CANCELLED"
        assert result.retriable is False
        assert result.error is not None
        assert result.metadata["adapter_name"] == "cli-automation-poc"
        assert result.metadata["domain"] == "cli"

    def test_legacy_error_field_preserved(self):
        """error field remains populated for backward-compatible consumers."""
        import threading
        adapter = CLIAdapter()
        cancel_event = threading.Event()
        cancel_event.set()
        task = TaskInput(
            task_id="cli-legacy",
            description="dir",
            domain="cli",
            cancel_event=cancel_event,
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(adapter.execute(task))
        assert result.error is not None and len(result.error) > 0


# ---------------------------------------------------------------------------
# Browser adapter error shape
# ---------------------------------------------------------------------------

class TestBrowserAdapterErrorShape:
    @pytest.mark.asyncio
    async def test_cancelled_failure_has_code_and_retriable(self):
        import threading
        adapter = BrowserAdapter()
        cancel_event = threading.Event()
        cancel_event.set()
        task = TaskInput(
            task_id="browser-cancel",
            description="open example.com",
            domain="web",
            cancel_event=cancel_event,
        )
        result = await adapter.execute(task)
        assert result.status == "failure"
        assert result.code == "CANCELLED"
        assert result.retriable is False
        assert result.metadata["adapter_name"] == "browser-gui-automation"
        assert result.metadata["domain"] == "web"

    @pytest.mark.asyncio
    async def test_timeout_failure_is_retriable(self):
        import asyncio as _asyncio
        adapter = BrowserAdapter()
        task = TaskInput(
            task_id="browser-timeout-code",
            description="open example.com",
            domain="web",
            timeout=1,
        )

        async def slow_task(**_kwargs):
            await _asyncio.sleep(2)

        with patch("trinity_core.adapters.browser.run_browser_task", side_effect=slow_task):
            result = await adapter.execute(task)

        assert result.status == "failure"
        assert result.code == "TIMEOUT"
        assert result.retriable is True
        assert result.metadata["adapter_name"] == "browser-gui-automation"
        assert result.metadata["domain"] == "web"


# ---------------------------------------------------------------------------
# Desktop adapter error shape
# ---------------------------------------------------------------------------

class TestDesktopAdapterErrorShape:
    @pytest.mark.asyncio
    async def test_cancelled_failure_has_code_and_retriable(self):
        import threading
        adapter = DesktopAdapter()
        cancel_event = threading.Event()
        cancel_event.set()
        task = TaskInput(
            task_id="desktop-cancel",
            description="open Notepad",
            domain="desktop",
            context={"app_name": "Notepad"},
            cancel_event=cancel_event,
        )
        result = await adapter.execute(task)
        assert result.status == "failure"
        assert result.code == "CANCELLED"
        assert result.retriable is False
        assert result.metadata["adapter_name"] == "api-accessibility-poc"
        assert result.metadata["domain"] == "desktop"


# ---------------------------------------------------------------------------
# Health check failure (TC-S1 AC3 / TC-S2 AC2 combined)
# ---------------------------------------------------------------------------

class TestHealthCheckFailureShape:
    @pytest.mark.asyncio
    async def test_unhealthy_dispatch_returns_normalized_shape(self):
        from trinity_core.trinity import TrinityExecutor

        async with TrinityExecutor() as executor:
            async def _unhealthy() -> bool:
                return False

            executor.adapters["cli"] = SimpleNamespace(
                health_check=_unhealthy,
                execute=None,
            )

            result = await executor.execute(
                TaskInput(task_id="hc-shape", description="list files", domain="cli")
            )

        assert result.status == "failure"
        assert result.category == "health_check_failed"
        assert result.code == "HEALTH_CHECK_FAILED"
        assert result.retriable is True
        assert result.metadata.get("reason") == "health_check_failed"
        assert result.metadata.get("domain") == "cli"
        assert result.error is not None
