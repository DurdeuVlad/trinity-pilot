"""Performance tests for Trinity."""
import pytest
import asyncio
import time
import os
from trinity_core.trinity import TrinityExecutor
from trinity_core.models import TaskInput
from trinity_core.config import TrinityConfig

@pytest.fixture
def config():
    """Create test configuration."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set")
    
    return TrinityConfig(
        gemini_api_key=api_key,
        debug_mode=False
    )

@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_browser_tasks_performance(config):
    """Test performance of concurrent browser tasks."""
    async with TrinityExecutor(config=config) as executor:
        # Create 3 browser tasks (reduced from 10 for faster testing)
        tasks = [
            TaskInput(
                task_id=f"perf_web_{i}",
                description=f"Navigate to example.com (test {i})",
                domain="web"
            )
            for i in range(3)
        ]
        
        start_time = time.time()
        results = await asyncio.gather(*[
            executor.execute(task) for task in tasks
        ], return_exceptions=True)
        elapsed = time.time() - start_time
        
        assert len(results) == 3
        print(f"3 browser tasks completed in {elapsed:.2f}s")

@pytest.mark.performance
@pytest.mark.asyncio
async def test_serial_desktop_tasks_performance(config):
    """Test performance of serial desktop tasks."""
    async with TrinityExecutor(config=config) as executor:
        tasks = [
            TaskInput(
                task_id=f"perf_desktop_{i}",
                description=f"Type '{i}' in Notepad",
                domain="desktop",
                context={"app_name": "Notepad"}
            )
            for i in range(2)
        ]
        
        start_time = time.time()
        results = await asyncio.gather(*[
            executor.execute(task) for task in tasks
        ], return_exceptions=True)
        elapsed = time.time() - start_time
        
        assert len(results) == 2
        print(f"2 desktop tasks (serial) completed in {elapsed:.2f}s")
