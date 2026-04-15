"""Tests for the unified-app Trinity bridge."""
from __future__ import annotations

import pytest

import orchestrator.trinity_bridge as trinity_bridge
from orchestrator.trinity_bridge import TrinityBridge


class FakeTaskResult:
    """Simple result payload compatible with bridge/orchestrator expectations."""

    def __init__(self, task_id: str, status: str, metadata: dict[str, str], error: str | None = None) -> None:
        self.task_id = task_id
        self.status = status
        self.metadata = metadata
        self.error = error

    def model_dump(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "metadata": self.metadata,
            "error": self.error,
        }


class FakeExecutor:
    """Minimal fake Trinity executor for fast, deterministic unit tests."""

    def __init__(self) -> None:
        self.initialized = False
        self.last_task = None
        self.adapters = {"cli": object(), "desktop": object(), "web": object()}

    async def initialize(self) -> None:
        self.initialized = True

    async def execute(self, task):
        self.last_task = task
        return FakeTaskResult(task_id=task.task_id, status="success", metadata={"adapter": task.domain})

    async def shutdown(self) -> None:
        self.initialized = False


@pytest.mark.asyncio
async def test_initialize_sets_executor():
    bridge = TrinityBridge()
    bridge.executor = FakeExecutor()

    await bridge.initialize()

    assert bridge.executor is not None
    assert bridge.executor.initialized is True


@pytest.mark.asyncio
async def test_execute_task_uses_executor():
    bridge = TrinityBridge()
    fake = FakeExecutor()
    bridge.executor = fake
    await bridge.initialize()

    result = await bridge.execute_task(
        task_id="test_001",
        description="List files in current directory",
        domain="cli",
    )

    assert result.task_id == "test_001"
    assert result.status == "success"
    assert fake.last_task is not None
    assert fake.last_task.domain == "cli"


@pytest.mark.asyncio
async def test_execute_task_requires_initialization():
    bridge = TrinityBridge()

    with pytest.raises(RuntimeError, match="not initialized"):
        await bridge.execute_task(
            task_id="test_002",
            description="Open notepad",
            domain="desktop",
        )


@pytest.mark.asyncio
async def test_execute_task_forwards_context_and_expected_outcome():
    """TrinityBridge.execute_task forwards context and expected_outcome to TaskInput."""
    bridge = TrinityBridge()
    fake = FakeExecutor()
    bridge.executor = fake
    await bridge.initialize()

    await bridge.execute_task(
        task_id="test_003",
        description="Open Notepad",
        domain="desktop",
        context={"app_name": "Notepad"},
        expected_outcome="Notepad is open",
    )

    assert fake.last_task is not None
    assert fake.last_task.context == {"app_name": "Notepad"}
    assert fake.last_task.expected_outcome == "Notepad is open"


@pytest.mark.asyncio
async def test_execute_task_forwards_verification_checks():
    bridge = TrinityBridge()
    fake = FakeExecutor()
    bridge.executor = fake
    await bridge.initialize()

    await bridge.execute_task(
        task_id="test_003b",
        description="Open example.com",
        domain="web",
        verification_checks=[{"kind": "url_equals", "target": "current_url", "expected": "https://example.com"}],
    )

    assert fake.last_task is not None
    assert fake.last_task.verification_checks[0].kind == "url_equals"


@pytest.mark.asyncio
async def test_execute_task_context_defaults_to_empty_dict():
    """TrinityBridge.execute_task defaults context to {} when not provided."""
    bridge = TrinityBridge()
    fake = FakeExecutor()
    bridge.executor = fake
    await bridge.initialize()

    await bridge.execute_task(
        task_id="test_004",
        description="echo hello",
        domain="cli",
    )

    assert fake.last_task.context == {}


@pytest.mark.asyncio
async def test_initialize_surfaces_missing_dependency_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = TrinityBridge()
    monkeypatch.setattr(trinity_bridge, "TrinityExecutor", None)
    monkeypatch.setattr(
        trinity_bridge,
        "_TRINITY_IMPORT_ERROR",
        ModuleNotFoundError("No module named 'audit_debugger'"),
    )

    with pytest.raises(RuntimeError, match="audit_debugger"):
        await bridge.initialize()
