"""Unified Trinity executor."""
import asyncio
import logging
from typing import Dict, Optional
from .adapter import TaskAdapter
from .adapters.browser import BrowserAdapter
from .adapters.desktop import DesktopAdapter
from .adapters.cli import CLIAdapter
from .models import TaskInput, TaskResult
from .executor import TaskQueue
from .config import TrinityConfig

logger = logging.getLogger(__name__)

class TrinityExecutor:
    """
    Unified executor for all Trinity modules.
    Handles async/sync differences and thread safety transparently.
    """
    
    def __init__(self, config: Optional[TrinityConfig] = None):
        """
        Initialize Trinity executor.
        
        Args:
            config: TrinityConfig instance. If None, loads from environment.
        """
        # Load config
        if config is None:
            config = TrinityConfig.from_env()
        self.config = config
        
        # Set up logging
        if config.debug_mode:
            logging.basicConfig(level=logging.DEBUG)
        
        # Initialize adapters
        self.adapters: Dict[str, TaskAdapter] = {}
        if config.browser.enabled:
            self.adapters["web"] = BrowserAdapter()
        if config.desktop.enabled:
            self.adapters["desktop"] = DesktopAdapter()
        if config.cli.enabled:
            self.adapters["cli"] = CLIAdapter()
        
        # Task queue for serial execution (Desktop/CLI)
        self.task_queue = TaskQueue(name="desktop_cli_queue")
        
        # Semaphore for concurrent browser tasks
        self.browser_semaphore = asyncio.Semaphore(config.max_concurrent_browser_tasks)
        
        self.initialized = False
    
    async def initialize(self):
        """Initialize executor and start task queue."""
        if self.initialized:
            logger.warning("TrinityExecutor already initialized")
            return
        
        await self.task_queue.start_worker()
        self.initialized = True
        logger.info("TrinityExecutor initialized")
    
    async def shutdown(self):
        """Shutdown executor and stop task queue."""
        if not self.initialized:
            return
        
        await self.task_queue.stop_worker()
        self.initialized = False
        logger.info("TrinityExecutor shutdown complete")
    
    async def execute(self, task: TaskInput) -> TaskResult:
        """
        Execute task using appropriate adapter.
        
        Args:
            task: Unified task input
            
        Returns:
            Unified task result
            
        Raises:
            ValueError: If domain is invalid
            RuntimeError: If executor not initialized
        """
        if not self.initialized:
            await self.initialize()
        
        if task.domain not in self.adapters:
            raise ValueError(f"Invalid domain: {task.domain}")
        
        adapter = self.adapters[task.domain]
        logger.info(f"Executing task {task.task_id} in domain '{task.domain}'")
        
        # Browser tasks: run directly with concurrency limit
        if task.domain == "web":
            async with self.browser_semaphore:
                logger.debug(f"Executing browser task {task.task_id}")
                return await adapter.execute(task)
        
        # Desktop/CLI tasks: use serial queue
        default_timeout = self.config.desktop.timeout if task.domain == "desktop" else self.config.cli.timeout
        timeout = task.timeout if task.timeout is not None else default_timeout
        return await self.task_queue.submit(task.task_id, adapter, task, timeout=float(timeout))
    
    async def health_check_all(self) -> Dict[str, bool]:
        """Check health of all modules."""
        results = {}
        for domain, adapter in self.adapters.items():
            try:
                results[domain] = await adapter.health_check()
            except Exception as e:
                logger.error(f"Health check failed for {domain}: {e}")
                results[domain] = False
        return results
    
    async def get_capabilities_all(self) -> Dict[str, Dict]:
        """Get capabilities of all modules."""
        results = {}
        for domain, adapter in self.adapters.items():
            results[domain] = adapter.get_capabilities()
        return results
    
    async def __aenter__(self):
        """Context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.shutdown()
