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
from orchestrator.macro_planner import MacroPlanner, _build_missing_resource_report_objective
from orchestrator.output_validator import OutputValidator
from orchestrator.prompt_registry import PromptRegistry
from orchestrator.execution_runner import (
    _completion_lacks_execution_evidence,
    _is_missing_resource_failure,
    _text_indicates_missing_resource,
)
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

    def test_done_requires_execution_evidence_for_operational_objectives(self) -> None:
        done_response = json.dumps({
            "rationale": "all done",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "Task is complete",
        })
        act_response = json.dumps({
            "rationale": "renaming file",
            "action_type": "cli",
            "module": "cli_runner",
            "parameters": {"command": "Rename-Item report.txt summary.txt"},
            "done": False,
            "result_summary": None,
        })
        final_done_response = json.dumps({
            "rationale": "done",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "Task is complete",
        })
        loop = self._loop([done_response, act_response, final_done_response])
        result = asyncio.run(loop.act("Rename report.txt to summary.txt", obj_index=1))
        assert result == "Task is complete"
        assert len(loop._bridge.calls) == 1

    def test_act_then_done(self) -> None:
        act_response = json.dumps({
            "rationale": "renaming file",
            "action_type": "cli",
            "module": "cli_runner",
            "parameters": {"command": "Rename-Item report.txt summary.txt"},
            "done": False,
            "result_summary": None,
        })
        done_response = json.dumps({
            "rationale": "done",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "File renamed",
        })
        loop = self._loop([act_response, done_response])
        result = asyncio.run(loop.act("Rename report.txt to summary.txt", obj_index=1))
        assert result == "File renamed"

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
        asyncio.run(loop.act("Rename report.txt to summary.txt", obj_index=1, adapt_hint="Try keyboard shortcut"))
        assert any("Try keyboard shortcut" in c for c in captured)

    def test_steer_hint_injected_on_next_turn_only(self) -> None:
        captured: list[str] = []
        steer_calls = 0

        class CapturingProvider:
            async def call(self, messages: list[dict], **kw) -> str:
                captured.append(messages[-1]["content"])
                if len(captured) == 1:
                    return json.dumps({
                        "rationale": "rename with cli",
                        "action_type": "cli",
                        "module": "cli_runner",
                        "parameters": {"command": "Rename-Item report.txt summary.txt"},
                        "done": False,
                        "result_summary": None,
                    })
                return json.dumps({
                    "rationale": "done",
                    "action_type": "done",
                    "module": None,
                    "parameters": {},
                    "done": True,
                    "result_summary": "File renamed",
                })

        def consume_steer() -> str:
            nonlocal steer_calls
            steer_calls += 1
            return "Prefer keyboard shortcuts" if steer_calls == 2 else ""

        loop = AgentLoop(
            provider=CapturingProvider(),
            bridge=FakeBridge(),
            emit_status=lambda m, l: None,
            cancel_requested=lambda: False,
            registry=PromptRegistry("gemini"),
            consume_steer=consume_steer,
        )

        result = asyncio.run(loop.act("Rename report.txt to summary.txt", obj_index=1))

        assert result == "File renamed"
        assert "USER STEERING" not in captured[0]
        assert "Prefer keyboard shortcuts" in captured[1]

    def test_steer_skip_request_stays_advisory_and_does_not_bypass_evidence(self) -> None:
        captured: list[str] = []
        responses = [
            json.dumps({
                "rationale": "skip ahead",
                "action_type": "done",
                "module": None,
                "parameters": {},
                "done": True,
                "result_summary": "Skipped",
            }),
            json.dumps({
                "rationale": "rename with cli",
                "action_type": "cli",
                "module": "cli_runner",
                "parameters": {"command": "Rename-Item report.txt summary.txt"},
                "done": False,
                "result_summary": None,
            }),
            json.dumps({
                "rationale": "done",
                "action_type": "done",
                "module": None,
                "parameters": {},
                "done": True,
                "result_summary": "File renamed",
            }),
        ]

        class CapturingProvider:
            def __init__(self) -> None:
                self._index = 0

            async def call(self, messages: list[dict], **kw) -> str:
                captured.append(messages[-1]["content"])
                response = responses[self._index]
                self._index += 1
                return response

        loop = AgentLoop(
            provider=CapturingProvider(),
            bridge=FakeBridge(),
            emit_status=lambda m, l: None,
            cancel_requested=lambda: False,
            registry=PromptRegistry("gemini"),
            consume_steer=lambda: "Skip this and go to the next step",
        )

        result = asyncio.run(loop.act("Rename report.txt to summary.txt", obj_index=1))

        assert result == "File renamed"
        assert len(loop._bridge.calls) == 1
        assert "Do not skip the objective" in captured[0]
        assert "Skip this and go to the next step" in captured[0]

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


class TestExecutionEvidenceGuards:
    def test_browser_objective_with_empty_payload_lacks_evidence(self) -> None:
        assert _completion_lacks_execution_evidence("Search for Lady Gaga on YouTube", {}) is True

    def test_informational_objective_does_not_require_payload_evidence(self) -> None:
        assert _completion_lacks_execution_evidence("Inform the user that the browser search failed", {}) is False

    def test_payload_with_execution_log_counts_as_evidence(self) -> None:
        payload = {
            "status": "success",
            "execution_log": [{"action": "search", "details": "Results loaded"}],
            "artifacts": [],
            "metadata": {},
        }
        assert _completion_lacks_execution_evidence("Search for Lady Gaga on YouTube", payload) is False


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

    def test_replan_missing_resource_returns_failure_report_objective(self) -> None:
        planner = MacroPlanner(ScriptedProvider([]), registry=PromptRegistry("gemini"))
        revised = asyncio.run(planner.replan(
            original_task="Open MissingApp and tell me its version",
            completed=[],
            failed=[("Open MissingApp", "ERROR: MissingApp was not found on this system")],
            remaining=["Tell me the app version"],
        ))
        assert revised == [_build_missing_resource_report_objective(False)]

    def test_replan_missing_resource_after_progress_preserves_partial_path(self) -> None:
        planner = MacroPlanner(ScriptedProvider([]), registry=PromptRegistry("gemini"))
        revised = asyncio.run(planner.replan(
            original_task="Get Python version and write it into MissingApp",
            completed=["Get the installed Python version"],
            failed=[("Open MissingApp", "ERROR: MissingApp does not exist")],
            remaining=["Write the version into MissingApp"],
        ))
        assert revised == [_build_missing_resource_report_objective(True)]


class TestFailureDetectionHelpers:
    def test_missing_resource_failure_detected_from_result_text(self) -> None:
        assert _is_missing_resource_failure(
            "ERROR: Application MissingApp was not found",
            {"status": "failure"},
        ) is True

    def test_missing_resource_failure_detected_from_raw_result_payload(self) -> None:
        payload = {
            "status": "failure",
            "metadata": {
                "raw_result": {
                    "status": "failure",
                    "error": "ERROR: target does not exist",
                }
            },
        }
        assert _is_missing_resource_failure("step failed", payload) is True

    def test_non_missing_failure_does_not_trigger_missing_resource_path(self) -> None:
        assert _is_missing_resource_failure(
            "ERROR: timed out waiting for response",
            {"status": "failure"},
        ) is False

    def test_reflection_critique_missing_resource_is_detected(self) -> None:
        assert _text_indicates_missing_resource(
            "The target application could not be found on this system."
        ) is True
