"""Regression tests for the live run helper script."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


def _load_live_run_module():
    script_path = Path(__file__).resolve().parent / "manual" / "test_live_run.py"
    spec = importlib.util.spec_from_file_location("unified_app_test_live_run", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_real_task_builds_macro_planner_with_provider(monkeypatch, capsys):
    """The live helper should use the current provider-backed MacroPlanner API."""
    module = _load_live_run_module()
    monkeypatch.delenv("GEMINI_MOCK", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "live-key")

    provider_object = object()
    seen: dict[str, object] = {}

    class FakePlan:
        steps = ["step one", "step two"]
        confidence = 0.75
        estimated_duration = 12

    class FakeMacroPlanner:
        def __init__(self, provider) -> None:
            seen["planner_provider"] = provider

        async def generate_plan(self, task_description: str, domain: str) -> FakePlan:
            seen["task_description"] = task_description
            seen["domain"] = domain
            return FakePlan()

    class FakeBridge:
        async def initialize(self) -> None:
            seen["bridge_initialized"] = True

        async def shutdown(self) -> None:
            seen["bridge_shutdown"] = True

    monkeypatch.setattr(module, "make_provider", lambda provider_name, api_key: provider_object, raising=False)
    monkeypatch.setattr(module, "MacroPlanner", FakeMacroPlanner)
    monkeypatch.setattr(module, "TrinityBridge", FakeBridge)

    result = asyncio.run(module.test_real_task())
    output = capsys.readouterr().out

    assert result is True
    assert seen["planner_provider"] is provider_object
    assert seen["bridge_initialized"] is True
    assert seen["bridge_shutdown"] is True
    assert "Plan generated successfully" in output
    assert "ALL TESTS PASSED" in output
