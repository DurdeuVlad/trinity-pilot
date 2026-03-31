"""Integration tests for the Plan → Act → Reflect → Replan orchestration flow."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.agent_loop import AgentLoop
from orchestrator.execution_context import ExecutionContext
from orchestrator.macro_planner import MacroPlanner
from orchestrator.output_validator import OutputValidator
from orchestrator.prompt_registry import PromptRegistry
from orchestrator.reflection_engine import ReflectionEngine


# ── Shared fakes ──────────────────────────────────────────────────────────────

class FakeBridge:
    """Minimal TrinityBridge stub."""

    def __init__(self, response: str = "OK (status=success)") -> None:
        self.response = response
        self.calls: list[dict] = []

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def execute_task(self, **kwargs) -> MagicMock:
        self.calls.append(kwargs)
        result = MagicMock()
        result.status = "success"
        result.output = self.response
        result.error = None
        return result


class ScriptedProvider:
    """Returns pre-scripted JSON responses in sequence."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.call_count = 0

    async def call(self, messages: list[dict], **kwargs) -> str:
        self.call_count += 1
        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp
        # Default: always done
        return json.dumps({
            "rationale": "done",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "Objective complete",
        })


# ── PromptRegistry ────────────────────────────────────────────────────────────

class TestPromptRegistry:
    def test_gemini_and_openai_have_different_action_prompts(self) -> None:
        g = PromptRegistry("gemini")
        o = PromptRegistry("openai")
        assert g.action_system_prompt() != o.action_system_prompt()

    def test_gemini_and_openai_have_different_reflection_prompts(self) -> None:
        g = PromptRegistry("gemini")
        o = PromptRegistry("openai")
        assert g.reflection_system_prompt() != o.reflection_system_prompt()

    def test_unknown_provider_falls_back_to_openai(self) -> None:
        r = PromptRegistry("anthropic")
        assert r.provider_name == "openai"

    def test_all_prompt_types_non_empty(self) -> None:
        for name in ["gemini", "openai"]:
            r = PromptRegistry(name)
            assert r.action_system_prompt()
            assert r.reflection_system_prompt()
            assert r.replan_system_prompt()
            assert r.decompose_system_prompt()


# ── ReflectionEngine ──────────────────────────────────────────────────────────

class TestReflectionEngine:
    def _engine(self, responses: list[str]) -> ReflectionEngine:
        registry = PromptRegistry("gemini")
        return ReflectionEngine(ScriptedProvider(responses), registry)

    def test_achieved_true(self) -> None:
        engine = self._engine(['{"achieved": true, "confidence": 0.95, "critique": null}'])
        reflection = asyncio.run(engine.reflect("open calculator", "OK (status=success)", 0))
        assert reflection.achieved is True
        assert reflection.confidence == 0.95
        assert reflection.critique is None

    def test_achieved_false_with_critique(self) -> None:
        engine = self._engine([
            '{"achieved": false, "confidence": 0.8, "critique": "Calculator did not open"}'
        ])
        reflection = asyncio.run(engine.reflect("open calculator", "OK (status=success)", 0))
        assert reflection.achieved is False
        assert "Calculator" in reflection.critique

    def test_fast_path_for_ai_error(self) -> None:
        engine = self._engine([])  # No LLM call should be made
        reflection = asyncio.run(engine.reflect("open X", "[AI error: timeout]", 0))
        assert reflection.achieved is False
        assert reflection.critique is not None

    def test_fast_path_for_stuck(self) -> None:
        engine = self._engine([])
        reflection = asyncio.run(engine.reflect("do Y", "[stuck: repeated]", 0))
        assert reflection.achieved is False

    def test_llm_failure_defaults_to_achieved(self) -> None:
        """If reflection itself fails, conservatively treat as achieved."""
        class FailingProvider:
            async def call(self, *a, **kw):
                raise RuntimeError("LLM down")

        engine = ReflectionEngine(FailingProvider(), PromptRegistry("openai"))
        reflection = asyncio.run(engine.reflect("do Z", "some result", 0))
        assert reflection.achieved is True


# ── AgentLoop ─────────────────────────────────────────────────────────────────

class TestAgentLoop:
    def _loop(self, responses: list[str], bridge_response: str = "OK") -> AgentLoop:
        registry = PromptRegistry("openai")
        return AgentLoop(
            provider=ScriptedProvider(responses),
            bridge=FakeBridge(bridge_response),
            emit_status=lambda msg, lvl: None,
            cancel_requested=lambda: False,
            registry=registry,
        )

    def test_done_on_first_turn(self) -> None:
        loop = self._loop([json.dumps({
            "rationale": "all done",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "Calculator is open",
        })])
        result = asyncio.run(loop.act("Open calculator", obj_index=1))
        assert result == "Calculator is open"

    def test_act_then_done(self) -> None:
        act_response = json.dumps({
            "rationale": "opening calculator",
            "action_type": "desktop",
            "module": "desktop_app",
            "parameters": {"action": "open", "app": "calc"},
            "done": False,
            "result_summary": None,
        })
        done_response = json.dumps({
            "rationale": "done",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "Calculator opened",
        })
        loop = self._loop([act_response, done_response])
        result = asyncio.run(loop.act("Open calculator", obj_index=1))
        assert result == "Calculator opened"

    def test_adapt_hint_injected_on_first_call(self) -> None:
        captured: list[str] = []

        class CapturingProvider:
            call_count = 0
            async def call(self, messages: list[dict], **kw) -> str:
                CapturingProvider.call_count += 1
                captured.append(messages[-1]["content"])
                return json.dumps({
                    "rationale": "done",
                    "action_type": "done",
                    "module": None,
                    "parameters": {},
                    "done": True,
                    "result_summary": "done",
                })

        registry = PromptRegistry("gemini")
        loop = AgentLoop(
            provider=CapturingProvider(),
            bridge=FakeBridge(),
            emit_status=lambda m, l: None,
            cancel_requested=lambda: False,
            registry=registry,
        )
        asyncio.run(loop.act("Open calculator", obj_index=1, adapt_hint="Try keyboard shortcut"))
        assert any("Try keyboard shortcut" in c for c in captured)

    def test_cancelled_returns_sentinel(self) -> None:
        loop = AgentLoop(
            provider=ScriptedProvider([]),
            bridge=FakeBridge(),
            emit_status=lambda m, l: None,
            cancel_requested=lambda: True,
            registry=PromptRegistry("gemini"),
        )
        result = asyncio.run(loop.act("do something", obj_index=1))
        assert result == "[cancelled]"

    def test_schema_error_returns_schema_error_string(self) -> None:
        bad_response = json.dumps({"totally": "wrong"})
        loop = self._loop([bad_response] * 15)
        result = asyncio.run(loop.act("do something", obj_index=1))
        assert result.startswith("[schema error:") or result.startswith("[max iterations")


# ── MacroPlanner ──────────────────────────────────────────────────────────────

class TestMacroPlanner:
    def test_generate_plan_returns_objectives(self) -> None:
        provider = ScriptedProvider([
            '{"objectives": ["Open app", "Do the thing", "Close app"]}'
        ])
        registry = PromptRegistry("gemini")
        planner = MacroPlanner(provider, registry=registry)
        plan = asyncio.run(planner.generate_plan("Do the thing end to end", "desktop"))
        assert plan.steps == ["Open app", "Do the thing"]
        assert plan.estimated_duration == 120

    def test_generate_plan_falls_back_to_raw_task(self) -> None:
        provider = ScriptedProvider(["not valid json"])
        registry = PromptRegistry("openai")
        planner = MacroPlanner(provider, registry=registry)
        plan = asyncio.run(planner.generate_plan("My task", "cli"))
        assert plan.steps == ["My task"]

    def test_replan_returns_revised_objectives(self) -> None:
        provider = ScriptedProvider([
            '{"revised_objectives": ["Fallback: log error instead"], "rationale": "original path blocked"}'
        ])
        registry = PromptRegistry("gemini")
        planner = MacroPlanner(provider, registry=registry)
        revised = asyncio.run(planner.replan(
            original_task="Do X then Y",
            completed=["Do X"],
            failed=[("Do Y", "[stuck: repeated]")],
            remaining=["Verify result"],
        ))
        assert revised == ["Fallback: log error instead"]

    def test_replan_returns_original_on_llm_failure(self) -> None:
        class FailProvider:
            async def call(self, *a, **kw):
                raise RuntimeError("LLM timeout")

        planner = MacroPlanner(FailProvider(), registry=PromptRegistry("openai"))
        original = ["Verify result", "Save file"]
        revised = asyncio.run(planner.replan(
            original_task="Do X",
            completed=[],
            failed=[("Do X", "ERROR: boom")],
            remaining=original,
        ))
        assert revised == original

    def test_replan_empty_remaining_returns_empty(self) -> None:
        planner = MacroPlanner(ScriptedProvider([]), registry=PromptRegistry("gemini"))
        revised = asyncio.run(planner.replan("task", [], [], []))
        assert revised == []
