"""Regression tests for A-02: resource cleanup when bridge.initialize() raises.

Without the fix, bridge.initialize() is called outside the outer try/finally block in
OrchestratorWorker._execute(), so a failure there bypasses HistoryManager.close().

Regression for A-02 (bug-hunter 2026-03-10).
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import orchestrator.orchestrator_core as core_mod


class _FakeProvider:
    async def call(self, messages, *, json_mode=True):
        return json.dumps({"done": True, "result_summary": "ok", "action_type": "done",
                           "module": None, "parameters": {}, "rationale": ""})

    async def probe(self): pass

    @property
    def provider_name(self): return "fake"


@pytest.mark.asyncio
async def test_history_manager_close_called_when_initialize_raises(qtbot):
    """HistoryManager.close() must be called even when bridge.initialize() raises.

    Regression for A-02 (bug-hunter 2026-03-10).
    Verifies that the resource-cleanup finally: block is reached regardless of
    whether bridge.initialize() succeeds or raises.
    """
    mock_history = MagicMock()
    mock_bridge = MagicMock()
    mock_bridge.initialize = AsyncMock(side_effect=RuntimeError("simulated init failure"))
    mock_bridge.shutdown = AsyncMock()
    mock_watcher = MagicMock()
    mock_watcher.stop_watching = MagicMock()
    mock_event_bus = MagicMock()

    with (
        patch.object(core_mod, "HistoryManager", return_value=mock_history),
        patch.object(core_mod, "TrinityBridge", return_value=mock_bridge),
        patch.object(core_mod, "get_event_bus", return_value=mock_event_bus),
        patch.object(core_mod, "make_provider", return_value=_FakeProvider()),
    ):
        worker = core_mod.OrchestratorWorker("test task", "cli")
        # Pre-set watcher so _ensure_screenshot_watcher() returns the mock
        # without creating real QTimers in the test environment.
        worker.screenshot_watcher = mock_watcher

        with pytest.raises(RuntimeError, match="simulated init failure"):
            await worker._execute()

    mock_history.close.assert_called_once()
