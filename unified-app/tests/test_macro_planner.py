"""Tests for MacroPlanner capability-aware planning (UA-S2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.macro_planner import MacroPlanner, _truncate_capabilities, _CAPABILITY_PAYLOAD_MAX_CHARS
from orchestrator.objectives_decomposer import ObjectivesDecomposer


_CLI_CAPABILITIES = {
    "schema_version": "1.0",
    "domain": "cli",
    "actions": ["run_command", "read_output", "write_file"],
    "limits": {"timeout_seconds": 30, "max_retries": 3},
    "constraints": {"thread_safe": True, "async": False, "platforms": ["windows", "linux"]},
}

_BROWSER_CAPABILITIES = {
    "schema_version": "1.0",
    "domain": "web",
    "actions": ["navigate", "click", "type", "screenshot"],
    "limits": {"timeout_seconds": 60, "max_retries": 3},
    "constraints": {"thread_safe": False, "async": True, "platforms": ["windows", "linux", "mac"]},
}


class _FakeProvider:
    """Sync-compatible fake provider that returns a fixed step list."""

    provider_name = "fake"

    def __init__(self, objectives: list[str]) -> None:
        self._response = json.dumps({"objectives": objectives})

    async def call(
        self,
        messages: list[dict],
        *,
        json_mode: bool = True,
        purpose: str | None = None,
    ) -> str:
        return self._response

    async def probe(self) -> None:
        pass


@pytest.mark.asyncio
async def test_planner_no_capabilities_returns_plan() -> None:
    provider = _FakeProvider(["step one", "step two"])
    planner = MacroPlanner(provider)
    plan = await planner.generate_plan("do something complex", "cli", capabilities=None)
    assert plan.steps == ["step one", "step two"]
    assert plan.domain == "cli"


@pytest.mark.asyncio
async def test_planner_with_capabilities_returns_plan() -> None:
    provider = _FakeProvider(["launch browser", "navigate to url"])
    planner = MacroPlanner(provider)
    plan = await planner.generate_plan("open website", "web", capabilities=_BROWSER_CAPABILITIES)
    assert len(plan.steps) >= 1


@pytest.mark.asyncio
async def test_planner_capability_prompt_injected_into_decomposer() -> None:
    provider = _FakeProvider(["run command"])
    planner = MacroPlanner(provider)
    with patch.object(
        ObjectivesDecomposer, "decompose", new_callable=AsyncMock
    ) as mock_decompose:
        mock_decompose.return_value = ["run command"]
        await planner.generate_plan("run a shell command", "cli", capabilities=_CLI_CAPABILITIES)
        _, call_kwargs = mock_decompose.call_args
        prompt_suffix = call_kwargs.get("prompt_suffix", "")
        assert "capabilities" in prompt_suffix.lower()
        assert "Only plan steps" in prompt_suffix


@pytest.mark.asyncio
async def test_planner_no_capabilities_prompt_not_injected() -> None:
    provider = _FakeProvider(["step one"])
    planner = MacroPlanner(provider)
    with patch.object(
        ObjectivesDecomposer, "decompose", new_callable=AsyncMock
    ) as mock_decompose:
        mock_decompose.return_value = ["step one"]
        await planner.generate_plan("do something simple", "cli", capabilities=None)
        _, call_kwargs = mock_decompose.call_args
        prompt_suffix = call_kwargs.get("prompt_suffix", "")
        assert prompt_suffix == ""


@pytest.mark.asyncio
async def test_planner_cli_capabilities_passed_through() -> None:
    provider = _FakeProvider(["run git status"])
    planner = MacroPlanner(provider)
    with patch.object(
        ObjectivesDecomposer, "decompose", new_callable=AsyncMock
    ) as mock_decompose:
        mock_decompose.return_value = ["run git status"]
        await planner.generate_plan("check git status", "cli", capabilities=_CLI_CAPABILITIES)
        _, call_kwargs = mock_decompose.call_args
        assert "run_command" in call_kwargs.get("prompt_suffix", "")


@pytest.mark.asyncio
async def test_planner_browser_capabilities_passed_through() -> None:
    provider = _FakeProvider(["navigate to example.com"])
    planner = MacroPlanner(provider)
    with patch.object(
        ObjectivesDecomposer, "decompose", new_callable=AsyncMock
    ) as mock_decompose:
        mock_decompose.return_value = ["navigate to example.com"]
        await planner.generate_plan("open example.com", "web", capabilities=_BROWSER_CAPABILITIES)
        _, call_kwargs = mock_decompose.call_args
        assert "navigate" in call_kwargs.get("prompt_suffix", "")


def test_truncate_capabilities_small_payload_unchanged() -> None:
    caps = {"actions": ["click"], "limits": {"timeout_seconds": 30}}
    result = _truncate_capabilities(caps)
    assert result == caps


def test_truncate_capabilities_large_payload_returns_summary() -> None:
    large_caps = {f"key_{i}": "x" * 200 for i in range(20)}
    assert len(json.dumps(large_caps)) > _CAPABILITY_PAYLOAD_MAX_CHARS
    result = _truncate_capabilities(large_caps)
    assert result != large_caps
    # Result contains only type strings, not the huge values
    for val in result.values():
        assert val == "str"


def test_truncate_capabilities_preserves_key_names() -> None:
    large_caps = {"actions": ["a"] * 500, "limits": {"timeout_seconds": 30}}
    if len(json.dumps(large_caps)) > _CAPABILITY_PAYLOAD_MAX_CHARS:
        result = _truncate_capabilities(large_caps)
        assert "actions" in result
        assert "limits" in result
