"""WorkflowBridge unit tests."""
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 not installed")

from unittest.mock import AsyncMock, MagicMock, patch

from trinity_pilot.config import Settings
from trinity_pilot.ui.bridge import WorkflowBridge


def _settings() -> Settings:
    return Settings(gemini_api_key="test-key")


class TestWorkflowBridge:
    def test_start_task_creates_task_record(self, qtbot):
        bridge = WorkflowBridge(settings=_settings(), db_path=":memory:")

        with patch("trinity_pilot.ui.bridge._WorkerThread") as MockThread:
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True
            MockThread.return_value = mock_thread

            task_id = bridge.start_task("open google.com")

        assert task_id
        record = bridge._store.get_task(task_id)
        assert record is not None
        assert record.user_request == "open google.com"

    def test_stop_task_calls_request_cancel(self, qtbot):
        bridge = WorkflowBridge(settings=_settings(), db_path=":memory:")

        with patch("trinity_pilot.ui.bridge._WorkerThread") as MockThread:
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True
            MockThread.return_value = mock_thread

            bridge.start_task("some task")
            bridge.stop_task()

        mock_thread.request_cancel.assert_called_once()
