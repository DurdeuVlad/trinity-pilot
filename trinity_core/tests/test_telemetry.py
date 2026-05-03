"""TC-S5: Executor telemetry events v1 tests."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from trinity_core.telemetry import (
    InMemoryCollector,
    emit_event,
    make_event_payload,
    redact_payload,
    register_collector,
    unregister_collector,
    TASK_STARTED,
    TASK_SUCCEEDED,
    TASK_FAILED,
    TASK_CANCELLED,
)
from trinity_core.config import TrinityConfig
from trinity_core.models import TaskInput


# ---------------------------------------------------------------------------
# redact_payload tests
# ---------------------------------------------------------------------------

class TestRedactPayload:
    def test_secret_key_is_redacted(self):
        payload = {"api_key": "sk-abc", "task_id": "t1"}
        result = redact_payload(payload)
        assert result["api_key"] == "[REDACTED]"
        assert result["task_id"] == "t1"

    def test_token_key_is_redacted(self):
        result = redact_payload({"auth_token": "secret123", "domain": "cli"})
        assert result["auth_token"] == "[REDACTED]"
        assert result["domain"] == "cli"

    def test_normal_keys_pass_through(self):
        payload = {"task_id": "t1", "domain": "web", "adapter_name": "BrowserAdapter"}
        assert redact_payload(payload) == payload

    def test_original_dict_not_mutated(self):
        payload = {"password": "top_secret", "x": 1}
        redact_payload(payload)
        assert payload["password"] == "top_secret"


# ---------------------------------------------------------------------------
# make_event_payload tests
# ---------------------------------------------------------------------------

class TestMakeEventPayload:
    def test_required_fields_present(self):
        p = make_event_payload(task_id="t1", domain="cli", adapter_name="CLIAdapter")
        assert p["task_id"] == "t1"
        assert p["domain"] == "cli"
        assert p["adapter_name"] == "CLIAdapter"

    def test_duration_ms_included_when_provided(self):
        p = make_event_payload(task_id="t", domain="web", adapter_name="A", duration_ms=42.5)
        assert p["duration_ms"] == 42.5

    def test_extra_fields_merged(self):
        p = make_event_payload(task_id="t", domain="web", adapter_name="A", extra={"reason": "x"})
        assert p["reason"] == "x"


# ---------------------------------------------------------------------------
# InMemoryCollector and emit_event integration
# ---------------------------------------------------------------------------

class TestInMemoryCollector:
    def setup_method(self):
        self.collector = InMemoryCollector()
        register_collector(self.collector)

    def teardown_method(self):
        unregister_collector(self.collector)

    def test_emitted_events_are_stored(self):
        emit_event(TASK_STARTED, {"task_id": "t1", "domain": "cli", "adapter_name": "CLIAdapter"})
        assert len(self.collector.events) == 1
        assert self.collector.events[0]["event_type"] == TASK_STARTED

    def test_secret_fields_are_redacted_before_collector_receives_event(self):
        emit_event(TASK_FAILED, {"task_id": "t2", "api_key": "sk-secret", "domain": "web", "adapter_name": "A"})
        assert self.collector.events[0]["api_key"] == "[REDACTED]"

    def test_multiple_event_types_captured(self):
        emit_event(TASK_STARTED, make_event_payload(task_id="t", domain="cli", adapter_name="C"))
        emit_event(TASK_SUCCEEDED, make_event_payload(task_id="t", domain="cli", adapter_name="C", duration_ms=10.0))
        types = [e["event_type"] for e in self.collector.events]
        assert TASK_STARTED in types
        assert TASK_SUCCEEDED in types


# ---------------------------------------------------------------------------
# Executor emits lifecycle events
# ---------------------------------------------------------------------------

class TestExecutorTelemetry:
    @pytest.mark.asyncio
    async def test_successful_dispatch_emits_started_and_succeeded(self):
        from trinity_core.trinity import ObjectiveOrchestrator
        from trinity_core.models import TaskResult

        class _Runtime:
            async def health_check(self):
                return True, None

            async def execute(self, task):
                return TaskResult(task_id=task.task_id, status="success", metadata={})

            async def close(self):
                return None

        collector = InMemoryCollector()
        register_collector(collector)
        try:
            config = TrinityConfig(openai_api_key="mock-openai-key", ai_provider="openai")
            async with ObjectiveOrchestrator(config=config, llm_provider_factory=lambda: SimpleNamespace()) as executor:
                task = TaskInput(task_id="tel-ok", description="list files", domain="cli")
                executor._build_sub_objective_executor = lambda _strategy_id: _Runtime()
                result = await executor.execute(task)
        finally:
            unregister_collector(collector)

        types = [e["event_type"] for e in collector.events]
        assert TASK_STARTED in types
        assert TASK_SUCCEEDED in types
        assert TASK_FAILED not in types

    @pytest.mark.asyncio
    async def test_unhealthy_adapter_emits_started_and_failed(self):
        from trinity_core.trinity import ObjectiveOrchestrator
        from trinity_core.models import TaskResult, StructuredError

        class _Runtime:
            async def health_check(self):
                return False, StructuredError(
                    layer="test",
                    phase="health_check",
                    error_type="TestError",
                    message="Unhealthy",
                    traceback="",
                )

            async def close(self):
                return None

        collector = InMemoryCollector()
        register_collector(collector)
        try:
            config = TrinityConfig(openai_api_key="mock-openai-key", ai_provider="openai")
            async with ObjectiveOrchestrator(config=config, llm_provider_factory=lambda: SimpleNamespace()) as executor:
                task = TaskInput(task_id="tel-bad", description="list files", domain="cli")
                executor._build_sub_objective_executor = lambda _strategy_id: _Runtime()
                await executor.execute(task)
        finally:
            unregister_collector(collector)

        types = [e["event_type"] for e in collector.events]
        assert TASK_STARTED in types
        assert TASK_FAILED in types

    @pytest.mark.asyncio
    async def test_event_payload_has_required_fields(self):
        from trinity_core.trinity import ObjectiveOrchestrator
        from trinity_core.models import TaskResult

        class _Runtime:
            async def health_check(self):
                return True, None

            async def execute(self, task):
                return TaskResult(task_id=task.task_id, status="success", metadata={})

            async def close(self):
                return None

        collector = InMemoryCollector()
        register_collector(collector)
        try:
            config = TrinityConfig(openai_api_key="mock-openai-key", ai_provider="openai")
            async with ObjectiveOrchestrator(config=config, llm_provider_factory=lambda: SimpleNamespace()) as executor:
                task = TaskInput(task_id="tel-fields", description="test", domain="cli")
                executor._build_sub_objective_executor = lambda _strategy_id: _Runtime()
                await executor.execute(task)
        finally:
            unregister_collector(collector)

        succeeded = next(e for e in collector.events if e["event_type"] == TASK_SUCCEEDED)
        assert "task_id" in succeeded
        assert "domain" in succeeded
        assert "adapter_name" in succeeded
        assert "duration_ms" in succeeded
