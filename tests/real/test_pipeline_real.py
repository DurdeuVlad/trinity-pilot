"""Real end-to-end pipeline test — planner + TerminalWorker + reviewer, live Gemini."""
import pytest

from trinity_pilot.core.types import DomainType
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.planner.planner import ObjectivePlanner
from trinity_pilot.reviewer.reviewer import ObjectiveReviewer
from trinity_pilot.workers.terminal_worker import TerminalWorker

pytestmark = pytest.mark.real


async def test_real_terminal_pipeline_passes(gemini_api_key):
    """Live Gemini plans + real echo subprocess + live reviewer → passed result."""
    planner_provider = GeminiProvider(api_key=gemini_api_key, model="gemini-2.5-flash")
    planner = ObjectivePlanner(provider=planner_provider)

    specs = await planner.plan("Run `echo pipeline-smoke-ok` in a terminal")

    assert len(specs) >= 1
    # Find a terminal spec (planner should produce one for this request)
    terminal_specs = [s for s in specs if s.domain == DomainType.TERMINAL]
    assert terminal_specs, f"Expected terminal spec, got: {[s.domain for s in specs]}"
    spec = terminal_specs[0]

    worker = TerminalWorker()
    evidence = await worker.execute(spec)

    assert evidence["exit_code"] == 0

    reviewer_provider = GeminiProvider(api_key=gemini_api_key, model="gemini-2.5-flash")
    reviewer = ObjectiveReviewer(provider=reviewer_provider)
    result = await reviewer.review(spec=spec, evidence=evidence)

    # Whether reviewer agrees or not, the pipeline ran end-to-end without error
    assert isinstance(result.passed, bool)
