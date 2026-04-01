"""Tests for task queue."""
import pytest
import asyncio
from trinity_core.executor import TaskQueue
from trinity_core.models import TaskInput, TaskResult

@pytest.mark.asyncio
async def test_task_queue_start_stop():
    """Test queue start/stop."""
    queue = TaskQueue(name="test")
    await queue.start_worker()
    assert queue.running
    await queue.stop_worker()
    assert not queue.running

@pytest.mark.asyncio
async def test_task_queue_serial_execution():
    """Test serial execution order."""
    queue = TaskQueue(name="test")
    await queue.start_worker()
    
    # Mock adapter that tracks execution order
    execution_order = []
    
    class MockAdapter:
        async def execute(self, task):
            execution_order.append(task.task_id)
            await asyncio.sleep(0.1)  # Simulate work
            return TaskResult(
                task_id=task.task_id,
                status="success",
                execution_log=[],
                artifacts=[],
                metadata={}
            )
    
    adapter = MockAdapter()
    
    # Submit 3 tasks
    task1 = TaskInput(task_id="1", description="Task 1", domain="cli", expected_outcome="Done")
    task2 = TaskInput(task_id="2", description="Task 2", domain="cli", expected_outcome="Done")
    task3 = TaskInput(task_id="3", description="Task 3", domain="cli", expected_outcome="Done")
    
    results = await asyncio.gather(
        queue.submit("1", adapter, task1),
        queue.submit("2", adapter, task2),
        queue.submit("3", adapter, task3)
    )
    
    # Verify serial execution
    assert execution_order == ["1", "2", "3"]
    assert all(r.status == "success" for r in results)
    
    await queue.stop_worker()
