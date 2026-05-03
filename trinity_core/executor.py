"""Task queue for serial execution of non-thread-safe modules."""
import asyncio
import inspect
from typing import Any, Dict, Optional
import logging
from .models import TaskInput, TaskResult

logger = logging.getLogger(__name__)


class TaskQueue:
    """Serial task queue for non-thread-safe modules."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.queue: asyncio.Queue = asyncio.Queue()
        self._pending: Dict[str, asyncio.Future] = {}
        self.worker_task: Optional[asyncio.Task] = None
        self.running = False

    async def start_worker(self):
        if self.running:
            logger.warning("Task queue '%s' already running", self.name)
            return
        self.running = True
        self.worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Task queue '%s' started", self.name)

    async def stop_worker(self):
        if not self.running:
            return
        self.running = False
        await self.queue.put(None)
        if self.worker_task:
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Task queue '%s' stopped", self.name)

    async def _worker_loop(self):
        logger.info("Worker loop started for queue '%s'", self.name)
        while self.running:
            item = await self.queue.get()
            if item is None:
                break

            task_id, adapter, task_input, future = item
            logger.info("Processing task %s in queue '%s'", task_id, self.name)

            try:
                result = await adapter.execute(task_input)
                logger.info("Task %s completed with status: %s", task_id, result.status)
                if not future.done():
                    future.set_result(result)
            except Exception as exc:
                logger.error("Task %s failed: %s", task_id, exc)
                failure = TaskResult(
                    task_id=task_id,
                    status="failure",
                    error=str(exc),
                    execution_log=[],
                    artifacts=[],
                    metadata={"queue": self.name},
                )
                if not future.done():
                    future.set_result(failure)
            finally:
                close_method = getattr(adapter, "close", None)
                if callable(close_method):
                    try:
                        close_result = close_method()
                        if inspect.isawaitable(close_result):
                            await close_result
                    except Exception as close_exc:
                        logger.debug("Task %s adapter close failed: %s", task_id, close_exc)
                self.queue.task_done()

    async def submit(
        self,
        task_id: str,
        adapter: Any,
        task_input: TaskInput,
        timeout: Optional[float] = None,
    ) -> TaskResult:
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[task_id] = future
        await self.queue.put((task_id, adapter, task_input, future))
        logger.info("Task %s submitted to queue '%s'", task_id, self.name)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(task_id, None)
