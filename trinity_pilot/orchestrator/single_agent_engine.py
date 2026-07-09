"""SingleAgentEngine — thin pipeline for the ablation experiment.

No Planner, no DAG, no Reviewer, no retry-with-reflection.
Receives a raw task string, runs SingleAgentWorker, returns result dict.
"""
from __future__ import annotations

import asyncio
from typing import Any

from trinity_pilot.config import Settings
from trinity_pilot.workers.single_agent_worker import SingleAgentWorker
from trinity_pilot.workers.worker_result import WorkerResult

# Step budget: same as per-worker budget (20 steps). Cross-domain SA tasks
# that need both browser and terminal tools are evaluated at parity with a
# single Trinity Pilot worker invocation; this is a conservative choice that
# slightly disadvantages SA on cross-domain tasks.
_DEFAULT_MAX_STEPS = 20


class SingleAgentEngine:
    """Ablation baseline engine. One worker, all tools, one ReAct loop."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self, task: str, *, max_steps: int = _DEFAULT_MAX_STEPS) -> dict[str, Any]:
        worker = SingleAgentWorker()
        result: WorkerResult = await worker.execute_raw(task, max_steps=max_steps)
        return {
            "status": "completed" if result.status == "success" else "failed",
            "single_agent_summary": result.summary,
            "evidence": result.evidence,
            "steps_taken": result.steps_taken,
            "tokens_used": result.tokens_used,
        }
