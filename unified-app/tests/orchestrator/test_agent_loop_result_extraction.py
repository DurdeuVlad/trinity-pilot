"""Regression tests for agent-loop result extraction helpers."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_UNIFIED = REPO_ROOT / "unified-app"
for _p in (str(REPO_ROOT), str(_UNIFIED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from orchestrator.agent_loop import _extract_result  # noqa: E402
from trinity_core.models import ExecutionLog, TaskResult  # noqa: E402


def test_extract_result_prefers_metadata_text_output() -> None:
    result = TaskResult(
        task_id="t1",
        status="success",
        execution_log=[],
        artifacts=[],
        metadata={"text_output": "The cat is a domestic species of small carnivorous mammal."},
    )
    assert _extract_result(result).startswith("The cat is a domestic species")


def test_extract_result_falls_back_to_execution_log_details() -> None:
    result = TaskResult(
        task_id="t2",
        status="success",
        execution_log=[
            ExecutionLog(
                step=1,
                action="read page",
                result="success",
                details="Paragraph content from the page.",
                timestamp="2026-03-23T00:00:00",
            )
        ],
        artifacts=[],
        metadata={},
    )
    assert _extract_result(result) == "Paragraph content from the page."
