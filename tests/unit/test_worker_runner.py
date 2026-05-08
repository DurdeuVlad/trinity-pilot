"""worker_runner smoke import tests — no Temporal runtime needed."""
from __future__ import annotations


class TestWorkerRunnerImport:
    def test_module_imports_without_error(self):
        import trinity_pilot.worker_runner as wr
        assert wr is not None

    def test_run_worker_is_callable(self):
        from trinity_pilot.worker_runner import run_worker
        assert callable(run_worker)

    def test_run_worker_async_is_callable(self):
        from trinity_pilot.worker_runner import run_worker_async
        assert callable(run_worker_async)

    def test_task_queue_constant_defined(self):
        from trinity_pilot.worker_runner import _TASK_QUEUE
        assert isinstance(_TASK_QUEUE, str)
        assert len(_TASK_QUEUE) > 0
