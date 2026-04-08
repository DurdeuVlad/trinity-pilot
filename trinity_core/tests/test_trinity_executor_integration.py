import pytest

from trinity_core.models import TaskInput, TaskResult
from trinity_core.trinity import TrinityExecutor


class _HealthyAdapter:
    async def health_check(self):
        return True

    async def execute(self, task):
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            code=None,
            retriable=False,
            error=None,
            execution_log=[],
            artifacts=[],
            metadata={"source": "adapter"},
        )


class _FailingRuntime:
    async def execute(self, task):
        raise RuntimeError("runtime failed")


@pytest.mark.asyncio
async def test_executor_falls_back_to_adapter_when_runtime_fails():
    async with TrinityExecutor() as executor:
        executor.adapters["web"] = _HealthyAdapter()
        executor.runtimes["web"] = _FailingRuntime()

        result = await executor.execute(TaskInput(task_id="x1", description="navigate", domain="web"))

    assert result.status == "success"
    assert result.metadata["source"] == "adapter"


class _SucceedingRuntime:
    async def execute(self, task):
        return TaskResult(
            task_id=task.task_id,
            status="success",
            category="success",
            code=None,
            retriable=False,
            error=None,
            execution_log=[],
            artifacts=[],
            metadata={"source": "runtime"},
        )


@pytest.mark.asyncio
async def test_executor_routes_browser_task_through_runtime():
    async with TrinityExecutor() as executor:
        executor.adapters["web"] = _HealthyAdapter()
        executor.runtimes["web"] = _SucceedingRuntime()

        result = await executor.execute(TaskInput(task_id="x2", description="navigate", domain="web"))

    assert result.status == "success"
    assert result.metadata["source"] == "runtime"


@pytest.mark.asyncio
async def test_executor_routes_cli_task_through_runtime():
    async with TrinityExecutor() as executor:
        executor.adapters["cli"] = _HealthyAdapter()
        executor.runtimes["cli"] = _SucceedingRuntime()

        result = await executor.execute(TaskInput(task_id="x3", description="run cmd", domain="cli"))

    assert result.status == "success"
    assert result.metadata["source"] == "runtime"
