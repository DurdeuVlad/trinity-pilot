"""worker_runner import smoke — verifies no crash without live Temporal."""


class TestWorkerRunnerImport:
    def test_import_does_not_raise(self):
        import trinity_pilot.worker_runner as wr
        assert callable(wr.run_worker)
        assert callable(wr.main)

    def test_task_queue_constant_set(self):
        from trinity_pilot.worker_runner import _TASK_QUEUE
        assert _TASK_QUEUE == "trinity-pilot"
