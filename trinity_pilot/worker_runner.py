"""Temporal worker process. Run: python -m trinity_pilot.worker_runner"""
from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from trinity_pilot.config import Settings
from trinity_pilot.workflow.activities import (
    execute_objective,
    plan_objectives,
    review_objective,
)
from trinity_pilot.workflow.task_workflow import TaskWorkflow

_TASK_QUEUE = "trinity-pilot"


async def run_worker(settings: Settings) -> None:
    client = await Client.connect(settings.temporal_host)
    worker = Worker(
        client,
        task_queue=_TASK_QUEUE,
        workflows=[TaskWorkflow],
        activities=[plan_objectives, execute_objective, review_objective],
    )
    print(f"Worker started on queue '{_TASK_QUEUE}' → {settings.temporal_host}")
    await worker.run()


def main() -> None:
    settings = Settings.from_env()
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
