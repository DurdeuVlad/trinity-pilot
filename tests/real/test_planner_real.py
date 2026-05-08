"""Real planner test — calls live Gemini API via ObjectivePlanner."""
import pytest

from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.planner.planner import ObjectivePlanner

pytestmark = pytest.mark.real


async def test_planner_returns_valid_specs(gemini_api_key):
    provider = GeminiProvider(api_key=gemini_api_key, model="gemini-2.0-flash")
    planner = ObjectivePlanner(provider=provider)

    specs = await planner.plan("Open a browser and navigate to https://example.com")

    assert len(specs) >= 1
    spec = specs[0]

    # All required fields present and non-empty
    assert spec.objective_id
    assert spec.goal
    assert spec.domain is not None
    assert spec.risk_class is not None
    assert spec.max_attempts >= 1
    assert spec.rollback_or_abort_rule

    # validate() passes (all 11 fields present)
    spec.validate()


async def test_planner_multi_step_task(gemini_api_key):
    provider = GeminiProvider(api_key=gemini_api_key, model="gemini-2.0-flash")
    planner = ObjectivePlanner(provider=provider)

    specs = await planner.plan(
        "Open a terminal, run `pip install requests`, then open a browser and navigate to https://pypi.org/project/requests/"
    )

    assert len(specs) >= 1
    # All specs validate
    for spec in specs:
        spec.validate()
    # Dependency order respected (no forward references)
    seen_ids = set()
    for spec in specs:
        for dep in spec.dependencies:
            assert dep in seen_ids, f"Dependency '{dep}' not yet seen before '{spec.objective_id}'"
        seen_ids.add(spec.objective_id)
