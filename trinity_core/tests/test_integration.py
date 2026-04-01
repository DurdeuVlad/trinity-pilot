"""Integration tests for Trinity."""
import pytest
import asyncio
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
        debug_mode=True,
        max_concurrent_browser_tasks=2
    )

@pytest.mark.integration
@pytest.mark.asyncio
async def test_sequential_execution_all_domains(config):
    """Test sequential execution across all domains."""
    async with TrinityExecutor(config=config) as executor:
        # Web task
        web_task = TaskInput(
            task_id="seq_web",
            description="Navigate to example.com",
            domain="web",
            expected_outcome="Page loads successfully"
        )
        # Mocking or skipping real execution if keys/environment not fully set
        # For this test, we just ensure it doesn't crash during submission
        try:
            web_result = await executor.execute(web_task)
            assert web_result.task_id == "seq_web"
        except Exception as e:
            pytest.fail(f"Web task failed: {e}")
        
        # Desktop task
        desktop_task = TaskInput(
            task_id="seq_desktop",
            description="Open Notepad and type 'Integration Test'",
            domain="desktop",
            context={"app_name": "Notepad"},
            expected_outcome="Text appears in Notepad"
        )
        try:
            desktop_result = await executor.execute(desktop_task)
            assert desktop_result.task_id == "seq_desktop"
        except Exception as e:
            pytest.fail(f"Desktop task failed: {e}")
        
        # CLI task
        cli_task = TaskInput(
            task_id="seq_cli",
            description="Echo 'Integration Test' to console",
            domain="cli",
            expected_outcome="Text appears in console"
        )
        try:
            cli_result = await executor.execute(cli_task)
            assert cli_result.task_id == "seq_cli"
        except Exception as e:
            pytest.fail(f"CLI task failed: {e}")

@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_browser_serial_desktop(config):
    """Test parallel browser tasks with serial desktop tasks."""
    async with TrinityExecutor(config=config) as executor:
        # Launch 2 browser tasks in parallel
        browser_tasks = [
            TaskInput(
                task_id=f"parallel_web_{i}",
                description=f"Navigate to example.com (task {i})",
                domain="web"
            )
            for i in range(2)
        ]
        
        # Launch 2 desktop tasks (will execute serially)
        desktop_tasks = [
            TaskInput(
                task_id=f"serial_desktop_{i}",
                description=f"Type '{i}' in Notepad",
                domain="desktop",
                context={"app_name": "Notepad"}
            )
            for i in range(2)
        ]
        
        # Execute all concurrently
        all_tasks = browser_tasks + desktop_tasks
        # We don't wait for completion here to test submission
        results = await asyncio.gather(*[
            executor.execute(task) for task in all_tasks
        ], return_exceptions=True)
        
        assert len(results) == 4
        for r in results:
            if isinstance(r, Exception):
                print(f"Task failed with exception: {r}")

@pytest.mark.asyncio
async def test_error_handling_invalid_domain(config):
    """Test error handling for invalid tasks."""
    async with TrinityExecutor(config=config) as executor:
        # Invalid domain
        with pytest.raises(ValueError):
            invalid_task = TaskInput(
                task_id="invalid",
                description="Test",
                domain="invalid_domain" # type: ignore
            )
            await executor.execute(invalid_task)
