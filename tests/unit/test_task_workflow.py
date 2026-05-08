"""TaskWorkflow retry loop tests — mocked activities, no real Temporal server."""
import json

import pytest

pytest.importorskip("temporalio.testing", reason="temporalio not installed")

from unittest.mock import AsyncMock, patch

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from trinity_pilot.workflow.task_workflow import TaskWorkflow


def _make_spec_dict(obj_id: str = "obj-1", max_attempts: int = 3) -> dict:
    return {
        "objective_id": obj_id,
        "goal": "run `echo hello`",
        "dependencies": [],
        "domain": "terminal",
        "required_capabilities": [],
        "risk_class": "low",
        "preconditions": [],
        "success_tests": [],
        "evidence_bundle": [],
        "max_attempts": max_attempts,
        "rollback_or_abort_rule": "abort",
        "metadata": {},
    }


class TestTaskWorkflowRetry:
    @pytest.mark.asyncio
    async def test_retry_succeeds_on_third_attempt(self):
        call_count = {"n": 0}

        async def mock_plan(user_request: str) -> list[dict]:
            return [_make_spec_dict(max_attempts=3)]

        async def mock_execute(spec_dict: dict) -> dict:
            return {"domain": "terminal", "objective_id": spec_dict["objective_id"]}

        async def mock_review(spec_dict: dict, evidence: dict) -> dict:
            call_count["n"] += 1
            if call_count["n"] < 3:
                return {"passed": False, "failure_reason": "failed_assertion", "notes": "bad", "recovery_hint": "retry"}
            return {"passed": True, "failure_reason": None, "notes": "", "recovery_hint": ""}

        async def mock_persist(*args) -> None:
            pass

        async def mock_save_reflection(*args) -> None:
            pass

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-queue",
                workflows=[TaskWorkflow],
                activities=[mock_plan, mock_execute, mock_review, mock_persist, mock_save_reflection],
            ):
                result = await env.client.execute_workflow(
                    TaskWorkflow.run,
                    "open google.com",
                    id="test-wf-1",
                    task_queue="test-queue",
                )
        assert result["status"] == "completed"
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_retry_context_injected_on_second_attempt(self):
        received_specs = []

        async def mock_plan(user_request: str) -> list[dict]:
            return [_make_spec_dict(max_attempts=2)]

        async def mock_execute(spec_dict: dict) -> dict:
            received_specs.append(dict(spec_dict))
            return {"domain": "terminal", "objective_id": spec_dict["objective_id"]}

        attempt = {"n": 0}

        async def mock_review(spec_dict: dict, evidence: dict) -> dict:
            attempt["n"] += 1
            if attempt["n"] == 1:
                return {"passed": False, "failure_reason": "failed_assertion", "notes": "first fail", "recovery_hint": "hint-one"}
            return {"passed": True, "failure_reason": None, "notes": "", "recovery_hint": ""}

        async def mock_persist(*args) -> None:
            pass

        async def mock_save_reflection(*args) -> None:
            pass

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-queue-2",
                workflows=[TaskWorkflow],
                activities=[mock_plan, mock_execute, mock_review, mock_persist, mock_save_reflection],
            ):
                await env.client.execute_workflow(
                    TaskWorkflow.run,
                    "do something",
                    id="test-wf-2",
                    task_queue="test-queue-2",
                )

        assert len(received_specs) == 2
        assert "retry_context" not in received_specs[0]
        assert "retry_context" in received_specs[1]
        ctx = json.loads(received_specs[1]["retry_context"])
        assert ctx[0]["recovery_hint"] == "hint-one"


