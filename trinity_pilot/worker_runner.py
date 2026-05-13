"""Temporal worker process. Run: python -m trinity_pilot.worker_runner

Top-level imports are lazy so this module can be imported in CI without
temporalio installed.
"""
from __future__ import annotations

import asyncio

_TASK_QUEUE = "trinity-pilot"


async def run_worker_async(temporal_host: str, on_ready=None) -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from trinity_pilot.workflow.activities import (
        execute_objective,
        persist_attempt,
        plan_objectives,
        save_reflection_activity,
        update_task_status_activity,
    )
    from trinity_pilot.workflow.task_workflow import TaskWorkflow

    client = await Client.connect(temporal_host)
    worker = Worker(
        client,
        task_queue=_TASK_QUEUE,
        workflows=[TaskWorkflow],
        activities=[
            plan_objectives,
            execute_objective,
            persist_attempt,
            save_reflection_activity,
            update_task_status_activity,
        ],
    )
    print(f"Worker started on queue '{_TASK_QUEUE}' -> {temporal_host}")
    if on_ready is not None:
        on_ready("Worker connected and running")
    await worker.run()


def run_worker() -> None:
    from trinity_pilot.config import Settings
    settings = Settings.from_env()
    asyncio.run(run_worker_async(settings.temporal_host))


def main() -> None:
    run_worker()


if __name__ == "__main__":
    main()
