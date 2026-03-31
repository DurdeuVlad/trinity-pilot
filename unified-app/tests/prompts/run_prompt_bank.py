"""Prompt Bank Runner -verifies the orchestrator works across diverse prompts.

Submits each prompt in bank.json to the live orchestrator (via named pipe),
polls for completion, and checks both invariants and category-specific criteria.

Usage:
    # Run full bank (requires app to be running):
    python unified-app/tests/prompts/run_prompt_bank.py

    # Run single category:
    python unified-app/tests/prompts/run_prompt_bank.py --category cli_happy

    # Run single prompt by ID:
    python unified-app/tests/prompts/run_prompt_bank.py --id cli_list_python_files

    # Dry-run (list prompts without executing):
    python unified-app/tests/prompts/run_prompt_bank.py --dry-run

Requires: the orchestrator desktop app must be running.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Allow running from repo root or from within unified-app/
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_APP_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_APP_ROOT))

from orchestrator.database import HistoryManager, TaskStatus

try:
    from mcp_server.task_submission_pipe import (
        PipeSubmissionUnavailable,
        submit_task_via_pipe,
    )
    _PIPE_AVAILABLE = True
except ImportError:
    _PIPE_AVAILABLE = False

_BANK_FILE = Path(__file__).parent / "bank.json"
_POLL_INTERVAL = 1.0          # seconds between DB polls
_TASK_TIMEOUT = 120.0         # max seconds to wait for a single task
_PIPE_SUBMIT_TIMEOUT = 10.0   # seconds for pipe handshake


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class InvariantResult:
    passed: bool
    name: str
    detail: str = ""


@dataclass
class PromptResult:
    prompt_id: str
    category: str
    description: str
    status: str = "SKIP"          # PASS | FAIL | SKIP | ERROR
    task_id: str = ""
    elapsed: float = 0.0
    final_status: str = ""        # success | partial | failure | cancelled
    invariant_failures: list[str] = field(default_factory=list)
    criteria_failure: str = ""
    error: str = ""


# ── Invariant checks ──────────────────────────────────────────────────────────

def check_invariants(
    task: Any,
    steps: list[Any],
    elapsed: float,
    expected_status: str,
) -> list[str]:
    """Return list of invariant failure messages (empty = all passed)."""
    failures: list[str] = []

    # 1. Task record must exist
    if task is None:
        failures.append("Task record not found in database")
        return failures

    # 2. Status must be a known value
    status_val = getattr(task.status, "value", str(task.status))
    known_statuses = {"completed", "failed", "cancelled", "running", "pending"}
    if status_val.lower() not in known_statuses:
        failures.append(f"Unknown task status: {status_val!r}")

    # 3. Must not have timed out externally (we waited _TASK_TIMEOUT)
    if elapsed >= _TASK_TIMEOUT:
        failures.append(f"Task exceeded {_TASK_TIMEOUT}s timeout (elapsed={elapsed:.1f}s)")

    # 4. Steps list must be non-empty (something was attempted)
    if not steps:
        failures.append("No execution steps recorded -orchestrator may not have run")

    # 5. result_data must not be a raw traceback
    result_data_raw = getattr(task, "result_data", None) or ""
    if isinstance(result_data_raw, str) and "Traceback (most recent call last)" in result_data_raw:
        failures.append("result_data contains a raw Python traceback -exception leaked to output")

    # 6. error_message (if any) must be human-readable, not a raw traceback
    error_msg = getattr(task, "error_message", None) or ""
    if "Traceback (most recent call last)" in error_msg:
        failures.append("error_message contains a raw Python traceback -not user-friendly")

    # 7. If expected_status is "partial", at least one step must have succeeded
    result_data = {}
    if isinstance(result_data_raw, str) and result_data_raw:
        try:
            result_data = json.loads(result_data_raw)
        except json.JSONDecodeError:
            pass
    actual_category = result_data.get("category", result_data.get("status", ""))
    if expected_status == "partial":
        completed_steps = [
            s for s in steps
            if getattr(getattr(s, "status", None), "value", str(getattr(s, "status", ""))) == "completed"
        ]
        if not completed_steps:
            failures.append(
                f"Expected at least one completed step for 'partial' result, found 0"
            )

    return failures


def get_task_final_status(task: Any) -> str:
    """Extract the human-facing final status string from the task record."""
    result_data_raw = getattr(task, "result_data", None) or ""
    if isinstance(result_data_raw, str) and result_data_raw:
        try:
            data = json.loads(result_data_raw)
            return data.get("status", data.get("category", "unknown"))
        except json.JSONDecodeError:
            pass
    status_val = getattr(task.status, "value", str(task.status))
    if status_val == "completed":
        return "success"
    return status_val


# ── Core runner ───────────────────────────────────────────────────────────────

def _wait_for_completion(
    history: HistoryManager,
    task_id: str,
    timeout: float = _TASK_TIMEOUT,
) -> Any:
    """Poll HistoryManager until the task reaches a terminal state."""
    terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = history.get_task(task_id)
        if task is not None and task.status in terminal:
            return task
        time.sleep(_POLL_INTERVAL)
    return history.get_task(task_id)


def _get_steps(history: HistoryManager, task_id: str) -> list[Any]:
    """Return execution steps for a task."""
    try:
        with history.get_session() as session:
            from orchestrator.database.models import ExecutionStep
            return session.query(ExecutionStep).filter_by(task_id=task_id).all()
    except Exception:
        return []


def run_prompt(
    prompt: dict,
    history: HistoryManager,
) -> PromptResult:
    """Submit one prompt and evaluate the result."""
    result = PromptResult(
        prompt_id=prompt["id"],
        category=prompt["category"],
        description=prompt["description"],
    )

    t_start = time.monotonic()

    # Submit via named pipe
    try:
        pipe_response = submit_task_via_pipe(
            description=prompt["description"],
            domain=prompt["domain"],
            timeout_seconds=_PIPE_SUBMIT_TIMEOUT,
        )
    except PipeSubmissionUnavailable as exc:
        result.status = "SKIP"
        result.error = f"App not reachable via pipe: {exc}"
        return result
    except Exception as exc:
        result.status = "ERROR"
        result.error = f"Pipe submission failed: {exc}"
        return result

    if not pipe_response.get("ok"):
        result.status = "ERROR"
        result.error = f"Pipe rejected task: {pipe_response.get('message', pipe_response)}"
        return result

    task_id = pipe_response.get("task_id", "")
    if not task_id:
        result.status = "ERROR"
        result.error = "Pipe response missing task_id"
        return result

    result.task_id = task_id

    # Wait for completion
    task = _wait_for_completion(history, task_id)
    result.elapsed = time.monotonic() - t_start

    if task is None:
        result.status = "ERROR"
        result.error = f"Task {task_id!r} not found after {result.elapsed:.1f}s"
        return result

    result.final_status = get_task_final_status(task)
    steps = _get_steps(history, task_id)

    # Invariant checks
    inv_failures = check_invariants(
        task=task,
        steps=steps,
        elapsed=result.elapsed,
        expected_status=prompt["expected_status"],
    )
    result.invariant_failures = inv_failures

    # Status expectation check
    expected = prompt["expected_status"]
    if expected != "any" and result.final_status != expected:
        result.criteria_failure = (
            f"Expected status={expected!r}, got {result.final_status!r}"
        )

    if inv_failures or result.criteria_failure:
        result.status = "FAIL"
    else:
        result.status = "PASS"

    return result


# ── Reporting ─────────────────────────────────────────────────────────────────

def _status_icon(status: str) -> str:
    return {"PASS": "OK", "FAIL": "XX", "SKIP": "~~", "ERROR": "!!"}.get(status, "??")


def print_result(r: PromptResult) -> None:
    icon = _status_icon(r.status)
    elapsed_str = f" ({r.elapsed:.1f}s)" if r.elapsed > 0 else ""
    print(f"  [{icon}] {r.prompt_id:<35} {r.status}{elapsed_str}")
    if r.invariant_failures:
        for f in r.invariant_failures:
            print(f"       INVARIANT: {f}")
    if r.criteria_failure:
        print(f"       CRITERIA:  {r.criteria_failure}")
    if r.error:
        print(f"       ERROR:     {r.error}")


def print_summary(results: list[PromptResult]) -> None:
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    total = len(results)
    print()
    print("-" * 60)
    print(
        f"  Results: {counts['PASS']}/{total} passed  |  "
        f"{counts['FAIL']} failed  |  "
        f"{counts['SKIP']} skipped  |  "
        f"{counts['ERROR']} errors"
    )
    print("-" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Run the prompt bank against the live orchestrator")
    parser.add_argument("--category", help="Only run prompts in this category")
    parser.add_argument("--id", help="Only run the prompt with this ID")
    parser.add_argument("--dry-run", action="store_true", help="List prompts without executing")
    args = parser.parse_args()

    if not _PIPE_AVAILABLE:
        print("ERROR: mcp_server.task_submission_pipe not importable -check your PYTHONPATH")
        return 1

    bank: list[dict] = json.loads(_BANK_FILE.read_text(encoding="utf-8"))

    # Filter
    if args.id:
        bank = [p for p in bank if p["id"] == args.id]
        if not bank:
            print(f"ERROR: No prompt with id={args.id!r}")
            return 1
    elif args.category:
        bank = [p for p in bank if p["category"] == args.category]
        if not bank:
            print(f"ERROR: No prompts in category={args.category!r}")
            return 1

    if args.dry_run:
        print(f"Prompt bank -{len(bank)} prompt(s):")
        for p in bank:
            print(f"  [{p['category']}] {p['id']}: {p['description'][:70]}")
        return 0

    print(f"Running {len(bank)} prompt(s) against live orchestrator...")
    print()

    history = HistoryManager()
    results: list[PromptResult] = []

    for prompt in bank:
        print(f"  -> {prompt['id']} ({prompt['domain']})")
        try:
            r = run_prompt(prompt, history)
        except Exception as exc:
            r = PromptResult(
                prompt_id=prompt["id"],
                category=prompt["category"],
                description=prompt["description"],
                status="ERROR",
                error=f"Unhandled exception: {exc}\n{traceback.format_exc()}",
            )
        print_result(r)
        results.append(r)

    history.close()
    print_summary(results)

    failed = [r for r in results if r.status in ("FAIL", "ERROR")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
