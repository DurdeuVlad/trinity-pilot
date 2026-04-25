"""Task queue for serial execution of non-thread-safe modules."""
import asyncio
import inspect
from typing import Any, Dict, Optional
import logging
from .models import TaskInput, TaskResult

logger = logging.getLogger(__name__)

class TaskQueue:
    """
    Serial task queue for non-thread-safe modules.
    Ensures Desktop and CLI tasks run one at a time.
    """
    
    def __init__(self, name: str = "default"):
        self.name = name
        self.queue: asyncio.Queue = asyncio.Queue()
        self.results: Dict[str, TaskResult] = {}
        self.worker_task: Optional[asyncio.Task] = None
        self.running = False
    
    async def start_worker(self):
        """Start background worker."""
        if self.running:
            logger.warning(f"Task queue '{self.name}' already running")
            return
        
        self.running = True
        self.worker_task = asyncio.create_task(self._worker_loop())
        logger.info(f"Task queue '{self.name}' started")
    
    async def stop_worker(self):
        """Stop background worker."""
        if not self.running:
            return
        
        self.running = False
        await self.queue.put(None)  # Sentinel to stop
        
        if self.worker_task:
            try:
                await self.worker_task
            except asyncio.CancelledError:
                logger.debug(f"Task queue '{self.name}' worker cancelled during shutdown")
            logger.info(f"Task queue '{self.name}' stopped")
    
    async def _worker_loop(self):
        """Process tasks serially."""
        logger.info(f"Worker loop started for queue '{self.name}'")
        
        while self.running:
            item = await self.queue.get()
            
            if item is None:  # Sentinel to stop
                break
            
            task_id, adapter, task_input = item
            logger.info(f"Processing task {task_id} in queue '{self.name}'")
            
            try:
                result = await adapter.execute(task_input)
                self.results[task_id] = result
                logger.info(f"Task {task_id} completed with status: {result.status}")
            except Exception as e:
                logger.error(f"Task {task_id} failed with exception: {e}")
                self.results[task_id] = TaskResult(
                    task_id=task_id,
                    status="failure",
                    error=str(e),
                    execution_log=[],
                    artifacts=[],
                    metadata={"queue": self.name}
                )
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
        timeout: Optional[float] = None
    ) -> TaskResult:
        """
        Submit task and wait for result.
        
        Args:
            task_id: Task identifier
            adapter: Adapter to execute task
            task_input: Task input
            timeout: Optional timeout in seconds
            
        Returns:
            TaskResult
            
        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        await self.queue.put((task_id, adapter, task_input))
        logger.info(f"Task {task_id} submitted to queue '{self.name}' (size: {self.queue.qsize()})")
        
        # Wait for result
        start_time = asyncio.get_event_loop().time()
        while task_id not in self.results:
            if timeout and (asyncio.get_event_loop().time() - start_time) > timeout:
                raise asyncio.TimeoutError(f"Task {task_id} timed out after {timeout}s")
            await asyncio.sleep(0.1)
        
        result = self.results.pop(task_id)
        return result
