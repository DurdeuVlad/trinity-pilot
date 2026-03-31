"""Chaos Bank Runner — verifies orchestrator resilience under injected failures.

Runs the prompt bank headlessly (no live app needed) with the ChaosLayer wrapping
the bridge. Verifies that the system never crashes, always produces structured output,
and degrades gracefully even when the underlying backend fails repeatedly.

Usage:
    python unified-app/tests/prompts/run_chaos_bank.py

    # Specific chaos mode:
    python unified-app/tests/prompts/run_chaos_bank.py --mode random_fail --prob 0.5

    # All modes:
    python unified-app/tests/prompts/run_chaos_bank.py --all-modes

Expected: most prompts return "failure" or "partial" — that is fine.
The test passes if invariants hold under chaos (no crashes, structured output).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.chaos_layer import ChaosConfig, ChaosLayer
from orchestrator.event_bus import EventBus
from orchestrator.execution_runner import TaskExecutionRunner
from orchestrator.macro_planner import ExecutionPlan

_BANK_FILE = Path(__file__).parent / "bank.json"


# ── Fake infrastructure (mirrors test_execution_runner.py fakes) ──────────────

def _is_reflection_call(messages: list[dict]) -> bool:
    system = messages[0].get("content", "") if messages else ""
    return "achieved" in system and "critique" in system


def _is_replan_call(messages: list[dict]) -> bool:
    system = messages[0].get("content", "") if messages else ""
    return "revised_objectives" in system


class _ChaosAwareProvider:
    """LLM provider that generates one real action before finishing.

    Generating a real action means execute_task IS called on the bridge,
    so the ChaosLayer actually gets exercised.

    For reflection calls: returns achieved=True so the objective completes
    even if the bridge returned a chaos error (we're testing resilience at
    the system level, not the reflection level).
    """

    def __init__(self) -> None:
        self._action_calls = 0

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        if _is_reflection_call(messages):
            return json.dumps({"achieved": True, "confidence": 0.9, "critique": None})
        if _is_replan_call(messages):
            return json.dumps({"revised_objectives": [], "rationale": "chaos test replan"})
        self._action_calls += 1
        if self._action_calls == 1:
            # First call: generate a real CLI action so the bridge is invoked
            return json.dumps({
                "rationale": "execute the task",
                "action_type": "cli",
                "module": "cli_runner",
                "parameters": {"command": "echo chaos-test"},
                "done": False,
            })
        return json.dumps({
            "rationale": "objective complete",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "task complete under chaos",
        })

    async def probe(self) -> None:
        pass

    @property
    def provider_name(self) -> str:
        return "fake"


class _BaseBridge:
    """Bridge that returns a real-looking TaskResult (before chaos wrapping)."""

    def __init__(self) -> None:
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        pass

    async def execute_task(self, task_id: str, description: str, domain: str, **kwargs: Any) -> Any:
        result = MagicMock()
        result.status = "success"
        result.output = f"ok: {description[:40]}"
        result.error = None
        result.execution_log = []
        result.artifacts = []
        result.metadata = {}
        return result


class _RecordingHistory:
    """Minimal history manager that captures completion payload."""

    def __init__(self) -> None:
        self.completed: list[dict] = []
        self.steps_added: list[tuple] = []

    def create_task(self, **kwargs: Any) -> None:
        pass

    def start_task(self, task_id: str) -> None:
        pass

    def complete_task(
        self, task_id: str, result_data: dict | None = None,
        error_message: str | None = None, status: Any = None,
    ) -> None:
        self.completed.append({
            "task_id": task_id,
            "result_data": result_data or {},
            "error_message": error_message,
            "status": status,
        })

    def add_step(self, task_id: str, step_number: int, description: str) -> None:
        self.steps_added.append((task_id, step_number, description))

    def update_step_status(
        self, task_id: str, step_number: int, status: Any,
        result_data: dict | None = None, error_message: str | None = None,
    ) -> None:
        pass

    def close(self) -> None:
        pass


class _FakePlanner:
    async def generate_plan(self, description: str, domain: str) -> ExecutionPlan:
        return ExecutionPlan(
            description=description,
            domain=domain,
            steps=[description],
            estimated_duration=5,
            confidence=0.9,
        )

    async def replan(
        self, original_task: str, completed: list, failed: list, remaining: list,
    ) -> list[str]:
        return remaining


class _FakeWatcher:
    def start_watching(self) -> None:
        pass

    def stop_watching(self) -> None:
        pass


class _FakeErrorHandler:
    def handle(self, exc: Exception, context: str, category: str | None = None) -> dict:
        return {"message": str(exc), "user_message": str(exc), "category": "backend_error"}

    def build_user_message(self, message: str, category: str | None = None) -> str:
        return message


# ── Invariant checks (chaos-specific) ─────────────────────────────────────────

def check_chaos_invariants(
    completion: dict | None,
    completions: list[dict],
    steps_added: list,
) -> list[str]:
    """Return invariant failures. These must hold even under chaos."""
    failures: list[str] = []

    if not completions:
        failures.append("No execution_complete event emitted — runner may have crashed silently")
        return failures

    last = completions[-1]

    # 1. Status must always be set
    if "status" not in last:
        failures.append("execution_complete payload missing 'status' field")

    # 2. Status must be a known value
    status = last.get("status", "")
    if status not in ("success", "partial", "failure", "cancelled"):
        failures.append(f"Unexpected status value: {status!r}")

    # 3. Completion payload must not contain a raw traceback
    for key, val in last.items():
        if isinstance(val, str) and "Traceback (most recent call last)" in val:
            failures.append(f"Field {key!r} contains a raw Python traceback")

    # 4. Something must have been attempted (plan created at least one step)
    if not steps_added:
        failures.append("No steps were added to history — plan generation may have failed silently")

    # 5. Under chaos, status should be failure or partial (not success with 100% fail rate)
    # This is a soft check — only warn, don't fail
    # (leaving as a comment — deterministic checking is tricky without seeding all chaos)

    return failures


# ── Core runner ───────────────────────────────────────────────────────────────

@dataclass
class ChaosResult:
    prompt_id: str
    category: str
    status: str = "UNKNOWN"   # PASS | FAIL | ERROR
    final_status: str = ""
    invariant_failures: list[str] = field(default_factory=list)
    error: str = ""


async def run_chaos_prompt(prompt: dict, config: ChaosConfig) -> ChaosResult:
    result = ChaosResult(prompt_id=prompt["id"], category=prompt["category"])

    bus = EventBus()
    base_bridge = _BaseBridge()
    chaos_bridge = ChaosLayer(base_bridge, config)
    history = _RecordingHistory()
    planner = _FakePlanner()
    watcher = _FakeWatcher()
    provider = _ChaosAwareProvider()

    completions: list[dict] = []
    bus.execution_complete.connect(lambda payload: completions.append(payload))

    runner = TaskExecutionRunner(
        run_id=f"chaos_{prompt['id']}",
        task_description=prompt["description"],
        domain=prompt["domain"],
        event_bus=bus,
        history_manager=history,
        error_handler=_FakeErrorHandler(),
        planner=planner,
        provider=provider,
        bridge=chaos_bridge,
        screenshot_watcher=watcher,
        cancel_requested=lambda: False,
        cancel_event=None,
    )

    try:
        await runner.execute()
    except Exception as exc:
        result.status = "FAIL"
        result.error = f"Runner raised unhandled exception: {exc}\n{traceback.format_exc()}"
        return result

    last_completion = completions[-1] if completions else None
    result.final_status = (last_completion or {}).get("status", "")

    inv_failures = check_chaos_invariants(
        completion=last_completion,
        completions=completions,
        steps_added=history.steps_added,
    )
    result.invariant_failures = inv_failures
    result.status = "FAIL" if inv_failures else "PASS"
    return result


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_result(r: ChaosResult, mode: str) -> None:
    icon = {"PASS": "OK", "FAIL": "XX", "ERROR": "!!"}.get(r.status, "??")
    print(f"  [{icon}] {r.prompt_id:<35} {r.status}  (final={r.final_status}, mode={mode})")
    for f in r.invariant_failures:
        print(f"       INVARIANT: {f}")
    if r.error:
        print(f"       ERROR:     {r.error[:200]}")


def print_summary(results: list[ChaosResult], mode: str) -> None:
    n_pass = sum(1 for r in results if r.status == "PASS")
    n_fail = sum(1 for r in results if r.status in ("FAIL", "ERROR"))
    total = len(results)
    print()
    print(f"  Chaos mode [{mode}]: {n_pass}/{total} invariant-safe, {n_fail} failures")


# ── Entry point ───────────────────────────────────────────────────────────────

_ALL_MODES = ["random_fail", "timeout", "partial_result", "corrupt_output"]


async def run_mode(bank: list[dict], config: ChaosConfig) -> list[ChaosResult]:
    results = []
    for prompt in bank:
        r = await run_chaos_prompt(prompt, config)
        print_result(r, config.mode)
        results.append(r)
    print_summary(results, config.mode)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run prompt bank under chaos conditions")
    parser.add_argument("--mode", default="random_fail", choices=_ALL_MODES, help="Chaos mode")
    parser.add_argument("--prob", type=float, default=0.5, help="Failure probability (random_fail)")
    parser.add_argument("--all-modes", action="store_true", help="Run all chaos modes")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    args = parser.parse_args()

    bank: list[dict] = json.loads(_BANK_FILE.read_text(encoding="utf-8"))

    print(f"Running {len(bank)} prompts under chaos conditions...")
    print()

    all_results: list[ChaosResult] = []

    modes = _ALL_MODES if args.all_modes else [args.mode]
    for mode in modes:
        print(f"--- Mode: {mode} ---")
        config = ChaosConfig(mode=mode, probability=args.prob, seed=args.seed)  # type: ignore[arg-type]
        results = asyncio.run(run_mode(bank, config))
        all_results.extend(results)

    total_fail = sum(1 for r in all_results if r.status in ("FAIL", "ERROR"))
    print()
    print("=" * 60)
    print(f"  Chaos run complete - {total_fail} invariant violation(s) across all modes")
    print("=" * 60)

    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
