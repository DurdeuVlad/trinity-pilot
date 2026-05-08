"""Planner unit tests. No live API calls — stub LLMProvider."""
from __future__ import annotations

import json

import pytest

from trinity_pilot.core.types import DomainType
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.planner.planner import ObjectivePlanner, PlanningError


def _make_spec_dict(**overrides) -> dict:
    base = {
        "objective_id": "obj-1",
        "goal": "Open example.com in browser",
        "dependencies": [],
        "domain": "browser",
        "required_capabilities": ["browser_navigation"],
        "risk_class": "low",
        "preconditions": [],
        "success_tests": ["page title is 'Example Domain'"],
        "evidence_bundle": ["screenshot"],
        "max_attempts": 3,
        "rollback_or_abort_rule": "abort",
    }
    base.update(overrides)
    return base


class StubProvider(LLMProvider):
    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def complete(self, messages: list[LLMMessage], system: str = "") -> LLMResponse:
        return LLMResponse(content=self._reply)

    async def complete_with_tools(self, messages, tools, system="") -> LLMResponse:
        return LLMResponse(content=self._reply)


class TestObjectivePlanner:
    async def test_valid_single_objective(self):
        payload = json.dumps([_make_spec_dict()])
        planner = ObjectivePlanner(StubProvider(payload))
        specs = await planner.plan("open example.com")
        assert len(specs) == 1
        assert specs[0].objective_id == "obj-1"
        assert specs[0].domain == DomainType.BROWSER

    async def test_valid_two_objectives_ordered(self):
        specs_data = [
            _make_spec_dict(objective_id="step-1", goal="Step 1"),
            _make_spec_dict(
                objective_id="step-2",
                goal="Step 2",
                dependencies=["step-1"],
            ),
        ]
        payload = json.dumps(specs_data)
        planner = ObjectivePlanner(StubProvider(payload))
        specs = await planner.plan("do two steps")
        ids = [s.objective_id for s in specs]
        assert ids.index("step-1") < ids.index("step-2")

    async def test_malformed_json_raises_planning_error(self):
        planner = ObjectivePlanner(StubProvider("not valid json {{{"))
        with pytest.raises(PlanningError, match="invalid JSON"):
            await planner.plan("anything")

    async def test_non_array_response_raises_planning_error(self):
        planner = ObjectivePlanner(StubProvider(json.dumps({"key": "value"})))
        with pytest.raises(PlanningError, match="JSON array"):
            await planner.plan("anything")

    async def test_empty_array_raises_planning_error(self):
        planner = ObjectivePlanner(StubProvider("[]"))
        with pytest.raises(PlanningError, match="empty plan"):
            await planner.plan("anything")

    async def test_missing_required_field_raises_planning_error(self):
        bad = _make_spec_dict()
        del bad["goal"]
        planner = ObjectivePlanner(StubProvider(json.dumps([bad])))
        with pytest.raises(PlanningError):
            await planner.plan("anything")

    async def test_strips_markdown_code_fence(self):
        payload = "```json\n" + json.dumps([_make_spec_dict()]) + "\n```"
        planner = ObjectivePlanner(StubProvider(payload))
        specs = await planner.plan("open example.com")
        assert len(specs) == 1

    async def test_malformed_json_includes_request_context(self):
        request = "open the browser and go to example.com please"
        planner = ObjectivePlanner(StubProvider("not valid json {{{"))
        with pytest.raises(PlanningError) as exc_info:
            await planner.plan(request)
        assert "Request context" in str(exc_info.value)
        # Truncated to 100 chars max
        assert request[:100] in str(exc_info.value)

    async def test_malformed_json_long_request_truncated_to_100(self):
        long_request = "x" * 200
        planner = ObjectivePlanner(StubProvider("not valid json {{{"))
        with pytest.raises(PlanningError) as exc_info:
            await planner.plan(long_request)
        error_msg = str(exc_info.value)
        assert "x" * 100 in error_msg
        # Full 200-char string should NOT appear verbatim (it's truncated)
        assert "x" * 200 not in error_msg

    async def test_plan_reorders_when_llm_returns_deps_before_dependents(self):
        """Even if LLM returns B before A (B depends on A), plan() returns [A, B]."""
        spec_b = _make_spec_dict(objective_id="obj-b", goal="Step B", dependencies=["obj-a"])
        spec_a = _make_spec_dict(objective_id="obj-a", goal="Step A", dependencies=[])
        # LLM returns B before A — wrong order
        payload = json.dumps([spec_b, spec_a])
        planner = ObjectivePlanner(StubProvider(payload))
        specs = await planner.plan("do A then B")
        ids = [s.objective_id for s in specs]
        assert ids.index("obj-a") < ids.index("obj-b")
