"""Planner prompt template tests — no LLM call needed."""
from trinity_pilot.planner.prompts import PLANNER_SYSTEM, PLANNER_USER_TEMPLATE


class TestPlannerPrompts:
    def test_user_template_contains_user_request(self):
        result = PLANNER_USER_TEMPLATE.format(user_request="open google.com")
        assert "open google.com" in result

    def test_user_template_non_empty(self):
        result = PLANNER_USER_TEMPLATE.format(user_request="x")
        assert len(result) > 10

    def test_system_prompt_non_empty(self):
        assert len(PLANNER_SYSTEM) > 100

    def test_system_prompt_mentions_json(self):
        assert "JSON" in PLANNER_SYSTEM

    def test_system_prompt_mentions_objective_id(self):
        assert "objective_id" in PLANNER_SYSTEM

    def test_user_template_has_format_placeholder(self):
        assert "{user_request}" in PLANNER_USER_TEMPLATE
