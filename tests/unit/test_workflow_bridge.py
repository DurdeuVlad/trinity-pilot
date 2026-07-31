"""WorkflowBridge unit tests."""
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 not installed")

import threading
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QThread, Signal

from trinity_pilot.config import Settings
from trinity_pilot.ui.bridge import WorkflowBridge


def _settings() -> Settings:
    return Settings(gemini_api_key="test-key")


class _EmittingWorker(QThread):
    """Small real QThread used to verify bridge callback affinity."""

    log_message = Signal(str)
    status_changed = Signal(str)
    task_finished = Signal(str, object)

    def __init__(self, *args, **kwargs):
        super().__init__()

    def run(self) -> None:
        self.log_message.emit("worker log")
        self.status_changed.emit("completed")
        self.task_finished.emit("worker-task", {"status": "completed"})


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

    def test_stop_task_can_return_without_waiting_for_worker(self, qtbot):
        bridge = WorkflowBridge(settings=_settings(), db_path=":memory:")

        with patch("trinity_pilot.ui.bridge._WorkerThread") as MockThread:
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = True
            MockThread.return_value = mock_thread

            bridge.start_task("some task")
            bridge.stop_task(wait_ms=0)

        mock_thread.request_cancel.assert_called_once()
        mock_thread.wait.assert_not_called()

    def test_main_thread_callbacks_are_relayed_from_worker(self, qtbot, tmp_path):
        bridge = WorkflowBridge(
            settings=_settings(),
            db_path=str(tmp_path / "bridge.db"),
        )
        # Avoid doing database work from the synthetic worker thread; this test
        # is specifically about the UI callback boundary.
        bridge._on_worker_finished = lambda task_id, result: None
        main_thread = QThread.currentThread()
        callback_threads: list[bool] = []
        done: list[dict] = []

        with patch("trinity_pilot.ui.bridge._WorkerThread", _EmittingWorker):
            bridge.start_task(
                "worker callback affinity",
                on_log=lambda message: callback_threads.append(QThread.currentThread() == main_thread),
                on_status=lambda status: callback_threads.append(QThread.currentThread() == main_thread),
                on_done=lambda result: (
                    callback_threads.append(QThread.currentThread() == main_thread),
                    done.append(result),
                ),
                main_thread_callbacks=True,
            )

            qtbot.waitUntil(lambda: len(done) == 1, timeout=1000)

        assert done == [{"status": "completed"}]
        assert len(callback_threads) == 3
        assert all(callback_threads)

    def test_headless_callbacks_are_synchronous(self, tmp_path):
        bridge = WorkflowBridge(
            settings=_settings(),
            db_path=str(tmp_path / "headless-bridge.db"),
        )
        bridge._on_worker_finished = lambda task_id, result: None
        callbacks: list[str] = []
        done = threading.Event()

        with patch("trinity_pilot.ui.bridge._WorkerThread", _EmittingWorker):
            bridge.start_task(
                "headless callback affinity",
                on_log=lambda message: callbacks.append("log"),
                on_status=lambda status: callbacks.append("status"),
                on_done=lambda result: (callbacks.append("done"), done.set()),
            )

            assert done.wait(timeout=1.0)

        assert callbacks == ["log", "status", "done"]
